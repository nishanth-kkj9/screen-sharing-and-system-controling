# Test Results — recorded honestly (section 0, rule 11)

Nothing below was invented. Every line states what was actually run, where, and
what happened. Items marked **[U]** have **not** been run on the real Windows
laptops and must be tested there before the demonstration.

## Environment where these tests ran

- Linux sandbox, Python 3.12.16
- mss 10.2.0, Pillow 11.3.0 (installed from `requirements.txt` bounds; PyAutoGUI
  is Windows-only input injection and is not exercised in these tests — a fake
  backend records the calls instead, per the section-14.1 test boundary)
- Tkinter GUI exercised under a virtual X server (Xvfb, 1280×800)
- All networking over real TCP sockets on 127.0.0.1, port 5000

Sections 6 and 7 were recorded on Windows 11, Python 3.15.2, Tk 9.0, with real
MSS capture and real PyAutoGUI injection; sections 1–5 are the earlier Linux
sandbox results and are kept as they were. The runtime dependencies now live in
the project-local `.venv`; the 42-test suite and the Windows smoke script were
re-run through `.venv\Scripts\python.exe` with the same results.

## 1. Automated unit tests — PASS (42/42)

Command: `python -m unittest discover -s tests -v`

- `tests/test_all.py` — the 14 section-24 reference tests (framing, partial reads,
  early EOF, oversize rejection, viewer-may-not-send-JPEG, bad JSON, normalized
  coordinates, latest-slot behaviour, key mapping, geometry). **14/14 pass**,
  matching the architecture document's claim.
- `tests/test_permissions.py` — 28 tests:
  - Single-controller rules (section 6.3): first request becomes pending; second
    request denied `request_pending`; request denied `controller_busy` while a
    controller is active; approve re-checks connection; reject/revoke/release/
    disconnect each clear the right state; permission re-checked per event.
  - Input validation (section 9.4): only the active controller acts; normalized
    coordinates mapped to pixels; corners nudged off the fail-safe points;
    out-of-range/NaN/string coordinates rejected; bad mouse button/action
    rejected; scroll amount validated and converted to 120-per-notch; key
    allowlist enforced (`enter` ok, `f5`/`ctrl` rejected); held keys/buttons
    released by `release_all()`.
  - Loopback integration (real TCP, fake frames/input): two viewers join and
    both receive frames; a third viewer is refused `viewer_limit_reached`;
    viewer 1 granted control; viewer 2 denied `controller_busy`; input reaches
    the backend; revoke returns viewer 1 to view-only **and releases the held
    key**; stale input after revocation performs nothing; viewer 2 can then be
    granted; disconnecting the controller does not disturb the other viewer;
    wrong session code denied, empty and non-ASCII codes denied without
    disturbing the Host, and a raw socket with three bad codes gets three
    denials then is closed.
  - Protocol order: the first message a new Viewer receives is `JOIN_ACCEPT`,
    never a cached JPEG frame.
  - Graceful exit: a Viewer that disconnects normally really does send
    `DISCONNECT` (raw listener records `["JOIN", "DISCONNECT"]`).

Result line: `Ran 42 tests ... OK`.

## 2. GUI smoke test under Xvfb — PASS (12/12, three consecutive runs)

Real Tkinter Host and Viewer windows driven through their actual widget
callbacks (Start Sharing, Connect, Request Control, Approve, Revoke,
Disconnect, Stop Sharing) with real TCP between them and fake frames/input.
Checks: viewer reaches view-only through the GUI; a decoded frame is displayed;
request → pending; approve → controlling; input reaches the backend; a
**synthetic left-click fired at the canvas reaches the Host through the real
`<ButtonPress-1>` binding**; a **synthetic X11 wheel event sends exactly one
notch**; revoke → view-only with held key released; disconnect → disconnected;
stop sharing → stopped; **no leftover reader/writer/capture/accept threads**.

