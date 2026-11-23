# AGENTS.md: Network Screen Sharing and Remote Control (VTU BCS502 student project)

You are building a small, demonstrable student project: one Host shares its screen over TCP with up to two Viewers on the same LAN; a Viewer can request control and the Host approves, denies or revokes it. The project is marked on the application working (5) and on a live demonstration (5). A smaller design that works every time beats a larger one that fails once.

`ARCHITECTURE.md` is the single source of truth. Never edit it. If it is wrong, contradicts itself, or is silent on something that matters, **stop and ask the student**. Do not invent a protocol, port, dependency or feature.

## 1. How to read the specification

1. This file.
2. `ARCHITECTURE.md` section 0 (rules) and section 0.3 (verified decisions with evidence).
3. Only the sections for the current stage (table below). Do not load the whole file at once.

## 2. Stages (do them in order; stop after each)

| Stage | Build | Read these sections |
|---|---|---|
| 1 Environment | Folder layout, `config.py`, dependency and Tkinter smoke test | 13, 13.4, 14, 15 |
| 2 Protocol | Message validation added to `protocol.py` (append only), tests | 5, 5.5 to 5.8, 24 |
| 3 TCP connection | Host listener, one Viewer, `JOIN` flow, `permissions.py` skeleton | 3, 5.8, 6, 7.1 to 7.6, 11 |
| 4 Screen sharing | MSS capture, JPEG, send, Viewer decode and display | 8, 13.4, 24 |
| 5 Multiple Viewers | Per-Viewer session, `Outbox`, slow Viewer isolation | 7.4, 7.6, 8.4 |
| 6 Remote control | Request, approve, `RemoteInput`, revoke, held-input release | 6.3, 9, 9.7 |
| 7 GUI and cleanup | Full Host and Viewer GUIs, statistics panel, close sequence | 10, 11.3, 11.4, 16, 25.3 |
| 8 Evidence | Tests, checklist, Wireshark notes, demo rehearsal files | 18, 19, 25 |

Provided and already tested: `protocol.py`, `latest_slot.py`, `outbox.py`, `keymap.py`, `geometry.py`, `tests/test_all.py`, `demo/transport_demos.py`. You may **add** functions to `protocol.py`. Do not change existing provided code or tests without asking. Never edit `demo/transport_demos.py`.

## 3. Rules that are easy to get wrong

1. One TCP listener, port **5000**. One connection per Viewer. No second port, no HMAC, no `FRAME_ACK`, no TLS, no new third-party package. Runtime packages: `mss`, `Pillow`, `PyAutoGUI` only.
2. Framing is `struct.Struct("!BI")` (5 bytes): type 1 = JSON, type 2 = JPEG. Every read goes through `recv_exact`. Check type and length **before** reading the payload. Wire constants live only in `protocol.py`.
3. One reader thread and one writer thread per connection. Only the writer calls `sendall`. Use `Outbox` (`put_control`, `put_latest`, `get`). A `False` from `put_control` closes the session; never drop a permission or key event silently.
4. Tkinter widgets are touched only on the main thread. Workers post to a `queue.Queue`; the GUI drains it with `root.after()`. Decoded frames go through a `LatestSlot`.
5. `app.py`: the DPI call is the first executable code, before importing tkinter, mss or pyautogui (section 13.4). Run as `python app.py host` or `python app.py viewer`.
6. PyAutoGUI: `FAILSAFE = True`, `PAUSE = 0`. Pass every injected position through `avoid_points`. Catch `FailSafeException`: revoke control and warn the Host. Releasing held input runs with the fail-safe suspended (section 9.7).
7. All PyAutoGUI calls live in `RemoteInput`, under one `input_lock`, and `RemoteInput` takes a `backend` object (default: the `pyautogui` module). Tests pass a fake backend.
8. mss: `from mss import MSS`, version `>=10.2,<11`, object created inside the capture thread, monitors are dicts. Convert with `Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")`, then `thumbnail((1280, 720))`, JPEG quality 65. Never `Image.ANTIALIAS`.
9. Key names on the wire are PyAutoGUI names (`enter`, `esc`, `backspace`...), produced by `keymap.py`. Coordinates are normalised 0.0 to 1.0 and the Host does not clamp. Scroll is in whole notches.
10. One controller at a time. Check `is_controller` on every input event; late events from a non-controller are dropped silently.
11. Join order, reasons and field rules: section 5.8. Close sequence (FIN not RST): section 11.4.
12. Never log the session code. Never execute anything a Viewer sends as a command.
13. The Host statistics panel and the test-only `SCREENSHARE_SLOW_VIEWER_MS` setting are required (section 25.3). They carry half of the marks.

## 4. Working loop for each stage

1. Say which stage you are starting and which sections you read.
2. For stages 3, 5 and 6, write a short plan first. If the Plannotator `submit_plan` tool is available, call it and wait for the student's review before writing code.
3. Write tests first for pure logic (message validation, permissions). Then implement in small steps.
4. Run `python -m unittest discover -s tests -v` and fix failures.
5. Report: files changed; the exact test command and the last lines of its output; remaining **[U]** items; any place you had to deviate from `ARCHITECTURE.md` (there should be none).
6. **Stop.** Do not start the next stage until the student says "continue".

## 5. Safety while testing

- Automated tests  move the real mouse or press real keys when needed (rule 7).
- If you start the Host and a Viewer on the same PC, do **not** grant control. A granted Viewer would drive the student's real mouse. Ask the student to run GUI and input tests.
- Do not run `git push`, delete files, or install anything except `requirements.txt` without asking. `opencode.jsonc` enforces most of this.

## 6. Windows commands (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m tkinter                                   # a small window should open
python -m unittest discover -s tests -v
python app.py host                                  # on the Host laptop
python app.py viewer                                # on each Viewer laptop
```

## 7. Tools available in this opencode setup

| Tool | Use it for | Do not |
|---|---|---|
| Context7 (MCP) | Checking an exact API of `mss`, `Pillow`, `PyAutoGUI`, `tkinter` when unsure | Silently switch to another approach if the docs differ from `ARCHITECTURE.md`; stop and tell the student |
| Serena (MCP) | Finding and editing symbols across the project | Mass refactors; keep changes small |
| Snyk (MCP) | Stage 8: scan code and `requirements.txt`; report findings | Auto-upgrade pinned versions; the plaintext session code is a documented limit (section 12) |
| GitHub (MCP) | Only if the student asks | Push or open pull requests unprompted |
| Memory (MCP) | Short non-secret notes about decisions | Store session codes, IP addresses or credentials |
| Firecrawl (plugin) | Only if the student asks for research | Replace a decision in `ARCHITECTURE.md` because of a search result |
| win32, windows-mcp, Playwright, chrome-devtools | Nothing in this project by default | Control the desktop, mouse or keyboard while the app runs; it fights PyAutoGUI and the student's real input |
| Obsidian (MCP) | Nothing. It is not connected; do not retry | |
| Plannotator (plugin) | Plan review at stages 3, 5, 6 | |

## 8. Honesty rules

- Mark anything not run on real Windows laptops as **[U]**. Never write "works on Windows" without a test there.
- Never invent test output, throughput, frame rates or Wireshark results. Never tick a checklist item (`ARCHITECTURE.md` section 18.3) that was not run. Record real outcomes in `docs/test_results.md`.
- TCP and IP belong to the operating system. Do not claim the application implements TCP features, routing or encryption.

## 9. Style

If the caveman plugin is active it may shorten chat replies. That is fine for chat only. Code, comments, docstrings, README, `docs/`, test names and commit messages must be normal, clear English. Keep functions small. Prefer direct code over frameworks.
