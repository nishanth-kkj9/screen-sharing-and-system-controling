# Setup Guide — Network-Based Screen Sharing and Remote Control

This is the only document you need to install, run and demonstrate the application.
`README.md` describes what the project is and how it works; this file covers the
practical steps.

The application has two roles: a **Host** that shares its screen, and a **Viewer**
that watches and, with the Host's approval, controls the Host's mouse and keyboard.
Everything runs over the OS-provided TCP on port **5000** — no internet, no relay
server, no accounts.

---

## 1. What you need

- Two or more Windows 10 / 11 laptops: one Host, up to **two** Viewers.
- Python **3.10 or newer** on every laptop (tested on Python 3.15.2 with Tk 9.0).
  The python.org installer includes Tkinter.
- A private LAN: the same Wi-Fi network, a phone hotspot that allows
  device-to-device traffic, or an Ethernet switch.
- TCP port **5000** free on the Host.
- The project folder copied to every laptop (clone the repository or copy the
  directory including `pyproject.toml` and `src/`).

The application is Windows-oriented: the Host injects input with PyAutoGUI, so
remote control is meant to run on Windows. Viewing itself only needs Python,
Tkinter, `mss` and Pillow.

---

## 2. Install on every laptop

Open PowerShell in the project folder.

```powershell
python --version            # must be 3.10+
python -m tkinter           # a small Tk window must appear; close it

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

What this does:

- `.venv` is a project-local virtual environment (ignored by Git); nothing is
  installed into the system Python.
- `pyproject.toml` holds the three runtime dependencies with bounds:
  `mss>=10.2,<11`, `Pillow>=10.0`, `PyAutoGUI>=0.9.54`.
- The editable install (`-e .`) puts the `screenshare` package on the import path
  and creates a `screenshare` command inside `.venv\Scripts`.

Verify the install:

```powershell
python -c "import screenshare.app; print('install ok')"
Get-ChildItem .venv\Scripts\screenshare.exe
```

**If PowerShell blocks `Activate.ps1`** with an execution-policy error, either
allow scripts for that window only:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

or skip activation entirely and call the interpreter directly, e.g.
`.\.venv\Scripts\python.exe -m screenshare host` (used in the commands below).

---

## 3. Start the application

With the environment activated:

```powershell
screenshare            # mode chooser window: Host or Viewer
screenshare host       # straight into Host mode
screenshare viewer     # straight into Viewer mode
```

Without activation, the same three commands:

```powershell
.\.venv\Scripts\python.exe -m screenshare
.\.venv\Scripts\python.exe -m screenshare host
.\.venv\Scripts\python.exe -m screenshare viewer
```

The window titles tell the roles apart:

- **`Screen Share - Host (TCP 5000)`** — the laptop sharing its screen.
- **`Screen Share - Viewer`** — the laptop watching.

---

## 4. Host laptop (share the screen)

1. Click **Start Sharing**.
   The panel changes to `listening`, shows `TCP port 5000 - listening on all
   interfaces`, a list of this laptop's IPv4 addresses, and a fresh
   **session code**. The code is 8 characters from an alphabet without
   `I`, `O`, `0` and `1` (to avoid misreading), and a **new code is generated
   every time sharing starts**.
2. Read the IPv4 address from the drop-down list (see section 5). Selecting an
   address only changes what is displayed — the Host listens on all interfaces.
3. When a Viewer asks for control, **Approve** or **Deny** it. The label
   `Controller: <name>` shows who is in control; **Revoke Control** takes it back
   immediately and releases any keys or buttons still held.
4. The **Viewer statistics** table shows each Viewer: name, peer `ip:port`,
   connected seconds, frames, bytes, and skipped frames (frames replaced in the
   one-item queue before they were sent). Below it: total FPS and KB/s.
   Select a row and click **Disconnect Viewer** to drop a stuck client.
5. **Stop Sharing** closes the listener, ends every Viewer session, releases all
   held remote input, and clears the session code.

The log box at the bottom records the important events: sharing started, a
connection waiting for JOIN, a Viewer connected, control granted, disconnects.

---

## 5. Find the Host's address

The Host window shows the best-guess LAN IPv4 address and a drop-down of every
candidate IPv4 (virtual adapters from VirtualBox, WSL or Hyper-V may appear too).
To confirm from a Viewer laptop:

```powershell
ipconfig
Test-NetConnection <host-ip> -Port 5000
```

`TcpTestSucceeded : True` means the TCP port is reachable. If it is `False`:

- the addresses are on different networks (check both `ipconfig` outputs),
- the Host is not sharing yet,
- the firewall rule is missing (section 6), or
- the hotspot blocks device-to-device traffic (some phone hotspots do — use a
  Wi-Fi router instead).

Windows blocks inbound `ping` by default, so a failing `ping` alone proves
nothing; test the TCP port instead.

---

## 6. Firewall rule (Host laptop only)

Run **once**, in an **elevated** PowerShell on the Host:

```powershell
New-NetFirewallRule -DisplayName "Student Screen Share TCP 5000" `
  -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

Check it:

```powershell
Get-NetFirewallRule -DisplayName "Student Screen Share TCP 5000"
```

**Also check the network profile — this is the most common reason a demo fails.**
Windows treats a newly joined Wi-Fi network, including a phone hotspot, as
**Public**; a Private-only rule then does not apply and Viewers cannot connect:

```powershell
Get-NetConnectionProfile
# only on the trusted demo network, if the Wi-Fi shows NetworkCategory = Public:
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