Bugs found and fixed by these tests (recorded for the report):
- `ImageTk.PhotoImage` without `master=` bound images to the default root, which
  breaks after the app.py mode chooser destroys its window — fixed by binding
  the photo to the viewer's canvas (verified: chooser-destroy → new root →
  frame display now passes).
- Binding `"<1>"` after `"<ButtonPress-1>"` **silently replaced the earlier
  binding** (Tk treats them as the same event), which would have killed remote
  left-clicks entirely — confirmed with a minimal Tk probe, fixed by moving
  `focus_set()` inside the press handlers.
- X11 delivers the wheel as Button-4/Button-5 (and possibly small deltas in
  `<MouseWheel>`), where `delta // 120` is 0 or absent — a scroll of amount 0
  would be **rejected by the Host and the connection closed** (verified
  directly against `RemoteInput`). Fixed with Button-4/5 bindings, a
  remembered last pointer position, and a minimum-one-notch clamp.
- Closing the listening socket alone did not wake the accept thread on Linux —
  fixed with `shutdown()` before `close()` in `stop_sharing()`.
- The viewer never entered `request_pending` state after sending
  `CONTROL_REQUEST` — fixed (state now follows section 6.2).
- A disconnect during the blocking `connect()` could be overwritten when
  `connect()` finished (state resurrection + zombie threads) — fixed with a
  re-check under the lock before starting the reader/writer.

Also recorded: the viewer writer's control queue is drained once per
`move_slot` wakeup (100 ms worst case when idle), so a discrete input (click,
scroll, key) can trail the event by up to that much. The smoke test waits for
each effect separately instead of checking immediately; this latency is by
design and is bounded.

## 3. End-to-end with REAL MSS capture — PASS

`screen_capture` used unmodified against a virtual display (mss 10.2.0):

- Primary monitor capture: 1280×800 → **1152×720** (aspect preserved, within
  the 1280×720 bound), JPEG at quality 65 → **13,587 bytes** per frame for a
  mostly-empty desktop.
- Two viewers over real TCP loopback each decoded **22 frames in 4.0 s**
  (≈5.5 FPS, consistent with the 5 FPS target plus pacing start-up).
- Control flow verified with fake input: grant → `move` (0.25, 0.75) → pixel
  (479, 809) on a 1920×1080 target screen, `keydown 'a'`/`keyup 'a'`; revoke
  released the held key; both viewers disconnected cleanly; server stopped; no
  leftover threads.

## 4. TCP-level observation — PASS (sandbox substitute)

Raw packet capture (tcpdump/scapy) is not permitted in this sandbox
(`CAP_NET_RAW` denied), so the OS TCP state table was observed instead via
`/proc/net/tcp` during a live run:

- `LISTEN` on port 5000 while sharing.
- Two `ESTABLISHED` connections after both viewers joined (one per viewer, as
  designed).
- Zero `ESTABLISHED` after both disconnected; `TIME_WAIT` teardown states seen
  (graceful FIN exchange).
- No `LISTEN` after Stop Sharing.

The `.pcapng` for the Wireshark demonstration (handshake, sequence/ack fields,
both-direction data, FIN) still has to be captured on the laptops — the
procedure is in `wireshark_demo.md`. **[U]**

## 5. NOT tested yet — must be run on the real Windows laptops **[U]**

Everything Windows-specific and network-specific, per the architecture's [U]
items plus the section 18.3 acceptance checklist:

- [ ] `SetProcessDpiAwareness` behaviour and mouse alignment at 125 %/150 %
      Windows display scaling (section 0.3 C4).
- [ ] PyAutoGUI input injection feel: `PAUSE = 0`, scroll notches
      (`amount * 120`), fail-safe corner behaviour with a real mouse (C1, C2, C6).
- [ ] Tkinter wheel `event.delta` as a multiple of 120 on Windows (C6). The
      GUI now also handles the X11 Button-4/5 form and clamps small deltas to
      one notch, but only Windows hardware confirms the 120-multiple claim.
