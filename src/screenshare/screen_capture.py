# file: screen_capture.py
"""MSS capture and Pillow JPEG helpers (section 8). No socket writes, no GUI updates."""
import io
import logging
import time

from PIL import Image

from screenshare import config

logger = logging.getLogger("screenshare.capture")


class CaptureError(Exception):
    pass


def create_capture():
    """Create one reusable MSS context (section 8.2: never per frame)."""
    from mss import MSS            # requires mss >= 10.2 (section 0.3 C3)
    return MSS()


def primary_monitor_dict(sct):
    """Primary monitor as a plain dict (mss 10.2 API, section 0.3 C3)."""
    mon = sct.primary_monitor
    return {"left": mon["left"], "top": mon["top"],
            "width": mon["width"], "height": mon["height"]}


def capture_frame_jpeg(sct):
    """Capture the primary monitor and return (jpeg_bytes, (w, h)) or None if too large."""
    mon = primary_monitor_dict(sct)
    shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    img.thumbnail((config.MAX_SCREEN_WIDTH, config.MAX_SCREEN_HEIGHT))  # aspect preserved
    if img.width < 1 or img.height < 1:
        return None
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=config.JPEG_QUALITY)
    data = buf.getvalue()
    if len(data) > config.MAX_JPEG_BYTES:   # section 8.4: drop, never bypass
        logger.warning("encoded frame %d bytes exceeds %d; dropped",
                       len(data), config.MAX_JPEG_BYTES)
        return None
    return data, (img.width, img.height)


def decode_jpeg_image(data):
    """Viewer side: decode JPEG bytes into a Pillow RGB image, or raise CaptureError."""
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise CaptureError("cannot decode JPEG frame") from exc


class FramePacer:
    """Paces the capture loop with a steady clock (section 8.2)."""

    def __init__(self, fps):
        self.interval = 1.0 / max(fps, 0.1)
        self._next = time.monotonic()

    def wait(self):
        now = time.monotonic()
        delay = self._next - now
        if delay > 0:
            time.sleep(delay)
        self._next = max(self._next + self.interval, time.monotonic())