Use the interface alias printed by the first command.

Remove it when the demonstration is over:

```powershell
Remove-NetFirewallRule -DisplayName "Student Screen Share TCP 5000"
```

Do **not** disable Windows Firewall, do not open the Public profile, and do not
set up router port forwarding. The rule is limited to the trusted Private profile.

---

## 7. Viewer laptop(s) (watch and control)

1. Enter the Host's IPv4 address in **Host IPv4 address** (default `127.0.0.1`
   is for same-machine testing only).
2. Enter the **session code** shown on the Host.
3. Click **Connect**.

The state label below the form shows the current state:

| Label | Meaning |
| --- | --- |
| `disconnected` | no connection |
| `connecting` | TCP connect in progress |
| `authenticating` | JOIN sent, waiting for the Host's JOIN_ACCEPT |
| `view-only` | frames are arriving; no control |
| `request pending` | control requested, waiting for the Host |
| `controlling` | remote input is being sent |

Notes:

- Up to two Viewers can connect; a third gets a "Host already has two Viewers"
  message.
- A wrong session code shows "The session code was wrong." and that connection
  ends, so click **Connect** again with the current code. (The Host also closes a
  TCP connection outright after three wrong JOINs on it; the GUI never needs this,
  because each attempt is a fresh connection.)
- A JOIN that never arrives within 10 seconds is closed by the Host.
- Both laptops must run the same project version (the protocol version is
  checked during JOIN).

---

## 8. Remote control

1. On the Viewer, click **Request Control**. The Host shows
   `Pending request from: <name>` and enables **Approve** / **Deny**.
2. The Host clicks **Approve**. Only one Viewer can control at a time: a second
   request is refused with `controller_busy`, and a second request while one is
   pending is refused with `request_pending`.
3. While `controlling`, the Viewer's canvas sends:

   - mouse movement, left/right button press and release (a press that starts
     outside the image is ignored; a release outside is clamped so a drag can
     never leave a button held),
   - wheel scrolling (accumulated per notch; small touchpad deltas are kept),
   - keyboard input for an allowlist only: **letters, digits, Enter, Space, Tab,
     Backspace, Esc, arrow keys, and Shift**.

   Other keys (function keys, punctuation outside the allowlist) are not forwarded.
   Ctrl, Alt and Windows-key combinations are not sent either: pressing Ctrl+A
   forwards `a` only. Shift is part of the allowlist, so Shift+key sends `shift`
   down/up around the letter.
4. The Viewer can click **Release Control**, or the Host can click
   **Revoke Control** at any time. Either way, any key or button still held is
   released on the Host.
5. **PyAutoGUI fail-safe.** Move the Host's *physical* mouse into a screen corner
   and remote input is cancelled immediately (control is revoked and the Host
   shows a warning). Injected positions are nudged one pixel off the exact corner
   pixels, so only the Host's real mouse can trigger it. The fail-safe is enabled
   for every input action; it is suspended only for the moment it takes to release
   held keys and buttons during a revoke, then restored.

Remote input does not reach UAC elevation prompts, the lock screen or other
protected desktops; Windows blocks synthetic input there by design.

---

## 9. Run the test suite

**Stop any running Host first.** The suite's loopback tests bind real TCP sockets
on `127.0.0.1:5000`. If that bind fails the end-to-end class is **skipped** and the
run reports `OK (skipped=...)` instead of 64 passing tests; on Windows
`SO_REUSEADDR` can even let the test Host bind alongside a running one, which gives
confusing results. Stop the Host first and the full 64 pass.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected result:

```text
Ran 64 tests in ...
OK
```

