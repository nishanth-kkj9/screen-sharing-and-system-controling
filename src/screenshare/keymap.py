# file: keymap.py
"""Tkinter keysym -> PyAutoGUI key name allowlist. The wire carries the PyAutoGUI name."""
import string

ALLOWED_KEYS = set(string.ascii_lowercase) | set(string.digits) | {
    "enter", "space", "tab", "backspace", "esc", "left", "up", "right", "down", "shift"}

TK_TO_WIRE = {"Return": "enter", "space": "space", "Tab": "tab", "BackSpace": "backspace",
              "Escape": "esc", "Left": "left", "Up": "up", "Right": "right", "Down": "down",
              "Shift_L": "shift", "Shift_R": "shift"}


def tk_keysym_to_wire(keysym):
    """Return an allowlisted wire key name, or None (the viewer then sends nothing)."""
    if keysym in TK_TO_WIRE:
        return TK_TO_WIRE[keysym]
    k = keysym.lower()
    return k if len(k) == 1 and k in ALLOWED_KEYS else None
