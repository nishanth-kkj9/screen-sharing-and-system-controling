"""Host window redesign: pure header/duration helpers, plus GUI behaviour and one
end-to-end run (real HostServer, real ViewerClient over a loopback socket)."""
import gc
import os
import queue
import tempfile
import time
import unittest

try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
    HAVE_TK = True
except Exception:                                     # no tkinter or no display
    HAVE_TK = False

from screenshare import config
from tests.test_permissions import FakeFrameSource, FakeInputBackend

ROW = {"id": "a", "name": "Ravi-PC", "peer": "10.0.0.2:5555", "seconds": 125, "frames": 10,
       "bytes": 3 * 1024 * 1024, "skipped": 4, "rtt_ms": 1.0, "tcp": None}


class PureHelperTests(unittest.TestCase):
    def test_format_duration(self):
        from screenshare.transport_view import format_duration
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(125.9), "2:05")
        self.assertEqual(format_duration(3725), "1:02:05")
        self.assertEqual(format_duration(-4), "0:00")

    def test_header_covers_every_state_and_priority(self):
        from screenshare.transport_view import host_header
        self.assertEqual(host_header(False, 0, None, None)[0], "idle")
        self.assertEqual(host_header(False, 2, "x", "y")[0], "idle")      # stopped wins
        self.assertEqual(host_header(True, 0, None, None)[1], "Sharing - waiting for Viewers")
        self.assertEqual(host_header(True, 1, None, None)[1], "Sharing with 1 Viewer")
        self.assertEqual(host_header(True, 2, None, None)[1], "Sharing with 2 Viewers")
        self.assertEqual(host_header(True, 2, "Ravi", None)[0], "request")
        self.assertEqual(host_header(True, 2, "Ravi", "Ravi")[0], "control")  # control wins
        for args in ((False, 0, None, None), (True, 0, None, None), (True, 1, "R", None),
                     (True, 1, None, "R")):
            kind, headline, hint = host_header(*args)
            self.assertIn(kind, ("idle", "sharing", "request", "control"))
            self.assertTrue(headline and hint)


@unittest.skipUnless(HAVE_TK, "needs tkinter and a display")
class HostWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SCREENSHARE_SETTINGS"] = os.path.join(self.tmp.name, "s.json")
        self.saved = {k: getattr(config, k) for k in ("PORT",)}
        self.root = tk.Tk()
        self.root.withdraw()
        from screenshare import gui
        from screenshare.server import HostServer
        self.win = gui.HostWindow(self.root, lambda ev: HostServer(
            ev, input_backend=FakeInputBackend(), frame_factory=FakeFrameSource))

    def tearDown(self):
        self.win._alive = False
        if self.win._after_id is not None:
            self.root.after_cancel(self.win._after_id)
        self.root.destroy()
        gc.collect()
        for key, value in self.saved.items():
            setattr(config, key, value)
        del os.environ["SCREENSHARE_SETTINGS"]
        self.tmp.cleanup()

    def started(self):
        self.win._on_started({"port": 5000, "ip": "10.0.0.5", "ips": ["10.0.0.5"],
                              "code": "AB12CD34"})

    def test_idle_then_started_header_and_copy_buttons(self):
        w = self.win
        self.assertEqual(w.state_label.cget("text"), "Not sharing")
        self.assertEqual(str(w.copy_code_button.cget("state")), "disabled")
        self.started()
        self.assertEqual(w.state_label.cget("text"), "Sharing - waiting for Viewers")
        self.assertEqual(w.code_label.cget("text"), "AB12CD34")
        self.assertEqual(str(w.copy_code_button.cget("state")), "normal")
        self.assertEqual(w.addr_label.cget("text"), "TCP port 5000 - listening on all interfaces")
        w._on_stopped(None)
        self.assertEqual(w.state_label.cget("text"), "Not sharing")
        self.assertEqual(w.code_label.cget("text"), "not sharing")

    def test_copy_code_never_writes_the_code_into_the_log(self):
        w = self.win
        self.started()
        w.on_copy_code()
        self.assertEqual(self.root.clipboard_get(), "AB12CD34")
        log = w.log_text.get("1.0", "end")
        self.assertIn("Session code copied", log)
        self.assertNotIn("AB12CD34", log)
        w.on_copy_address()
        self.assertEqual(self.root.clipboard_get(), "10.0.0.5")

    def test_disconnect_button_needs_a_selected_row(self):
        w = self.win
        self.started()
        w._on_stats({"viewers": [ROW], "fps": 5.0, "kbps": 9.0})
        self.assertEqual(str(w.disconnect_viewer_button.cget("state")), "disabled")
        w.stats_table.selection_set("a")
        w.root.update_idletasks()
        w._update_disconnect_state()
        self.assertEqual(str(w.disconnect_viewer_button.cget("state")), "normal")
        w._on_stats({"viewers": [dict(ROW, seconds=130)], "fps": 5.0, "kbps": 9.0})
        self.assertIn("a", w.stats_table.selection())          # selection survives refresh
        self.assertEqual(w.stats_table.set("a", "time"), "2:10")
        self.assertEqual(w.stats_table.set("a", "bytes"), "3.00 MB")
        self.assertEqual(w.totals_label.cget("text"), "Total: 5.0 FPS, 9.0 KB/s")
        w._on_stats({"viewers": [], "fps": 0.0, "kbps": 0.0})
        self.assertEqual(str(w.disconnect_viewer_button.cget("state")), "disabled")

    def test_request_and_control_states_are_visible(self):
        w = self.win
        self.started()
        w._on_stats({"viewers": [ROW], "fps": 5.0, "kbps": 9.0})
        w._on_control_request("Ravi-PC")
        self.assertEqual(w.state_label.cget("text"), "Control request from Ravi-PC")
        self.assertEqual(w.request_label.cget("text"), "Pending request from: Ravi-PC")
        self.assertEqual(str(w.approve_button.cget("state")), "normal")
        w._on_status({"status": {"pending_requester": None, "active_controller": "Ravi-PC"}})
        self.assertEqual(w.state_label.cget("text"), "Ravi-PC is controlling this PC")
        self.assertEqual(w.controller_label.cget("text"), "Controller: Ravi-PC")
        self.assertEqual(w.stats_table.set("a", "control"), "Controlling")
        self.assertEqual(str(w.approve_button.cget("state")), "disabled")
        self.assertEqual(str(w.revoke_button.cget("state")), "normal")
        w._on_status({"status": {"pending_requester": None, "active_controller": None}})
        self.assertEqual(w.controller_label.cget("text"), "Controller: none")
        self.assertEqual(w.stats_table.set("a", "control"), "View only")
        self.assertEqual(w.state_label.cget("text"), "Sharing with 1 Viewer")

    def test_log_lines_are_timestamped(self):
        self.win._on_log("hello")
        line = self.win.log_text.get("1.0", "end").splitlines()[0]
        self.assertRegex(line, r"^\d\d:\d\d:\d\d  hello$")

    def test_stopping_clears_everything(self):
        w = self.win
        self.started()
        w._on_stats({"viewers": [ROW], "fps": 5.0, "kbps": 9.0})
        w._on_control_request("Ravi-PC")
        w._on_stopped(None)
        self.assertEqual(w.stats_table.get_children(), ())
        self.assertEqual(w.request_label.cget("text"), "No pending control request.")
        self.assertEqual(w.controller_label.cget("text"), "Controller: none")
        self.assertEqual(str(w.stop_button.cget("state")), "disabled")


