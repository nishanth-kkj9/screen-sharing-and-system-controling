"""Persistent user settings (one small JSON file). Standard library only, no Tk.

A missing, unreadable or corrupt file never stops the application: every bad or
missing value falls back to its default. Values are validated before they are saved
or applied, so a typo in the dialog cannot put the Host into an impossible state."""
import json
import os
import tempfile

DEFAULTS = {
    "port": 5000,
    "fps": 5,
    "jpeg_quality": 65,
    "max_width": 1280,
    "max_height": 720,
    "max_viewers": 2,
    "slow_viewer_ms": 0,
    "viewer_name": "",
    "last_host": "127.0.0.1",
}
LIMITS = {                       # inclusive (low, high)
    "port": (1024, 65535),
    "fps": (1, 15),
    "jpeg_quality": (30, 95),
    "max_width": (320, 1920),
    "max_height": (240, 1080),
    "max_viewers": (1, 2),       # the architecture allows at most two Viewers
    "slow_viewer_ms": (0, 2000),
}
TEXT_MAX = {"viewer_name": 32, "last_host": 64}    # 32 = config.CLIENT_NAME_MAX_LENGTH


def settings_path():
    """SCREENSHARE_SETTINGS wins (used by tests); else %APPDATA% or ~/.config."""
    override = os.environ.get("SCREENSHARE_SETTINGS")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "screenshare", "settings.json")


def _to_int(value):
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise ValueError("not a number")


def validate(raw):
    """Return (clean, errors). `clean` always has every key; `errors` maps a key to
    a message for each value that was wrong (that key then holds its default)."""
    raw = raw if isinstance(raw, dict) else {}
    clean, errors = {}, {}
    for key, default in DEFAULTS.items():
        if key not in raw:
            clean[key] = default
            continue
        value = raw[key]
        if key in LIMITS:
            low, high = LIMITS[key]
            try:
                number = _to_int(value)
            except (ValueError, TypeError):
                errors[key] = "must be a whole number from %d to %d" % (low, high)
                clean[key] = default
                continue
            if not low <= number <= high:
                errors[key] = "must be from %d to %d" % (low, high)
                clean[key] = default
                continue
            clean[key] = number
        else:
            if not isinstance(value, str):
                errors[key] = "must be text"
                clean[key] = default
                continue
            value = value.strip()
            if len(value) > TEXT_MAX[key] or not value.isprintable():
                errors[key] = "must be printable text of at most %d characters" % TEXT_MAX[key]
                clean[key] = default
                continue
            clean[key] = value
    return clean, errors


def load(path=None):
    """Settings from disk; defaults for anything missing or invalid. Never raises."""
    try:
        with open(path or settings_path(), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        raw = {}
    clean, _errors = validate(raw)
    return clean


def save(values, path=None):
    """Validate, then write atomically. Raises ValueError listing bad fields."""
    clean, errors = validate(values)
    if errors:
        raise ValueError("; ".join("%s %s" % (k, v) for k, v in sorted(errors.items())))
    target = path or settings_path()
    folder = os.path.dirname(target) or "."
    os.makedirs(folder, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(clean, out, indent=2, sort_keys=True)
        os.replace(temp, target)               # a crash never leaves half a file
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    return clean


def apply(values, cfg):
    """Copy validated settings onto the config module. Call only while the Host is
    stopped (the listener port and viewer limit are read when sharing starts).
    slow_viewer_ms = 0 leaves cfg.DEMO_SLOW_VIEWER_MS alone, so the documented
    SCREENSHARE_SLOW_VIEWER_MS environment variable keeps working."""
    clean, errors = validate(values)
    if errors:
        raise ValueError("; ".join("%s %s" % (k, v) for k, v in sorted(errors.items())))
    cfg.PORT = clean["port"]
    cfg.TARGET_FPS = clean["fps"]
    cfg.JPEG_QUALITY = clean["jpeg_quality"]
    cfg.MAX_SCREEN_WIDTH = clean["max_width"]
    cfg.MAX_SCREEN_HEIGHT = clean["max_height"]
    cfg.MAX_VIEWERS = clean["max_viewers"]
    if clean["slow_viewer_ms"] > 0:
        cfg.DEMO_SLOW_VIEWER_MS = clean["slow_viewer_ms"]
    return clean