- [ ] MSS capture of a real Windows primary monitor; real frame sizes and
      throughput on the Wi-Fi/hotspot link.
- [ ] `Test-NetConnection <host-ip> -Port 5000` between laptops; hotspot
      device-to-device reachability; the Private-profile firewall rule.
- [ ] The full section 18.3 checklist between two machines: third viewer denied
      cleanly, control approved/denied, revoke immediacy after the current input
      action, held-key release, Wireshark capture of the real connection.
      (All of these except the two-machine link and the Wireshark capture were done
      on one Windows machine — see sections 6 and 7.)
- [ ] The `JOIN` 10-second timeout against a real connecting viewer (C9) — **done on
      one machine, see section 7** — and the `TCP_NODELAY` effect on mouse-move
      latency (C10) between two machines.

Update this file with real numbers and outcomes as each item is tested; do not
mark a checkbox before the test has actually been run.

## 6. Windows run on the development laptop — PARTIAL PASS

Environment actually used: Windows, Python 3.15.2 (`C:\Python315\python.exe`),
Tk 9.0, mss 10.2.0, Pillow 13.0.0, PyAutoGUI 0.9.54, all three packages installed
from `requirements.txt`. Real MSS capture of the real primary monitor, real TCP
on 127.0.0.1:5000, fake input backend (no real mouse/keyboard injection).

Command: `python -m unittest discover -s tests -v` → `Ran 42 tests ... OK`.

Observed on this machine:

- Real MSS capture + Pillow JPEG: 1280×720 output, 71,120–134,643 bytes per frame,
  125–191 ms per capture+encode.
- First message after `JOIN` was `JOIN_ACCEPT` (`screen_width` 1280, `screen_height`
  720, `fps` 5); at least 3 JPEG frames followed within 6 s.
- Control request → Host approval → `KEY_DOWN` reached the input backend; revoke
  released the held key (`key_up` recorded).
- `HostWindow` and `ViewerWindow` construct and render on the real Windows Tk 9.0.

Two real defects were found and fixed by this run:

- The Host writer could send the cached JPEG **before** the queued `JOIN_ACCEPT`,
  because it drained the control queue only before waiting for a frame. Fixed by
  draining once more after `take()` and before sending the frame; regression test
  `test_join_accept_is_first_message` added.
- `python -m unittest discover -s tests` failed with `Start directory is not
  importable` because `tests/` had no `__init__.py`. Fixed.

A third defect was found by review and is covered by a new test:

- `ViewerClient.disconnect()` called `shutdown(SHUT_WR)` **before** the writer
  flushed the queued `DISCONNECT`, so the message could never be sent: a send on a
  half-closed socket raises `WinError 10058` (verified directly with
  `socket.socketpair()`). The stop event is now set first, the writer drains, then
  the socket is shut down. Regression test
  `test_disconnect_is_sent_before_close` records `["JOIN", "DISCONNECT"]` on a raw
  listener.

Still **not** tested on Windows **[U]**: real PyAutoGUI injection and feel
(`PAUSE = 0`, scroll notches, fail-safe corners with a real mouse), DPI scaling
alignment at 125 %/150 %, two-laptop/hotspot traffic, `Test-NetConnection`, the
firewall rule, and the Wireshark capture. The section 5 list still applies.

## 7. Live GUI run on Windows with real injection — PASS

Both real Tk windows were started from the command line (`python app.py host`,
`python app.py viewer`) on the same laptop and driven through their own widgets
with the desktop automation tool. The Host ran with its console output redirected
to a log file so exit-time noise would be visible.

Observed, in order:

- Host: `Start Sharing` → `listening`, address `192.168.239.112:5000`, fresh
  session code `R5WFCFYG`.
