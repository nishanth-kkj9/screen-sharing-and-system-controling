# AGENT_FIX_GUIDE.md — exact code and instructions (one file)

Repo: `nishanth-kkj9/screen-sharing-and-system-controling`, commit `a8d5a98`.
Defect list and spec references: `REQUIREMENTS_FOR_AGENT.md` (DEF-1 … DEF-6, S-1 … S-7, E-1 … E-8).
This file contains **the code that fixes DEF-1 … DEF-6 and S-1, S-2**, the tests for it, and the steps to apply and check it.

## 1. What was actually verified (so you know how far to trust this)

| Check | Result |
|---|---|
| `git apply --check fix.patch` on a **pristine clone** of `a8d5a98` | OK, applies cleanly |
| New tests `tests/test_audit_fixes.py` (16 tests) on the **original** code | **15 fail / error**, 1 passes (the "third Viewer still denied" guard, which must pass on both) |
| Same 16 tests on the **patched** code | **16 pass**, repeated 3 times, no flakiness seen |
| Whole suite after patch (`unittest discover -s tests`) | **Ran 80 tests … OK** on Python 3.12 **and** 3.13 (64 old + 16 new) |
| `ConnectionClosed: peer closed` tracebacks in the suite output | **2 before → 0 after** |
| `compileall` | OK |
| **NOT verified here** | The Tk button change (no `tkinter` in the sandbox), anything on real Windows, PyAutoGUI, two laptops, Python 3.10. See section 6. |

Design decisions the student must approve (the spec is silent on them):
1. **New constant `config.MAX_PENDING_JOINS = 4`**: how many sockets may wait for `JOIN` on top of the 2 admitted Viewers. Without a cap, one client could open unlimited threads. It is an internal guard, not a protocol change.
2. **`Start Sharing` now takes one test screenshot first** (about 0.1–0.2 s) and refuses to start if capture cannot work. The same probe already ran at first `JOIN`, so the threading pattern is not new, but confirm on Windows.
3. **The Viewer "Release Control" button becomes "Cancel Request" while a request is pending** (spec 6.3 rule 9 requires the cancel; the button is the simplest way to offer it).

## 2. Apply it (5 minutes)

Stop any running Host first (the suite binds port 5000).

```powershell
cd <repo folder>
git switch -c fix/audit-defects
# 1. save the diff from section 3 as fix.patch (outside the repo is fine), then:
git apply --check ..\fix.patch
git apply ..\fix.patch
# 2. save the test file from section 4 as tests\test_audit_fixes.py
# 3. run everything
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall -q src tests demo
git add -A ; git commit -m "Fix audit defects DEF-1..DEF-6 and add regression tests"
```

Expected last lines: `Ran 80 tests in ...s` then `OK`. If a test is **skipped**, a Host still holds port 5000.

**Red → green check (do it once, it proves the tests mean something):**
```powershell
git stash push -- src                      # tests stay, fixes go away
.\.venv\Scripts\python.exe -m unittest tests.test_audit_fixes   # must FAIL (15 of 16)
git stash pop                              # fixes come back
.\.venv\Scripts\python.exe -m unittest tests.test_audit_fixes   # must PASS (16 of 16)
```

## 3. The patch (`fix.patch`, against commit `a8d5a98`)

