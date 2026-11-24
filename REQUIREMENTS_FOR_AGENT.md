# REQUIREMENTS_FOR_AGENT.md — what the finished project must satisfy

Repo audited: `nishanth-kkj9/screen-sharing-and-system-controling` (1 commit `a8d5a98`, 44 tracked files, all `src/`, `tests/`, `demo/` and docs read in full).
Companion file: `SUGGESTIONS_FOR_AGENT.md` (how to fix, in what order, with test sketches).
Spec of record: `ARCHITECTURE_FINAL_v5.md` (read-only; never edit it).

## 0. Evidence tags (used everywhere below)

| Tag | Meaning |
|---|---|
| **[V]** | I ran it during the audit and saw the result. |
| **[R]** | I read the code and it matches; not separately run. |
| **[D]** | Only the author's `docs/test_results.md` says so; I did not re-run it. |
| **[U]** | Cannot be tested in a Linux sandbox (two laptops, Windows input, Wireshark). The student must run it. |

What I ran: `python -m unittest discover -s tests` → **64 tests OK on Python 3.12 and 3.13** [V]; `compileall` on Python 3.11 OK [V]; Python 3.10 not available here, so the `>=3.10` claim is **unverified**. Six reproduction scripts against a real `HostServer` (fake input backend, fake frames, loopback) — results in section 3.

## 1. Fixed constraints (do not change)

1. TCP only, port **5000**, one connection per Viewer, max **2** Viewers, 5-byte header `!BI`, types 1 (JSON) and 2 (JPEG). No new port, protocol, dependency or feature.
2. `ARCHITECTURE_FINAL_v5.md` and `demo/transport_demos.py` stay byte-identical.
3. PyAutoGUI `FAILSAFE = True` always. Held input is released with the fail-safe suspended only inside `_release_held`.
4. Provided reference modules (`protocol.py`, `latest_slot.py`, `outbox.py`, `keymap.py`, `geometry.py`): ask the student before changing existing code; appending is allowed.
5. Keep all 64 existing tests green. Add tests for every fix below. Test on real Windows laptops before claiming the project works (spec rule 10).
6. Automated tests must never move the real mouse or grant control on the student's PC.

## 2. What already satisfies the spec (no work needed)

| Requirement (spec section) | Status |
|---|---|
| Framing, `recv_exact`, size checks before payload (5, 24) | [V] 18 reference tests + 12 contract tests pass |
| Exact reason lists, directions, required fields, bool-not-int (5.5–5.8) | [V] `tests/test_protocol.py` |
| Join order, `JOIN_ACCEPT` is the first message (5.8, 8.2) | [V] `test_join_accept_is_first_message` |
| Wrong code ×3 then close; empty/non-ASCII code safe (5.7, 16) | [V] two tests |
| Third Viewer refused `viewer_limit_reached` (5.8) | [V] `test_two_viewers_share_grant_revoke` (but see DEF-4) |
| Single controller, `controller_busy`, `request_pending` (6.3 rules 1–8) | [V] `PermissionRules` |
| Key allowlist, scroll ±20, normalized coords, no host clamp (9.3, 9.7) | [V] `InputValidation` |
| Fail-safe corners nudged, trip releases held input and revokes (9.5, 9.7) | [V] tests + earlier real-pyautogui run in this audit |
| Graceful `DISCONNECT`, then `shutdown(SHUT_WR)` + drain (11.3, 11.4) | [V] `test_disconnect_is_sent_before_close`; FIN on the wire still **[U]** |
| `stop_sharing()` does not freeze the Tk thread | [V] 0.20 s with 2 Viewers |
| Threading: one reader/writer per socket, Tk only on main thread, `Outbox`/`LatestSlot` | [R] `server.py`, `client.py`, `gui.py` |
| DPI call first in `app.py`; `master=` on `PhotoImage`; `<ButtonPress-1>` focus fix | [R] |
| Stats panel + `SCREENSHARE_SLOW_VIEWER_MS` (10.1, 25.3, 15) | [V] env-var test; panel [R] (but see DEF-6) |

## 3. Confirmed defects — each must be fixed (priority order)

Each row: what is wrong → proof → required behaviour. Fix sketches are in `SUGGESTIONS_FOR_AGENT.md`.