@unittest.skipUnless(HAVE_TK, "needs tkinter and a display")
class EndToEndTests(unittest.TestCase):
    """Real HostServer on a free loopback port, real ViewerClient, window updated by events."""

    def test_connect_request_approve_revoke_disconnect(self):
        tmp = tempfile.TemporaryDirectory()
        os.environ["SCREENSHARE_SETTINGS"] = os.path.join(tmp.name, "s.json")
        saved = config.PORT
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        config.PORT = probe.getsockname()[1]
        probe.close()
        root = tk.Tk()
        root.withdraw()
        from screenshare import gui
        from screenshare.client import ViewerClient
        from screenshare.server import HostServer
        win = gui.HostWindow(root, lambda ev: HostServer(
            ev, input_backend=FakeInputBackend(), frame_factory=FakeFrameSource))
        viewer_events = queue.Queue()
        viewer = ViewerClient(viewer_events, "E2E-Viewer")

        def pump(until, seconds=6.0):
            end = time.time() + seconds
            while time.time() < end:
                root.update()
                if until():
                    return True
                time.sleep(0.02)
            return False
        try:
            self.assertIsNone(win.server.start_sharing())
            self.assertTrue(pump(lambda: win._sharing))
            code = win.code_label.cget("text")
            self.assertEqual(len(code), 8)
            viewer.connect("127.0.0.1", code)
            self.assertTrue(pump(lambda: len(win.stats_table.get_children()) == 1))
            self.assertEqual(win.state_label.cget("text"), "Sharing with 1 Viewer")
            viewer.request_control()
            self.assertTrue(pump(lambda: win.approve_button.instate(["!disabled"])))
            self.assertEqual(win.state_label.cget("text"), "Control request from E2E-Viewer")
            win.on_approve()
            self.assertTrue(pump(lambda: win.controller_label.cget("text") == "Controller: E2E-Viewer"))
            self.assertIn("is controlling this PC", win.state_label.cget("text"))
            win.on_revoke()
            self.assertTrue(pump(lambda: win.controller_label.cget("text") == "Controller: none"))
            iid = win.stats_table.get_children()[0]
            win.stats_table.selection_set(iid)
            win.on_disconnect_viewer()
            self.assertTrue(pump(lambda: not win.stats_table.get_children()))
            self.assertIn("disconnected", win.log_text.get("1.0", "end"))
        finally:
            viewer.disconnect()
            win.server.stop_sharing()
            pump(lambda: not win._sharing, 3.0)
            win._alive = False
            if win._after_id is not None:
                root.after_cancel(win._after_id)
            root.destroy()
            gc.collect()
            config.PORT = saved
            del os.environ["SCREENSHARE_SETTINGS"]
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