```diff
--- a/src/screenshare/client.py
+++ b/src/screenshare/client.py
@@ -136,11 +136,17 @@
             self._enqueue({"type": "CONTROL_REQUEST"})
 
     def release_control(self):
+        """CONTROLLING -> VIEW_ONLY (release) and REQUEST_PENDING -> VIEW_ONLY
+        (cancel the request), section 6.2. Ignored in any other state."""
+        with self._lock:
+            previous = self.state
+        if previous not in (CONTROLLING, REQUEST_PENDING):
+            return
         self._enqueue({"type": "CONTROL_RELEASE"})
         # The Host stops accepting our input the moment it processes the release,
         # so the local state must not keep claiming control (section 6.2).
-        if self.state == CONTROLLING:
-            self._set_state(VIEW_ONLY, "control released")
+        self._set_state(VIEW_ONLY, "control released" if previous == CONTROLLING
+                        else "control request cancelled")
 
     def send_move(self, nx, ny):
         """Latest-position slot so stale moves are replaced, never queued (7.4)."""
@@ -238,17 +244,17 @@
             self._set_state(VIEW_ONLY, "connected (view-only)")
             return True
         if mtype == "JOIN_DENIED":
-            reason = msg.get("reason", "unknown")
-            if reason == "invalid_session_code":
-                self._emit("join_denied", reason)
-                return False                  # GUI lets the user retry the join
-            self._emit("join_denied", reason)
-            return False
+            self._emit("join_denied", msg.get("reason", "unknown"))
+            return False                      # the user clicks Connect again to retry
         if mtype == "STATUS":
             self._emit("status", msg)
             return True
         if mtype == "CONTROL_GRANTED":
-            self._set_state(CONTROLLING, "control granted")
+            # A cancel can cross a grant on the wire. Only a Viewer that is still
+            # waiting may become the controller; otherwise the Host has (or will)
+            # release it and the UI must not claim control.
+            if self.state == REQUEST_PENDING:
+                self._set_state(CONTROLLING, "control granted")
             return True
         if mtype == "CONTROL_DENIED":
             if self.state == CONTROLLING:
--- a/src/screenshare/config.py
+++ b/src/screenshare/config.py
@@ -8,6 +8,7 @@
 HOST = "0.0.0.0"
 PORT = 5000
 MAX_VIEWERS = 2
+MAX_PENDING_JOINS = 4              # sockets allowed to wait for JOIN beyond the admitted Viewers
 PROTOCOL_VERSION = 1
 
 # Image pipeline.
--- a/src/screenshare/gui.py
+++ b/src/screenshare/gui.py
@@ -480,7 +480,10 @@
         self.disconnect_button.config(state="normal" if connected else "disabled")
         self.request_button.config(
             state="normal" if state == client_mod.VIEW_ONLY else "disabled")
-        self.release_button.config(state="normal" if controlling else "disabled")
+        pending = state == client_mod.REQUEST_PENDING
+        self.release_button.config(
+            state="normal" if (controlling or pending) else "disabled",
+            text="Cancel Request" if pending else "Release Control")
 
     def _on_join_denied(self, reason):
         friendly = {
--- a/src/screenshare/permissions.py
+++ b/src/screenshare/permissions.py
@@ -73,6 +73,15 @@
                 return True
             return False
 
+    def cancel_pending(self, viewer_id):
+        """The pending Viewer withdraws its own request (spec 6.3 rule 9).
+        Returns True if a pending request of this Viewer was cleared."""
+        with self._lock:
+            if self.pending_controller_id == viewer_id:
+                self.pending_controller_id = None
+                return True
+            return False
+
     def drop(self, viewer_id):
         """Viewer disconnected. Returns (was_pending, was_active)."""
         with self._lock:
--- a/src/screenshare/remote_input.py
+++ b/src/screenshare/remote_input.py
@@ -130,9 +130,16 @@
 
     def handle(self, msg, is_active_controller):
         """Handle one input message. Returns one of the RESULT_* codes.
-        Every action runs under input_lock (section 7.6 rule 3)."""
+        Every action runs under input_lock (section 7.6 rule 3).
+
+        `is_active_controller` is a bool, or a zero-argument callable that is
+        evaluated INSIDE input_lock. Pass a callable from the Host so the
+        permission check and the injection are one atomic step: a revoke can then
+        never slip in between them and leave a key held (spec 6.3 rule 8)."""
         with self.input_lock:
-            return self._handle(msg, is_active_controller)
+            allowed = (is_active_controller() if callable(is_active_controller)
+                       else is_active_controller)
+            return self._handle(msg, allowed)
 
     def _handle(self, msg, is_active_controller):
         if not is_active_controller:
--- a/src/screenshare/server.py
+++ b/src/screenshare/server.py
@@ -32,6 +32,7 @@
         self.addr = addr
         self.name = None
         self.authenticated = False
+        self.admitted = False              # slot taken under _sessions_lock before JOIN_ACCEPT
         self.bad_codes = 0
         # One Outbox per connection (section 7.6 rule 1): ordered control messages
         # plus one latest frame that is replaced instead of queued.
@@ -180,6 +181,9 @@
         """Returns an error string on failure (GUI shows it), or None on success."""
         if self.state != "stopped":
             return None
+        problem = self._probe_frame()          # fail early, before any Viewer is told it is watching
+        if problem:
+            return "Screen capture is not available: %s" % problem
         listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
         try:
             listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
@@ -343,7 +347,9 @@
                     except OSError:
                         pass
                     break
-                if len(self._sessions) >= config.MAX_VIEWERS:
+                # Spec 5.8 step 5: the Viewer limit counts JOINED Viewers. This
+                # accept-time cap only bounds sockets that are still waiting for JOIN.
+                if len(self._sessions) >= config.MAX_VIEWERS + config.MAX_PENDING_JOINS:
                     denied = True
                 else:
                     denied = False
@@ -427,7 +433,9 @@
                     break                      # stream is unsynchronised; just close
                 if not self._dispatch(session, msg):
                     break
-        except (OSError, protocol.ProtocolError) as exc:
+        except (OSError, protocol.ProtocolError, protocol.ConnectionClosed) as exc:
+            # ConnectionClosed is not an OSError; a Viewer that hangs up during the
+            # JOIN phase (Test-NetConnection, a port probe, a closed laptop) is normal.
             logger.info("reader for %s ended: %r", session.display, exc)
         finally:
             session.close()
@@ -470,6 +478,16 @@
                                % (session.addr[0], session.bad_codes))
                     return False
                 continue                       # retry allowed while attempts remain
+            # Spec 5.8 step 5, after the code check: take a Viewer slot atomically,
+            # so two simultaneous JOINs cannot both get the last one.
+            with self._sessions_lock:
+                full = sum(1 for s in self._sessions.values() if s.admitted) >= config.MAX_VIEWERS
+                if not full:
+                    session.admitted = True
+            if full:
+                self._emit("log", "Connection from %s refused: viewer limit reached" % session.addr[0])
+                self._send(session, {"type": "JOIN_DENIED", "reason": "viewer_limit_reached"})
+                return False
             # Authenticated.
             session.name = name
             session.sock.settimeout(None)      # C9: after JOIN_ACCEPT
@@ -518,12 +536,16 @@
             if self.perm.release(session.id):
                 self.remote_input.release_all()
                 self._broadcast_status()
+            elif self.perm.cancel_pending(session.id):
+                self._emit("log", "%s cancelled the control request" % session.display)
+                self._broadcast_status()       # Host Approve/Deny buttons disable
             return True
         if mtype in INPUT_TYPES:
             # Permission is re-checked for EVERY input event (rule 6.3 #8).
-            if not self.perm.is_active(session.id):
-                return True                    # stale input after revoke: dropped silently
-            result = self.remote_input.handle(msg, True)
+            # The callable is evaluated inside input_lock (see RemoteInput.handle),
+            # so revoke_control() cannot interleave between check and injection.
+            result = self.remote_input.handle(
+                msg, lambda: self.perm.is_active(session.id))
             if result == "rejected":
                 # Well-formed message with bad values: answer invalid_input and keep
                 # the session open (section 5.8).
@@ -536,8 +558,14 @@
 
     def _capture_loop(self, stop_event):
         source = None
+        failures = 0
         try:
-            source = self._frame_factory()
+            try:
+                source = self._frame_factory()
+            except Exception as exc:
+                logger.exception("screen capture could not start")
+                self._emit("warning", "Screen capture could not start: %s" % exc)
+                return
             pacer = screen_capture.FramePacer(config.TARGET_FPS)
             while not stop_event.is_set():
                 if not self._any_authenticated():
@@ -548,8 +576,12 @@
                     result = source()
                 except Exception:
                     logger.exception("screen capture failed")
+                    failures += 1
+                    if failures == 5:          # warn once, not on every retry
+                        self._emit("warning", "Screen capture keeps failing; Viewers receive no new frames")
                     time.sleep(0.5)
                     continue
+                failures = 0
                 if result is None:
                     continue
                 data, size = result
@@ -570,7 +602,8 @@
     # ---------------- helpers ----------------
 
     def _probe_frame(self):
-        """One-shot capture so a first JOIN_ACCEPT can carry the real frame size."""
+        """One-shot capture so a first JOIN_ACCEPT can carry the real frame size.
+        Returns None on success or an error string."""
         try:
             source = self._frame_factory()
             try:
@@ -581,8 +614,10 @@
             if result is not None:
                 with self._frame_lock:
                     self._last_frame, self._last_frame_size = result
-        except Exception:
+            return None
+        except Exception as exc:
             logger.warning("initial frame probe failed", exc_info=True)
+            return str(exc) or type(exc).__name__
 
     def _any_authenticated(self):
         with self._sessions_lock:
@@ -642,7 +677,11 @@
             self.remote_input.release_all()    # held keys/buttons released (9.5)
         if session.authenticated:
             self._emit("log", "Viewer '%s' disconnected (%s)" % (session.name, reason))
-        self._broadcast_status()
+            self._broadcast_status()           # S-2: a never-joined socket changes nothing
+            if not self._any_authenticated():
+                # The capture loop idles with no Viewer, so nobody else would clear
+                # the Host table and totals.
+                self._emit("stats", {"viewers": [], "fps": 0.0, "kbps": 0.0})
 
     def _emit(self, kind, data):
         self.events.put((kind, data))
```

