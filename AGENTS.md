# AGENTS.md: Network Screen Sharing and Remote Control (VTU BCS502)

Marked on the application working (5) and a live demonstration (5). A smaller design that works every time beats a larger one that fails once.

## Project status (2026-11-26)
The fix task and the approved extension are finished and committed on `feat/transport-dashboard`. The tree already has PING/PONG, kernel TCP statistics, the Transport dashboard, the Settings dialogs, the Menu with the Demo guide, and `tools/`; the additions are recorded in `docs/EXTENSIONS.md`. `ARCHITECTURE_FINAL_v5.md` is the spec of record and read-only — if it is wrong or silent on something that matters, stop and ask the student. Anything not already in the tree is still forbidden: never invent a protocol, port, dependency or feature.
1. Fixed facts: TCP port 5000, one connection per Viewer, max 2 Viewers, 5-byte header `!BI`, type 1 JSON / 2 JPEG, runtime packages `mss`, `Pillow`, `PyAutoGUI` only (Scapy is only for `tools/`), PyAutoGUI `FAILSAFE = True`.
2. Provided reference modules (`protocol.py`, `latest_slot.py`, `outbox.py`, `keymap.py`, `geometry.py`): ask before changing existing code. `demo/transport_demos.py` is never edited.
3. Automated tests never move the real mouse and never grant control on the student's PC. Stop any running Host before the suite (it uses port 5000).

## Tools: use all of them
Run `opencode2 mcp list` once at the start; skip servers that show failed (obsidian is currently failing). Use the others on every task and say in the report what each showed.
| Tool | Use |
|---|---|
| Serena | find every caller before changing a function; check nothing else uses what you remove |
| Context7 | check the exact API of `mss`, `Pillow`, `PyAutoGUI`, `tkinter` before writing a call you are unsure of; tell the student if it differs from the spec |
| Snyk | scan code and `pyproject.toml` after changes; report findings; the plaintext session code is a documented limit |
| GitHub | read similar projects or issues; commit on a branch; never push without the student |
| Memory | short notes on decisions and current step, no session codes |
| Plannotator | submit a plan for review before any change that is not in the guide |
| Firecrawl | research when asked or when a fact is uncertain; never override the spec because of a search result |
| windows-mcp / win32 | screenshot the Host and Viewer windows to check layout, the Cancel Request button and the stats panel; announce before clicking; never grant control while clicking |
| Playwright / chrome-devtools | only if useful (for example to open exported reports) |

## Loop
1. Say which step you start. 2. Make the change. 3. Run `.\.venv\Scripts\python.exe -m unittest discover -s tests`. 4. Report: files changed, exact command, last lines of output, tools used, remaining [U] items. 5. Stop and wait for "continue".

## Windows commands
```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; python -m pip install -e .
python -m unittest discover -s tests
screenshare host      # Host laptop
screenshare viewer    # each Viewer laptop
```