The 64 tests are: 18 section-24 reference tests (framing, slot, outbox, keys,
geometry), 12 protocol-contract tests (required fields, directions, reason
lists), and 34 permission/input/statistics tests including a full loopback flow
(two viewers, grant, revoke, held-key release, viewer limit, wrong codes,
non-ASCII codes, JOIN_ACCEPT ordering, graceful disconnect). No real mouse is
moved and no display is required.

---

## 10. Optional: slow-Viewer flow-control demonstration

The Viewer's reader can deliberately sleep after each frame, which shows the
single-connection flow-control behaviour with the application itself. This is a
test-only setting, **off by default** (`0`).

In the PowerShell window that will start the **Viewer**:

```powershell
$env:SCREENSHARE_SLOW_VIEWER_MS = "200"     # 200 ms per frame
.\.venv\Scripts\python.exe -m screenshare viewer
```

Remove it afterwards:

```powershell
Remove-Item Env:SCREENSHARE_SLOW_VIEWER_MS
```

A malformed value is ignored (the app falls back to `0`) instead of stopping.

---

## 11. Module-4 transport demonstrations

`demo/transport_demos.py` is a separate standard-library program; it never
imports the application. Run it while Wireshark captures (section 12):

```powershell
.\.venv\Scripts\python.exe demo\transport_demos.py boundaries   # TCP byte stream vs UDP datagrams
.\.venv\Scripts\python.exe demo\transport_demos.py ports        # one server port, two client ports
```

Across two laptops it uses TCP **6000** (add a firewall rule for 6000 as well, or
run it on the same machine):

```powershell
# laptop B (receiver), first:
.\.venv\Scripts\python.exe demo\transport_demos.py flow-recv --delay 0.05 --chunk 1024
# laptop A (sender):
.\.venv\Scripts\python.exe demo\transport_demos.py flow-send --host <B-ip>
```

`boundaries` and `ports` have been run on Windows over loopback; the two-laptop
flow-control run is still untested here (see `docs/test_results.md`, section 10).

---

## 12. Wireshark capture

The capture procedure, display filters and the narration for the transport-layer
evidence are in [`docs/wireshark_demo.md`](docs/wireshark_demo.md).

Short version: capture on the Wi-Fi adapter, filter `tcp port 5000`, and record a
full session (handshake → JOIN/JPEG data → control grant → revoke → FIN).

---

## 13. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Cannot listen on TCP port 5000: ...` | another Host instance or the test suite already uses the port | stop the other process; check with `Get-NetTCPConnection -LocalPort 5000` |
| Viewer: "Could not connect to the Host: ..." | wrong IP, different network, firewall, Host not sharing | `ipconfig`, `Test-NetConnection <ip> -Port 5000`, start sharing, add the Private rule |
| "The session code was wrong." | typo, or code from an earlier session | read the current code on the Host; a new code is generated per sharing session |
| Viewer returns to `disconnected` after Connect | the JOIN was denied or the code was wrong; each attempt is a new connection | enter the current code and click **Connect** again |
| "The Host already has two Viewers." | two Viewers already connected | close one Viewer |
| "The Host speaks a different protocol version." | different project versions | use the same code on both laptops |
| Viewer stays `view-only`, no image | Host not sharing, or capture failing | check the Host log box; stop and restart sharing |
| Remote input does nothing | not `controlling`, allowlist key, or UAC/lock screen | check the state label; only allowlisted keys are forwarded; UAC prompts cannot be controlled |
| Control stops by itself, Host warns about the fail-safe | Host's physical mouse was moved into a screen corner | move the mouse away; request control again |
| Remote cursor is offset from the real one | display scaling differs between laptops | the app sets per-monitor DPI awareness; 125% has been verified, other values should be checked on the real Host |
| Tests report `OK (skipped=...)` instead of 64 passing | a Host still holds port 5000, so the loopback tests skipped (or, with `SO_REUSEADDR`, bound a second listener) | stop the Host, then re-run the suite |
| PowerShell blocks `Activate.ps1` | execution policy | `Set-ExecutionPolicy -Scope Process Bypass`, or call `.venv\Scripts\python.exe` directly |

---

## 14. What has been verified, and what has not

`docs/test_results.md` records every check honestly. In short:

- **Verified:** the 64-test suite, the entry points, real screen capture over
  loopback, a live Host/Viewer session with control granted and revoked, and
  remote mouse/keyboard/scroll delivery — on Windows 11 at 125% display scaling.
- **Not verified yet `[U]`:** two real laptops over a hotspot/router, 150%
  scaling, the firewall rule on a second machine, a Wireshark `.pcapng`, and the
  FIN-sequence proof on the wire.

Run the `[U]` items on the demonstration laptops before the viva and update
`docs/test_results.md` with the real outcome.