### What each hunk does

| Defect | Files | Change |
|---|---|---|
| **DEF-1** input after revoke | `remote_input.py`, `server.py` | `RemoteInput.handle()` accepts a bool **or a callable** and evaluates it **inside `input_lock`**. `_dispatch` passes `lambda: self.perm.is_active(session.id)`. Check and injection are one atomic step, so a revoke cannot land in between and leave a key held. Lock order is `input_lock → perm._lock`; nothing takes them in the opposite order (`revoke_control` calls `clear_active()` first, releases that lock, then `release_all()`). |
| **DEF-2** thread traceback | `server.py` | `_reader_loop` also catches `protocol.ConnectionClosed` (it is not an `OSError`). `protocol.py` is untouched. |
| **DEF-3** cancel pending | `permissions.py`, `server.py`, `client.py`, `gui.py` | New `PermissionManager.cancel_pending()`; Host handles `CONTROL_RELEASE` from a pending Viewer, logs it and broadcasts `STATUS` (the Host GUI already disables Approve/Deny when `pending_requester` is `None`). `ViewerClient.release_control()` works in `CONTROLLING` and `REQUEST_PENDING`. `CONTROL_GRANTED` is honoured only in `REQUEST_PENDING` (a cancel can cross a grant on the wire). GUI shows "Cancel Request". |
| **DEF-4** slots | `config.py`, `server.py` | `ViewerSession.admitted`; the limit is checked **after the code check, under `_sessions_lock`** (spec 5.8 step 5), so two simultaneous JOINs cannot both take the last slot. Accept-time cap is `MAX_VIEWERS + MAX_PENDING_JOINS`. |
| **DEF-5** capture failure | `server.py` | `_probe_frame()` returns an error string; `start_sharing()` returns `"Screen capture is not available: …"` (the GUI already shows that string in a message box). The capture thread emits a `warning` if the source cannot be created, and once after 5 consecutive failed frames. |
| **DEF-6** stale stats | `server.py` | `_cleanup_session` emits an empty `stats` event when the last Viewer leaves. It does **not** call `stats_snapshot()` from the reader thread, because that method owns a rate window documented as capture-thread-only. |
| **S-1** | `client.py` | The two identical `JOIN_DENIED` branches are one. |
| **S-2** | `server.py` | A socket that never authenticated no longer triggers a `STATUS` broadcast. |

