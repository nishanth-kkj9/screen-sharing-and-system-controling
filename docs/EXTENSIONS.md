# Student-approved extensions to the specification

`ARCHITECTURE_FINAL_v5.md` stays the specification of record and is not edited.
This file lists what was added on top of it, so a reader can tell spec from extension.

## 1. PING / PONG (application round-trip time)
- Viewer announces `"features": ["ping"]` inside JOIN. Extra JOIN fields are ignored by the
  section 5.5 contract, so an older Viewer still joins.
- Only a Viewer that announced `ping` is pinged. Host to Viewer: `{"type":"PING","id":<int>}` about
  once per second (`config.PING_INTERVAL`), at most one unanswered PING at a time, forgotten
  after `config.PING_TIMEOUT` seconds. Viewer to Host: `{"type":"PONG","id":<same int>}`.
- Both are ordinary JSON messages (type 1) in the existing 5-byte framing. `PROTOCOL_VERSION`
  stays 1. A malformed PONG is answered with ERROR `unsupported_message` like any bad message.
- The measured time includes the Viewer's processing, so it is labelled "App RTT".

## 2. Kernel TCP statistics (`tcpstats.py`)
Read-only. Windows 10 version 1703 or later: `WSAIoctl(SIO_TCP_INFO)` returning `TCP_INFO_v0`
(no administrator rights). Linux (development only): `getsockopt(TCP_INFO)`. Any failure gives
`None` and the dashboard shows a dash. The program never computes or fakes these numbers.

## 3. Transport dashboard (`transport_view.py`, `gui.TransportDashboard`)
Host window, Menu > Transport Dashboard. Per Viewer: App RTT, TCP RTT, retransmitted data,
duplicate ACKs, congestion window, send window, bytes in flight, skipped frames. A second table
names each TCP feature and shows the live evidence for it.

## 4. Settings (`settings.py`, `gui.SettingsDialog`)
JSON file in `%APPDATA%\screenshare\settings.json`. Host: port, FPS, JPEG quality, maximum
screen size, maximum Viewers (1 or 2). Viewer: port, name, slow-Viewer delay (flow-control
demonstration), last Host address. Values are validated; a corrupt file falls back to defaults.
Settings apply only while stopped or disconnected.

## 5. Offline analysis tool (`tools/pcap_report.py`)
Reads a Wireshark capture with Scapy and prints handshake, retransmissions, duplicate ACKs,
zero-window events, window sizes and FIN/RST. Optional; not part of the application.
Install with `pip install -r tools/requirements-tools.txt`.

## What was NOT changed
Port, header, max Viewers, runtime packages (`mss`, `Pillow`, `PyAutoGUI` only), fail-safe.