- Raw TCP clients against the live Host: viewer 1 `JOIN_ACCEPT` (screen 1280×720),
  viewer 2 `JOIN_ACCEPT`, viewer 3 `JOIN_DENIED` / `viewer_limit_reached` — the
  denial arrived intact, with no `ConnectionResetError`. Host log:
  `Connection from 192.168.239.112:55998 waiting for JOIN` then
  `refused: viewer limit reached`.
- Viewer GUI: connected to `192.168.239.112:5000` with the code → `view-only`, and
  the canvas showed the live mirrored desktop (recursive view visible). Host list
  showed `LAPTOP-NHODPEG5`.
- `Request Control` → `request pending` on the viewer, `Pending request from:
  LAPTOP-NHODPEG5` on the Host → `Approve` → viewer `controlling`,
  `Controller: LAPTOP-NHODPEG5`.
- Real injection: a click and then typed text through the viewer canvas inserted
  ` live2` into a real Notepad window on the shared desktop (line ended at
  `remote test 123 live2`, 21 characters).
- `Revoke Control` on the Host → viewer `view-only`, `Controller: none`, Revoke
  disabled. Typing `BLOCKED` into the viewer canvas afterwards changed nothing:
  the Notepad line stayed at 21 characters.
- `Request Control` → `Approve` → `Release Control` → viewer returned to
  `view-only` immediately (this is the regression test's behaviour, confirmed live).
- Closing the viewer window removed it from the Host list
  (`Viewer 'LAPTOP-NHODPEG5' disconnected (writer exited)`).
- Three wrong session codes on one raw connection: three `JOIN_DENIED
  invalid_session_code`, then Host log `192.168.239.112 closed after 3 wrong
  session codes`.
- `Stop Sharing` → state `stopped`; `Test-NetConnection 192.168.239.112 -Port 5000`
  → `TcpTestSucceeded: False`.
- Closing the Host window exited with code 0 and the redirected log file was
  **0 bytes** — no traceback and no Tk `invalid command name` noise.

Real MSS capture + JPEG in the same build (Windows smoke script, no injection):
1280×720 at 73,414 and 82,882 bytes, 90–95 ms capture+encode; `JOIN_ACCEPT` was the
first message; 3 JPEG frames followed within 6 s; grant/revoke released the held
key; both windows built on Tk 9.0.

Three defects were found by this run and fixed:

- The third viewer's `JOIN_DENIED` was lost to a Windows TCP reset, because the
  socket was closed while it still held the client's unread `JOIN`. A short-lived
  worker now sends the denial, half-closes with `shutdown(SHUT_WR)`, drains up to
  2 s, then closes (`_deny_connection`). Verified twice: scripted and against the
  live Host.
- `ViewerClient.release_control()` left the viewer UI showing `controlling` until
  the Host's next status broadcast. It now sets `view-only` immediately; regression
  test `ClientState.test_release_control_returns_to_view_only` added.
- Closing a window while its `root.after()` poll was pending printed
  `invalid command name ...` on the console at exit. The poll ids are now cancelled
  in `on_close()`.

DPI consistency on this machine: `mss` primary monitor 1920×1080 equals
`pyautogui.size()` 1920×1080 after `SetProcessDpiAwareness(2)`; fail-safe points are
the four corners (0,0), (0,1079), (1919,0), (1919,1079).

Still **not** tested **[U]**: two physical laptops over a hotspot, display scaling
at 125 %/150 %, the Private-profile firewall rule between machines, and a Wireshark
`.pcapng` (no Npcap/Wireshark or `tshark` on this machine, `pktmon` needs
administrator, and loopback traffic is not captured here).

## 8. Transport-layer checks that do not need a second laptop — PASS

- **C9, JOIN timeout.** A raw TCP client that connected and sent nothing was closed
  after **10.0 s**, having received no bytes; Host log:
  `Connection from 127.0.0.1:60474 waiting for JOIN` then
  `Connection from 127.0.0.1 timed out without JOIN`.
- **Firewall state of this machine (read-only observation).** `Get-NetFirewallRule
  -DisplayName "*5000*"` returned **no rule**, and all three profiles (Domain,
  Private, Public) are enabled with `DefaultInboundAction = NotConfigured`.
  Connections from the same machine to `192.168.239.112:5000` still worked, but a
  real second laptop may be blocked until the rule from the README is added in an
  elevated PowerShell. Adding the rule was **not** attempted (no administrator
  rights here) — this remains **[U]**.
- **Thread accounting.** After Stop Sharing the suite's thread check and the smoke
  script both leave no reader/writer/capture/accept workers behind; the listening
  socket is gone (`TcpTestSucceeded: False`).

## 9. Review-driven hardening, then a second live GUI run — PASS

An independent review of `server.py`, `client.py`, `gui.py` and `protocol.py` found
six real weaknesses. All six were fixed and the suite grew from 39 to **42 tests**:

1. `_handle_join` compared the supplied code with `secrets.compare_digest()`, which
   raises `TypeError` on non-ASCII text (a malformed JOIN could crash the reader
   thread), and `self.session_code or ""` made an **empty** code match a stopped
   Host. Now the code must be an ASCII `str` and `session_code` must not be `None`.
   New test: `EndToEndFlow.test_join_rejects_empty_and_non_ascii_code` (both are
   `JOIN_DENIED / invalid_session_code`, and the Host still serves its real code
   afterwards).
2. The accept worker could reserve a session **after** `stop_sharing()` had
   snapshotted the session list, leaving a session (and its threads) attached to a
   stopped Host and counted against `MAX_VIEWERS`. The slot reservation now checks
   the stop event under the lock and closes the socket instead.
3. `_deny_connection` drained the denied client with only a per-recv timeout; a
   client trickling bytes could hold the thread forever. The drain now has a total
   2-second deadline.
4. `start_sharing()` replaced `self._stop_event`/`self.listener`, which the accept
   and capture loops re-read every iteration. A worker outliving the bounded 1-second
   join could adopt the **new** listener or event (duplicate capture/accept thread).
   Both loops now receive the listener and stop event as thread arguments.
5. `ViewerClient.connect()` published `self.sock`, `_stop_event` and the queues
   outside the lock after its state re-check, so a `disconnect()` in that window was
   lost; stale reader/writer threads also used `self.*` and could shut down a newer
   connection. Publication now happens inside the same critical section, and each
   worker gets its own socket/stop-event/queue/slot arguments; `_on_connection_lost`
   ignores a socket that is no longer `self.sock`.
6. A `CONTROL_DENIED` arriving after `CONTROL_GRANTED` (possible when a Viewer in
   `CONTROLLING` sends another request) forced `VIEW_ONLY` while the Host still
   regarded it as the controller. A deny is now ignored while `CONTROLLING`, and
   `request_control()` only queues a request from `VIEW_ONLY`. New tests:
   `ClientState.test_duplicate_control_denied_keeps_control`,
   `ClientState.test_request_control_only_from_view_only`.

Re-verified after these changes, all through `.venv\Scripts\python.exe`:

- `python -m unittest discover -s tests` → `Ran 42 tests ... OK`.
- JOIN-timeout script → closed after 10.0 s with `timed out without JOIN`.
- Viewer-limit script → 2 × `JOIN_ACCEPT`, then `JOIN_DENIED /
  viewer_limit_reached`, first viewer still receiving afterwards.
- Windows smoke → real MSS 1280×720 (76,595 bytes, 111 ms), `JOIN_ACCEPT` first,
  3 frames, grant/revoke released the held key, both windows on Tk 9.0.
- **Live GUI run** (`app.py host` and `app.py viewer` launched from the venv, driven
  through the real widgets): Host `listening`, code `FZMPBUUD`; Viewer connected over
  `192.168.239.112:5000` and showed `view-only` with live frames; Request → Approve →
  `controlling` (`Controller: LAPTOP-NHODPEG5`); Release → `view-only` and
  `Controller: none`; Disconnect → `disconnected`; closing the Viewer removed it from
  the Host list (`disconnected (writer exited)`); Stop Sharing → `stopped`; the
  listening port was closed (`TcpTestSucceeded: False`) and the Host exited with code
  0 and a **0-byte** console log. No app processes were left behind.

## 10. Demonstration kit — `boundaries` and `ports` run on Windows — PASS

`demo/transport_demos.py` was copied from the provided starter kit byte for byte
(identical SHA-256) and run with `.venv\Scripts\python.exe` on this Windows laptop
over loopback. Standard library only; nothing in the screen-sharing code is used.

```text
> python demo/transport_demos.py boundaries
UDP: sent (10, 20, 30) -> receiver read [10, 20, 30] (message boundaries kept)
TCP: sent (10, 20, 30) -> receiver read [60] (total 60 bytes; TCP does not keep message boundaries, so read sizes need not match send sizes)
=> this is why the project adds a 5-byte header: type + length (protocol.py)

> python demo/transport_demos.py ports
Viewer 1: client ('127.0.0.1', 64815) -> server port 64814 (server sees peer ('127.0.0.1', 64815))
Viewer 2: client ('127.0.0.1', 64816) -> server port 64814 (server sees peer ('127.0.0.1', 64816))
Same server port, different client ports: the OS tells the two connections apart
by (source IP, source port, destination IP, destination port).
```

The TCP read of `[60]` is this machine's behaviour; TCP may also split the same three
sends into more reads, so the claim to make is that TCP gives **no guarantee** of
message boundaries, not that it always merges them.

Still **not** run for the demo kit **[U]**: `flow-recv` / `flow-send` across two real
laptops on TCP 6000 with Wireshark capturing the receiver window, and the same effect
through the application with `SCREENSHARE_SLOW_VIEWER_MS` set on one Viewer.

## 11. Contract-alignment pass against `ARCHITECTURE_FINAL_v5.md` — PASS (64/64)

Everything below was run on this Windows laptop through
`.venv\Scripts\python.exe`. Nothing was invented; commands and outputs are as shown.

### Automated tests

```text
> .venv\Scripts\python.exe -m unittest discover -s tests
Ran 64 tests in 19.4s
OK

> .venv\Scripts\python.exe -m compileall -q (all project .py + tests + demo)
exit 0
```

Split: 18 reference tests (`tests/test_all.py`) + 12 new protocol-contract tests
(`tests/test_protocol.py`) + 34 permission/E2E tests (`tests/test_permissions.py`).

What this pass added or corrected, each with its evidence:

- **`outbox.py` restored byte-for-byte** from the provided starter kit (SHA-256
  identical) with its 4 `OutboxTests` back in `tests/test_all.py`. Both the Host
  writer and the Viewer writer now use one `Outbox` per connection (control first,
  latest frame/move second, blocking `get()`, `None` = closed), replacing the
  separate `control_queue` + `LatestSlot` pair (sections 7.4 and 7.6 rule 1).
- **`permissions.py` created** (spec section 14 requires it): `PermissionManager`
  moved out of `server.py` unchanged; `server.py` re-exports it so existing test
  imports keep working.
- **JSON contract validation appended to `protocol.py`** (sections 5.5, 5.7, 5.8):
  `validate_message()`, `REQUIRED_FIELDS`, per-direction type sets and the exact
  reason lists. New `tests/test_protocol.py` (12 tests) covers missing fields,
  wrong types, `bool`-as-`int`, nullables and direction mistakes.
- **Wrong reason strings fixed**: `unsupported_version` and `invalid_name` for
  JOIN denials (were `unsupported_message`), `host_revoked` for Host revoke,
  `failsafe` for fail-safe revoke (was `host_rejected`), `DISCONNECT reason
  host_stopped` / `user_exit`.
- **Bad input values now answer `ERROR invalid_input` and keep the session open**
  (section 5.8) instead of closing it — regression test
  `test_invalid_input_value_keeps_session_open` proves the session still carries
  input afterwards.
- **Close sequence follows section 11.4**: flush queued control →
  `shutdown(SHUT_WR)` → drain ≤ 2 s (only when no live reader) → close. The
  Viewer does the same non-blocking (writer sends FIN, reader drains).
- **Host statistics panel** (sections 10.1, 25.3): per-Viewer peer/seconds/frames/
  bytes/skipped rows, totals in FPS and KB/s, and a `Disconnect Viewer` button.
  `stats_snapshot()` emits `"stats"` events from the capture loop.
- **Address row** is now an editable Combobox listing every candidate IPv4
  (`lan_ip_candidates()`), section 3.3.
- **Viewer input rules**: scroll accumulator sends `int(accumulator / 120)`
  notches, keeps the remainder, clamps ±20 (section 9.7); a button-up outside the
  image is always sent, clamped to the image rectangle, so a drag ending outside
  cannot leave a button held (section 9.3).
- **`remote_input.py`**: single `input_lock` around every PyAutoGUI call;
  `release_all()` suspends the fail-safe only while it runs and restores it in
  `finally` (section 9.7); the `_pixel` clamp was removed because validation
  already rejects out-of-range coordinates (section 9.3).
- **`SCREENSHARE_SLOW_VIEWER_MS`** (sections 15, 25.3): test-only Viewer-side
  per-frame sleep, default 0, malformed values ignored — covered by
  `SlowViewerSetting`.

### Live Windows GUI check (real Tk, loopback, no control granted)

Script output (Host + Viewer windows constructed and driven through their own
callbacks; input-rule checks use a recording fake client, no real mouse/keyboard):

```text
host state: listening code length: 8
ip candidates: ('192.168.239.112', '172.17.208.1', '192.168.137.1')
stats row: SmokeViewer ('127.0.0.1:58738', '1 s', '7', '12838', '1')
totals: Total: 5.0 FPS, 9.0 KB/s
disconnect viewer: OK {'type': 'STATUS', 'viewer_count': 0, ...}
scroll accumulator: OK [('scroll', 1, ...), ('scroll', -1, ...)]
clamped button-up: OK [('button', 'left', 'up', 0.0, 0.0)]
GUI STATS AND INPUT CHECKS OK
```

### Snyk scans (stage 8)

- `snyk_auth` → logged in; `snyk_trust` → folder trusted.
- `snyk_sca_scan` (open-source, `requirements.txt`, `skip_unresolved`) →
  **`issueCount: 0`**. No dependency upgrades were made (none suggested).
- `snyk_code_scan` (SAST) → ran after enabling Snyk Code for the organization
  (SNYK-CODE-0005 resolved; SARIF coverage: 25 `.py` files). **2 findings, both
  `python/BindToAllNetworkInterfaces` (CWE-284, warning, priority 400):**
  1. `demo/transport_demos.py:66`
  2. `network-screen-sharing-starter/network-screen-sharing/demo/transport_demos.py:66`
  (the same provided file, present twice). Both are the provided Module-4
  demonstration deliberately binding `0.0.0.0` to show TCP behaviour; the spec
  forbids editing provided code, and the demonstration needs a wildcard bind.
  **Accepted by design, no change made.** The application's own `HOST = "0.0.0.0"`
  (spec section 15) was not flagged.

### File-structure pass

Deep comparison of every file against spec section 14 and the provided starter
kit: the root layout already matches the required structure exactly. Changes made:
README project tree and test counts updated (`outbox.py`, `permissions.py`,
`tests/test_protocol.py` added; `server.py` description corrected), and the three
regenerable `__pycache__` directories removed. `network-screen-sharing-starter/`
is **kept unchanged** as the provided kit (provenance of `outbox.py` and
`demo/transport_demos.py`; the spec forbids editing provided code).

> **Superseded by section 12:** the flat root layout described here was later
> moved into the `src/screenshare/` package as a deliberate project decision.
> Everything else in this section still holds.

## 12. `src/` package layout move, then a live session on the new layout — PASS

### What moved

The 12 modules (`config`, `protocol`, `server`, `client`, `screen_capture`,
`latest_slot`, `outbox`, `permissions`, `keymap`, `geometry`, `remote_input`,
`gui`) plus `app.py` moved into the importable package `src/screenshare/`, with
`__init__.py`, `__main__.py` and a `pyproject.toml` console script
(`screenshare host|viewer`). This is a deliberate departure from section 14's flat
root layout, chosen for presentation; no protocol, timing, threading or permission
behaviour was touched.

Byte-level check of the move: across the 13 moved files, only **20 import lines**
changed (`from config import ...` → `from screenshare import ...`, including three
indented imports inside functions in `remote_input.py` that the first pass missed).
Every other line is identical (`git diff -M`).

`requirements.txt` was deleted; the same three dependency bounds now live only in
`pyproject.toml`, installed with a project-local editable install
(`python -m pip install -e .`). The `.venv` stays outside version control.

### Untouched files (SHA-256 compared before and after)

17 files, all identical, including `ARCHITECTURE_FINAL_v5.md`,
`demo/transport_demos.py` and the whole `network-screen-sharing-starter/` kit.

### Automated verification on the new layout

| Check | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m unittest discover -s tests` | **PASS** — `Ran 64 tests … OK` (same 18 / 12 / 34 split) |
| `python -m compileall -q src tests` | **PASS** — exit 0 |
| `python -c "import screenshare.app"` | **PASS** |
| Console script `screenshare = screenshare.app:main` | **PASS** — resolves and starts |
| No `sys.path.insert` left in `tests/`, no flat `import config`-style imports left | **PASS** (grep) |

### Live session on the new layout (real Tk, real OS input, loopback)

Run at **125% Windows display scaling** (DPI 120, 1920×1080 physical) — the scaling
of this laptop — so cursor alignment was exercised at 125%.

Both entry points were started under the new layout (`screenshare` Host GUI and
`python -m screenshare viewer`). The Host ran with a recording backend that logs
what PyAutoGUI would receive instead of injecting it, so the automated session
could not move this laptop's own mouse and create a feedback loop. Mouse and
keyboard actions were produced by real OS input (the visible cursor moves, real
key presses), not by synthetic messages inside the app.

| Step | Observed |
| --- | --- |
| Host: *Start Sharing* (real click) | `listening`, TCP 5000 on all interfaces, session code `TV4ZCA87` |
| Viewer: session code + *Connect* | stream live: 1434 frames, ~4.9 FPS, ~540 KB/s; Viewer canvas shows the Host desktop |
| Viewer: *Request Control* | Host shows `request pending` |
| Host: *Approve* | both windows show `controlling`, `Controller: LAPTOP-NHOOFE65` |
| Host recorder log (hover, click, drag, wheel, keys) | 65 moves, 3 left-down + 3 left-up, 2 wheel notches, `key_down a` / `key_up a`, `key_down shift` / `key_up shift` |
| One drag across the Viewer canvas | Host side: 1 left-down, 46 moves, 1 left-up |
| Host: *Revoke Control* | Host `Controller: none`, Viewer `view-only` (viewing continues) |
| Clicks and moves after revoke | **none** reached the Host (recorder log 84 → 84 lines) |

### Still NOT tested after this move **[U]**

- Two real laptops over a hotspot or router (section 5) — **`[U]`**.
- 150% scaling — **`[U]`** (125% is now covered above).
- Windows Firewall *Private* profile inbound rule (section 5) — **`[U]`**.
- Wireshark `.pcapng` capture of the application traffic — **`[U]`**.
- The section 11.4 FIN-sequence proof on the wire — **`[U]`**.

