"""Read-only kernel TCP statistics for one connected socket (dashboard evidence).

The operating system's TCP implements acknowledgement, retransmission, flow control
and congestion control; this module only READS what the kernel reports. Every
function returns None instead of raising, because the dashboard must never be able
to break a sharing session.

Windows: WSAIoctl(SIO_TCP_INFO) -> TCP_INFO_v0 (Windows 10 version 1703 or later,
no administrator rights). Linux: getsockopt(TCP_INFO), used for development only."""
import ctypes
import socket
import struct
import sys

SIO_TCP_INFO = 0xD8000027          # _WSAIORW(IOC_VENDOR, 39) in mstcpip.h


class TcpInfoV0(ctypes.Structure):
    """Field order copied from TCP_INFO_v0 (mstcpip.h). ctypes applies the same
    natural alignment as the C compiler (ULONG64 on 8 bytes)."""
    _fields_ = [
        ("State", ctypes.c_uint32), ("Mss", ctypes.c_uint32),
        ("ConnectionTimeMs", ctypes.c_uint64), ("TimestampsEnabled", ctypes.c_ubyte),
        ("RttUs", ctypes.c_uint32), ("MinRttUs", ctypes.c_uint32),
        ("BytesInFlight", ctypes.c_uint32), ("Cwnd", ctypes.c_uint32),
        ("SndWnd", ctypes.c_uint32), ("RcvWnd", ctypes.c_uint32),
        ("RcvBuf", ctypes.c_uint32), ("BytesOut", ctypes.c_uint64),
        ("BytesIn", ctypes.c_uint64), ("BytesReordered", ctypes.c_uint32),
        ("BytesRetrans", ctypes.c_uint32), ("FastRetrans", ctypes.c_uint32),
        ("DupAcksIn", ctypes.c_uint32), ("TimeoutEpisodes", ctypes.c_uint32),
        ("SynRetrans", ctypes.c_ubyte),
    ]


def parse_windows(buffer):
    """TCP_INFO_v0 bytes -> normalised dict, or None when the buffer is too short."""
    if len(buffer) < ctypes.sizeof(TcpInfoV0):
        return None
    info = TcpInfoV0.from_buffer_copy(buffer)
    return {
        "source": "windows",
        "rtt_ms": info.RttUs / 1000.0,
        "cwnd": info.Cwnd,                    # bytes
        "snd_wnd": info.SndWnd,               # bytes: the receiver's advertised window
        "in_flight": info.BytesInFlight,      # sent but not yet acknowledged, bytes
        "retrans": info.BytesRetrans,
        "retrans_unit": "bytes",
        "fast_retrans": info.FastRetrans,
        "dup_acks": info.DupAcksIn,
        "timeouts": info.TimeoutEpisodes,
    }


# struct tcp_info prefix (linux/tcp.h): offsets of the fields used below.
_LINUX_MIN = 104
_L_MSS, _L_UNACKED, _L_RTT, _L_CWND, _L_TOTAL_RETRANS = 16, 24, 68, 80, 100


def parse_linux(buffer):
    """struct tcp_info bytes -> normalised dict, or None when too short."""
    if len(buffer) < _LINUX_MIN:
        return None
    mss = struct.unpack_from("I", buffer, _L_MSS)[0]
    return {
        "source": "linux",
        "rtt_ms": struct.unpack_from("I", buffer, _L_RTT)[0] / 1000.0,
        "cwnd": struct.unpack_from("I", buffer, _L_CWND)[0] * mss,       # segments -> bytes
        "snd_wnd": None,
        "in_flight": struct.unpack_from("I", buffer, _L_UNACKED)[0] * mss,
        "retrans": struct.unpack_from("I", buffer, _L_TOTAL_RETRANS)[0],
        "retrans_unit": "segments",
        "fast_retrans": None,
        "dup_acks": None,
        "timeouts": None,
    }


_ws2_ioctl = None


def _windows_ioctl():
    global _ws2_ioctl
    if _ws2_ioctl is None:
        dll = ctypes.WinDLL("ws2_32", use_last_error=True)
        func = dll.WSAIoctl
        func.argtypes = [ctypes.c_size_t, ctypes.c_uint32,
                         ctypes.c_void_p, ctypes.c_uint32,
                         ctypes.c_void_p, ctypes.c_uint32,
                         ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p]
        func.restype = ctypes.c_int
        _ws2_ioctl = func
    return _ws2_ioctl


def read(sock):
    """Statistics for a connected TCP socket, or None if unavailable for any reason."""
    try:
        if sys.platform == "win32":
            version = ctypes.c_uint32(0)                     # 0 = TCP_INFO_v0
            out = TcpInfoV0()
            returned = ctypes.c_uint32(0)
            result = _windows_ioctl()(
                sock.fileno(), SIO_TCP_INFO,
                ctypes.byref(version), ctypes.sizeof(version),
                ctypes.byref(out), ctypes.sizeof(out),
                ctypes.byref(returned), None, None)
            if result != 0 or returned.value < ctypes.sizeof(out):
                return None
            return parse_windows(bytes(out))
        option = getattr(socket, "TCP_INFO", None)
        if option is None:
            return None
        return parse_linux(sock.getsockopt(socket.IPPROTO_TCP, option, _LINUX_MIN))
    except Exception:                      # closed socket, old Windows, odd platform
        return None
