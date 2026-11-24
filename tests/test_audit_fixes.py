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
