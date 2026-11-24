# Network-Based Screen Sharing and Remote Control System

A Python desktop application that lets one **Host** computer share its screen with up to
two **Viewer** computers over a private LAN / Wi-Fi / phone hotspot, with Host-approved,
single-controller remote mouse and keyboard control.

- **Course:** VTU B.E. CSE — BCS502 Computer Networks (2022 Scheme, Semester V)
- **Transport:** OS-provided TCP over IPv4, application port **5000 only**
- **Framing:** 5-byte header (`struct.Struct("!BI")`) — type (1 byte) + payload length (4 bytes, big-endian)
- **Message types:** `1` = UTF-8 JSON, `2` = JPEG
- **Stack:** Python 3 standard library + `mss`, `Pillow`, `PyAutoGUI`

## Project structure

```text
network-screen-sharing/
├── pyproject.toml          # Package metadata, dependency bounds, console script
├── src/
│   └── screenshare/
│       ├── __init__.py
│       ├── __main__.py     # `python -m screenshare`
│       ├── app.py          # Entry point; DPI awareness is set FIRST (section 13.4)
│       ├── config.py       # Port, limits, frame rate, image size, session-code constants
│       ├── protocol.py     # 5-byte header, exact reads, JSON validation (section 24 code)
│       ├── server.py       # Host listener, Viewer sessions, permission coordination, lifecycle
│       ├── client.py       # Viewer connection, reader and serialized writer
│       ├── screen_capture.py # MSS capture, Pillow JPEG encode/decode, frame pacing
│       ├── latest_slot.py  # One-item latest-value slot (section 24 code)
│       ├── outbox.py       # Per-connection control queue + latest frame (section 24 code)
│       ├── permissions.py  # PermissionManager: pending/active controller state (section 6.3)
│       ├── keymap.py       # Tkinter keysym -> PyAutoGUI wire names (section 24 code)
│       ├── geometry.py     # Coordinate and fail-safe helpers (section 24 code)
│       ├── remote_input.py # Input validation and allowlisted PyAutoGUI execution
│       └── gui.py          # Tkinter Host and Viewer interfaces
├── demo/
│   └── transport_demos.py # Separate Module-4 demos (TCP 6000, standard library only)
├── README.md
├── SETUP_GUIDE.md         # Install, run, firewall, tests, demos, troubleshooting
├── .gitignore             # .venv/, __pycache__/, *.pyc, build artifacts
├── tests/
│   ├── __init__.py
│   ├── test_all.py        # Section-24 reference tests (framing, slot, outbox, keys, geometry)
│   ├── test_protocol.py   # JSON contract: fields, directions, reason lists (sections 5.5-5.8)
│   └── test_permissions.py# Single-controller rules + loopback integration flow
└── docs/
    ├── wireshark_demo.md  # Capture procedure, filters, demonstration sequence
    ├── test_results.md    # What has actually been tested, and what has not
    └── superpowers/       # Design note and task plan for the src/ layout move
```

`.venv/` (the local virtual environment) is created by the setup step and is
not part of the source tree.

## Setup and running

All installation, firewall, running, testing, demonstration and troubleshooting
steps are in **[SETUP_GUIDE.md](SETUP_GUIDE.md)** — this README does not repeat them.

The application is started with `screenshare host` on the sharing laptop and
`screenshare viewer` on each viewing laptop (or `python -m screenshare host|viewer`);
`screenshare` alone shows a Host/Viewer chooser.

## How it works

- **One full-duplex TCP connection per Viewer** on port 5000 — no second port, no
  control/stream split. TCP (provided by the OS) handles reliability, ordering and
  flow/congestion control; the 5-byte application header only marks message
  boundaries, which TCP's byte stream does not preserve.
- **Host pipeline:** MSS grabs the primary monitor once per frame → Pillow converts
  to RGB and resizes (aspect preserved, at most 1280×720) → one JPEG (quality 65) is
  encoded and the same bytes go to every Viewer → each Viewer's writer sends the
  newest frame from a one-item `LatestSlot` (no queue buildup), after draining
  pending control messages.
- **Threads (Host):** GUI, accept worker, capture worker, plus one reader and one
  writer worker per Viewer socket. Only a connection's writer ever calls `sendall()`
  on that socket. The Viewer has the mirror-image model. GUI updates happen only on
  the Tkinter thread, fed by queues drained with `root.after()`.
- **Permissions:** `PermissionManager` enforces one pending request and one active
  controller. Every input message is re-checked against `active_controller_id`.
  Revocation, release, disconnect and Host shutdown all release keys/buttons still
  held. PyAutoGUI's fail-safe stays enabled; injected positions are nudged 1 px off
  the exact corner pixels so only the Host's physical mouse in a corner stops remote
  input.
- **Session code:** an 8-character code from `secrets.choice()` per sharing session,
  compared with `secrets.compare_digest`. It is plaintext on the wire — a convenience
  gate for a trusted LAN, not real security.

## Known limitations

- 5 FPS JPEG updates; a much slower Viewer can display older frames (accepted
  trade-off of the single-connection design).
- No audio, file transfer, encryption, internet relay, mobile clients or video
  codecs (non-goals of version 1).
- Remote input does not reach UAC prompts, the lock screen or other protected
  desktops; display scaling can affect cursor alignment (verify on the real Host).

See `docs/test_results.md` for what has and has not been verified on real hardware,
and `docs/wireshark_demo.md` for the packet-analysis demonstration.