## 4. The tests (`tests/test_audit_fixes.py`)

```python
# file: tests/test_audit_fixes.py
"""Regression tests for the audit defects DEF-1 .. DEF-6 (see REQUIREMENTS_FOR_AGENT.md).
Real TCP on 127.0.0.1:5057, fake input backend and fake frames: no real mouse, no display."""
import queue
import socket
import threading
import time
import types
import unittest

from screenshare import client as client_mod
from screenshare import config, protocol
from screenshare.outbox import Outbox
from screenshare.permissions import PermissionManager
from screenshare.server import HostServer
from tests.test_permissions import FakeFrameSource, FakeInputBackend

TEST_PORT = 5057          # not 5000, so a running Host or the other tests never collide


def wait_for(predicate, timeout=3.0, step=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


class HostCase(unittest.TestCase):
    """A started HostServer on TEST_PORT; any exception escaping a thread is recorded."""

    def setUp(self):
        self._old_port = config.PORT
        config.PORT = TEST_PORT
        self.events = queue.Queue()
        self.backend = FakeInputBackend()
        self.srv = HostServer(self.events, input_backend=self.backend,
                              frame_factory=FakeFrameSource)
        self.assertIsNone(self.srv.start_sharing())
        self.thread_errors = []
        self._old_hook = threading.excepthook
        threading.excepthook = lambda a: self.thread_errors.append(a.exc_type.__name__)
        self.socks = []

    def tearDown(self):
        for s in self.socks:
            try:
                s.close()
            except OSError:
                pass
        self.srv.stop_sharing()
        threading.excepthook = self._old_hook
        config.PORT = self._old_port

    def raw(self):
        s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=5)
        self.socks.append(s)
        return s

    def join(self, name="V", code=None):
        s = self.raw()
        s.sendall(protocol.encode_json_message({
            "type": "JOIN", "protocol_version": 1, "client_name": name,
            "session_code": code or self.srv.session_code}))
        return s

    @staticmethod
    def next_json(sock, wanted=None, timeout=4.0):
        """First JSON message (of type `wanted`, if given); JPEG frames are skipped."""
        deadline = time.monotonic() + timeout
        sock.settimeout(0.5)
        while time.monotonic() < deadline:
            try:
                mtype, payload = protocol.recv_message(sock, protocol.HOST_TO_VIEWER)
            except socket.timeout:
                continue
            if mtype == protocol.TYPE_JSON:
                msg = protocol.decode_json_payload(payload)
                if wanted is None or msg["type"] == wanted:
                    return msg
        return None

    @staticmethod
    def send(sock, message):
        sock.sendall(protocol.encode_json_message(message))


class Def1_RevokeVersusInput(HostCase):
    def test_revoke_between_check_and_inject_leaves_nothing_held(self):
        srv = self.srv
        session = types.SimpleNamespace(id="v1", display="v1")
        srv.perm.request("v1")
        srv.perm.approve("v1")
        original = srv.perm.is_active
        revokers = []

        def racing(viewer_id):
            active = original(viewer_id)
            if active and not revokers:
                t = threading.Thread(target=srv.revoke_control)   # Host clicks Revoke now
                revokers.append(t)
                t.start()
                t.join(0.5)    # old code: revoke completes here; new code: it waits for input_lock
            return active

        srv.perm.is_active = racing
        srv._dispatch(session, {"type": "KEY_DOWN", "key": "a"})
        for t in revokers:
            t.join(3)
        self.assertEqual(srv.remote_input.held, ([], []), "a key was left held after revoke")
        downs = self.backend.calls.count(("keydown", "a"))
        ups = self.backend.calls.count(("keyup", "a"))
        self.assertEqual(downs, ups)

    def test_handle_accepts_callable_and_bool(self):
        from screenshare.remote_input import RemoteInput, RESULT_OK, RESULT_NOT_CONTROLLER
        ri = RemoteInput(backend=FakeInputBackend())
        msg = {"type": "KEY_DOWN", "key": "a"}
        self.assertEqual(ri.handle(msg, lambda: True), RESULT_OK)
        self.assertEqual(ri.handle(msg, lambda: False), RESULT_NOT_CONTROLLER)
        self.assertEqual(ri.handle(msg, True), RESULT_OK)


class Def2_HangUpDuringJoin(HostCase):
    def test_connect_then_close_raises_no_thread_exception(self):
        s = self.raw()
        time.sleep(0.2)
        s.close()
        time.sleep(0.5)
        self.assertEqual(self.thread_errors, [])

    def test_close_after_a_denial_raises_no_thread_exception(self):
        s = self.join(code="WRONGWRD")
        self.assertEqual(self.next_json(s)["reason"], "invalid_session_code")
        s.close()
        time.sleep(0.5)
        self.assertEqual(self.thread_errors, [])


class Def3_CancelPendingRequest(HostCase):
    def test_permission_manager_cancel_pending(self):
        pm = PermissionManager()
        pm.request("v1")
        self.assertFalse(pm.cancel_pending("v2"))
        self.assertTrue(pm.cancel_pending("v1"))
        self.assertIsNone(pm.pending_id())
        self.assertEqual(pm.request("v2"), ("pending", None))

    def test_pending_viewer_can_cancel_over_the_wire(self):
        v1, v2 = self.join("V1"), self.join("V2")
        self.assertEqual(self.next_json(v1)["type"], "JOIN_ACCEPT")
        self.assertEqual(self.next_json(v2)["type"], "JOIN_ACCEPT")
        self.send(v1, {"type": "CONTROL_REQUEST"})
        self.assertTrue(wait_for(lambda: self.srv.perm.pending_id() is not None))
        self.send(v1, {"type": "CONTROL_RELEASE"})
        self.assertTrue(wait_for(lambda: self.srv.perm.pending_id() is None),
                        "pending request was not cleared by CONTROL_RELEASE")
        self.send(v2, {"type": "CONTROL_REQUEST"})     # V2 is no longer refused
        self.assertTrue(wait_for(lambda: self.srv.perm.pending_id() is not None))

    def test_client_release_control_cancels_a_pending_request(self):
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
        viewer.state = client_mod.REQUEST_PENDING
        viewer.outbox = Outbox()
        viewer.release_control()
        self.assertEqual(viewer.state, client_mod.VIEW_ONLY)
        kind, data = viewer.outbox.get(0.1)
        payload = data[protocol.HEADER.size:]
        self.assertEqual(protocol.decode_json_payload(payload)["type"], "CONTROL_RELEASE")

    def test_client_ignores_a_grant_that_arrives_after_cancel(self):
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
        viewer.state = client_mod.VIEW_ONLY
        self.assertTrue(viewer._handle_message({"type": "CONTROL_GRANTED"}))
        self.assertEqual(viewer.state, client_mod.VIEW_ONLY)

    def test_client_release_does_nothing_in_view_only(self):
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
        viewer.state = client_mod.VIEW_ONLY
        viewer.outbox = Outbox()
        viewer.release_control()
        self.assertIsNone(viewer.outbox.get(0.05))


class Def4_ViewerSlots(HostCase):
    def test_idle_sockets_do_not_take_viewer_slots(self):
        self.raw()
        self.raw()                      # two sockets that never send JOIN
        time.sleep(0.2)
        v = self.join("Real")
        self.assertEqual(self.next_json(v)["type"], "JOIN_ACCEPT")

    def test_third_joined_viewer_is_still_denied(self):
        v1, v2 = self.join("V1"), self.join("V2")
        self.assertEqual(self.next_json(v1)["type"], "JOIN_ACCEPT")
        self.assertEqual(self.next_json(v2)["type"], "JOIN_ACCEPT")
        v3 = self.join("V3")
        msg = self.next_json(v3)
        self.assertEqual((msg["type"], msg["reason"]), ("JOIN_DENIED", "viewer_limit_reached"))

    def test_waiting_sockets_are_bounded(self):
        for _ in range(config.MAX_VIEWERS + config.MAX_PENDING_JOINS):
            self.raw()
        time.sleep(0.3)
        extra = self.raw()
        msg = self.next_json(extra)
        self.assertEqual(msg["reason"], "viewer_limit_reached")

    def test_wrong_code_is_reported_before_the_limit(self):
        v1, v2 = self.join("V1"), self.join("V2")
        self.next_json(v1)
        self.next_json(v2)
        v3 = self.join("V3", code="WRONGWRD")
        self.assertEqual(self.next_json(v3)["reason"], "invalid_session_code")


class Def5_CaptureFailure(unittest.TestCase):
    def setUp(self):
        self._old_port = config.PORT
        config.PORT = TEST_PORT

    def tearDown(self):
        config.PORT = self._old_port

    def test_start_sharing_refuses_when_capture_cannot_work(self):
        def broken():
            raise RuntimeError("no display")
        srv = HostServer(queue.Queue(), input_backend=FakeInputBackend(), frame_factory=broken)
        error = srv.start_sharing()
        self.assertIn("Screen capture", error)
        self.assertEqual(srv.state, "stopped")

    def test_repeated_capture_failures_reach_the_host(self):
        broken = threading.Event()

        class Source:
            def __init__(self):
                self.good = FakeFrameSource()

            def __call__(self):
                if broken.is_set():
                    raise RuntimeError("capture lost")
                return self.good()

            def close(self):
                pass

        events = queue.Queue()
        srv = HostServer(events, input_backend=FakeInputBackend(), frame_factory=Source)
        self.assertIsNone(srv.start_sharing())
        s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=5)
        try:
            s.sendall(protocol.encode_json_message({
                "type": "JOIN", "protocol_version": 1, "client_name": "V",
                "session_code": srv.session_code}))
            time.sleep(0.5)
            broken.set()
            found = []

            def seen():
                while not events.empty():
                    kind, data = events.get()
                    if kind == "warning":
                        found.append(data)
                return bool(found)

            self.assertTrue(wait_for(seen, timeout=9.0), "no capture warning reached the Host")
            self.assertIn("Screen capture", found[0])
        finally:
            s.close()
            srv.stop_sharing()


class Def6_StatsAfterLastViewerLeaves(HostCase):
    def test_cleanup_emits_stats_with_no_viewers(self):
        v = self.join("V")
        self.assertEqual(self.next_json(v)["type"], "JOIN_ACCEPT")
        time.sleep(0.6)
        while not self.events.empty():
            self.events.get()
        self.send(v, {"type": "DISCONNECT", "reason": "user_exit"})
        v.close()
        got = []

        def saw_empty_stats():
            while not self.events.empty():
                kind, data = self.events.get()
                if kind == "stats" and data["viewers"] == []:
                    got.append(data)
            return bool(got)

        self.assertTrue(wait_for(saw_empty_stats, timeout=3.0),
                        "Host GUI never told that the last Viewer left")


if __name__ == "__main__":
    unittest.main()
```

