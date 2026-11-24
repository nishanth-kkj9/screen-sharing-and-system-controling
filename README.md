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
├── .gitignore             # .venv/, __pycache__/, *.pyc, build artifacts
├── tests/
│   ├── __init__.py
│   ├── test_all.py        # Section-24 reference tests (framing, slot, outbox, keys, geometry)
│   ├── test_protocol.py   # JSON contract: fields, directions, reason lists (sections 5.5-5.8)
│   └── test_permissions.py# Single-controller rules + loopback integration flow
└── docs/
    ├── wireshark_demo.md  # Capture procedure, filters, demonstration sequence
    └── test_results.md    # What has actually been tested, and what has not
```

`.venv/` (the local virtual environment) is created by the setup step below and is
not part of the source tree.

## Setup (Windows laptops)

1. Install Python 3.10+ from python.org (tick "Add python.exe to PATH"). Verify Tkinter:

   ```powershell
   python --version
   python -m tkinter
   ```

2. Create a project-local virtual environment and install the three runtime
   dependencies **into it** (`pip` under `.venv` installs nothing into the system
   Python):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1          # cmd.exe: .\.venv\Scripts\activate.bat
   python -m pip install --upgrade pip
   python -m pip install -e .
   ```

   `pyproject.toml` holds the dependency bounds — `mss>=10.2,<11` (because
   `from mss import MSS` and `sct.primary_monitor` require mss 10.2.0 or newer),
   `Pillow>=10.0` and `PyAutoGUI>=0.9.54`. The editable install puts the
   `screenshare` package on the import path and creates the `screenshare` command.

   If PowerShell blocks the activation script, either run
   `Set-ExecutionPolicy -Scope Process Bypass` for that window only, or skip
   activation and call the interpreter directly:
   `.\.venv\Scripts\python.exe -m screenshare host`.

3. Allow inbound TCP 5000 on the Private firewall profile (Host laptop, elevated
   PowerShell — only when you understand the profile scope):

   ```powershell
   New-NetFirewallRule -DisplayName "Student Screen Share TCP 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
   ```

   Do **not** disable Windows Firewall or open the Public profile. Check the rule
   afterwards with
   `Get-NetFirewallRule -DisplayName "Student Screen Share TCP 5000"`.

## Running

With the virtual environment activated (or prefix every command with
`.\.venv\Scripts\python.exe`):

```powershell
screenshare                       # shows a mode chooser
screenshare host                  # or start straight into Host mode
screenshare viewer                # or straight into Viewer mode

.\.venv\Scripts\python.exe -m screenshare host     # same, without the console script
.\.venv\Scripts\python.exe -m screenshare viewer
```

**Host:** click *Start Sharing*. The window shows the LAN IPv4 address, TCP port 5000
and a fresh 8-character session code (generated with `secrets` for each session).

**Viewer (on the other laptops):** enter the Host's Wi-Fi IPv4 address (from
`ipconfig` on the Host) and the session code, then *Connect*. Both Viewers see the
Host screen. *Request Control* asks the Host for permission; only one Viewer can
control at a time; the Host can revoke at any moment.

**Finding the Host address:** on the Host run `ipconfig` and read the IPv4 address
under the active Wi-Fi adapter (the app also displays it). Test reachability from a
Viewer with `Test-NetConnection <host-ip> -Port 5000` — expect `TcpTestSucceeded: True`.
If it fails, check the IP, server state, firewall and hotspot client/AP isolation
(some phone hotspots block device-to-device traffic; use a Wi-Fi router instead).

## Running the tests

Install the package once first (editable install: `python -m pip install -e .`),
then run the suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite contains 64 tests: 18 section-24 reference tests, 12 protocol-contract
tests (required fields, directions, reason lists), and 34 for the permission rules,
input validation, fail-safe handling, Host statistics and a full loopback integration
flow (two viewers, grant, revoke, held-key release, viewer-limit refusal, wrong-code
handling, non-ASCII and empty session codes, JOIN_ACCEPT ordering, graceful
DISCONNECT, release returning to view-only). Everything runs without PyAutoGUI or a
display.

## Transport-layer demonstrations (Module 4)

`demo/transport_demos.py` is a separate standard-library program; it never imports the
application. Run it while Wireshark captures:

```powershell
.\.venv\Scripts\python.exe demo\transport_demos.py boundaries   # TCP byte stream vs UDP datagrams
.\.venv\Scripts\python.exe demo\transport_demos.py ports        # one server port, two client ports
# Across two laptops on TCP 6000 (add the firewall rule for 6000 as well):
#   laptop B: python demo\transport_demos.py flow-recv --delay 0.05 --chunk 1024
#   laptop A: python demo\transport_demos.py flow-send --host <B-ip>
```

`boundaries` and `ports` were run on this Windows laptop over loopback; the two-laptop
flow-control run is still untested here (see `docs/test_results.md`, section 10).

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
