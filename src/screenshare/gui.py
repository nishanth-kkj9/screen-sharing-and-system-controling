# file: gui.py
"""Tkinter Host and Viewer interfaces (section 10). All widget updates happen on
the GUI thread; workers communicate only through queues drained by root.after()."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from screenshare import client as client_mod
from screenshare import config
from screenshare.geometry import widget_to_norm
from screenshare.keymap import tk_keysym_to_wire
from PIL import ImageTk

POLL_MS = 50          # GUI queue polling interval (section 7.1)
GUI_POLL_MS = 40      # decoded-frame polling (slightly faster than the event queue)


class HostWindow:
    """Host controls (section 10.1)."""

    def __init__(self, root, server_factory):
        self.root = root
        self.events = queue.Queue()
        self.server = server_factory(self.events)
        root.title("Screen Share - Host (TCP %d)" % config.PORT)
        root.minsize(480, 420)

        state = ttk.LabelFrame(root, text="Sharing state", padding=8)
        state.pack(fill="x", padx=10, pady=6)
        self.state_label = ttk.Label(state, text="stopped", font=("TkDefaultFont", 11, "bold"))
        self.state_label.pack(anchor="w")
        self.addr_label = ttk.Label(state, text="Address: (not sharing)")
        self.addr_label.pack(anchor="w")
        # Section 3.3: show every candidate IPv4 (virtual adapters appear too) and
        # let the student correct the best guess. The Host binds 0.0.0.0 regardless.
        self.ip_box = ttk.Combobox(state, width=24)
        self.ip_box.pack(anchor="w", pady=(2, 0))
        self.code_label = ttk.Label(state, text="Session code: (not sharing)")
        self.code_label.pack(anchor="w")
        self.start_button = ttk.Button(state, text="Start Sharing", command=self.on_start)
        self.start_button.pack(anchor="w", pady=(6, 0))
        self.stop_button = ttk.Button(state, text="Stop Sharing", command=self.on_stop,
                                      state="disabled")
        self.stop_button.pack(anchor="w", pady=2)

        viewers = ttk.LabelFrame(root, text="Viewer statistics", padding=8)
        viewers.pack(fill="both", expand=True, padx=10, pady=6)
        columns = ("peer", "time", "frames", "bytes", "skipped")
        self.stats_table = ttk.Treeview(viewers, columns=columns, height=4)
        self.stats_table.heading("#0", text="Viewer")
        self.stats_table.column("#0", width=150, anchor="w")
        for column, title, width in (("peer", "Peer ip:port", 150), ("time", "Connected", 80),
                                     ("frames", "Frames", 70), ("bytes", "Bytes", 90),
                                     ("skipped", "Skipped", 70)):
            self.stats_table.heading(column, text=title)
            self.stats_table.column(column, width=width, anchor="e")
        self.stats_table.pack(fill="both", expand=True)
        self.totals_label = ttk.Label(viewers, text="Total: 0.0 FPS, 0.0 KB/s")
        self.totals_label.pack(anchor="w", pady=(4, 0))
        self.disconnect_viewer_button = ttk.Button(
            viewers, text="Disconnect Viewer", command=self.on_disconnect_viewer,
            state="disabled")
        self.disconnect_viewer_button.pack(anchor="w", pady=(4, 0))

        control = ttk.LabelFrame(root, text="Remote control", padding=8)
        control.pack(fill="x", padx=10, pady=6)
        self.request_label = ttk.Label(control, text="No pending control request.")
        self.request_label.pack(anchor="w")
        self.approve_button = ttk.Button(control, text="Approve", command=self.on_approve,
                                         state="disabled")
        self.approve_button.pack(side="left", pady=(6, 0))
        self.deny_button = ttk.Button(control, text="Deny", command=self.on_deny,
                                      state="disabled")
        self.deny_button.pack(side="left", padx=6, pady=(6, 0))
        self.controller_label = ttk.Label(control, text="Controller: none")
        self.controller_label.pack(anchor="w", pady=(6, 0))
        self.revoke_button = ttk.Button(control, text="Revoke Control",
                                        command=self.on_revoke, state="disabled")
        self.revoke_button.pack(anchor="w", pady=2)

        self.log_text = tk.Text(root, height=6, state="disabled", wrap="word")
        self.log_text.pack(fill="both", padx=10, pady=(6, 10))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._alive = True
        self._after_id = None
        self._poll()

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

    def _on_started(self, data):
        self.state_label.config(text="listening")
        self.addr_label.config(text="TCP port %d - listening on all interfaces" % data["port"])
        candidates = data.get("ips") or [data["ip"]]
        self.ip_box.config(values=candidates)
        self.ip_box.set(data["ip"])
        self.code_label.config(text="Session code: %s" % data["code"])
        self._set_buttons()

    def _on_stopped(self, data):
        self.state_label.config(text="stopped")
        self.addr_label.config(text="Address: (not sharing)")
        self.ip_box.set("")
        self.ip_box.config(values=[])
        self.code_label.config(text="Session code: (not sharing)")
        self.stats_table.delete(*self.stats_table.get_children())
        self.totals_label.config(text="Total: 0.0 FPS, 0.0 KB/s")
        self.disconnect_viewer_button.config(state="disabled")
        self.request_label.config(text="No pending control request.")
        self.controller_label.config(text="Controller: none")
        self.approve_button.config(state="disabled")
        self.deny_button.config(state="disabled")
        self.revoke_button.config(state="disabled")
        self._set_buttons()

    def _on_stats(self, data):
        """Per-Viewer counters and totals (sections 10.1 and 25.3). Rows are updated
        in place so the selection used by Disconnect Viewer survives the refresh."""
        table = self.stats_table
        live = set()
        for row in data["viewers"]:
            live.add(row["id"])
            values = (row["peer"], "%.0f s" % row["seconds"], row["frames"],
                      row["bytes"], row["skipped"])
            if table.exists(row["id"]):
                table.item(row["id"], text=row["name"], values=values)
            else:
                table.insert("", "end", iid=row["id"], text=row["name"], values=values)
        for iid in table.get_children():
            if iid not in live:
                table.delete(iid)
        self.totals_label.config(text="Total: %.1f FPS, %.1f KB/s" % (data["fps"], data["kbps"]))
        self.disconnect_viewer_button.config(state="normal" if live else "disabled")

    def _on_status(self, data):
        status = data["status"]
        pending = status.get("pending_requester")
        active = status.get("active_controller")
        if pending:
            self.request_label.config(text="Pending request from: %s" % pending)
            self.approve_button.config(state="normal")
            self.deny_button.config(state="normal")
        else:
            self.request_label.config(text="No pending control request.")
            self.approve_button.config(state="disabled")
            self.deny_button.config(state="disabled")
        if active:
            self.controller_label.config(text="Controller: %s" % active)
            self.revoke_button.config(state="normal")
        else:
            self.controller_label.config(text="Controller: none")
            self.revoke_button.config(state="disabled")

    def _on_control_request(self, name):
        # Status broadcast arrives right behind it; the label update is instant.
        self.request_label.config(text="Pending request from: %s" % name)
        self.approve_button.config(state="normal")
        self.deny_button.config(state="normal")
        self.root.bell()

    def _on_warning(self, text):
        messagebox.showwarning("Host", text)

    def _on_log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")


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
        self.host_entry.insert(0, "127.0.0.1")
        self.host_entry.grid(row=0, column=1, padx=6)
        ttk.Label(form, text="Session code:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.code_entry = ttk.Entry(form, width=10)
        self.code_entry.grid(row=0, column=3, padx=6)
        self.connect_button = ttk.Button(form, text="Connect", command=self.on_connect)
        self.connect_button.grid(row=0, column=4, padx=(10, 0))
        self.disconnect_button = ttk.Button(form, text="Disconnect", command=self.on_disconnect,
                                            state="disabled")
        self.disconnect_button.grid(row=0, column=5, padx=6)

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
        threading.Thread(target=self.client.connect, args=(host, code),
                         daemon=True).start()   # connect() blocks; never in a callback

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
        self.release_button.config(state="normal" if controlling else "disabled")

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
    root = tk.Tk()
    HostWindow(root, lambda events: _build_server(events))
    root.mainloop()


def _build_server(events):
    from screenshare.server import HostServer
    return HostServer(events)


def run_viewer():
    root = tk.Tk()
    ViewerWindow(root, lambda events: _build_client(events))
    root.mainloop()


def _build_client(events):
    import socket as _socket
    return client_mod.ViewerClient(events, _socket.gethostname())