How the key tests work, so nobody "fixes" them away:
- **DEF-1** forces the race deterministically: the permission check returns `True`, then a thread runs `revoke_control()` and the check waits up to 0.5 s. With the old code the revoke finishes first and the key is injected afterwards (held forever). With the new code the revoke blocks on `input_lock`, the injection completes, then the revoke releases it. Invariant checked: `held == ([], [])` and every key-down has a key-up.
- **DEF-2** installs `threading.excepthook` and fails if any worker thread dies with an exception.
- **DEF-5** second test needs about 3 s (five failed frames at 0.5 s each).

## 5. Remaining text fixes (docs only, exact replacements)

1. `README.md`, "How it works", Host pipeline bullet. Replace
   `each Viewer's writer sends the newest frame from a one-item `LatestSlot` (no queue buildup), after draining pending control messages.`
   with
   `each Viewer has one `Outbox` (control messages first, plus a single latest-frame slot that is replaced, never queued); that Viewer's writer thread sends from it, so a slow Viewer cannot build up a backlog.`
2. `README.md` project tree: under `tests/` add `test_audit_fixes.py   # regression tests for the audit defects (DEF-1..DEF-6)`.
3. `SETUP_GUIDE.md` §9 and §13: change "64 passing" to "80 passing"; the breakdown becomes 18 + 12 + 34 + 16.
4. `docs/test_results.md`: add a new section at the end, **only with outputs you really ran on your laptop**: the `Ran 80 tests` line, the red→green output, and the manual checks from section 6. Put one line at the top: `Current suite: 80 tests (sections 1, 6 and 9 describe earlier builds).`
5. `README.md`, Known limitations: add `The mode argument is optional: with no or an unknown mode a Host/Viewer chooser opens (the spec says to print usage; this was a deliberate choice).` (S-3, so spec, README and code agree.)
6. Ask before touching S-6 (`network-screen-sharing-starter/` inside the repo). It holds the old restrictive `AGENTS.md`, an identical copy of the architecture, and the flat modules.

