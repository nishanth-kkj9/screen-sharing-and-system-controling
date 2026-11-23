# file: remote_input.py
"""Host permission checks and allowlisted PyAutoGUI actions (sections 9 and 12).

Validation and held-input bookkeeping are pure Python; the actual OS input calls go
through a backend object so automated tests never move a real mouse (module boundary
table in section 14.1). The default backend is created lazily so importing this
module does not require PyAutoGUI.
"""
import logging
import threading

from screenshare.keymap import ALLOWED_KEYS
from screenshare.geometry import norm_to_pixel, avoid_points

logger = logging.getLogger("screenshare.remote_input")

MOUSE_BUTTONS = ("left", "right")
MOUSE_ACTIONS = ("down", "up")
MAX_SCROLL_NOTCHES = 20

RESULT_OK = "ok"
RESULT_REJECTED = "rejected"          # invalid values; caller decides the response
RESULT_NOT_CONTROLLER = "not_controller"  # permission check failed
RESULT_FAILSAFE = "failsafe"          # PyAutoGUI fail-safe fired; caller must revoke


class PyAutoGUIBackend:
    """Thin wrapper over PyAutoGUI; the only place it is imported."""

    def __init__(self):
        import pyautogui  # imported only when a real Host runs
        pyautogui.FAILSAFE = True   # section 9.5: never disable
        pyautogui.PAUSE = 0         # section 0.3 C1: no 0.1 s sleep per call
        self._pyautogui = pyautogui

    @property
    def failsafe_points(self):
        return list(self._pyautogui.FAILSAFE_POINTS)

    def set_failsafe(self, enabled):
        """Only release_all() suspends the fail-safe, and only while it runs
        (section 9.7): after a trip the pointer is still in a corner, so every
        release call would otherwise raise too."""
        self._pyautogui.FAILSAFE = bool(enabled)

    def size(self):
        return self._pyautogui.size()

    def move_to(self, x, y):
        self._pyautogui.moveTo(x, y)

    def mouse_down(self, x, y, button):
        self._pyautogui.mouseDown(x, y, button=button)

    def mouse_up(self, button):
        self._pyautogui.mouseUp(button=button)

    def scroll(self, clicks):
        self._pyautogui.scroll(clicks)

    def key_down(self, key):
        self._pyautogui.keyDown(key)

    def key_up(self, key):
        self._pyautogui.keyUp(key)


