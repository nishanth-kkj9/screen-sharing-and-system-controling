# app.py: these lines come BEFORE importing tkinter, mss or pyautogui (section 13.4)
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor; Windows 8.1+
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()    # older fallback
    except Exception:
        pass                                         # not Windows (tests) or already set

import tkinter  # noqa: E402
import sys      # noqa: E402

import gui      # noqa: E402  (imports tkinter, PIL and the project modules)


def main(argv):
    mode = "choose"
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        mode = args[0]
    if mode not in ("host", "viewer"):
        root = tkinter.Tk()
        root.title("Screen Share")
        root.resizable(False, False)
        tkinter.Label(root, text="Network-Based Screen Sharing and Remote Control",
                      font=("TkDefaultFont", 12, "bold")).pack(padx=24, pady=(24, 8))
        tkinter.Label(root, text="Choose the mode for this computer:",
                      ).pack(padx=24, pady=(0, 12))
        buttons = tkinter.Frame(root)
        buttons.pack(pady=(0, 8))
        tkinter.Button(buttons, text="Host (share this screen)", width=28,
                       command=lambda: _launch(root, "host")).pack(pady=3)
        tkinter.Button(buttons, text="Viewer (watch and control)", width=28,
                       command=lambda: _launch(root, "viewer")).pack(pady=3)
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    elif mode == "host":
        gui.run_host()
    else:
        gui.run_viewer()


def _launch(root, mode):
    root.destroy()
    if mode == "host":
        gui.run_host()
    else:
        gui.run_viewer()


if __name__ == "__main__":
    main(sys.argv)