## 6. Manual checks on the Windows laptops (**[U]**, not verifiable in the sandbox)

Record each result honestly in `docs/test_results.md`.

| # | Do | Expect |
|---|---|---|
| M-1 | Viewer: Connect, click **Request Control**, then click the button that now says **Cancel Request** | Viewer returns to `view-only`; Host text returns to "No pending control request." and Approve/Deny grey out; a second Viewer can now request. (Tk change is compile-checked only.) |
| M-2 | From a Viewer laptop run `Test-NetConnection <host-ip> -Port 5000` while the Host console is visible | `TcpTestSucceeded : True`, **no traceback** on the Host console, both Viewer slots still free |
| M-3 | Host: stop sharing, temporarily make capture fail if you can (for example run the Host as a service session without a desktop) | `Start Sharing` shows "Screen capture is not available: …" |
| M-4 | One Viewer connects, then closes its window | Host table row and `Total` line clear within a second |
| M-5 | Real Host + Viewer on **two laptops**, grant control, type, then Revoke while typing fast | No key stays pressed on the Host afterwards (open Notepad, type, check nothing repeats) |
| M-6 | Python **3.10** if you want to keep `requires-python = ">=3.10"` | Suite passes; otherwise raise the minimum to what you tested |
| M-7 | Demo evidence E-1 … E-8 from `REQUIREMENTS_FOR_AGENT.md` section 5 | Wireshark `.pcapng`, FIN proof, flow-control run, firewall rule on the second machine |

