# file: permissions.py
"""PermissionManager: single-controller permission state (architecture section 6.3).

Pure state under its own lock. No sockets, no Tkinter, no PyAutoGUI (module boundary
table, section 14.1), so the unittest suite can exercise every rule without a network.
"""
import threading


class PermissionManager:
    """One pending request and one active controller, or None for either."""

    def __init__(self):
        self._lock = threading.Lock()
        self.pending_controller_id = None
        self.active_controller_id = None

    def request(self, viewer_id):
        """Returns ("pending", None) or ("deny", reason)."""
        with self._lock:
            if self.active_controller_id is not None:
                return "deny", "controller_busy"
            if self.pending_controller_id is not None:
                return "deny", "request_pending"
            self.pending_controller_id = viewer_id
            return "pending", None

    def pending_id(self):
        with self._lock:
            return self.pending_controller_id

    def active_id(self):
        with self._lock:
            return self.active_controller_id

    def approve(self, viewer_id, is_connected=None):
        """Host approves. Re-checks the session is still connected and that no
        controller is active (rule 4). Returns 'granted', 'stale' or 'gone'."""
        with self._lock:
            if self.pending_controller_id != viewer_id:
                return "stale"
            if self.active_controller_id is not None:
                self.pending_controller_id = None
                return "stale"
            if is_connected is not None and not is_connected(viewer_id):
                self.pending_controller_id = None
                return "gone"
            self.pending_controller_id = None
            self.active_controller_id = viewer_id
            return "granted"

    def reject(self, viewer_id=None):
        """Host denies the pending request; returns the cleared id or None."""
        with self._lock:
            if self.pending_controller_id is None:
                return None
            if viewer_id is None or self.pending_controller_id == viewer_id:
                cleared, self.pending_controller_id = self.pending_controller_id, None
                return cleared
            return None

    def clear_active(self):
        """Host revokes; returns the cleared controller id or None."""
        with self._lock:
            cleared, self.active_controller_id = self.active_controller_id, None
            return cleared

    def release(self, viewer_id):
        """Viewer voluntarily releases control. Returns True if it was active."""
        with self._lock:
            if self.active_controller_id == viewer_id:
                self.active_controller_id = None
                return True
            return False

    def cancel_pending(self, viewer_id):
        """The pending Viewer withdraws its own request (spec 6.3 rule 9).
        Returns True if a pending request of this Viewer was cleared."""
        with self._lock:
            if self.pending_controller_id == viewer_id:
                self.pending_controller_id = None
                return True
            return False

    def drop(self, viewer_id):
        """Viewer disconnected. Returns (was_pending, was_active)."""
        with self._lock:
            was_pending = self.pending_controller_id == viewer_id
            was_active = self.active_controller_id == viewer_id
            if was_pending:
                self.pending_controller_id = None
            if was_active:
                self.active_controller_id = None
            return was_pending, was_active

    def is_active(self, viewer_id):
        with self._lock:
            return self.active_controller_id == viewer_id

    def reset(self):
        with self._lock:
            self.pending_controller_id = None
            self.active_controller_id = None
