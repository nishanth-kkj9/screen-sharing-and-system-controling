"""Framing for the single-connection protocol (section 5). No GUI, no PyAutoGUI."""
import json
import math
import struct

HEADER = struct.Struct("!BI")
TYPE_JSON = 1
TYPE_JPEG = 2
MAX_JSON_BYTES = 64 * 1024
MAX_JPEG_BYTES = 4 * 1024 * 1024
VIEWER_TO_HOST = "viewer_to_host"
HOST_TO_VIEWER = "host_to_viewer"


class ConnectionClosed(Exception):
    pass


class ProtocolError(Exception):
    pass


def recv_exact(sock, byte_count):
    """Read exactly byte_count bytes or raise ConnectionClosed."""
    buf = bytearray(byte_count)
    view = memoryview(buf)
    got = 0
    while got < byte_count:
        n = sock.recv_into(view[got:], byte_count - got)
        if n == 0:
            raise ConnectionClosed("peer closed the connection")
        got += n
    return bytes(buf)


def encode_message(message_type, payload):
    if message_type == TYPE_JSON:
        limit = MAX_JSON_BYTES
    elif message_type == TYPE_JPEG:
        limit = MAX_JPEG_BYTES
    else:
        raise ProtocolError("unknown message type %r" % message_type)
    if not payload or len(payload) > limit:
        raise ProtocolError("payload size %d not allowed" % len(payload))
    return HEADER.pack(message_type, len(payload)) + payload


def encode_json_message(data):
    return encode_message(TYPE_JSON, json.dumps(data, separators=(",", ":")).encode("utf-8"))


def recv_message(sock, direction):
    """Read and validate one framed message; returns (type, payload)."""
    message_type, length = HEADER.unpack(recv_exact(sock, HEADER.size))
    if message_type == TYPE_JSON:
        if length == 0 or length > MAX_JSON_BYTES:
            raise ProtocolError("bad JSON length %d" % length)
    elif message_type == TYPE_JPEG:
        if direction == VIEWER_TO_HOST:
            raise ProtocolError("viewer must not send JPEG")
        if length == 0 or length > MAX_JPEG_BYTES:
            raise ProtocolError("bad JPEG length %d" % length)
    else:
        raise ProtocolError("unknown message type %d" % message_type)
    return message_type, recv_exact(sock, length)  # length checked BEFORE this read


def decode_json_payload(payload):
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("invalid JSON payload") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        raise ProtocolError("JSON must be an object with a string 'type'")
    return obj


def valid_norm(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# JSON message contract (sections 5.5 and 5.8). Appended below the reference code
# above, which is unchanged. No GUI and no PyAutoGUI here.
# ---------------------------------------------------------------------------

JOIN_DENIED_REASONS = frozenset({
    "invalid_session_code", "viewer_limit_reached", "unsupported_version", "invalid_name"})
CONTROL_DENIED_REASONS = frozenset({"controller_busy", "request_pending", "host_rejected"})
CONTROL_REVOKED_REASONS = frozenset({"host_revoked", "failsafe", "host_stopped"})
DISCONNECT_REASONS = frozenset({"host_stopped", "user_exit"})
ERROR_REASONS = frozenset({"unsupported_message", "invalid_input"})

VIEWER_TO_HOST_TYPES = frozenset({
    "JOIN", "CONTROL_REQUEST", "CONTROL_RELEASE", "MOUSE_MOVE", "MOUSE_BUTTON",
    "SCROLL", "KEY_DOWN", "KEY_UP", "DISCONNECT", "PONG"})
HOST_TO_VIEWER_TYPES = frozenset({
    "JOIN_ACCEPT", "JOIN_DENIED", "STATUS", "CONTROL_GRANTED", "CONTROL_DENIED",
    "CONTROL_REVOKED", "DISCONNECT", "ERROR", "PING"})

_STR = (str,)
_INT = (int,)
_NUM = (int, float)
_NULLABLE_STR = (str, type(None))

# Required fields and their types per section 5.5. Extra unknown fields are ignored.
REQUIRED_FIELDS = {
    "JOIN": (("protocol_version", _INT), ("client_name", _STR), ("session_code", _STR)),
    "JOIN_ACCEPT": (("viewer_id", _STR), ("host_name", _STR), ("screen_width", _INT),
                    ("screen_height", _INT), ("fps", _INT)),
    "JOIN_DENIED": (("reason", _STR),),
    "STATUS": (("viewer_count", _INT), ("active_controller", _NULLABLE_STR),
               ("pending_requester", _NULLABLE_STR)),
    "CONTROL_DENIED": (("reason", _STR),),
    "CONTROL_REVOKED": (("reason", _STR),),
    "MOUSE_MOVE": (("x", _NUM), ("y", _NUM)),
    "MOUSE_BUTTON": (("button", _STR), ("action", _STR), ("x", _NUM), ("y", _NUM)),
    "SCROLL": (("amount", _INT), ("x", _NUM), ("y", _NUM)),
    "KEY_DOWN": (("key", _STR),),
    "KEY_UP": (("key", _STR),),
    "ERROR": (("reason", _STR),),
    "PING": (("id", _INT),),            # extension: docs/EXTENSIONS.md
    "PONG": (("id", _INT),),
}


def validate_message(msg, direction):
    """Check direction and required fields/types (sections 5.5, 5.7, 5.8).

    Returns None when the message is well formed for this direction, otherwise
    "unsupported_message". Value ranges (coordinates, keys, scroll) are checked by
    the Host's input handler, not here.
    """
    mtype = msg.get("type")
    allowed = VIEWER_TO_HOST_TYPES if direction == VIEWER_TO_HOST else HOST_TO_VIEWER_TYPES
    if mtype not in allowed:
        return "unsupported_message"
    for name, types in REQUIRED_FIELDS.get(mtype, ()):
        if name not in msg:
            return "unsupported_message"      # a missing field is invalid even if nullable
        value = msg[name]
        # bool is a subclass of int, but no field in the contract is a boolean.
        if isinstance(value, bool) or not isinstance(value, types):
            return "unsupported_message"
    return None