## 7. Root files so opencode actually reads instructions (S-7)

The repo root has no `AGENTS.md` and no `opencode.jsonc`, so opencode loads nothing. Create both at the **repository root**. The old copy under `network-screen-sharing-starter/` is not loaded and is the old, restrictive version.

### `AGENTS.md`

````markdown
# AGENTS.md: Network Screen Sharing and Remote Control (VTU BCS502)

Marked on the application working (5) and a live demonstration (5). A smaller design that works every time beats a larger one that fails once.

## Mode: fix and verify (the application already exists)
1. Read `REQUIREMENTS_FOR_AGENT.md`, then `AGENT_FIX_GUIDE.md`. Apply the patch and tests exactly as written; if anything does not apply or a test result differs from what the guide states, stop and report it. Do not improvise a different fix.
2. `ARCHITECTURE_FINAL_v5.md` is the spec of record and read-only. If it is wrong or silent on something that matters, stop and ask the student. Never invent a protocol, port, dependency or feature.
3. Fixed facts: TCP port 5000, one connection per Viewer, max 2 Viewers, 5-byte header `!BI`, type 1 JSON / 2 JPEG, runtime packages `mss`, `Pillow`, `PyAutoGUI` only, PyAutoGUI `FAILSAFE = True`.
4. Provided reference modules (`protocol.py`, `latest_slot.py`, `outbox.py`, `keymap.py`, `geometry.py`): ask before changing existing code. `demo/transport_demos.py` is never edited.
5. Automated tests never move the real mouse and never grant control on the student's PC. Stop any running Host before the suite (it uses port 5000).

