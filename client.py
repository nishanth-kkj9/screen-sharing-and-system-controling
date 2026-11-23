# file: client.py
"""Viewer TCP connection, reader and serialized writer (sections 4.2, 7.3, 7.4).

The GUI talks to ViewerClient through `events` (a queue.Queue) and the public
action methods; GUI callbacks never call sendall() themselves."""
import logging
import socket
import threading
import time

import config
import protocol
import screen_capture
from latest_slot import LatestSlot
from outbox import Outbox

logger = logging.getLogger("screenshare.client")

# Viewer states (section 6.2).
DISCONNECTED = "disconnected"
CONNECTING = "connecting"
AUTHENTICATING = "authenticating"
VIEW_ONLY = "view_only"
REQUEST_PENDING = "request_pending"
CONTROLLING = "controlling"

HOST_TO_VIEWER_TYPES = {"JOIN_ACCEPT", "JOIN_DENIED", "STATUS", "CONTROL_GRANTED",
                        "CONTROL_DENIED", "CONTROL_REVOKED", "ERROR", "DISCONNECT"}


class ViewerClient:
    """One Viewer application core."""

    def __init__(self, events, name):
        self.events = events
        self.name = name
        self.state = DISCONNECTED
        self.sock = None
        self.session_code = None
        self.outbox = None                 # one Outbox per connection (section 7.6)
        self.image_slot = None             # decoded frame slot for the GUI (8.5)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._closed = False
        self._frame_size = None
        self._reader_thread = None
        self._writer_thread = None

    # ---------------- connection lifecycle ----------------

    def connect(self, host, session_code):
        """Called from the GUI via a worker (never blocks the GUI thread)."""
        with self._lock:
            if self.state != DISCONNECTED:
                return
            self.state = CONNECTING
        self.session_code = session_code
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, config.PORT))
            sock.settimeout(None)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # C10
            except OSError:
                pass
        except OSError as exc:
            with self._lock:
                self.state = DISCONNECTED
            self._emit("connect_failed", str(exc))
            return
        # A disconnect() during the blocking connect() must win: re-check the
        # state under the lock before spinning up the reader/writer threads,
        # otherwise they would resurrect a connection the user closed. The new
        # socket, stop event and queues are published in the SAME critical
        # section, so a disconnect() can never see a half-installed connection.
        with self._lock:
            if self.state == DISCONNECTED:
                try:
                    sock.close()
                except OSError:
                    pass
                return
            self.sock = sock
            self._stop_event = threading.Event()
            self._closed = False
            self.outbox = Outbox(max_control=config.MAX_CONTROL_QUEUE_ITEMS)
            self.image_slot = LatestSlot()
            self.state = AUTHENTICATING
            stop_event = self._stop_event
            outbox = self.outbox
            image_slot = self.image_slot
        reader = threading.Thread(
            target=self._reader_loop, args=(sock, stop_event, image_slot),
            name="viewer-reader", daemon=True)
        writer = threading.Thread(
            target=self._writer_loop, args=(sock, outbox),
            name="viewer-writer", daemon=True)
        self._reader_thread = reader
        self._writer_thread = writer
        reader.start()
        writer.start()
        self._enqueue({"type": "JOIN", "protocol_version": config.PROTOCOL_VERSION,
                      "client_name": self.name, "session_code": session_code})
        self._emit("state", self.state)

    def disconnect(self, graceful=True):
        """User-requested disconnect (sections 11.3 and 11.4). Does not block the GUI:
        the writer flushes DISCONNECT and then sends FIN with shutdown(SHUT_WR);
        the reader drains what the Host still sends and closes the socket."""
        with self._lock:
            if self.state == DISCONNECTED:
                return
            outbox = self.outbox
            stop_event = self._stop_event
            sock = self.sock
        if graceful and outbox is not None:
            outbox.put_control(protocol.encode_json_message(
                {"type": "DISCONNECT", "reason": "user_exit"}))
        if stop_event is not None:            # None while connect() is still blocking
            stop_event.set()
        if outbox is not None:
            outbox.close()                    # writer drains control, then exits
        if sock is not None:
            try:
                sock.settimeout(0.5)          # wake a reader blocked in recv()
            except OSError:
                pass
        self._set_state(DISCONNECTED, "disconnected")

    # ---------------- GUI actions ----------------

    def request_control(self):
        if self.state == VIEW_ONLY:
            self._set_state(REQUEST_PENDING, "control requested; waiting for the Host")
            self._enqueue({"type": "CONTROL_REQUEST"})

    def release_control(self):
        self._enqueue({"type": "CONTROL_RELEASE"})
        # The Host stops accepting our input the moment it processes the release,
        # so the local state must not keep claiming control (section 6.2).
        if self.state == CONTROLLING:
            self._set_state(VIEW_ONLY, "control released")

    def send_move(self, nx, ny):
        """Latest-position slot so stale moves are replaced, never queued (7.4)."""
        if self.state == CONTROLLING and self.outbox is not None:
            self.outbox.put_latest({"x": nx, "y": ny})

    def send_button(self, button, action, nx, ny):
        self._enqueue({"type": "MOUSE_BUTTON", "button": button,
                       "action": action, "x": nx, "y": ny})

    def send_scroll(self, amount, nx, ny):
        self._enqueue({"type": "SCROLL", "amount": amount, "x": nx, "y": ny})

    def send_key(self, wire_key, down):
        self._enqueue({"type": "KEY_DOWN" if down else "KEY_UP", "key": wire_key})

    # ---------------- workers ----------------

    def _writer_loop(self, sock, outbox):
        """The only thread that writes to the Host socket (section 7.4). Outbox.get()
        blocks without polling and yields control messages before the latest mouse
        position. Its socket/outbox arguments are fixed at start, so a worker left
        over from an older connection can never write to a newer one."""
        move = {"type": "MOUSE_MOVE"}
        try:
            while True:
                item = outbox.get()
                if item is None:
                    break                     # closed and drained
                kind, data = item
                if kind == "control":
                    sock.sendall(data)
                else:
                    move["x"], move["y"] = data["x"], data["y"]
                    sock.sendall(protocol.encode_json_message(move))
            try:
                sock.shutdown(socket.SHUT_WR)  # FIN after the flushed DISCONNECT (11.4)
            except OSError:
                pass
        except (OSError, protocol.ProtocolError) as exc:
            logger.info("viewer writer ended: %r", exc)
            self._on_connection_lost(sock)

    def _reader_loop(self, sock, stop_event, image_slot):
        try:
            while not stop_event.is_set():
                try:
                    mtype, payload = protocol.recv_message(
                        sock, protocol.HOST_TO_VIEWER)
                except protocol.ConnectionClosed:
                    break
                if mtype == protocol.TYPE_JPEG:
                    try:
                        image = screen_capture.decode_jpeg_image(payload)
                    except screen_capture.CaptureError:
                        logger.warning("dropped an undecodable frame")
                        continue              # drop the frame, do not crash (16)
                    image_slot.put(image)     # LatestSlot, never unbounded (8.5)
                    if config.DEMO_SLOW_VIEWER_MS:
                        # Test-only flow-control demonstration (sections 15, 25.3).
                        time.sleep(config.DEMO_SLOW_VIEWER_MS / 1000.0)
                else:
                    try:
                        msg = protocol.decode_json_payload(payload)
                    except protocol.ProtocolError:
                        logger.warning("dropped a malformed JSON message")
                        continue
                    if not self._handle_message(msg):
                        break
        except (OSError, protocol.ProtocolError) as exc:
            logger.info("viewer reader ended: %r", exc)
        finally:
            self._drain_then_close(sock, stop_event)

    def _drain_then_close(self, sock, stop_event):
        """Section 11.4: after a user-requested disconnect keep reading and discarding
        until EOF or 2 seconds pass, so the close ends with FIN rather than RST."""
        if stop_event.is_set():
            deadline = time.monotonic() + 2.0
            try:
                while time.monotonic() < deadline:
                    sock.settimeout(max(0.05, deadline - time.monotonic()))
                    if not sock.recv(4096):
                        break
            except OSError:
                pass
        self._on_connection_lost(sock, stop_event)

    def _handle_message(self, msg):
        """Returns False when the connection should end."""
        mtype = msg.get("type")
        if mtype not in HOST_TO_VIEWER_TYPES:
            return False                      # invalid direction/content: drop link
        if mtype == "JOIN_ACCEPT":
            self._set_state(VIEW_ONLY, "connected (view-only)")
            return True
        if mtype == "JOIN_DENIED":
            reason = msg.get("reason", "unknown")
            if reason == "invalid_session_code":
                self._emit("join_denied", reason)
                return False                  # GUI lets the user retry the join
            self._emit("join_denied", reason)
            return False
        if mtype == "STATUS":
            self._emit("status", msg)
            return True
        if mtype == "CONTROL_GRANTED":
            self._set_state(CONTROLLING, "control granted")
            return True
        if mtype == "CONTROL_DENIED":
            if self.state == CONTROLLING:
                return True                   # late duplicate: we already have control
            self._set_state(VIEW_ONLY, "control denied: %s" % msg.get("reason", "unknown"))
            return True
        if mtype == "CONTROL_REVOKED":
            if self.state == CONTROLLING:
                self._set_state(VIEW_ONLY, "control revoked")
            return True
        if mtype == "DISCONNECT":
            return False
        if mtype == "ERROR":
            self._emit("server_error", msg.get("reason", "unknown"))
            return True
        return True

    # ---------------- helpers ----------------

    def _enqueue(self, message_dict):
        if self.outbox is None:
            return
        if not self.outbox.put_control(protocol.encode_json_message(message_dict)):
            self._on_connection_lost()        # never silently drop a transition (7.4)

    def _set_state(self, state, message):
        with self._lock:
            previous, self.state = self.state, state
        if previous != state:
            self._emit("state", state)
        self._emit("log", message)

    def _on_connection_lost(self, sock=None, stop_event=None):
        with self._lock:
            if sock is not None and sock is not self.sock:
                return                        # a worker from an older connection
            if self._closed:
                return
            self._closed = True
        (stop_event or self._stop_event).set()
        target = sock if sock is not None else self.sock
        if target is not None:
            try:
                target.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                target.close()
            except OSError:
                pass
        if self.image_slot is not None:
            self.image_slot.close()
        self._set_state(DISCONNECTED, "connection closed")

    def _emit(self, kind, data):
        self.events.put((kind, data))