### DEF-1 (High) — input can be injected after a revoke, leaving a key stuck on the Host
- **Where:** `server.py:524-526` checks `perm.is_active()` **outside** `input_lock`, then calls `remote_input.handle(msg, True)`.
- **Proof [V]:** repro R4. A `KEY_DOWN a` that passed the check while the Host revoked produced backend calls `[('kd','a')]` after revoke finished, with **no** `key_up` and `active controller: None`. The key stays held until something else releases it.
- **Spec:** 6.3 rule 8 (permission re-checked per event), 7.6 rule 3 (revoke takes effect after the current action; held input released).
- **Required:** the permission check and the injection happen atomically under `input_lock`. After `revoke_control()` returns, no action runs and `RemoteInput.held == ([], [])`.

### DEF-2 (High for the demo) — `ConnectionClosed` escapes the JOIN-phase reader as an unhandled thread exception
- **Where:** `server.py:430` catches `(OSError, ProtocolError)` only; `_handle_join` (`:440`) raises `protocol.ConnectionClosed`.
- **Proof [V]:** repro R1 — connect then close → `threading.excepthook` receives `ConnectionClosed`. The repo's **own test run already prints this traceback twice** (wrong-code tests). The documented pre-demo step `Test-NetConnection <ip> -Port 5000` (`SETUP_GUIDE.md` §5) does exactly this, so the Host console shows a traceback in front of the examiner.
- **Required:** a Viewer that disconnects before or during JOIN ends its session quietly (log line at most). No traceback. Add a regression test that fails if any thread exception occurs.

### DEF-3 (Medium) — a pending control request cannot be cancelled
- **Where:** `permissions.release()` (`:68`) only handles the active controller; `client.release_control()` (`client.py:138`) is not usable while pending; GUI release button is enabled only in `CONTROLLING` (`gui.py:483`).
- **Proof [V]:** repro R3 — Viewer 1 sends `CONTROL_REQUEST`, then `CONTROL_RELEASE`: `pending` stays set, and Viewer 2's request is then denied `request_pending`. The Host's Approve/Deny prompt would stay open for a Viewer that gave up.
- **Spec:** 6.3 rule 9 and the state diagram (`REQUEST_PENDING --> VIEW_ONLY: CONTROL_RELEASE`).
- **Required:** `CONTROL_RELEASE` from the pending Viewer clears `pending_controller_id`, broadcasts `STATUS`, and the Host buttons disable. The Viewer UI offers a way to cancel (Release/Cancel button enabled in `REQUEST_PENDING`).
- **Also required [I]:** because a cancel can cross a grant on the wire, the Viewer must ignore a `CONTROL_GRANTED` that arrives when it is not in `REQUEST_PENDING` (otherwise the Viewer shows "controlling" while the Host has already released).

### DEF-4 (Medium) — unauthenticated sockets consume the two Viewer slots
- **Where:** `server.py:346` `len(self._sessions) >= config.MAX_VIEWERS` counts every accepted socket, including ones that have not sent `JOIN`.
- **Proof [V]:** repro R2 — two idle TCP connections, then a legitimate Viewer with the correct code gets `JOIN_DENIED viewer_limit_reached`. The slots stay blocked for up to `JOIN_TIMEOUT` (10 s). `Test-NetConnection`, a port scan, or a stuck client can lock real Viewers out during the demo.
- **Spec:** 5.8 step 5 — the limit applies "if `MAX_VIEWERS` Viewers are already **joined**", after the code check; 3.2 / 217 say "authenticated Viewer sessions".
- **Required:** only admitted (authenticated) Viewers count toward `MAX_VIEWERS`; the admit decision is made under `_sessions_lock` so two simultaneous JOINs cannot both take the last slot. Unauthenticated sockets are bounded by a separate small cap so a client cannot open unlimited threads.

### DEF-5 (Medium) — screen-capture failure is silent
- **Where:** `server.py:540` (`_frame_factory()` inside `_capture_loop`), `:564` (crash handler only logs), `:572-585` (`_probe_frame` swallows the error).
- **Proof [V]:** repro R5 — with a factory that raises: the Viewer still gets `JOIN_ACCEPT` with an invented `1280×720`, then only `STATUS` messages, **no frames, ever**; the Host emitted only `log/started/status` events — no warning reaches the GUI, and the capture thread is dead so it never recovers.
- **Required:** if capture cannot start, `Start Sharing` shows an error (or the Host shows a warning) and no Viewer is told it is watching a screen. Repeated per-frame failures raise one Host warning.

