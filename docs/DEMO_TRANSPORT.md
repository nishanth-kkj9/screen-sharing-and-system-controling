# Transport-layer demonstration script (about 6 minutes)

Run `python -m unittest discover -s tests` first. Stop any other Host first (port 5000).

1. **Start**: Host: Start Sharing, then open **Menu > Transport Dashboard** (menu bar; **Menu > Demo > Demo guide** walks the steps). Two Viewers connect.
   Say: one TCP connection per Viewer; the dashboard shows each Viewer's App RTT and TCP RTT.
2. **Connection management** (Wireshark, filter `tcp.port == 5000`): show SYN, SYN-ACK, ACK;
   then Disconnect a Viewer and show FIN/ACK. A normal Disconnect ends with FIN/ACK; a RST appears
   only when a peer dies abruptly (process killed, cable pulled), so FIN means an orderly close.
3. **Acknowledgement and sequence numbers**: click a data segment, show seq/ack/window; point to
   "In flight" and "Send window" on the dashboard.
4. **Flow control**: on one Viewer: Settings, "Slow Viewer delay" 300, Save, reconnect. The
   dashboard's "Frames skipped" rises and App RTT grows for that Viewer only; the other Viewer is
   unaffected. Say: the receiver window fills, TCP slows the sender, our latest-frame slot drops
   old frames.
5. **Error control**: with a loss tool running (see below) show "Retransmitted" and "Dup ACKs"
   rising and `tcp.analysis.retransmission` in Wireshark. Without loss, say plainly that a healthy
   LAN shows zero and that is a correct result.
6. **After the demo**: `python tools/pcap_report.py capture.pcapng --port 5000`.

Loss tool (not part of this project, optional): Clumsy, a Windows packet loss/lag simulator built on
WinDivert, https://jagt.github.io/clumsy/ . Filter it to port 5000 and use a small drop percentage.
It installs a network driver while running and needs administrator rights.

Say in the viva: TCP does error detection and recovery by retransmission, not error correction;
the operating system implements ACKs, retransmission, flow control and congestion control; this
program only reads their counters.
