# file: tests/test_permissions.py
"""Single-controller permission rules (section 6.3) and the request->grant->input->
revoke flow with a fake input backend. No real remote-control actions happen here
(module boundary table, section 14.1)."""
import os
import queue
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remote_input import RemoteInput, RESULT_OK, RESULT_NOT_CONTROLLER, RESULT_REJECTED
from server import PermissionManager, HostServer


class PermissionRules(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager()

    def test_first_request_becomes_pending(self):
        self.assertEqual(self.pm.request("v1"), ("pending", None))
        self.assertEqual(self.pm.pending_id(), "v1")
        self.assertIsNone(self.pm.active_id())

    def test_second_request_denied_while_pending(self):
        self.pm.request("v1")
        self.assertEqual(self.pm.request("v2"), ("deny", "request_pending"))

    def test_request_denied_while_controller_active(self):
        self.pm.request("v1")
        self.assertEqual(self.pm.approve("v1"), "granted")
        self.assertEqual(self.pm.request("v2"), ("deny", "controller_busy"))

    def test_approve_activates_controller(self):
        self.pm.request("v1")
        self.assertEqual(self.pm.approve("v1"), "granted")
        self.assertEqual(self.pm.active_id(), "v1")
        self.assertIsNone(self.pm.pending_id())

    def test_approve_is_rechecked(self):
        self.pm.request("v1")
        self.assertEqual(self.pm.approve("v1", is_connected=lambda vid: False), "gone")
        self.assertIsNone(self.pm.pending_id())
        self.assertIsNone(self.pm.active_id())

    def test_reject_clears_pending(self):
        self.pm.request("v1")
        self.assertEqual(self.pm.reject(), "v1")
        self.assertIsNone(self.pm.pending_id())
        # After rejection another viewer may request.
        self.assertEqual(self.pm.request("v2"), ("pending", None))

    def test_revoke_clears_active(self):
        self.pm.request("v1")
        self.pm.approve("v1")
        self.assertEqual(self.pm.clear_active(), "v1")
        self.assertIsNone(self.pm.active_id())
        self.assertEqual(self.pm.request("v2"), ("pending", None))

    def test_voluntary_release(self):
        self.pm.request("v1")
        self.pm.approve("v1")
        self.assertTrue(self.pm.release("v1"))
        self.assertFalse(self.pm.release("v2"))   # not the controller anymore

    def test_disconnect_of_controller_clears_state(self):
        self.pm.request("v1")
        self.pm.approve("v1")
        was_pending, was_active = self.pm.drop("v1")
        self.assertEqual((was_pending, was_active), (False, True))
        self.assertIsNone(self.pm.active_id())

    def test_disconnect_of_pending_viewer(self):
        self.pm.request("v1")
        was_pending, was_active = self.pm.drop("v1")
        self.assertEqual((was_pending, was_active), (True, False))
        self.assertIsNone(self.pm.pending_id())

    def test_is_active_and_permission_recheck(self):
        self.assertFalse(self.pm.is_active("v1"))
        self.pm.request("v1")
        self.pm.approve("v1")
        self.assertTrue(self.pm.is_active("v1"))
        self.pm.clear_active()
        self.assertFalse(self.pm.is_active("v1"))


class FakeInputBackend:
    """Records actions; never touches the OS."""

    def __init__(self, screen=(1920, 1080)):
        self.screen = screen
        self.calls = []
        self.failsafe_points = [(0, 0), (0, screen[1] - 1),
                                (screen[0] - 1, 0), (screen[0] - 1, screen[1] - 1)]

    def size(self):
        return self.screen

    def move_to(self, x, y):
        self.calls.append(("move", x, y))

    def mouse_down(self, x, y, button):
        self.calls.append(("down", x, y, button))

    def mouse_up(self, button):
        self.calls.append(("up", button))

    def scroll(self, clicks):
        self.calls.append(("scroll", clicks))

    def key_down(self, key):
        self.calls.append(("keydown", key))

    def key_up(self, key):
        self.calls.append(("keyup", key))


class InputValidation(unittest.TestCase):
    def setUp(self):
        self.backend = FakeInputBackend()
        self.ri = RemoteInput(backend=self.backend)

    def test_only_active_controller_acts(self):
        result = self.ri.handle({"type": "MOUSE_MOVE", "x": 0.5, "y": 0.5}, False)
        self.assertEqual(result, RESULT_NOT_CONTROLLER)
        self.assertEqual(self.backend.calls, [])

    def test_move_maps_normalized_to_pixels(self):
        self.assertEqual(
            self.ri.handle({"type": "MOUSE_MOVE", "x": 0.5, "y": 0.5}, True), RESULT_OK)
        self.assertEqual(self.backend.calls, [("move", 959, 539)])

    def test_move_corners_avoid_fail_safe(self):
        self.ri.handle({"type": "MOUSE_MOVE", "x": 0.0, "y": 0.0}, True)
        self.ri.handle({"type": "MOUSE_MOVE", "x": 1.0, "y": 1.0}, True)
        moves = [c for c in self.backend.calls if c[0] == "move"]
        self.assertIn(("move", 1, 1), moves)
        self.assertIn(("move", 1918, 1078), moves)

    def test_move_out_of_range_rejected(self):
        for x, y in ((-0.1, 0.5), (1.1, 0.5), (0.5, "a"), (None, 0.5)):
            self.assertEqual(
                self.ri.handle({"type": "MOUSE_MOVE", "x": x, "y": y}, True),
                RESULT_REJECTED)
        self.assertEqual(self.backend.calls, [])

    def test_bad_button_and_action_rejected(self):
        for msg in ({"type": "MOUSE_BUTTON", "button": "middle", "action": "down",
                     "x": 0.5, "y": 0.5},
                    {"type": "MOUSE_BUTTON", "button": "left", "action": "click",
                     "x": 0.5, "y": 0.5}):
            self.assertEqual(self.ri.handle(msg, True), RESULT_REJECTED)

    def test_scroll_uses_120_per_notch(self):
        self.assertEqual(
            self.ri.handle({"type": "SCROLL", "amount": 2, "x": 0.5, "y": 0.5}, True),
            RESULT_OK)
        scroll = [c for c in self.backend.calls if c[0] == "scroll"]
        self.assertEqual(scroll, [("scroll", 240)])

    def test_scroll_bad_amount_rejected(self):
        for amount in (0, 2.5, "2", True, 999):
            self.assertEqual(
                self.ri.handle({"type": "SCROLL", "amount": amount, "x": 0.5, "y": 0.5},
                               True), RESULT_REJECTED)

    def test_key_allowlist_enforced(self):
        self.assertEqual(self.ri.handle({"type": "KEY_DOWN", "key": "enter"}, True),
                         RESULT_OK)
        self.assertEqual(self.ri.handle({"type": "KEY_DOWN", "key": "f5"}, True),
                         RESULT_REJECTED)
        self.assertEqual(self.ri.handle({"type": "KEY_DOWN", "key": "ctrl"}, True),
                         RESULT_REJECTED)

    def test_release_suspends_and_restores_failsafe(self):
        """Section 9.7: releasing held input is the only place the fail-safe is
        suspended, and it is always restored afterwards."""
        class Backend(FakeInputBackend):
            def __init__(self):
                super().__init__()
                self.failsafe = True
                self.states = []

            def set_failsafe(self, enabled):
                self.failsafe = enabled
                self.states.append(enabled)

        backend = Backend()
        ri = RemoteInput(backend=backend)
        ri.handle({"type": "KEY_DOWN", "key": "shift"}, True)
        ri.handle({"type": "MOUSE_BUTTON", "button": "left", "action": "down",
                   "x": 0.5, "y": 0.5}, True)
        ri.release_all()
        self.assertEqual(backend.states, [False, True])
        self.assertTrue(backend.failsafe)
        self.assertEqual(ri.held, ([], []))
        self.assertIn(("keyup", "shift"), backend.calls)
        self.assertIn(("up", "left"), backend.calls)

    def test_failsafe_trip_releases_held_input_and_reports(self):
        class FailSafeException(Exception):
            pass

        class Backend(FakeInputBackend):
            def __init__(self):
                super().__init__()
                self.states = []

            def set_failsafe(self, enabled):
                self.states.append(enabled)

            def move_to(self, x, y):
                raise FailSafeException("pointer in a corner")

        backend = Backend()
        ri = RemoteInput(backend=backend)
        ri.handle({"type": "KEY_DOWN", "key": "shift"}, True)
        result = ri.handle({"type": "MOUSE_MOVE", "x": 0.5, "y": 0.5}, True)
        self.assertEqual(result, "failsafe")
        self.assertEqual(ri.held, ([], []))
        self.assertEqual(backend.states, [False, True])

    def test_out_of_range_is_rejected_not_clamped(self):
        """Section 9.3: the Host does not clamp; an out-of-range coordinate is invalid."""
        self.assertEqual(
            self.ri.handle({"type": "MOUSE_MOVE", "x": 1.5, "y": 0.5}, True), RESULT_REJECTED)
        self.assertEqual(self.backend.calls, [])

    def test_held_keys_and_buttons_released(self):
        self.ri.handle({"type": "KEY_DOWN", "key": "shift"}, True)
        self.ri.handle({"type": "MOUSE_BUTTON", "button": "left", "action": "down",
                        "x": 0.5, "y": 0.5}, True)
        self.assertEqual(self.ri.held, (["shift"], ["left"]))
        self.ri.release_all()
        self.assertEqual(self.ri.held, ([], []))
        ups = [c for c in self.backend.calls if c[0] in ("keyup", "up")]
        self.assertEqual(sorted(ups), [("keyup", "shift"), ("up", "left")])


class DisconnectMessage(unittest.TestCase):
    """Section 11.3: a normal Viewer exit must actually send DISCONNECT."""

    def test_disconnect_is_sent_before_close(self):
        import socket
        import client as client_mod
        import config
        import protocol

        received = []
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def serve():
            conn, _ = listener.accept()
            try:
                while True:
                    _mtype, payload = protocol.recv_message(conn, protocol.VIEWER_TO_HOST)
                    received.append(protocol.decode_json_payload(payload)["type"])
            except (protocol.ConnectionClosed, OSError):
                pass
            finally:
                conn.close()
                listener.close()

        threading.Thread(target=serve, daemon=True).start()
        original_port = config.PORT
        config.PORT = port
        try:
            viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
            viewer.connect("127.0.0.1", "CODE")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and "JOIN" not in received:
                time.sleep(0.02)
            self.assertIn("JOIN", received)
            viewer.disconnect()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and "DISCONNECT" not in received:
                time.sleep(0.02)
            self.assertEqual(received, ["JOIN", "DISCONNECT"])
        finally:
            config.PORT = original_port


class ClientState(unittest.TestCase):
    def test_release_control_returns_to_view_only(self):
        """Section 6.2: CONTROLLING -> VIEW_ONLY on CONTROL_RELEASE."""
        import client as client_mod
        from outbox import Outbox
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
        viewer.state = client_mod.CONTROLLING
        viewer.outbox = Outbox()
        viewer.release_control()
        self.assertEqual(viewer.state, client_mod.VIEW_ONLY)
        kind, data = viewer.outbox.get(0.1)
        self.assertEqual(kind, "control")
        import protocol
        mtype, length = protocol.HEADER.unpack(data[:protocol.HEADER.size])
        self.assertEqual((mtype, length), (protocol.TYPE_JSON, len(data) - protocol.HEADER.size))
        payload = data[protocol.HEADER.size:]
        self.assertEqual(protocol.decode_json_payload(payload)["type"], "CONTROL_RELEASE")

    def test_duplicate_control_denied_keeps_control(self):
        """A late CONTROL_DENIED must not drop a Viewer the Host already granted."""
        import client as client_mod
        from outbox import Outbox
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
        viewer.state = client_mod.CONTROLLING
        viewer.outbox = Outbox()
        keep = viewer._handle_message({"type": "CONTROL_DENIED", "reason": "controller_busy"})
        self.assertTrue(keep)
        self.assertEqual(viewer.state, client_mod.CONTROLLING)

    def test_request_control_only_from_view_only(self):
        """CONTROL_REQUEST must not be queued while already controlling."""
        import client as client_mod
        from outbox import Outbox
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop D")
        viewer.state = client_mod.CONTROLLING
        viewer.outbox = Outbox()
        viewer.request_control()
        self.assertIsNone(viewer.outbox.get(0.05))
        self.assertEqual(viewer.state, client_mod.CONTROLLING)


class FakeFrameSource:
    """Deterministic tiny frames; no MSS, no display."""

    def __init__(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (200, 30, 30)).save(buf, format="JPEG")
        self.jpeg = buf.getvalue()

    def __call__(self):
        return self.jpeg, (64, 48)

    def close(self):
        pass


class EndToEndFlow(unittest.TestCase):
    """Two ViewerClient cores against a real HostServer on 127.0.0.1, with fake
    input injection and fake frames (local integration test, section 18.2)."""

    @classmethod
    def setUpClass(cls):
        cls.server_events = queue.Queue()
        cls.backend = FakeInputBackend()
        cls.server = HostServer(cls.server_events, input_backend=cls.backend,
                                frame_factory=FakeFrameSource)
        error = cls.server.start_sharing()
        if error:
            raise unittest.SkipTest("cannot listen on port 5000: %s" % error)
        cls.code = cls.server.session_code

    @classmethod
    def tearDownClass(cls):
        cls.server.stop_sharing()

    def connect_viewer(self, name):
        import client as client_mod
        events = queue.Queue()
        viewer = client_mod.ViewerClient(events, name)
        viewer.connect("127.0.0.1", self.code)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if viewer.state == client_mod.VIEW_ONLY:
                return viewer, events
            if viewer.state == client_mod.DISCONNECTED:
                self.fail("viewer %s dropped during join" % name)
            time.sleep(0.02)
        self.fail("viewer %s never reached view-only" % name)

    def drain(self, events, kind, timeout=3.0):
        """Return the newest event of `kind` seen before the deadline."""
        found = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                k, data = events.get(timeout=0.05)
            except queue.Empty:
                continue
            if k == kind:
                found = data
        return found

    def wait_frame(self, viewer, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image = viewer.image_slot.take(timeout=0.05)
            if image is not None:
                return image
        self.fail("no frame received")

    def test_join_accept_is_first_message(self):
        """The first bytes a Viewer sees must be JOIN_ACCEPT, never a JPEG frame
        (the cached frame is queued right behind it, section 8.2)."""
        import protocol
        import socket
        sock = socket.create_connection(("127.0.0.1", 5000), timeout=5)
        try:
            sock.sendall(protocol.encode_json_message({
                "type": "JOIN", "protocol_version": 1,
                "client_name": "Laptop Z", "session_code": self.code}))
            mtype, payload = protocol.recv_message(sock, protocol.HOST_TO_VIEWER)
            self.assertEqual(mtype, protocol.TYPE_JSON)
            self.assertEqual(protocol.decode_json_payload(payload)["type"], "JOIN_ACCEPT")
        finally:
            sock.close()

    def test_join_rejects_empty_and_non_ascii_code(self):
        """An empty or non-ASCII session code is refused without killing the Host
        (compare_digest raises TypeError on non-ASCII text)."""
        import protocol
        import socket
        for code in ("", "\u00c9" * 8):
            sock = socket.create_connection(("127.0.0.1", 5000), timeout=5)
            try:
                sock.sendall(protocol.encode_json_message({
                    "type": "JOIN", "protocol_version": 1,
                    "client_name": "Laptop Zed", "session_code": code}))
                mtype, payload = protocol.recv_message(sock, protocol.HOST_TO_VIEWER)
                self.assertEqual(mtype, protocol.TYPE_JSON)
                msg = protocol.decode_json_payload(payload)
                self.assertEqual(msg["type"], "JOIN_DENIED")
                self.assertEqual(msg["reason"], "invalid_session_code")
            finally:
                sock.close()
        # The Host is still serving its real code afterwards.
        v, events = self.connect_viewer("Laptop Y")
        self.wait_frame(v)
        v.disconnect()

    def test_two_viewers_share_grant_revoke(self):
        v1, e1 = self.connect_viewer("Laptop B")
        v2, e2 = self.connect_viewer("Laptop C")
        self.addCleanup(v1.disconnect)
        self.addCleanup(v2.disconnect)
        self.wait_frame(v1)
        self.wait_frame(v2)

        # Third viewer is refused (MAX_VIEWERS = 2).
        import client as client_mod
        v3_events = queue.Queue()
        v3 = client_mod.ViewerClient(v3_events, "Laptop D")
        v3.connect("127.0.0.1", self.code)
        reason = self.drain(v3_events, "join_denied")
        self.assertEqual(reason, "viewer_limit_reached")
        v3.disconnect(graceful=False)

        # Viewer 1 asks for control; the Host approves.
        v1.request_control()
        self.drain(e1, "status")
        self.server.approve_request()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and v1.state != client_mod.CONTROLLING:
            time.sleep(0.02)
        self.assertEqual(v1.state, client_mod.CONTROLLING)

        # Viewer 2 asking while a controller is active is denied immediately.
        v2.request_control()
        reason = self.drain(e2, "log")
        self.assertIn("control denied: controller_busy", reason)

        # Only the active controller's input reaches the backend. Control messages
        # (keys) are sent before the latest mouse position, so wait for both.
        v1.send_move(0.5, 0.5)
        v1.send_key("enter", down=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (
                ("keydown", "enter") in self.backend.calls
                and ("move", 959, 539) in self.backend.calls):
            time.sleep(0.02)
        self.assertIn(("keydown", "enter"), self.backend.calls)
        self.assertIn(("move", 959, 539), self.backend.calls)

        # Revocation releases held keys and returns the viewer to view-only.
        self.server.revoke_control()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and v1.state != client_mod.VIEW_ONLY:
            time.sleep(0.02)
        self.assertEqual(v1.state, client_mod.VIEW_ONLY)
        self.assertEqual(self.server.perm.active_id(), None)
        self.assertIn(("keyup", "enter"), self.backend.calls)

        # A stale input message after revocation performs nothing.
        before = len(self.backend.calls)
        v1.send_move(0.25, 0.25)
        time.sleep(0.3)
        self.assertEqual(len(self.backend.calls), before)

        # Viewer 2 may now request and be granted.
        v2.request_control()
        self.drain(e2, "status")
        self.server.approve_request()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and v2.state != client_mod.CONTROLLING:
            time.sleep(0.02)
        self.assertEqual(v2.state, client_mod.CONTROLLING)

        # Disconnecting the controller does not disturb the other viewer.
        v2.disconnect()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and v1.state == client_mod.DISCONNECTED:
            time.sleep(0.02)
        self.assertEqual(v1.state, client_mod.VIEW_ONLY)
        v1.disconnect()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, names = self.server.status_snapshot()
            if status["viewer_count"] == 0:
                break
            time.sleep(0.05)
        self.assertEqual(status["viewer_count"], 0)
        self.assertIsNone(status["active_controller"])

    def test_stats_counters_and_disconnect_viewer(self):
        """Sections 10.1 / 25.3: per-Viewer peer, frames, bytes and skipped frames,
        plus the Host's Disconnect Viewer action for a silently vanished Viewer."""
        v, events = self.connect_viewer("Laptop S")
        self.addCleanup(v.disconnect)
        self.wait_frame(v)
        stats = self.server.stats_snapshot()
        row = next(r for r in stats["viewers"] if r["name"] == "Laptop S")
        self.assertTrue(row["peer"].startswith("127.0.0.1:"))
        self.assertGreater(row["frames"], 0)
        self.assertGreater(row["bytes"], 0)
        self.assertGreaterEqual(row["skipped"], 0)
        self.assertGreater(row["seconds"], 0)
        self.server.disconnect_viewer(row["id"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, _names = self.server.status_snapshot()
            if status["viewer_count"] == 0:
                break
            time.sleep(0.05)
        self.assertEqual(status["viewer_count"], 0)
        v.disconnect()

    def test_invalid_input_value_keeps_session_open(self):
        """Section 5.8: a well-formed input message with bad values is answered with
        ERROR invalid_input and the session stays open."""
        import client as client_mod
        v, events = self.connect_viewer("Laptop I")
        self.addCleanup(v.disconnect)
        v.request_control()
        self.drain(events, "status")          # wait until the Host registered the request
        self.server.approve_request()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and v.state != client_mod.CONTROLLING:
            time.sleep(0.02)
        self.assertEqual(v.state, client_mod.CONTROLLING)
        v.send_scroll(999, 0.5, 0.5)          # outside the -20..20 allowlist
        self.assertEqual(self.drain(events, "server_error"), "invalid_input")
        self.assertEqual(v.state, client_mod.CONTROLLING)
        v.send_key("enter", down=True)        # the session still carries input
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and ("keydown", "enter") not in self.backend.calls:
            time.sleep(0.02)
        self.assertIn(("keydown", "enter"), self.backend.calls)
        v.send_key("enter", down=False)
        self.server.revoke_control()
        v.disconnect()

    def test_wrong_session_code_denied_then_closed_after_three(self):
        """Host rule (sections 5.7 / 11.2 / 16): three wrong codes on one TCP
        connection get three JOIN_DENIED replies, then the connection closes."""
        import client as client_mod
        import protocol
        events = queue.Queue()
        viewer = client_mod.ViewerClient(events, "Laptop X")
        viewer.connect("127.0.0.1", "WRONGWRD")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and viewer.state != client_mod.DISCONNECTED:
            time.sleep(0.02)
        self.assertEqual(viewer.state, client_mod.DISCONNECTED)
        reason = None
        try:
            while True:
                k, data = events.get_nowait()
                if k == "join_denied":
                    reason = data
        except queue.Empty:
            pass
        self.assertEqual(reason, "invalid_session_code")

        # Raw socket: send three bad JOINs, expect three denials, then EOF.
        import socket
        sock = socket.create_connection(("127.0.0.1", 5000), timeout=5)
        try:
            for _ in range(3):
                sock.sendall(protocol.encode_json_message(
                    {"type": "JOIN", "protocol_version": 1,
                     "client_name": "Laptop X", "session_code": "BADCODE1"}))
                mtype, payload = protocol.recv_message(sock, protocol.HOST_TO_VIEWER)
                msg = protocol.decode_json_payload(payload)
                self.assertEqual(msg["type"], "JOIN_DENIED")
                self.assertEqual(msg["reason"], "invalid_session_code")
            with self.assertRaises(protocol.ConnectionClosed):
                protocol.recv_message(sock, protocol.HOST_TO_VIEWER)
        finally:
            sock.close()


class SlowViewerSetting(unittest.TestCase):
    """Section 15: SCREENSHARE_SLOW_VIEWER_MS is test-only, defaults to 0, and a
    malformed value must not stop the application from starting."""

    def test_environment_variable_is_read_safely(self):
        import importlib
        import config
        original = os.environ.get("SCREENSHARE_SLOW_VIEWER_MS")
        try:
            for value, expected in (("250", 250), ("0", 0), ("abc", 0), ("-5", 0)):
                os.environ["SCREENSHARE_SLOW_VIEWER_MS"] = value
                importlib.reload(config)
                self.assertEqual(config.DEMO_SLOW_VIEWER_MS, expected, value)
        finally:
            if original is None:
                os.environ.pop("SCREENSHARE_SLOW_VIEWER_MS", None)
            else:
                os.environ["SCREENSHARE_SLOW_VIEWER_MS"] = original
            importlib.reload(config)
        self.assertEqual(config.DEMO_SLOW_VIEWER_MS, 0)


if __name__ == "__main__":
    unittest.main()
