"""Constants and limits (architecture section 15). No mutable session state lives here."""
import os
import secrets

# Wire constants are defined ONLY in protocol.py (section 15); imported, never redefined.
from protocol import HEADER, TYPE_JSON, TYPE_JPEG, MAX_JSON_BYTES, MAX_JPEG_BYTES  # noqa: F401

HOST = "0.0.0.0"
PORT = 5000
MAX_VIEWERS = 2
PROTOCOL_VERSION = 1

# Image pipeline.
MAX_SCREEN_WIDTH = 1280
MAX_SCREEN_HEIGHT = 720
TARGET_FPS = 5
JPEG_QUALITY = 65

# Sessions and queues.
MAX_BAD_SESSION_CODES = 3          # per TCP connection
MAX_CONTROL_QUEUE_ITEMS = 128      # messages per connection
JOIN_TIMEOUT = 10.0                # seconds until JOIN_ACCEPT is sent (section 0.3 C9)

SESSION_CODE_LENGTH = 8
SESSION_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CLIENT_NAME_MAX_LENGTH = 32

# Test-only demonstration setting (sections 15 and 25.3). 0 = off in normal use.
# Above 0, the Viewer's reader sleeps this many milliseconds after each frame, so
# the flow-control demonstration can be shown with the application itself.
try:
    DEMO_SLOW_VIEWER_MS = max(0, int(os.environ.get("SCREENSHARE_SLOW_VIEWER_MS", "0")))
except ValueError:
    DEMO_SLOW_VIEWER_MS = 0        # a malformed setting must not stop the app


def generate_session_code():
    """New temporary code for each sharing session (architecture sections 12 and 15)."""
    return "".join(secrets.choice(SESSION_CODE_ALPHABET) for _ in range(SESSION_CODE_LENGTH))
