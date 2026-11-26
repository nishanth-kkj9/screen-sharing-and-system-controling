"""Pure text for the Host Transport dashboard (no Tk), so it can be unit-tested.

Each TCP feature is matched with the evidence the project can really show. Values
the kernel did not supply are shown as a dash, never as a made-up number."""

DASH = "—"


def fmt_bytes(value):
    if value is None:
        return DASH
    if value < 1024:
        return "%d B" % value
    if value < 1024 * 1024:
        return "%.1f KB" % (value / 1024.0)
    return "%.2f MB" % (value / (1024.0 * 1024.0))


def fmt_ms(value):
    return DASH if value is None else "%.2f ms" % value


def fmt_count(value):
    return DASH if value is None else str(value)


def retrans_text(tcp):
    if not tcp:
        return DASH
    unit = "B" if tcp["retrans_unit"] == "bytes" else "seg"
    return "%d %s" % (tcp["retrans"], unit)


def viewer_rows(rows):
    """One tuple of strings per Viewer for the dashboard table."""
    out = []
    for row in rows:
        tcp = row.get("tcp")
        out.append((
            row["name"],
            fmt_ms(row.get("rtt_ms")),
            fmt_ms(tcp["rtt_ms"]) if tcp else DASH,
            retrans_text(tcp),
            fmt_count(tcp["dup_acks"]) if tcp else DASH,
            fmt_bytes(tcp["cwnd"]) if tcp else DASH,
            fmt_bytes(tcp["snd_wnd"]) if tcp else DASH,
            fmt_bytes(tcp["in_flight"]) if tcp else DASH,
            str(row["skipped"]),
        ))
    return out


VIEWER_COLUMNS = ("Viewer", "App RTT", "TCP RTT", "Retransmitted", "Dup ACKs",
                  "Cwnd", "Send window", "In flight", "Frames skipped")


def explainer(rows):
    """(TCP feature, what it does, live evidence) for the viva. Evidence is built
    only from numbers present in `rows`."""
    tcps = [r["tcp"] for r in rows if r.get("tcp")]
    retrans = sum(t["retrans"] for t in tcps)
    unit = tcps[0]["retrans_unit"] if tcps else ""
    skipped = sum(r["skipped"] for r in rows)
    ports = ", ".join(r["peer"] for r in rows) or DASH
    live_retrans = (DASH if not tcps else
                    "%d %s retransmitted so far" % (retrans, "bytes" if unit == "bytes" else "segments"))
    windows = [t["snd_wnd"] for t in tcps if t["snd_wnd"] is not None]
    live_flow = ("%s frames skipped" % skipped
                 + ("; smallest send window %s" % fmt_bytes(min(windows)) if windows else ""))
    cwnds = [t["cwnd"] for t in tcps]
    return [
        ("Connection management", "three-way handshake, FIN close",
         "Wireshark: tcp.flags.syn == 1 and tcp.flags.fin == 1"),
        ("Multiplexing by port", "port numbers pick the process", "peers: " + ports),
        ("Acknowledgement", "receiver confirms bytes",
         "in flight: " + (", ".join(fmt_bytes(t["in_flight"]) for t in tcps) if tcps else DASH)),
        ("Error control", "lost data is sent again", live_retrans),
        ("Error detection", "checksum, done by the operating system",
         "Wireshark: tcp.checksum.status"),
        ("Flow control", "receiver window limits the sender", live_flow),
        ("Congestion control", "congestion window limits the sender",
         "cwnd: " + (", ".join(fmt_bytes(c) for c in cwnds) if cwnds else DASH)),
    ]


def format_duration(seconds):
    """125 -> '2:05', 3725 -> '1:02:05' (Connected column)."""
    seconds = max(int(seconds), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "%d:%02d:%02d" % (hours, minutes, secs) if hours else "%d:%02d" % (minutes, secs)


def host_header(sharing, viewers, pending, active):
    """(kind, headline, hint) for the status header. Pure, so it is unit-tested."""
    if not sharing:
        return "idle", "Not sharing", "Press Start Sharing to share this screen."
    if active:
        return "control", "%s is controlling this PC" % active, \
            "Press Revoke Control to take it back at any time."
    if pending:
        return "request", "Control request from %s" % pending, \
            "Press Approve to allow it or Deny to refuse."
    if viewers:
        return "sharing", "Sharing with %d Viewer%s" % (viewers, "" if viewers == 1 else "s"), \
            "Viewers watch only. A Viewer must ask for control and you approve it."
    return "sharing", "Sharing - waiting for Viewers", \
        "Give a Viewer the address and session code below."
