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
