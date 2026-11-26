"""Offline TCP report for a .pcap/.pcapng captured while the project runs.

  python tools/pcap_report.py capture.pcapng [--port 5000]

Reads the file only (no admin rights, no Npcap needed). It reports what the
capture shows; it never invents events. Requires: pip install scapy
"""
import argparse
from collections import defaultdict

from scapy.all import IP, TCP, rdpcap

FIN, SYN, RST, ACK = 0x01, 0x02, 0x04, 0x10


def dedupe(packets, window_ms):
    """Drop byte-identical copies seen within window_ms (Linux 'lo' sniffing shows
    every packet twice). Real retransmissions come >= 200 ms later, so 1 ms is safe."""
    last, out = {}, []
    for pkt in packets:
        if IP not in pkt or TCP not in pkt:
            out.append(pkt)
            continue
        k = (pkt[IP].src, pkt[IP].dst, pkt[TCP].sport, pkt[TCP].dport, int(pkt[TCP].flags),
             pkt[TCP].seq, pkt[TCP].ack, len(bytes(pkt[TCP].payload)))
        if k in last and (float(pkt.time) - last[k]) * 1000 <= window_ms:
            continue
        last[k] = float(pkt.time)
        out.append(pkt)
    return out


def analyse(packets, port):
    flows = defaultdict(lambda: {
        "syn": None, "synack": None, "ack3": False, "fin": 0, "rst": 0,
        "data_segments": 0, "data_bytes": 0, "retrans": 0, "dup_acks": 0,
        "zero_window": 0, "min_win": None, "max_win": 0, "wscale": {},
        "rtt_ms": None, "_seen": {}, "_last_ack": {}, "_dups": {}})
    for pkt in packets:
        if IP not in pkt or TCP not in pkt:
            continue
        ip, tcp = pkt[IP], pkt[TCP]
        if port not in (tcp.sport, tcp.dport):
            continue
        a, b = (ip.src, tcp.sport), (ip.dst, tcp.dport)
        key = tuple(sorted((a, b)))
        f = flows[key]
        flags, t = int(tcp.flags), float(pkt.time)
        length = len(bytes(tcp.payload))
        if flags & SYN:
            for name, val in tcp.options:
                if name == "WScale":
                    f["wscale"][a] = val
            if not flags & ACK:
                f["syn"] = t
            else:
                f["synack"] = t
                if f["syn"] is not None:
                    f["rtt_ms"] = (t - f["syn"]) * 1000
        elif flags & ACK and f["synack"] is not None and not f["ack3"] and not length:
            f["ack3"] = True
        if flags & FIN:
            f["fin"] += 1
        if flags & RST:
            f["rst"] += 1
        win = tcp.window << f["wscale"].get(a, 0) if not flags & SYN else tcp.window
        f["min_win"] = win if f["min_win"] is None else min(f["min_win"], win)
        f["max_win"] = max(f["max_win"], win)
        if win == 0 and not flags & (SYN | RST | FIN):
            f["zero_window"] += 1
        if length:
            f["data_segments"] += 1
            f["data_bytes"] += length
            end = tcp.seq + length
            if end <= f["_seen"].get(a, 0) or (a, tcp.seq) in f["_seen"]:
                f["retrans"] += 1
            f["_seen"][a] = max(f["_seen"].get(a, 0), end)
            f["_seen"][(a, tcp.seq)] = True
        elif flags & ACK and not flags & (SYN | FIN | RST):
            if f["_last_ack"].get(a) == tcp.ack:
                f["_dups"][a] = f["_dups"].get(a, 0) + 1
                f["dup_acks"] += 1
            else:
                f["_dups"][a] = 0
            f["_last_ack"][a] = tcp.ack
    return flows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--dedupe-ms", type=float, default=0.0,
                    help="drop identical packets closer than this (use 1 for Linux loopback captures)")
    args = ap.parse_args()
    flows = analyse(dedupe(rdpcap(args.pcap), args.dedupe_ms) if args.dedupe_ms else rdpcap(args.pcap), args.port)
    if not flows:
        print("No TCP packets on port %d in this capture." % args.port)
        return
    for (a, b), f in flows.items():
        print("Flow %s:%d <-> %s:%d" % (a[0], a[1], b[0], b[1]))
        print("  handshake        :", "SYN, SYN-ACK, ACK seen" if f["syn"] is not None and f["synack"] is not None and f["ack3"]
              else "incomplete (capture started late?)")
        if f["rtt_ms"] is not None:
            print("  handshake RTT    : %.3f ms" % f["rtt_ms"])
        print("  data             : %d segments, %d bytes" % (f["data_segments"], f["data_bytes"]))
        print("  retransmissions  :", f["retrans"])
        print("  duplicate ACKs   :", f["dup_acks"])
        print("  zero-window      :", f["zero_window"])
        print("  window (bytes)   : min %s, max %s" % (f["min_win"], f["max_win"]))
        print("  FIN / RST        : %d / %d" % (f["fin"], f["rst"]))


if __name__ == "__main__":
    main()