class RemoteInput:
    """Validates and executes input events for the single active controller."""

    def __init__(self, backend=None, on_failsafe=None):
        self._backend = backend
        self._on_failsafe = on_failsafe
        self._held_keys = set()
        self._held_buttons = set()
        # One lock for every PyAutoGUI call, including held-input release, so a
        # revoke takes effect after the current input action completes (7.6 rule 3).
        self.input_lock = threading.Lock()

    @property
    def backend(self):
        if self._backend is None:
            self._backend = PyAutoGUIBackend()
        return self._backend

    # ---- validation (pure; also used directly by unit tests) ----

    @staticmethod
    def validate_move(msg):
        import protocol
        if not (protocol.valid_norm(msg.get("x")) and protocol.valid_norm(msg.get("y"))):
            raise ValueError("invalid move coordinates")
        return float(msg["x"]), float(msg["y"])

    @staticmethod
    def validate_button(msg):
        import protocol
        if msg.get("button") not in MOUSE_BUTTONS or msg.get("action") not in MOUSE_ACTIONS:
            raise ValueError("invalid mouse button/action")
        if not (protocol.valid_norm(msg.get("x")) and protocol.valid_norm(msg.get("y"))):
            raise ValueError("invalid button coordinates")
        return msg["button"], msg["action"], float(msg["x"]), float(msg["y"])

    @staticmethod
    def validate_scroll(msg):
        amount = msg.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or not (1 <= abs(amount) <= MAX_SCROLL_NOTCHES):
            raise ValueError("invalid scroll amount")
        import protocol
        if not (protocol.valid_norm(msg.get("x")) and protocol.valid_norm(msg.get("y"))):
            raise ValueError("invalid scroll coordinates")
        return amount, float(msg["x"]), float(msg["y"])

    @staticmethod
    def validate_key(msg):
        key = msg.get("key")
        if key not in ALLOWED_KEYS:
            raise ValueError("key not in allowlist")
        return key

    # ---- execution ----

    def _pixel(self, nx, ny):
        """Map normalized Viewer coordinates to a fail-safe-safe Host pixel.
        The Host does not clamp (section 9.3): validate_* already rejected any
        coordinate outside 0.0-1.0."""
        width, height = self.backend.size()
        x, y = norm_to_pixel(nx, ny, width, height)
        return avoid_points(x, y, self.backend.failsafe_points, width, height)

    def handle(self, msg, is_active_controller):
        """Handle one input message. Returns one of the RESULT_* codes.
        Every action runs under input_lock (section 7.6 rule 3)."""
        with self.input_lock:
            return self._handle(msg, is_active_controller)

    def _handle(self, msg, is_active_controller):
        if not is_active_controller:
            return RESULT_NOT_CONTROLLER
        kind = msg.get("type")
        try:
            if kind == "MOUSE_MOVE":
                x, y = self.validate_move(msg)
                px, py = self._pixel(x, y)
                self.backend.move_to(px, py)
            elif kind == "MOUSE_BUTTON":
                button, action, x, y = self.validate_button(msg)
                px, py = self._pixel(x, y)
                if action == "down":
                    self.backend.mouse_down(px, py, button)
                    self._held_buttons.add(button)
                else:
                    self.backend.mouse_up(button)
                    self._held_buttons.discard(button)
            elif kind == "SCROLL":
                amount, x, y = self.validate_scroll(msg)
                px, py = self._pixel(x, y)
                self.backend.move_to(px, py)
                self.backend.scroll(amount * 120)   # section 0.3 C6
            elif kind == "KEY_DOWN":
                key = self.validate_key(msg)
                self.backend.key_down(key)
                self._held_keys.add(key)
            elif kind == "KEY_UP":
                key = self.validate_key(msg)
                self.backend.key_up(key)
                self._held_keys.discard(key)
            else:
                raise ValueError("not an input message")
        except ValueError as exc:
            logger.warning("rejected input %r: %s", kind, exc)
            return RESULT_REJECTED
        except Exception as exc:  # pyautogui.FailSafeException and friends
            if type(exc).__name__ == "FailSafeException":
                logger.warning("PyAutoGUI fail-safe triggered; releasing held input")
                self._release_held()
                if self._on_failsafe:
                    self._on_failsafe()
                return RESULT_FAILSAFE
            raise
        return RESULT_OK

    def release_all(self):
        """Release every key/button still held by the controlled session (section 9.5).
        Runs under input_lock, so it cannot interleave with an input action."""
        with self.input_lock:
            self._release_held()

    def _release_held(self):
        """Caller holds input_lock. The fail-safe is suspended only here and only
        for the duration of the release (section 9.7), then always restored."""
        set_failsafe = getattr(self.backend, "set_failsafe", None)
        if set_failsafe is not None:
            set_failsafe(False)
        try:
            for key in sorted(self._held_keys):
                try:
                    self.backend.key_up(key)
                except Exception:
                    logger.exception("key_up(%r) during release failed", key)
            for button in sorted(self._held_buttons):
                try:
                    self.backend.mouse_up(button)
                except Exception:
                    logger.exception("mouse_up(%r) during release failed", button)
            self._held_keys.clear()
            self._held_buttons.clear()
        finally:
            if set_failsafe is not None:
                set_failsafe(True)

    @property
    def held(self):
        return sorted(self._held_keys), sorted(self._held_buttons)
