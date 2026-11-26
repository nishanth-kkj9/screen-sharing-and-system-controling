# file: gui.py
"""Tkinter Host and Viewer interfaces (section 10). All widget updates happen on
the GUI thread; workers communicate only through queues drained by root.after()."""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont

from screenshare import client as client_mod
from screenshare import config
from screenshare import demo_guide
from screenshare import settings
from screenshare import transport_view
from screenshare.geometry import widget_to_norm
from screenshare.keymap import tk_keysym_to_wire
from PIL import ImageTk

POLL_MS = 50          # GUI queue polling interval (section 7.1)
GUI_POLL_MS = 40      # decoded-frame polling (slightly faster than the event queue)

# Host window look. Colours only supplement text: every state is also written out.
STATE_COLORS = {"idle": "#8a8f98", "sharing": "#2e9e4f", "request": "#d98e04",
                "control": "#2563eb"}
ALERT_BG, ALERT_FG = "#fff4ce", "#4d3b00"     # pending control request panel


class HostWindow:
    """Host controls (section 10.1)."""

    def __init__(self, root, server_factory):
        self.root = root
        self.events = queue.Queue()
        self.server = server_factory(self.events)
        root.title(self._title())
        root.minsize(780, 650)
        self.demo = None
        self._build_menu()
        self.dashboard = None
        self._settings_dialog = None
        self._last_stats = {"viewers": []}
        self._sharing = False
        self._pending = None
        self._active = None

        style = ttk.Style(root)
        base = tkfont.nametofont("TkDefaultFont")
        size = abs(int(base.actual("size"))) or 9
        self._fonts = {
            "title": tkfont.Font(root=root, family=base.actual("family"), size=size + 4,
                                 weight="bold"),
            "code": tkfont.Font(root=root, family=tkfont.nametofont("TkFixedFont").actual("family"),
                                size=size + 5, weight="bold"),
            "bold": tkfont.Font(root=root, family=base.actual("family"), size=size,
                                weight="bold"),
        }
        line = tkfont.Font(root=root, font=base).metrics("linespace")
        style.configure("Host.Treeview", rowheight=line + 8)
        style.configure("Host.Treeview.Heading", font=self._fonts["bold"])
        self._bg = style.lookup("TFrame", "background") or root.cget("background")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=3)
        root.rowconfigure(4, weight=1)
        pad = {"padx": 10, "pady": (8, 0)}

        # 1. Status header: what is happening, and the one primary action.
        header = ttk.Frame(root, padding=(2, 0))
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        header.columnconfigure(1, weight=1)
        self.state_dot = tk.Canvas(header, width=20, height=20, highlightthickness=0,
                                   bg=self._bg)
        self._dot = self.state_dot.create_oval(3, 3, 17, 17, fill=STATE_COLORS["idle"],
                                               outline="")
        self.state_dot.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        self.state_label = ttk.Label(header, text="Not sharing", font=self._fonts["title"])
        self.state_label.grid(row=0, column=1, sticky="w")
        self.hint_label = ttk.Label(header, text="", foreground="#555555")
        self.hint_label.grid(row=1, column=1, sticky="w")
        actions = ttk.Frame(header)
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self.start_button = ttk.Button(actions, text="Start Sharing", command=self.on_start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Stop Sharing", command=self.on_stop,
                                      state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))

        # 2. Connection details a Viewer needs (address + code), each with Copy.
        connect = ttk.LabelFrame(root, text="Connect a Viewer", padding=8)
        connect.grid(row=1, column=0, sticky="ew", **pad)
        connect.columnconfigure(3, weight=1)
        ttk.Label(connect, text="Host address").grid(row=0, column=0, sticky="w")
        # Section 3.3: show every candidate IPv4 (virtual adapters appear too) and
        # let the student correct the best guess. The Host binds 0.0.0.0 regardless.
        self.ip_box = ttk.Combobox(connect, width=24)
        self.ip_box.grid(row=0, column=1, sticky="w", padx=8)
        self.copy_address_button = ttk.Button(connect, text="Copy", width=7,
                                              command=self.on_copy_address, state="disabled")
        self.copy_address_button.grid(row=0, column=2)
        ttk.Label(connect, text="Session code").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.code_label = ttk.Label(connect, text="not sharing", foreground="#555555")
        self.code_label.grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))
        self.copy_code_button = ttk.Button(connect, text="Copy", width=7,
                                           command=self.on_copy_code, state="disabled")
        self.copy_code_button.grid(row=1, column=2, pady=(6, 0))
        self.addr_label = ttk.Label(connect, text="Address: (not sharing)", foreground="#555555")
        self.addr_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 3. Connected Viewers.
        viewers = ttk.LabelFrame(root, text="Connected Viewers", padding=8)
        viewers.grid(row=2, column=0, sticky="nsew", **pad)
        viewers.columnconfigure(0, weight=1)
        viewers.rowconfigure(0, weight=1)
        columns = ("control", "peer", "time", "frames", "bytes", "skipped")
        self.stats_table = ttk.Treeview(viewers, columns=columns, height=4,
                                        selectmode="browse", style="Host.Treeview")
        self.stats_table.heading("#0", text="Viewer")
        self.stats_table.column("#0", width=170, anchor="w", stretch=True)
        for column, title, width in (("control", "Control", 90), ("peer", "Address", 150),
                                     ("time", "Connected", 80), ("frames", "Frames", 70),
                                     ("bytes", "Data", 80), ("skipped", "Skipped", 70)):
            self.stats_table.heading(column, text=title)
            self.stats_table.column(column, width=width, anchor="w" if column == "control" else "e",
                                    stretch=column in ("peer",))
        self.stats_table.grid(row=0, column=0, sticky="nsew")
        self.stats_table.bind("<<TreeviewSelect>>", lambda e: self._update_disconnect_state())
        foot = ttk.Frame(viewers)
        foot.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        foot.columnconfigure(0, weight=1)
        self.totals_label = ttk.Label(foot, text="Total: 0.0 FPS, 0.0 KB/s")
        self.totals_label.grid(row=0, column=0, sticky="w")
        self.disconnect_viewer_button = ttk.Button(
            foot, text="Disconnect Viewer", command=self.on_disconnect_viewer, state="disabled")
        self.disconnect_viewer_button.grid(row=0, column=1, sticky="e")

        # 4. Remote control: the request is an alert panel, the controller is a status row.
        control = ttk.LabelFrame(root, text="Remote control", padding=8)
        control.grid(row=3, column=0, sticky="ew", **pad)
        control.columnconfigure(0, weight=1)
        self.request_panel = tk.Frame(control, bg=self._bg, padx=6, pady=6)
        self.request_panel.grid(row=0, column=0, sticky="ew")
        self.request_panel.columnconfigure(0, weight=1)
        self.request_label = tk.Label(self.request_panel, text="No pending control request.",
                                      bg=self._bg, anchor="w")
        self.request_label.grid(row=0, column=0, sticky="w")
        self.approve_button = ttk.Button(self.request_panel, text="Approve",
                                         command=self.on_approve, state="disabled")
        self.approve_button.grid(row=0, column=1, padx=(8, 0))
        self.deny_button = ttk.Button(self.request_panel, text="Deny", command=self.on_deny,
                                      state="disabled")
        self.deny_button.grid(row=0, column=2, padx=(6, 0))
        who = ttk.Frame(control)
        who.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        who.columnconfigure(0, weight=1)
        self.controller_label = ttk.Label(who, text="Controller: none")
        self.controller_label.grid(row=0, column=0, sticky="w", padx=6)
        self.revoke_button = ttk.Button(who, text="Revoke Control", command=self.on_revoke,
                                        state="disabled")
        self.revoke_button.grid(row=0, column=1, sticky="e")

        # 5. Activity log (timestamped, scrollable).
        activity = ttk.LabelFrame(root, text="Activity", padding=8)
        activity.grid(row=4, column=0, sticky="nsew", padx=10, pady=(8, 10))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(0, weight=1)
        self.log_text = tk.Text(activity, height=6, state="disabled", wrap="word")
        self.log_text.tag_configure("time", foreground="#6b7280")
        scroll = ttk.Scrollbar(activity, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._alive = True
        self._after_id = None
        self._refresh_header()
        self._poll()

    @staticmethod
    def _title():
        return "Screen Share - Host (TCP %d)" % config.PORT

    # ---------- GUI-thread actions ----------

    def on_start(self):
        error = self.server.start_sharing()
        if error:
            messagebox.showerror("Start Sharing", error)

    def on_stop(self):
        self.server.stop_sharing()

    def on_approve(self):
        self.server.approve_request()

    def on_deny(self):
        self.server.deny_request()

    def on_revoke(self):
        self.server.revoke_control()

    def on_disconnect_viewer(self):
        selected = self.stats_table.selection()
        if selected:
            self.server.disconnect_viewer(selected[0])

    def on_copy_address(self):
        value = self.ip_box.get().strip()
        if value:
            self.copy_text(value, "Host address copied")

    def on_copy_code(self):
        code = self.code_label.cget("text")
        if self._sharing and code:
            self.copy_text(code, "Session code copied")

    def on_dashboard(self):
        if self.dashboard is not None and self.dashboard.winfo_exists():
            self.dashboard.lift()
            return
        self.dashboard = TransportDashboard(self.root, self._dashboard_closed)
        self.dashboard.update_stats(self._last_stats)

    def _dashboard_closed(self):
        self.dashboard = None

    def on_settings(self):
        if self.server.state != "stopped":
            messagebox.showinfo("Settings", "Stop sharing before changing settings.")
            return
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        self._settings_dialog = SettingsDialog(
            self.root, "Host settings", HOST_SETTING_FIELDS, self._settings_saved)

    def _settings_saved(self, saved):
        settings.apply(saved, config)
        self.root.title(self._title())
        self._on_log("Settings saved: port %d, %d FPS, JPEG quality %d, up to %d Viewer(s)"
                     % (saved["port"], saved["fps"], saved["jpeg_quality"], saved["max_viewers"]))


    # ---------- Demo menu ----------

    def _build_menu(self):
        """One 'Menu' button in the menu bar. Its dropdown lists the three areas:
        Demo (submenu), Transport Dashboard and Settings."""
        bar = tk.Menu(self.root)
        main = tk.Menu(bar, tearoff=False)
        demo = tk.Menu(main, tearoff=False)
        demo.add_command(label="Demo guide (6 steps)...", command=self.on_demo)
        demo.add_command(label="Save evidence snapshot...", command=self.on_save_snapshot)
        demo.add_separator()
        filters = tk.Menu(demo, tearoff=False)
        for step in demo_guide.STEPS:
            filters.add_command(label=step["title"],
                                command=lambda f=step["filter"]: self.copy_text(f))
        demo.add_cascade(label="Copy Wireshark filter", menu=filters)
        main.add_cascade(label="Demo", menu=demo)
        main.add_command(label="Transport Dashboard", command=self.on_dashboard)
        main.add_command(label="Settings...", command=self.on_settings)
        bar.add_cascade(label="Menu", menu=main)
        self.root.config(menu=bar)

    def copy_text(self, text, message=None):
        """Copy to the clipboard. `message` replaces the log line (the session code
        is not written into the log)."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._on_log(message or "Copied to clipboard: " + text)

    def on_demo(self):
        if self.demo is not None and self.demo.winfo_exists():
            self.demo.lift()
            return
        self.demo = DemoWindow(self.root, self.copy_text, self.on_save_snapshot)
        self.demo.update_stats(self._last_stats)

    def on_save_snapshot(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".txt", initialfile="transport_evidence.txt",
            filetypes=[("Text", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as out:
                out.write(demo_guide.snapshot_text(self._last_stats["viewers"]))
        except OSError as exc:
            messagebox.showerror("Save evidence", "Could not save: %s" % exc)
            return
        self._on_log("Evidence snapshot saved: " + path)

    def on_close(self):
        self._alive = False
        # Cancel pending timers: a callback firing after destroy() prints
        # 'invalid command name' on the console as the app exits.
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self.server.stop_sharing()
        self.root.destroy()

    # ---------- event draining ----------

    def _poll(self):
        if not self._alive:
            return
        try:
            while True:
                kind, data = self.events.get_nowait()
                handler = getattr(self, "_on_" + kind, None)
                if handler:
                    handler(data)
        except queue.Empty:
            pass
        self._after_id = self.root.after(POLL_MS, self._poll)

    def _set_buttons(self):
        listening = self.server.state == "listening"
        self.start_button.config(state="disabled" if listening else "normal")
        self.stop_button.config(state="normal" if listening else "disabled")

    def _refresh_header(self):
        kind, headline, hint = transport_view.host_header(self._sharing, len(self.stats_table.get_children()),
                                           self._pending, self._active)
        self.state_label.config(text=headline)
        self.hint_label.config(text=hint)
        self.state_dot.itemconfigure(self._dot, fill=STATE_COLORS[kind])

    def _update_disconnect_state(self):
        enabled = bool(self.stats_table.selection())
        self.disconnect_viewer_button.config(state="normal" if enabled else "disabled")

    def _show_request(self, pending):
        """Pending request = amber alert panel; otherwise the panel is plain."""
        self._pending = pending
        bg, fg = (ALERT_BG, ALERT_FG) if pending else (self._bg, "black")
        self.request_panel.config(bg=bg)
        self.request_label.config(
            bg=bg, fg=fg, font=self._fonts["bold"] if pending else "TkDefaultFont",
            text="Pending request from: %s" % pending if pending
            else "No pending control request.")
        state = "normal" if pending else "disabled"
        self.approve_button.config(state=state)
        self.deny_button.config(state=state)

    def _mark_controller(self, active):
        self._active = active
        self.controller_label.config(text="Controller: %s" % active if active
                                     else "Controller: none")
        self.revoke_button.config(state="normal" if active else "disabled")
        for iid in self.stats_table.get_children():
            name = self.stats_table.item(iid, "text")
            self.stats_table.set(iid, "control", "Controlling" if active and name == active
                                 else "View only")

    def _on_started(self, data):
        self._sharing = True
        self.addr_label.config(text="TCP port %d - listening on all interfaces" % data["port"])
        candidates = data.get("ips") or [data["ip"]]
        self.ip_box.config(values=candidates)
        self.ip_box.set(data["ip"])
        self.code_label.config(text=data["code"], font=self._fonts["code"], foreground="black")
        self.copy_address_button.config(state="normal")
        self.copy_code_button.config(state="normal")
        self._set_buttons()
        self._refresh_header()

    def _on_stopped(self, data):
        self._sharing = False
        self.addr_label.config(text="Address: (not sharing)")
        self.ip_box.set("")
        self.ip_box.config(values=[])
        self.code_label.config(text="not sharing", font="TkDefaultFont", foreground="#555555")
        self.copy_address_button.config(state="disabled")
        self.copy_code_button.config(state="disabled")
        self.stats_table.delete(*self.stats_table.get_children())
        self.totals_label.config(text="Total: 0.0 FPS, 0.0 KB/s")
        self._update_disconnect_state()
        self._last_stats = {"viewers": []}
        if self.dashboard is not None:
            self.dashboard.update_stats(self._last_stats)
        self._show_request(None)
        self._mark_controller(None)
        self._set_buttons()
        self._refresh_header()
        self._on_log("Sharing stopped")

    def _on_stats(self, data):
        """Per-Viewer counters and totals (sections 10.1 and 25.3). Rows are updated
        in place so the selection used by Disconnect Viewer survives the refresh."""
        self._last_stats = data
        if self.dashboard is not None:
            self.dashboard.update_stats(data)
        if self.demo is not None and self.demo.winfo_exists():
            self.demo.update_stats(data)
        table = self.stats_table
        live = set()
        for row in data["viewers"]:
            live.add(row["id"])
            control = "Controlling" if self._active and row["name"] == self._active else "View only"
            values = (control, row["peer"], transport_view.format_duration(row["seconds"]), row["frames"],
                      transport_view.fmt_bytes(row["bytes"]), row["skipped"])
            if table.exists(row["id"]):
                table.item(row["id"], text=row["name"], values=values)
            else:
                table.insert("", "end", iid=row["id"], text=row["name"], values=values)
        for iid in table.get_children():
            if iid not in live:
                table.delete(iid)
        self.totals_label.config(text="Total: %.1f FPS, %.1f KB/s" % (data["fps"], data["kbps"]))
        self._update_disconnect_state()
        self._refresh_header()

    def _on_status(self, data):
        status = data["status"]
        self._show_request(status.get("pending_requester"))
        self._mark_controller(status.get("active_controller"))
        self._refresh_header()

    def _on_control_request(self, name):
        # Status broadcast arrives right behind it; the panel update is instant.
        self._show_request(name)
        self._refresh_header()
        self._on_log("Control request from %s" % name)
        self.root.bell()

    def _on_warning(self, text):
        messagebox.showwarning("Host", text)

    def _on_log(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", stamp + "  ", "time")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")


class SettingsDialog(tk.Toplevel):
    """Edit and save settings. `fields` is a list of (key, label, hint). Values are
    validated by settings.validate(); the message line shows what is wrong."""

    def __init__(self, parent, title, fields, on_saved):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self._on_saved = on_saved
        self.entries = {}
        current = settings.load()
        body = ttk.Frame(self, padding=10)
        body.pack()
        for row, (key, label, hint) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(body, width=14)
            entry.insert(0, str(current[key]))
            entry.grid(row=row, column=1, padx=6)
            ttk.Label(body, text=hint).grid(row=row, column=2, sticky="w")
            self.entries[key] = entry
        self.message = ttk.Label(body, text="", foreground="firebrick", wraplength=420)
        self.message.grid(row=len(fields), column=0, columnspan=3, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Defaults", command=self.on_defaults).pack(side="left")
        ttk.Button(buttons, text="Save", command=self.on_save).pack(side="left", padx=6)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left")

    def on_defaults(self):
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(settings.DEFAULTS[key]))

    def on_save(self):
        values = settings.load()
        for key, entry in self.entries.items():
            values[key] = entry.get()
        clean, errors = settings.validate(values)
        if errors:
            self.message.config(text="; ".join(
                "%s %s" % (key.replace("_", " "), why) for key, why in sorted(errors.items())))
            return
        try:
            saved = settings.save(clean)
        except (OSError, ValueError) as exc:
            self.message.config(text="Could not save: %s" % exc)
            return
        self._on_saved(saved)
        self.destroy()


HOST_SETTING_FIELDS = (
    ("port", "TCP port", "1024-65535 (Viewers must use the same port)"),
    ("fps", "Frames per second", "1-15"),
    ("jpeg_quality", "JPEG quality", "30-95 (higher = sharper, more bytes)"),
    ("max_width", "Max screen width", "320-1920 pixels"),
    ("max_height", "Max screen height", "240-1080 pixels"),
    ("max_viewers", "Max Viewers", "1-2"),
)
VIEWER_SETTING_FIELDS = (
    ("port", "TCP port", "1024-65535 (must match the Host)"),
    ("viewer_name", "Name shown to Host", "blank = computer name, up to 32 characters"),
    ("slow_viewer_ms", "Slow Viewer delay (ms)", "0 = off; 200-500 demonstrates flow control"),
)


class TransportDashboard(tk.Toplevel):
    """Live transport-layer evidence for the Host (read-only view of Host statistics).
    All text comes from transport_view, which shows a dash where a number is unknown."""

    def __init__(self, parent, on_close):
        super().__init__(parent)
        self.title("Transport dashboard (TCP)")
        self.minsize(1000, 460)
        self._on_close = on_close
        top = ttk.LabelFrame(self, text="Per Viewer connection", padding=8)
        top.pack(fill="x", padx=10, pady=6)
        columns = transport_view.VIEWER_COLUMNS[1:]
        widths = (80, 80, 115, 80, 85, 105, 85, 115)        # wide enough for each heading
        self.table = ttk.Treeview(top, columns=columns, height=3)
        self.table.heading("#0", text=transport_view.VIEWER_COLUMNS[0])
        self.table.column("#0", width=190, anchor="w")
        for column, width in zip(columns, widths):
            self.table.heading(column, text=column)
            self.table.column(column, width=width, anchor="e")
        self.table.pack(fill="x")
        self.note = ttk.Label(top, text="", wraplength=940, justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        bottom = ttk.LabelFrame(self, text="What TCP is doing for this program", padding=8)
        bottom.pack(fill="both", expand=True, padx=10, pady=6)
        self.explain = ttk.Treeview(bottom, columns=("what", "evidence"), height=7)
        self.explain.heading("#0", text="TCP feature")
        self.explain.heading("what", text="What it does")
        self.explain.heading("evidence", text="Live evidence")
        self.explain.column("#0", width=170, anchor="w")
        self.explain.column("what", width=260, anchor="w")
        self.explain.column("evidence", width=500, anchor="w")
        self.explain.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.update_stats({"viewers": []})

    def close(self):
        self._on_close()
        self.destroy()

    def update_stats(self, data):
        rows = data["viewers"]
        live = set()
        for row, values in zip(rows, transport_view.viewer_rows(rows)):
            live.add(row["id"])
            if self.table.exists(row["id"]):
                self.table.item(row["id"], text=values[0], values=values[1:])
            else:
                self.table.insert("", "end", iid=row["id"], text=values[0], values=values[1:])
        for iid in self.table.get_children():
            if iid not in live:
                self.table.delete(iid)
        for feature, what, evidence in transport_view.explainer(rows):
            if self.explain.exists(feature):
                self.explain.item(feature, values=(what, evidence))
            else:
                self.explain.insert("", "end", iid=feature, text=feature, values=(what, evidence))
        if not rows:
            self.note.config(text="No Viewer connected.")
        elif any(r.get("tcp") for r in rows):
            self.note.config(text="App RTT is a PING/PONG over the TCP connection and includes "
                                  "the Viewer's processing time. TCP RTT, retransmissions, window "
                                  "and cwnd are read from the operating system; this program does "
                                  "not compute them.")
        else:
            self.note.config(text="Kernel TCP counters are not available on this computer "
                                  "(Windows 10 version 1703 or later is needed). App RTT and "
                                  "skipped frames are still real measurements.")


class DemoWindow(tk.Toplevel):
    """Guided transport-layer demo: step list, what to do/say, live evidence check."""

    def __init__(self, parent, copy_text, save_snapshot):
        super().__init__(parent)
        self.title("Demo guide - transport layer")
        self.minsize(760, 380)
        self._copy_text = copy_text
        self._rows = []
        left = ttk.Frame(self, padding=8)
        left.pack(side="left", fill="y")
        self.steps = tk.Listbox(left, width=44, height=10, exportselection=False)
        for step in demo_guide.STEPS:
            self.steps.insert("end", step["title"])
        self.steps.pack(fill="y", expand=True)
        self.steps.bind("<<ListboxSelect>>", lambda e: self._show())
        right = ttk.Frame(self, padding=8)
        right.pack(side="left", fill="both", expand=True)
        self.title_label = ttk.Label(right, font=("TkDefaultFont", 12, "bold"))
        self.title_label.pack(anchor="w")
        self.do_label = ttk.Label(right, wraplength=470, justify="left")
        self.do_label.pack(anchor="w", pady=(8, 0))
        self.say_label = ttk.Label(right, wraplength=470, justify="left")
        self.say_label.pack(anchor="w", pady=(8, 0))
        self.filter_label = ttk.Label(right, wraplength=470, justify="left")
        self.filter_label.pack(anchor="w", pady=(8, 0))
        box = ttk.LabelFrame(right, text="Live evidence from this Host", padding=8)
        box.pack(fill="x", pady=(10, 0))
        self.evidence = ttk.Label(box, wraplength=450, justify="left")
        self.evidence.pack(anchor="w")
        row = ttk.Frame(right)
        row.pack(anchor="w", pady=(10, 0))
        ttk.Button(row, text="Previous", command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(row, text="Next", command=lambda: self._move(1)).pack(side="left", padx=6)
        ttk.Button(row, text="Copy Wireshark filter",
                   command=lambda: self._copy_text(demo_guide.STEPS[self.index()]["filter"])
                   ).pack(side="left")
        ttk.Button(row, text="Save evidence", command=save_snapshot).pack(side="left", padx=6)
        self.steps.selection_set(0)
        self._show()

    def index(self):
        selected = self.steps.curselection()
        return selected[0] if selected else 0

    def _move(self, delta):
        i = min(max(self.index() + delta, 0), len(demo_guide.STEPS) - 1)
        self.steps.selection_clear(0, "end")
        self.steps.selection_set(i)
        self._show()

    def _show(self):
        i = self.index()
        step = demo_guide.STEPS[i]
        self.title_label.config(text=step["title"])
        self.do_label.config(text="Do: " + step["do"])
        self.say_label.config(text="Say: " + step["say"])
        self.filter_label.config(text="Wireshark filter: " + step["filter"])
        status, text = demo_guide.evaluate(i, self._rows)
        self.evidence.config(text="%s %s" % (demo_guide.ICON[status], text))
        for n in range(len(demo_guide.STEPS)):
            mark = demo_guide.ICON[demo_guide.evaluate(n, self._rows)[0]]
            self.steps.delete(n)
            self.steps.insert(n, "%s %s" % (mark, demo_guide.STEPS[n]["title"]))
        self.steps.selection_clear(0, "end")
        self.steps.selection_set(i)

    def update_stats(self, data):
        self._rows = data["viewers"]
        self._show()


class ScreenCanvas(ttk.Frame):
    """Aspect-ratio preserving display area (section 10.2)."""

    def __init__(self, root):
        super().__init__(root, padding=4)
        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.photo = None            # keep a reference or Tk stops drawing it (8.5)
        self.image = None
        self._rect = (0, 0, 1, 1)

    def set_image(self, image):
        self.image = image
        self._draw()

    def _draw(self):
        if self.image is None:
            return
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        iw, ih = self.image.size
        scale = min(cw / iw, ch / ih)
        dw, dh = max(int(iw * scale), 1), max(int(ih * scale), 1)
        left = (cw - dw) // 2
        top = (ch - dh) // 2
        self._rect = (left, top, dw, dh)
        # master= is required: without it the photo binds to the default root,
        # which may be a different (or destroyed) Tk interpreter (app.py launcher).
        self.photo = ImageTk.PhotoImage(self.image.resize((dw, dh)), master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(left, top, image=self.photo, anchor="nw")

    def resize_bind(self):
        self.canvas.bind("<Configure>", lambda e: self._draw())

    def event_to_norm(self, event):
        """Widget pixel -> normalized coordinates inside the displayed image."""
        return widget_to_norm(event.x, event.y, *self._rect)

    def clamped_norm(self, event):
        """Section 9.3: a button-up outside the image is still sent, clamped to the
        image rectangle, so a drag ending outside cannot leave a button held."""
        left, top, width, height = self._rect
        x = min(max(event.x, left), left + max(width - 1, 0))
        y = min(max(event.y, top), top + max(height - 1, 0))
        return widget_to_norm(x, y, left, top, width, height)


class ViewerWindow:
    """Viewer controls (section 10.2)."""

    def __init__(self, root, client_factory):
        self.root = root
        self.events = queue.Queue()
        self.client = client_factory(self.events)
        root.title("Screen Share - Viewer")
        root.minsize(640, 480)

        form = ttk.LabelFrame(root, text="Connection", padding=8)
        form.pack(fill="x", padx=10, pady=6)
        ttk.Label(form, text="Host IPv4 address:").grid(row=0, column=0, sticky="w")
        self.host_entry = ttk.Entry(form, width=18)
        self.host_entry.insert(0, settings.load()["last_host"])
        self.host_entry.grid(row=0, column=1, padx=6)
        ttk.Label(form, text="Session code:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.code_entry = ttk.Entry(form, width=10)
        self.code_entry.grid(row=0, column=3, padx=6)
        self.connect_button = ttk.Button(form, text="Connect", command=self.on_connect)
        self.connect_button.grid(row=0, column=4, padx=(10, 0))
        self.disconnect_button = ttk.Button(form, text="Disconnect", command=self.on_disconnect,
                                            state="disabled")
        self.disconnect_button.grid(row=0, column=5, padx=6)
        bar = tk.Menu(root)
        main = tk.Menu(bar, tearoff=False)
        main.add_command(label="Settings...", command=self.on_settings)
        bar.add_cascade(label="Menu", menu=main)
        root.config(menu=bar)
        self._settings_dialog = None

        self.state_label = ttk.Label(root, text="disconnected",
                                     font=("TkDefaultFont", 11, "bold"))
        self.state_label.pack(anchor="w", padx=12)

        self.screen = ScreenCanvas(root)
        self.screen.pack(fill="both", expand=True, padx=10, pady=6)
        self.screen.resize_bind()

        control = ttk.Frame(root, padding=(10, 4))
        control.pack(fill="x")
        self.request_button = ttk.Button(control, text="Request Control",
                                         command=self.on_request, state="disabled")
        self.request_button.pack(side="left")
        self.release_button = ttk.Button(control, text="Release Control",
                                         command=self.on_release, state="disabled")
        self.release_button.pack(side="left", padx=6)
        self.hint_label = ttk.Label(
            control, text="Input is sent only while controlling (letters, digits, "
                          "Enter, Space, Tab, Backspace, Esc, arrows, Shift).")
        self.hint_label.pack(side="left", padx=10)

        self._bind_input()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._alive = True
        self._after_id = None
        self._frames_after_id = None
        self._last_norm = None          # last normalized pointer position (X11 wheel)
        self._wheel_remainder = 0       # sub-notch wheel delta kept between events (9.7)
        self._poll()
        self._poll_frames()

    # ---------- input binding (only effective while controlling) ----------

    def _bind_input(self):
        c = self.screen.canvas
        c.bind("<Motion>", self._on_motion)
        # focus_set() lives INSIDE the press handlers: binding "<1>" separately
        # would silently REPLACE "<ButtonPress-1>" (Tk treats them as the same
        # event) and kill remote left-clicks entirely.
        c.bind("<ButtonPress-1>", lambda e: (c.focus_set(),
                                             self._on_button(e, "left", "down")))
        c.bind("<ButtonRelease-1>", lambda e: self._on_button(e, "left", "up"))
        c.bind("<ButtonPress-3>", lambda e: (c.focus_set(),
                                             self._on_button(e, "right", "down")))
        c.bind("<ButtonRelease-3>", lambda e: self._on_button(e, "right", "up"))
        c.bind("<MouseWheel>", self._on_wheel)
        # X11 delivers the wheel as Button-4/Button-5 instead of <MouseWheel>.
        c.bind("<Button-4>", lambda e: self._on_wheel_delta(1))
        c.bind("<Button-5>", lambda e: self._on_wheel_delta(-1))
        c.bind("<KeyPress>", self._on_key_down)
        c.bind("<KeyRelease>", self._on_key_up)
        # Keep keyboard focus on the canvas so key events arrive.
        c.focus_set()
        c.bind("<Enter>", lambda e: c.focus_set())

    def _norm(self, event):
        if self.client.state != client_mod.CONTROLLING:
            return None
        return self.screen.event_to_norm(event)

    def _on_motion(self, event):
        n = self._norm(event)
        if n:
            self._last_norm = n          # remembered for X11 wheel events
            self.client.send_move(*n)

    def _on_button(self, event, button, action):
        if self.client.state != client_mod.CONTROLLING:
            return
        n = self.screen.event_to_norm(event)
        if n is None:
            if action != "up":
                return                      # moves and presses outside the image: ignore
            n = self.screen.clamped_norm(event)   # always release a held button (9.3)
            if n is None:
                return
        self._last_norm = n                 # Button events also refresh the position
        self.client.send_button(button, action, *n)

    def _on_wheel(self, event):
        n = self._norm(event)
        if not n:
            return
        self._last_norm = n
        # Section 9.7: accumulate the raw delta and send int(accumulator / 120)
        # notches, truncating towards zero and keeping the remainder, so small
        # touchpad deltas are neither lost nor biased.
        self._wheel_remainder += event.delta
        notches = int(self._wheel_remainder / 120)
        if notches:
            self._wheel_remainder -= notches * 120
            notches = max(-20, min(20, notches))   # the Host accepts -20..20 only
            self.client.send_scroll(notches, *n)

    def _on_wheel_delta(self, notches):
        """X11 Button-4/5 wheel events carry no coordinates, so reuse the last
        normalized pointer position seen in <Motion>."""
        n = self._last_norm
        if (self.client.state == client_mod.CONTROLLING and n is not None):
            self.client.send_scroll(notches, n[0], n[1])

    def _on_key_down(self, event):
        if self.client.state != client_mod.CONTROLLING:
            return
        wire = tk_keysym_to_wire(event.keysym)
        if wire:
            self.client.send_key(wire, down=True)

    def _on_key_up(self, event):
        if self.client.state != client_mod.CONTROLLING:
            return
        wire = tk_keysym_to_wire(event.keysym)
        if wire:
            self.client.send_key(wire, down=False)

    # ---------- GUI-thread actions ----------

    def on_connect(self):
        host = self.host_entry.get().strip()
        code = self.code_entry.get().strip()
        if not host or not code:
            messagebox.showerror("Connect", "Enter the Host IPv4 address and session code.")
            return
        try:                                    # remember the address; never block connecting
            current = settings.load()
            current["last_host"] = host
            settings.save(current)
        except (OSError, ValueError):
            pass
        threading.Thread(target=self.client.connect, args=(host, code),
                         daemon=True).start()   # connect() blocks; never in a callback

    def on_settings(self):
        if self.client.state != client_mod.DISCONNECTED:
            messagebox.showinfo("Settings", "Disconnect before changing settings.")
            return
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        self._settings_dialog = SettingsDialog(
            self.root, "Viewer settings", VIEWER_SETTING_FIELDS, self._settings_saved)

    def _settings_saved(self, saved):
        import socket as _socket
        settings.apply(saved, config)
        self.client.name = saved["viewer_name"] or _socket.gethostname()

    def on_disconnect(self):
        self.client.disconnect()

    def on_request(self):
        self.client.request_control()

    def on_release(self):
        self.client.release_control()

    def on_close(self):
        self._alive = False
        # Cancel pending timers: a callback firing after destroy() prints
        # 'invalid command name' on the console as the app exits.
        for after_id in (self._after_id, self._frames_after_id):
            if after_id is not None:
                self.root.after_cancel(after_id)
        self.client.disconnect(graceful=False)
        self.root.destroy()

    # ---------- event draining ----------

    def _poll(self):
        if not self._alive:
            return
        try:
            while True:
                kind, data = self.events.get_nowait()
                handler = getattr(self, "_on_" + kind, None)
                if handler:
                    handler(data)
        except queue.Empty:
            pass
        self._after_id = self.root.after(POLL_MS, self._poll)

    def _poll_frames(self):
        if not self._alive:
            return
        if self.client.image_slot is not None:
            image = self.client.image_slot.take(timeout=0)
            if image is not None:
                self.screen.set_image(image)    # PhotoImage created on the GUI thread
        self._frames_after_id = self.root.after(GUI_POLL_MS, self._poll_frames)

    STATE_TEXT = {
        client_mod.DISCONNECTED: "disconnected",
        client_mod.CONNECTING: "connecting",
        client_mod.AUTHENTICATING: "authenticating",
        client_mod.VIEW_ONLY: "view-only",
        client_mod.REQUEST_PENDING: "request pending",
        client_mod.CONTROLLING: "controlling",
    }

    def _on_state(self, state):
        self.state_label.config(text=self.STATE_TEXT.get(state, state))
        controlling = state == client_mod.CONTROLLING
        connected = state in (client_mod.VIEW_ONLY, client_mod.REQUEST_PENDING, controlling)
        self.connect_button.config(state="disabled" if connected else "normal")
        self.disconnect_button.config(state="normal" if connected else "disabled")
        self.request_button.config(
            state="normal" if state == client_mod.VIEW_ONLY else "disabled")
        pending = state == client_mod.REQUEST_PENDING
        self.release_button.config(
            state="normal" if (controlling or pending) else "disabled",
            text="Cancel Request" if pending else "Release Control")

    def _on_join_denied(self, reason):
        friendly = {
            "invalid_session_code": "The session code was wrong.",
            "viewer_limit_reached": "The Host already has two Viewers.",
            "unsupported_version": "The Host speaks a different protocol version.",
            "invalid_name": "The Host refused this computer name.",
            "unsupported_message": "The Host refused the join request.",
        }.get(reason, "Join denied: %s" % reason)
        messagebox.showerror("Join denied", friendly)

    def _on_connect_failed(self, error):
        messagebox.showerror("Connect", "Could not connect to the Host: %s" % error)

    def _on_status(self, msg):
        pass                                    # informational only on the Viewer

    def _on_server_error(self, reason):
        messagebox.showerror("Host message", "The Host reported: %s" % reason)

    def _on_log(self, message):
        pass                                    # status label already shows the state


def run_host():
    settings.apply(settings.load(), config)     # saved port, FPS, quality, limits
    root = tk.Tk()
    HostWindow(root, lambda events: _build_server(events))
    root.mainloop()


def _build_server(events):
    from screenshare.server import HostServer
    return HostServer(events)


def run_viewer():
    settings.apply(settings.load(), config)
    root = tk.Tk()
    ViewerWindow(root, lambda events: _build_client(events))
    root.mainloop()


def _build_client(events):
    import socket as _socket
    return client_mod.ViewerClient(
        events, settings.load()["viewer_name"] or _socket.gethostname())
