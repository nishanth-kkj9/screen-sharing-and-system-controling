"""Builds the real Host and Viewer windows with fake capture/input and checks the
new Settings and Transport dashboard behaviour. Skipped when Tk or a display is missing."""
import gc
import os
import queue
import tempfile
import unittest
from unittest import mock

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_TK = True
except Exception:                       # no tkinter, or no display
    HAVE_TK = False

from screenshare import config, settings
from tests.test_permissions import FakeFrameSource, FakeInputBackend

ROW = {"id": "v1", "name": "Laptop B", "peer": "10.0.0.2:50000", "seconds": 3.0,
       "frames": 10, "bytes": 5000, "skipped": 2, "rtt_ms": 2.5,
       "tcp": {"rtt_ms": 1.0, "cwnd": 14600, "snd_wnd": 65535, "in_flight": 2048,
               "retrans": 1460, "retrans_unit": "bytes", "dup_acks": 3}}


@unittest.skipUnless(HAVE_TK, "needs tkinter and a display")
class GuiSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SCREENSHARE_SETTINGS"] = os.path.join(self.tmp.name, "s.json")
        self.saved_cfg = {k: getattr(config, k) for k in (
            "PORT", "TARGET_FPS", "JPEG_QUALITY", "MAX_SCREEN_WIDTH", "MAX_SCREEN_HEIGHT",
            "MAX_VIEWERS", "DEMO_SLOW_VIEWER_MS")}
        self.root = tk.Tk()
        self.root.withdraw()
        self.windows = []

    def tearDown(self):
        for w in self.windows:                      # stop the polling timers before destroy
            w._alive = False
            for name in ("_after_id", "_frames_after_id"):
                after_id = getattr(w, name, None)
                if after_id is not None:
                    self.root.after_cancel(after_id)
        self.root.destroy()
        self.windows.clear()
        gc.collect()                                # free Tk objects on THIS thread
        for key, value in self.saved_cfg.items():
            setattr(config, key, value)
        del os.environ["SCREENSHARE_SETTINGS"]
        self.tmp.cleanup()

    def host(self):
        from screenshare import gui
        from screenshare.server import HostServer
        window = gui.HostWindow(self.root, lambda ev: HostServer(
            ev, input_backend=FakeInputBackend(), frame_factory=FakeFrameSource))
        self.windows.append(window)
        return window

    def test_dashboard_shows_rows_and_clears(self):
        window = self.host()
        window.on_dashboard()
        window.events.put(("stats", {"viewers": [ROW], "fps": 5.0, "kbps": 10.0}))
        window._poll()
        self.root.update()
        dash = window.dashboard
        self.assertEqual(dash.table.get_children(), ("v1",))
        self.assertEqual(dash.table.item("v1", "values")[2], "1460 B")
        evidence = {dash.explain.item(i, "text"): dash.explain.item(i, "values")[1]
                    for i in dash.explain.get_children()}
        self.assertIn("1460 bytes retransmitted", evidence["Error control"])
        window.events.put(("stopped", None))
        window._poll()
        self.assertEqual(dash.table.get_children(), ())
        window.on_dashboard()                       # second click re-uses the window
        self.assertIs(window.dashboard, dash)
        dash.close()
        self.assertIsNone(window.dashboard)

    def test_dashboard_opened_late_shows_the_last_stats(self):
        window = self.host()
        window.events.put(("stats", {"viewers": [ROW], "fps": 5.0, "kbps": 10.0}))
        window._poll()
        window.on_dashboard()
        self.assertEqual(window.dashboard.table.get_children(), ("v1",))

    def test_host_settings_save_applies_to_config(self):
        window = self.host()
        window.on_settings()
        dialog = window._settings_dialog
        dialog.entries["port"].delete(0, "end")
        dialog.entries["port"].insert(0, "5300")
        dialog.entries["fps"].delete(0, "end")
        dialog.entries["fps"].insert(0, "9")
        dialog.on_save()
        self.assertEqual((config.PORT, config.TARGET_FPS), (5300, 9))
        self.assertEqual(settings.load()["port"], 5300)
        self.assertIn("5300", self.root.title())

    def test_bad_value_shows_message_and_changes_nothing(self):
        window = self.host()
        window.on_settings()
        dialog = window._settings_dialog
        dialog.entries["fps"].delete(0, "end")
        dialog.entries["fps"].insert(0, "99")
        dialog.on_save()
        self.assertIn("fps", dialog.message.cget("text"))
        self.assertEqual(config.TARGET_FPS, self.saved_cfg["TARGET_FPS"])
        self.assertFalse(os.path.exists(settings.settings_path()))
        self.assertTrue(dialog.winfo_exists())

    def test_viewer_settings_change_name_and_remember_host(self):
        from screenshare import gui
        from screenshare.client import ViewerClient
        window = gui.ViewerWindow(self.root, lambda ev: ViewerClient(ev, "pc"))
        self.windows.append(window)
        window.on_settings()
        dialog = window._settings_dialog
        dialog.entries["viewer_name"].delete(0, "end")
        dialog.entries["viewer_name"].insert(0, "Laptop B")
        dialog.on_save()
        self.assertEqual(window.client.name, "Laptop B")
        window.host_entry.delete(0, "end")
        window.host_entry.insert(0, "192.168.1.20")
        window.code_entry.insert(0, "ABCD2345")
        with mock.patch("screenshare.gui.threading.Thread") as worker:
            window.on_connect()                     # no real connection in a test
        worker.assert_called_once()
        self.assertEqual(settings.load()["last_host"], "192.168.1.20")


if __name__ == "__main__":
    unittest.main()
