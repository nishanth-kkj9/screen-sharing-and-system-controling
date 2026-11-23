"""Pure coordinate helpers (no pyautogui import, so they are testable anywhere)."""


def norm_to_pixel(nx, ny, width, height, left=0, top=0):
    return left + int(nx * (width - 1)), top + int(ny * (height - 1))


def avoid_points(x, y, points, width, height, left=0, top=0):
    """PyAutoGUI's fail-safe fires when the pointer is on an exact corner pixel
    (pyautogui.FAILSAFE_POINTS). Nudge an injected position 1 px inwards so only the
    HOST's physical mouse can trigger it."""
    if (x, y) in set(points):
        x += 1 if x <= left else -1
        y += 1 if y <= top else -1
    return x, y


def widget_to_norm(px, py, img_left, img_top, img_w, img_h):
    """Viewer: widget pixel -> 0..1 inside the DISPLAYED image; None if in the letterbox."""
    if img_w <= 0 or img_h <= 0:
        return None
    if not (img_left <= px < img_left + img_w and img_top <= py < img_top + img_h):
        return None
    return (px - img_left) / max(img_w - 1, 1), (py - img_top) / max(img_h - 1, 1)