## Tools: use all of them
Run `opencode2 mcp list` once at the start; skip servers that show failed (obsidian is currently failing). Use the others on every task and say in the report what each showed.
| Tool | Use |
|---|---|
| Serena | find every caller before changing a function; check nothing else uses what you remove |
| Context7 | check the exact API of `mss`, `Pillow`, `PyAutoGUI`, `tkinter` before writing a call you are unsure of; tell the student if it differs from the spec |
| Snyk | scan code and `pyproject.toml` after changes; report findings; the plaintext session code is a documented limit |
| GitHub | read similar projects or issues; commit on a branch; never push without the student |
| Memory | short notes on decisions and current step, no session codes |
| Plannotator | submit a plan for review before any change that is not in the guide |
| Firecrawl | research when asked or when a fact is uncertain; never override the spec because of a search result |
| windows-mcp / win32 | screenshot the Host and Viewer windows to check layout, the Cancel Request button and the stats panel; announce before clicking; never grant control while clicking |
| Playwright / chrome-devtools | only if useful (for example to open exported reports) |

## Loop
1. Say which step you start. 2. Make the change. 3. Run `.\.venv\Scripts\python.exe -m unittest discover -s tests`. 4. Report: files changed, exact command, last lines of output, tools used, remaining [U] items. 5. Stop and wait for "continue".

## Windows commands
```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; python -m pip install -e .
python -m unittest discover -s tests
screenshare host      # Host laptop
screenshare viewer    # each Viewer laptop
```
````

### `opencode.jsonc`

```jsonc
// Last matching rule wins, so broad rules come first. Shape checked against the opencode permissions docs; PowerShell command patterns are untested.
{
  "$schema": "https://opencode.ai/config.json",
  "permissions": [
    { "action": "shell", "resource": "*", "effect": "ask" },
    { "action": "shell", "resource": ".\\.venv\\Scripts\\python.exe -m unittest *", "effect": "allow" },
    { "action": "shell", "resource": "python -m unittest *", "effect": "allow" },
    { "action": "shell", "resource": "python -m compileall *", "effect": "allow" },
    { "action": "shell", "resource": "git status *", "effect": "allow" },
    { "action": "shell", "resource": "git diff *", "effect": "allow" },
    { "action": "shell", "resource": "git log *", "effect": "allow" },
    { "action": "shell", "resource": "git push *", "effect": "deny" },
    { "action": "shell", "resource": "git reset --hard *", "effect": "deny" },
    { "action": "shell", "resource": "Remove-Item *", "effect": "deny" },
    { "action": "edit", "resource": "ARCHITECTURE_FINAL_v5.md", "effect": "deny" },
    { "action": "edit", "resource": "demo/transport_demos.py", "effect": "deny" },
    { "action": "edit", "resource": "src/screenshare/protocol.py", "effect": "ask" },
    { "action": "edit", "resource": "src/screenshare/outbox.py", "effect": "ask" },
    { "action": "edit", "resource": "src/screenshare/latest_slot.py", "effect": "ask" },
    { "action": "edit", "resource": "src/screenshare/keymap.py", "effect": "ask" },
    { "action": "edit", "resource": "src/screenshare/geometry.py", "effect": "ask" }
  ]
}
```

Nothing here restricts which MCP servers or plugins the agent may use. Only dangerous shell commands (push, hard reset, delete) and the read-only spec are guarded.

## 8. Prompt to paste into `opencode2`

```text
Read AGENTS.md, then REQUIREMENTS_FOR_AGENT.md, then AGENT_FIX_GUIDE.md.
Create a branch fix/audit-defects. Apply the patch in section 3 of the guide with git apply, add the test file from section 4, and run the full suite.
Expected: 80 tests OK. Then do the red->green check from section 2.
Use every available MCP server and plugin to check your own work: Serena for callers of RemoteInput.handle and release_control, Context7 for any API you are unsure of, Snyk for a new code and dependency scan, and windows-mcp or win32 to screenshot the Host and Viewer windows if the display is available. Say what each one showed.
Then make the documentation edits in section 5. Do not touch the demo file or the spec. Report files changed, the exact commands with the last lines of output, tools used, and the manual checks in section 6 that I still have to run on the laptops. Stop after the report.
```
