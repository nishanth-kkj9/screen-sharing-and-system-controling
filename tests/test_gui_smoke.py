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

    def test_demo_menu_window_and_snapshot(self):
        from screenshare import gui
        win = self.host()
        menu = self.root.nametowidget(self.root.cget("menu"))
        self.assertEqual(menu.index("end"), 0)               # a single top-level button
        self.assertEqual(menu.entrycget(0, "label"), "Menu")
        main = menu.nametowidget(menu.entrycget(0, "menu"))
        self.assertEqual([main.entrycget(i, "label") for i in range(main.index("end") + 1)],
                         ["Demo", "Transport Dashboard", "Settings..."])
        demo = main.nametowidget(main.entrycget(0, "menu"))
        self.assertEqual(demo.entrycget(0, "label"), "Demo guide (6 steps)...")
        win.on_demo()
        self.assertIsNotNone(win.demo)
        win._on_stats({"viewers": [dict(ROW, skipped=7)], "fps": 5.0, "kbps": 10.0})
        self.assertIn("[OK]", win.demo.evidence.cget("text") + win.demo.steps.get(0))
        win.demo._move(3)                                   # flow-control step
        self.assertIn("skipped", win.demo.evidence.cget("text"))
        win.copy_text("tcp.port == 5000")
        self.assertEqual(self.root.clipboard_get(), "tcp.port == 5000")
        path = os.path.join(self.tmp.name, "e.txt")
        with mock.patch.object(gui.filedialog, "asksaveasfilename", return_value=path):
            win.on_save_snapshot()
        with open(path, encoding="utf-8") as fh:
            self.assertIn("6. Evidence and report", fh.read())
        win.demo.destroy()


if __name__ == "__main__":
    unittest.main()


def _menus_replace_buttons(self):
    if True:
        from screenshare import gui
        host = self.host()
        texts = [w.cget("text") for w in _all_widgets(self.root) if w.winfo_class() == "TButton"]
        self.assertNotIn("Transport Dashboard", texts)
        self.assertNotIn("Settings...", texts)
        hmenu = self.root.nametowidget(self.root.cget("menu"))
        hmain = hmenu.nametowidget(hmenu.entrycget(0, "menu"))
        self.assertEqual(hmain.entrycget(2, "label"), "Settings...")
        host.on_dashboard()
        self.assertTrue(host.dashboard.winfo_exists())
        host.dashboard.destroy()
        root2 = tk.Tk()
        root2.withdraw()
        try:
            from screenshare.client import ViewerClient
            viewer = gui.ViewerWindow(root2, lambda ev: ViewerClient(ev, "t"))
            vmenu = root2.nametowidget(root2.cget("menu"))
            self.assertEqual(vmenu.entrycget(0, "label"), "Menu")
            vmain = vmenu.nametowidget(vmenu.entrycget(0, "menu"))
            self.assertEqual(vmain.entrycget(0, "label"), "Settings...")
            self.assertNotIn("Settings...", [w.cget("text") for w in _all_widgets(root2)
                                              if w.winfo_class() == "TButton"])
            viewer._alive = False
            root2.after_cancel(viewer._after_id)
            root2.after_cancel(viewer._frames_after_id)
        finally:
            root2.destroy()


GuiSmoke.test_host_and_viewer_menus_replace_buttons = _menus_replace_buttons


def _all_widgets(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_all_widgets(child))
    return out