### DEF-6 (Low–Medium) — stats table and totals go stale after the last Viewer leaves
- **Where:** `"stats"` events are emitted only from the capture loop (`server.py:563`), which idles when nobody is authenticated; `_cleanup_session` (`:634`) never emits one.
- **Proof [V]:** repro R7 — after the only Viewer disconnected, **zero events** were emitted in 1.5 s and `stats_snapshot()` is `[]`. By `gui._on_stats` (`:168`) the Host table row and `Total` label would therefore remain **[I]**.
- **Required:** `_cleanup_session` emits a fresh `stats` event so the table, totals and the Disconnect Viewer button reset immediately.

## 4. Smaller items (fix with the above, low risk)

| ID | Item | Where | Evidence |
|---|---|---|---|
| S-1 | Dead duplicate branch: both `JOIN_DENIED` paths return `False` and emit the same event | `client.py:240-246` | [R] |
| S-2 | `_cleanup_session` broadcasts `STATUS` even for a session that never authenticated (every failed JOIN) | `server.py:645` | [R] |
| S-3 | `app.py` opens a chooser for an unknown mode; spec line 1071 says print usage and exit. The author's design doc says this is deliberate and README documents the chooser. Decide once and make spec/README/code agree (the spec is read-only, so record the deviation in README). | `app.py:23-24` | [R] |
| S-4 | README says the writer sends "from a one-item `LatestSlot`"; code uses `Outbox` | `README.md` "How it works" | [R] |
| S-5 | `docs/test_results.md` header still says the 42-test suite; sections 11-12 say 64 | `docs/test_results.md` | [R] |
| S-6 | Stale `network-screen-sharing-starter/` copy inside the repo: old flat modules, old `ARCHITECTURE.md` (identical to v5), and the **old restrictive `AGENTS.md`**. It gives two copies of every reference module and doubles the Snyk finding. The student's design note kept it on purpose, so ask before removing. | repo root | [V] byte-compare |
| S-7 | The repo root has **no `AGENTS.md` and no `opencode.jsonc`**, so opencode loads no project instructions. Add the root files from the companion package. | repo root | [V] `ls` |

## 5. Evidence required for the demonstration marks (all **[U]** — only the student can produce them)

The professor wants the transport layer demonstrated. Everything below is currently **not done** according to `docs/test_results.md` §5, §7, §12.

| ID | Evidence | Acceptance |
|---|---|---|
| E-1 | Host + 1–2 Viewers on **two or three physical laptops** (router or hotspot with device-to-device allowed) | Viewer sees live frames; control granted and revoked; third Viewer denied |
| E-2 | Wireshark `.pcapng` captured on the Host Wi-Fi adapter, filter `tcp.port == 5000` | Shows SYN/SYN-ACK/ACK, seq/ack numbers, data both ways, FIN exchange; saved plus 3 screenshots |
| E-3 | FIN vs RST proof (spec 11.4) | Normal Viewer exit ends with FIN/ACK; no RST in the same stream |
| E-4 | Flow control, two ways: `demo/transport_demos.py flow-recv/flow-send` across laptops **and** the app with `SCREENSHARE_SLOW_VIEWER_MS=200` on one Viewer | Window shrinks / `tcp.analysis.zero_window` only if it actually occurs; Host `Skipped` counter rises for the slow Viewer while the other stays smooth |
| E-5 | Windows firewall rule + network profile on the second machine | `Test-NetConnection <host> -Port 5000` → `TcpTestSucceeded : True` |
| E-6 | 150 % display scaling alignment (125 % already done on one machine [D]) | Remote click lands where the Viewer clicked |
| E-7 | Python 3.10 (declared minimum) | Suite passes, or raise `requires-python` to what was really tested |
| E-8 | Update `docs/test_results.md` with the real outcome of each item; never mark an item before running it | |

Truthfulness rule for the viva: `cwnd` is not visible in packets; zero-window / retransmission filters may show nothing on a healthy LAN and that is a valid result (already stated in `docs/wireshark_demo.md`; keep it).

## 6. Definition of done

1. DEF-1 … DEF-6 fixed, each with a test that fails before the fix and passes after (red → green).
2. Full suite green on Windows with `.venv\Scripts\python.exe -m unittest discover -s tests`; count ≥ 64 + new tests. Stop any running Host first (port 5000).
3. `python -m compileall -q src tests demo` exit 0; Snyk code + SCA scans re-run and reported.
4. README / test_results corrected (S-4, S-5), root `AGENTS.md` + `opencode.jsonc` in place (S-7).
5. E-1 … E-8 done by the student and recorded.
6. The agent's final report lists: files changed, exact commands and last lines of output, which MCP servers/plugins were used and what each showed, and anything still **[U]**.
