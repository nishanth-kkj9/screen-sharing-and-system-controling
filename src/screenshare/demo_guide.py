"""Demo guide content and live checks (no Tk, so it is unit-tested).

Each step says what to do, what to say, which Wireshark filter proves it, and a check()
that reads the SAME Host statistics rows the dashboard uses. A check reports one of:
  "ok"      the evidence is on screen now
  "waiting" the action for this step has not happened yet
  "manual"  proof lives in Wireshark / a file, the program cannot see it
Nothing here is invented: a number is shown only if the Host or the kernel supplied it."""
import time

from screenshare import transport_view as tv


def _tcps(rows):
    return [r["tcp"] for r in rows if r.get("tcp")]


def _c_connect(rows):
    if not rows:
        return "waiting", "No Viewer connected yet."
    return "ok", "%d Viewer(s): %s" % (len(rows), ", ".join(r["peer"] for r in rows))


def _c_manual(text):
    return lambda rows: ("manual", text)


def _c_ack(rows):
    t = _tcps(rows)
    if not t:
        return "waiting", "No kernel counters (needs a Viewer and Windows 10 1703+ / Linux)."
    return "ok", "in flight " + ", ".join(tv.fmt_bytes(x["in_flight"]) for x in t) + \
        "; TCP RTT " + ", ".join(tv.fmt_ms(x["rtt_ms"]) for x in t)


def _c_flow(rows):
    skipped = {r["name"]: r["skipped"] for r in rows if r["skipped"] > 0}
    if skipped:
        win = [x["snd_wnd"] for x in _tcps(rows) if x["snd_wnd"] is not None]
        extra = "; smallest send window " + tv.fmt_bytes(min(win)) if win else ""
        return "ok", "frames skipped: " + ", ".join("%s=%d" % kv for kv in skipped.items()) + extra
    return "waiting", "Nothing skipped yet. On one Viewer set Settings > Slow Viewer delay 300, reconnect."


def _c_error(rows):
    t = _tcps(rows)
    if not t:
        return "waiting", "No kernel counters."
    total = sum(x["retrans"] for x in t)
    unit = "bytes" if t[0]["retrans_unit"] == "bytes" else "segments"
    if total > 0:
        return "ok", "%d %s retransmitted - TCP recovered lost data." % (total, unit)
    return "waiting", ("0 retransmitted. A healthy LAN shows zero; say so, or cause loss "
                       "(Wi-Fi off 3-5 s / Clumsy) and watch this change.")


STEPS = (
    {"title": "1. Connections (multiplexing)",
     "do": "Start Sharing, connect two Viewers.",
     "say": "One TCP connection per Viewer. Same server port 5000, different client ports.",
     "filter": "tcp.port == 5000", "check": _c_connect},
    {"title": "2. Connection management",
     "do": "Capture on the real network card, then Disconnect one Viewer.",
     "say": "Three-way handshake at connect, FIN/ACK at a clean disconnect, done by the OS.",
     "filter": "tcp.flags.syn == 1 || tcp.flags.fin == 1",
     "check": _c_manual("Proof is in Wireshark: SYN, SYN-ACK, ACK and FIN/ACK.")},
    {"title": "3. Acknowledgement and sequence numbers",
     "do": "Click one data segment in Wireshark; keep the Transport Dashboard open.",
     "say": "The receiver ACKs bytes; 'In flight' is sent-but-unacknowledged data.",
     "filter": "tcp.port == 5000 && tcp.len > 0", "check": _c_ack},
    {"title": "4. Flow control",
     "do": "On ONE Viewer: Settings > Slow Viewer delay 300 > Save > reconnect.",
     "say": "The slow receiver's window shrinks, TCP slows the sender, our latest-frame slot "
            "drops old frames. The other Viewer is unaffected.",
     "filter": "tcp.analysis.zero_window || tcp.analysis.window_full", "check": _c_flow},
    {"title": "5. Error control",
     "do": "Cause a short network loss (see docs/DEMO_TRANSPORT.md), or state that LAN loss is zero.",
     "say": "TCP detects loss by missing ACKs and retransmits. Detection and recovery, not correction.",
     "filter": "tcp.analysis.retransmission || tcp.analysis.fast_retransmission",
     "check": _c_error},
    {"title": "6. Evidence and report",
     "do": "Menu > Demo > Save evidence snapshot; then python tools/pcap_report.py capture.pcapng --port 5000",
     "say": "The numbers on this screen come from the operating system, cross-checked with the capture.",
     "filter": "tcp.port == 5000", "check": _c_manual("Snapshot and capture report are files you show.")},
)

ICON = {"ok": "[OK]", "waiting": "[..]", "manual": "[Wireshark]"}


def evaluate(index, rows):
    """(status, text) for STEPS[index] from the current Host statistics rows."""
    return STEPS[index]["check"](rows)


def snapshot_text(rows, when=None):
    """Plain-text evidence file: every step's live status, then the Viewer table."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
    lines = ["Screen Share - transport evidence snapshot", when, ""]
    for i, step in enumerate(STEPS):
        status, text = evaluate(i, rows)
        lines.append("%s %s: %s" % (ICON[status], step["title"], text))
    lines += ["", "\t".join(tv.VIEWER_COLUMNS)]
    lines += ["\t".join(r) for r in tv.viewer_rows(rows)]
    return "\n".join(lines) + "\n"
