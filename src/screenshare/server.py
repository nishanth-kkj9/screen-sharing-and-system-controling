# file: server.py
"""Host listener, Viewer sessions, permission coordination and Host lifecycle
(architecture sections 3, 4.1, 6, 7.2, 7.4, 11).

Threading model (section 7.2): one accept worker, one capture worker, and one
reader + one writer worker per Viewer socket. Only the writer worker of a
session ever calls sendall() on that socket (section 7.4)."""
import logging
import secrets
import socket
import threading
import time

from screenshare import config
from screenshare import protocol
from screenshare import screen_capture
from screenshare.outbox import Outbox
from screenshare.permissions import PermissionManager
from screenshare.remote_input import RemoteInput

logger = logging.getLogger("screenshare.server")

INPUT_TYPES = {"MOUSE_MOVE", "MOUSE_BUTTON", "SCROLL", "KEY_DOWN", "KEY_UP"}


class ViewerSession:
    """One authenticated (or authenticating) Viewer TCP connection."""

    def __init__(self, session_id, sock, addr):
        self.id = session_id
        self.sock = sock
        self.addr = addr
        self.name = None
        self.authenticated = False
        self.bad_codes = 0
        # One Outbox per connection (section 7.6 rule 1): ordered control messages
        # plus one latest frame that is replaced instead of queued.
        self.outbox = Outbox(max_control=config.MAX_CONTROL_QUEUE_ITEMS)
        self.stop_event = threading.Event()
        self.reader_thread = None
        self.writer_thread = None
        # Statistics for the Host panel (sections 10.1 and 25.3). Written by the
        # writer thread, read by the capture thread when it emits a stats event.
        self.connected_at = time.monotonic()
        self.frames_sent = 0
        self.bytes_sent = 0
        self._close_lock = threading.Lock()
        self._closed = False
        self._cleaned = False

    @property
    def alive(self):
        return self.authenticated and not self.stop_event.is_set()

    @property
    def display(self):
        return self.name if self.name else "%s:%s" % self.addr[:2]

    @property
    def frames_skipped(self):
        """Frames overwritten in the slot before this Viewer's writer sent them."""
        return self.outbox.replaced

    def enqueue_control(self, message_dict):
        """Queue one JSON message for the writer. Returns False when the bounded
        control queue is full or closed; the caller must then close the session
        (section 7.4: never drop a permission or input transition silently)."""
        return self.outbox.put_control(protocol.encode_json_message(message_dict))

    def mark_cleaned(self):
        with self._close_lock:
            if self._cleaned:
                return False
            self._cleaned = True
            return True

    def close(self):
        """Idempotent (section 11.3). Lets the writer flush queued control messages,
        then follows the section 11.4 close sequence so a normal end sends FIN, not
        RST: shutdown(SHUT_WR), drain what the Viewer still sends, then close."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.stop_event.set()
        self.outbox.close()
        if self.writer_thread is not None and self.writer_thread is not threading.current_thread():
            self.writer_thread.join(timeout=1.0)
        try:
            self.sock.shutdown(socket.SHUT_WR)      # FIN after the queued bytes
        except OSError:
            pass
        deadline = time.monotonic() + 2.0
        reader = self.reader_thread
        # Only drain here when no reader worker is still reading this socket:
        # one reader per connection (section 7.2). A live reader consumes the
        # Viewer's remaining bytes itself until the socket is closed below.
        if reader is None or not reader.is_alive() or reader is threading.current_thread():
            try:
                self.sock.settimeout(0.2)
                while time.monotonic() < deadline:
                    if not self.sock.recv(4096):
                        break                       # EOF: the Viewer finished too
            except OSError:
                pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class _MssFrameSource:
    """Default frame source: one reusable MSS context inside the capture thread."""

    def __init__(self):
        self._sct = screen_capture.create_capture()

    def __call__(self):
        return screen_capture.capture_frame_jpeg(self._sct)

    def close(self):
        try:
            self._sct.close()
        except Exception:
            pass


def lan_ip():
    """Best-effort LAN IPv4 of this machine (no packets are actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def lan_ip_candidates():
    """Every candidate IPv4 of this machine, best guess first (section 3.3).
    Virtual adapters (VirtualBox, WSL, Hyper-V) often appear in this list."""
    best = lan_ip()
    found = []
    try:
        found = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    return [best] + [a for a in found if a != best]


class HostServer:
    """Host application core. The GUI talks to it through `events` (a queue.Queue)
    and the public action methods; it never touches sockets itself."""

    def __init__(self, events, input_backend=None, frame_factory=None):
        self.events = events
        self.state = "stopped"           # stopped / listening / stopping (section 6.1)
        self.session_code = None
        self.perm = PermissionManager()
        self.remote_input = RemoteInput(backend=input_backend)
        self._frame_factory = frame_factory or (lambda: _MssFrameSource())
        self.listener = None
        self._stop_event = threading.Event()
        self._sessions = {}
        self._sessions_lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._last_frame = None
        self._last_frame_size = None
        self._stats_mark = (time.monotonic(), 0, 0)
        self._threads = []

    # ---------------- lifecycle ----------------

    def start_sharing(self):
        """Returns an error string on failure (GUI shows it), or None on success."""
        if self.state != "stopped":
            return None
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((config.HOST, config.PORT))
            listener.listen(5)
        except OSError as exc:
            listener.close()
            return "Cannot listen on TCP port %d: %s" % (config.PORT, exc)
        self.listener = listener
        self.session_code = config.generate_session_code()
        self._stop_event = threading.Event()
        self._last_frame = None
        self._last_frame_size = None
        self._stats_mark = (time.monotonic(), 0, 0)
        self._threads = []
        self.state = "listening"
        accept_thread = threading.Thread(
            target=self._accept_loop, args=(listener, self._stop_event),
            name="accept", daemon=True)
        capture_thread = threading.Thread(
            target=self._capture_loop, args=(self._stop_event,),
            name="capture", daemon=True)
        self._threads = [accept_thread, capture_thread]
        accept_thread.start()
        capture_thread.start()
        self._emit("started", {"ip": lan_ip(), "ips": lan_ip_candidates(),
                               "port": config.PORT, "code": self.session_code})
        self._emit("log", "Sharing started; listening on TCP port %d" % config.PORT)
        return None

    def stop_sharing(self):
        if self.state != "listening":
            return
        self.state = "stopping"
        self._stop_event.set()
        if self.listener is not None:
            # shutdown() wakes a thread blocked in accept() on Linux; close()
            # alone does not. On Windows closesocket() unblocks accept().
            try:
                self.listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.listener.close()
            except OSError:
                pass
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        joinable = list(self._threads)
        for session in sessions:
            if session.authenticated:
                session.enqueue_control({"type": "DISCONNECT", "reason": "host_stopped"})
            joinable.extend(t for t in (session.reader_thread, session.writer_thread) if t)
            session.close()
        for thread in joinable:
            thread.join(timeout=1.0)          # bounded waits only (section 11.3)
        self.remote_input.release_all()        # never leave input held (section 9.5)
        self.perm.reset()
        with self._sessions_lock:
            self._sessions.clear()
        self.session_code = None
        self.state = "stopped"
        self._emit("stopped", None)

    # ---------------- GUI actions ----------------

    def approve_request(self):
        pending = self.perm.pending_id()
        if pending is None:
            return
        result = self.perm.approve(pending, is_connected=self._is_connected)
        session = self._sessions.get(pending)
        if result == "granted" and session is not None:
            self._emit("log", "Control granted to %s" % session.name)
            if not self._send(session, {"type": "CONTROL_GRANTED"}):
                return
        self._broadcast_status()

    def deny_request(self):
        pending = self.perm.reject()
        if pending is None:
            return
        session = self._sessions.get(pending)
        if session is not None:
            self._send(session, {"type": "CONTROL_DENIED", "reason": "host_rejected"})
        self._broadcast_status()

    def revoke_control(self):
        active = self.perm.clear_active()
        if active is None:
            return
        self.remote_input.release_all()
        session = self._sessions.get(active)
        if session is not None:
            self._send(session, {"type": "CONTROL_REVOKED", "reason": "host_revoked"})
        self._broadcast_status()

    def disconnect_viewer(self, session_id):
        """Host action for a Viewer that vanished silently (section 7.6 rule 4)."""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None:
            return
        self._send(session, {"type": "DISCONNECT", "reason": "host_stopped"})
        self._cleanup_session(session, "disconnected by Host")

    def status_snapshot(self):
        with self._sessions_lock:
            sessions = [s for s in self._sessions.values() if s.authenticated]
        return self._status_dict(sessions), [s.name for s in sessions]

    def stats_snapshot(self):
        """Per-Viewer counters and total rates for the Host panel (sections 10.1, 25.3).

        Called from the capture worker only, so the rate window needs no lock.
        """
        with self._sessions_lock:
            sessions = [s for s in self._sessions.values() if s.authenticated]
        now = time.monotonic()
        rows = []
        frames = bytes_ = 0
        for session in sessions:
            rows.append({
                "id": session.id,
                "name": session.display,
                "peer": "%s:%d" % session.addr[:2],
                "seconds": now - session.connected_at,
                "frames": session.frames_sent,
                "bytes": session.bytes_sent,
                "skipped": session.frames_skipped,
            })
            frames += session.frames_sent
            bytes_ += session.bytes_sent
        mark_time, mark_frames, mark_bytes = self._stats_mark
        elapsed = now - mark_time
        fps = (frames - mark_frames) / elapsed if elapsed > 0 else 0.0
        kbps = (bytes_ - mark_bytes) / elapsed / 1024.0 if elapsed > 0 else 0.0
        self._stats_mark = (now, frames, bytes_)
        return {"viewers": rows, "fps": fps, "kbps": kbps}

    # ---------------- workers ----------------

    def _accept_loop(self, listener, stop_event):
        while not stop_event.is_set():
            try:
                sock, addr = listener.accept()
            except OSError:
                break
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # C10
            except OSError:
                pass
            # Reserve the viewer slot here, in this single thread, so the
            # two-viewer limit cannot be raced (section 3.2).
            with self._sessions_lock:
                if stop_event.is_set():
                    # stop_sharing() already snapshotted the session list; a
                    # session created now would never be closed by it.
                    try:
                        sock.close()
                    except OSError:
                        pass
                    break
                if len(self._sessions) >= config.MAX_VIEWERS:
                    denied = True
                else:
                    denied = False
                    session = ViewerSession(secrets.token_hex(4), sock, addr)
                    self._sessions[session.id] = session
            if denied:
                # Deny on a short-lived worker: the socket still holds the
                # client's unread JOIN, and closing with unread data makes
                # Windows send RST, which destroys the JOIN_DENIED we just sent.
                threading.Thread(target=self._deny_connection, args=(sock, addr),
                                 name="deny", daemon=True).start()
                self._emit("log", "Connection from %s refused: viewer limit reached" % addr[0])
                continue
            sock.settimeout(config.JOIN_TIMEOUT)   # C9: until JOIN_ACCEPT is sent
            session.reader_thread = threading.Thread(
                target=self._reader_loop, args=(session,), name="reader-" + session.id, daemon=True)
            session.writer_thread = threading.Thread(
                target=self._writer_loop, args=(session,), name="writer-" + session.id, daemon=True)
            session.reader_thread.start()
            session.writer_thread.start()
            self._emit("log", "Connection from %s:%s waiting for JOIN" % addr)

    def _deny_connection(self, sock, addr):
        """Send JOIN_DENIED and drain the client's bytes before closing, so the
        denial is not lost to a TCP reset (section 11.2)."""
        try:
            sock.sendall(protocol.encode_json_message(
                {"type": "JOIN_DENIED", "reason": "viewer_limit_reached"}))
            sock.shutdown(socket.SHUT_WR)
            sock.settimeout(2.0)
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and sock.recv(4096):
                pass                          # EOF, idle 2 s or 2 s total ends the drain
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _writer_loop(self, session):
        """The only thread that writes to this Viewer's socket (section 7.4).
        Outbox.get() blocks without polling and returns control messages before the
        latest frame; None means the box is closed and drained, so the thread exits."""
        try:
            while True:
                item = session.outbox.get()
                if item is None:
                    return
                kind, data = item
                if kind == "control":
                    session.sock.sendall(data)
                else:
                    packet = protocol.encode_message(protocol.TYPE_JPEG, data)
                    session.sock.sendall(packet)
                    session.frames_sent += 1
                    session.bytes_sent += len(packet)
        except (OSError, protocol.ProtocolError) as exc:
            logger.info("writer for %s ended: %r", session.display, exc)
        finally:
            self._cleanup_session(session, "writer exited")

    def _reader_loop(self, session):
        try:
            if not self._handle_join(session):
                return
            while not session.stop_event.is_set():
                try:
                    mtype, payload = protocol.recv_message(
                        session.sock, protocol.VIEWER_TO_HOST)
                except protocol.ConnectionClosed:
                    break
                except socket.timeout:
                    break
                if mtype != protocol.TYPE_JSON:
                    break                      # cannot happen: recv_message rejects it
                try:
                    msg = protocol.decode_json_payload(payload)
                except protocol.ProtocolError:
                    break                      # stream is unsynchronised; just close
                if not self._dispatch(session, msg):
                    break
        except (OSError, protocol.ProtocolError) as exc:
            logger.info("reader for %s ended: %r", session.display, exc)
        finally:
            session.close()
            self._cleanup_session(session, "reader exited")

    def _handle_join(self, session):
        """Run the JOIN exchange. Returns True once authenticated."""
        while not session.stop_event.is_set():
            try:
                mtype, payload = protocol.recv_message(session.sock, protocol.VIEWER_TO_HOST)
            except socket.timeout:
                self._emit("log", "Connection from %s timed out without JOIN" % session.addr[0])
                return False
            if mtype != protocol.TYPE_JSON:
                return False
            try:
                msg = protocol.decode_json_payload(payload)
            except protocol.ProtocolError:
                return False
            if msg.get("type") != "JOIN" or protocol.validate_message(msg, protocol.VIEWER_TO_HOST):
                self._try_send_error(session, "unsupported_message")
                return False
            if msg["protocol_version"] != config.PROTOCOL_VERSION:
                self._send(session, {"type": "JOIN_DENIED", "reason": "unsupported_version"})
                return False
            name = msg["client_name"]
            if not name or not name.isprintable() or len(name) > config.CLIENT_NAME_MAX_LENGTH:
                self._send(session, {"type": "JOIN_DENIED", "reason": "invalid_name"})
                return False
            code = msg.get("session_code")
            # compare_digest() raises TypeError on non-ASCII text, and "" would
            # match a stopped Host whose session_code is None, so validate first.
            if (not isinstance(code, str) or not code.isascii()
                    or self.session_code is None
                    or not secrets.compare_digest(code, self.session_code)):
                session.bad_codes += 1
                self._send(session, {"type": "JOIN_DENIED", "reason": "invalid_session_code"})
                if session.bad_codes >= config.MAX_BAD_SESSION_CODES:
                    self._emit("log", "%s closed after %d wrong session codes"
                               % (session.addr[0], session.bad_codes))
                    return False
                continue                       # retry allowed while attempts remain
            # Authenticated.
            session.name = name
            session.sock.settimeout(None)      # C9: after JOIN_ACCEPT
            if self._last_frame_size is None:
                self._probe_frame()
            width, height = self._last_frame_size or (config.MAX_SCREEN_WIDTH,
                                                      config.MAX_SCREEN_HEIGHT)
            if not self._send(session, {
                    "type": "JOIN_ACCEPT",
                    "viewer_id": session.id,
                    "host_name": socket.gethostname(),
                    "screen_width": width,
                    "screen_height": height,
                    "fps": config.TARGET_FPS,
            }):
                return False
            if self._last_frame is not None:
                session.outbox.put_latest(self._last_frame)   # no blank window (8.2)
            # Only now may the capture loop put frames into this session's slot,
            # so JOIN_ACCEPT is always the first message the Viewer receives.
            session.authenticated = True
            self._emit("log", "Viewer '%s' connected from %s:%s" % (name, session.addr[0], session.addr[1]))
            self._broadcast_status()
            return True
        return False

    def _dispatch(self, session, msg):
        """Handle one decoded Viewer message. Returns False to end the session."""
        mtype = msg.get("type")
        if protocol.validate_message(msg, protocol.VIEWER_TO_HOST) is not None:
            self._try_send_error(session, "unsupported_message")
            return False
        if mtype == "JOIN":                    # second JOIN on an authenticated connection
            self._try_send_error(session, "unsupported_message")
            return False
        if mtype == "DISCONNECT":
            return False
        if mtype == "CONTROL_REQUEST":
            decision, reason = self.perm.request(session.id)
            if decision == "deny":
                return self._send(session, {"type": "CONTROL_DENIED", "reason": reason})
            self._broadcast_status()
            self._emit("control_request", session.name)
            return True
        if mtype == "CONTROL_RELEASE":
            if self.perm.release(session.id):
                self.remote_input.release_all()
                self._broadcast_status()
            return True
        if mtype in INPUT_TYPES:
            # Permission is re-checked for EVERY input event (rule 6.3 #8).
            if not self.perm.is_active(session.id):
                return True                    # stale input after revoke: dropped silently
            result = self.remote_input.handle(msg, True)
            if result == "rejected":
                # Well-formed message with bad values: answer invalid_input and keep
                # the session open (section 5.8).
                self._try_send_error(session, "invalid_input")
                return True
            if result == "failsafe":
                self._on_failsafe(session)
            return True
        return True

    def _capture_loop(self, stop_event):
        source = None
        try:
            source = self._frame_factory()
            pacer = screen_capture.FramePacer(config.TARGET_FPS)
            while not stop_event.is_set():
                if not self._any_authenticated():
                    time.sleep(0.2)            # idle while nobody watches (6.1)
                    continue
                pacer.wait()
                try:
                    result = source()
                except Exception:
                    logger.exception("screen capture failed")
                    time.sleep(0.5)
                    continue
                if result is None:
                    continue
                data, size = result
                with self._frame_lock:
                    self._last_frame, self._last_frame_size = data, size
                with self._sessions_lock:
                    sessions = [s for s in self._sessions.values() if s.authenticated]
                for session in sessions:       # same bytes reused for every Viewer (4.1 #7)
                    if not session.stop_event.is_set():
                        session.outbox.put_latest(data)
                self._emit("stats", self.stats_snapshot())
        except Exception:
            logger.exception("capture worker crashed")
        finally:
            if source is not None and hasattr(source, "close"):
                source.close()

    # ---------------- helpers ----------------

    def _probe_frame(self):
        """One-shot capture so a first JOIN_ACCEPT can carry the real frame size."""
        try:
            source = self._frame_factory()
            try:
                result = source()
            finally:
                if hasattr(source, "close"):
                    source.close()
            if result is not None:
                with self._frame_lock:
                    self._last_frame, self._last_frame_size = result
        except Exception:
            logger.warning("initial frame probe failed", exc_info=True)

    def _any_authenticated(self):
        with self._sessions_lock:
            return any(s.authenticated for s in self._sessions.values())

    def _is_connected(self, viewer_id):
        # NOTE: called with the permission lock held (from perm.approve); the
        # lock order permission -> sessions must never be reversed elsewhere.
        with self._sessions_lock:
            session = self._sessions.get(viewer_id)
            return session is not None and session.alive

    def _send(self, session, message):
        """Queue a control message for this session's writer. A full or closed
        Outbox means the session is closed cleanly, never a silent drop (7.4)."""
        if session.enqueue_control(message):
            return True
        self._cleanup_session(session, "control queue full")
        return False

    def _try_send_error(self, session, reason):
        session.enqueue_control({"type": "ERROR", "reason": reason})

    def _on_failsafe(self, session):
        self.perm.clear_active()               # release_all() already ran in handle()
        self._send(session, {"type": "CONTROL_REVOKED", "reason": "failsafe"})
        self._broadcast_status()
        self._emit("warning", "PyAutoGUI fail-safe triggered - remote input revoked")

    def _status_dict(self, sessions):
        active = self.perm.active_id()
        pending = self.perm.pending_id()
        by_id = {s.id: s for s in sessions}
        return {
            "type": "STATUS",
            "viewer_count": len(sessions),
            "active_controller": by_id[active].name if active in by_id else None,
            "pending_requester": by_id[pending].name if pending in by_id else None,
        }

    def _broadcast_status(self):
        with self._sessions_lock:
            sessions = [s for s in self._sessions.values() if s.authenticated]
        status = self._status_dict(sessions)
        for session in sessions:
            self._send(session, status)
        self._emit("status", {"status": status, "viewers": [s.name for s in sessions]})

    def _cleanup_session(self, session, reason):
        if not session.mark_cleaned():
            return
        session.close()
        with self._sessions_lock:
            self._sessions.pop(session.id, None)
        was_pending, was_active = self.perm.drop(session.id)
        if was_active:
            self.remote_input.release_all()    # held keys/buttons released (9.5)
        if session.authenticated:
            self._emit("log", "Viewer '%s' disconnected (%s)" % (session.name, reason))
        self._broadcast_status()

    def _emit(self, kind, data):
        self.events.put((kind, data))
