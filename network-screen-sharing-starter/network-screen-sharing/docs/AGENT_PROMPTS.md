# Prompts to paste into opencode, one stage at a time

Start every stage in a fresh session or after `/compact` so the context stays small. After each stage, read the report, run the tests yourself, then paste the next prompt.

Common line at the start of each prompt: "Follow AGENTS.md. ARCHITECTURE.md is read-only."

## Stage 1: Environment
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 1. Read sections 0, 0.3, 13, 13.4, 14, 15 only.
Create the folder layout from section 14 (empty modules with a docstring are fine), config.py with the constants from section 15 (wire constants stay in protocol.py), and app.py that sets DPI awareness first and accepts `host` or `viewer`. Do not implement networking yet.
Run the unit tests and a Tkinter smoke test. Report as described in AGENTS.md section 4, then stop.
```

## Stage 2: Protocol
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 2. Read sections 5, 5.5 to 5.8 and 24 only.
Add JSON message validation to protocol.py (append only): required fields and types per section 5.5, allowed values and reason lists per section 5.8, direction checks. Write tests first in tests/test_protocol.py. Do not change existing functions or tests.
Report and stop.
```

## Stage 3: TCP connection (plan first)
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 3. Read sections 3, 5.8, 6, 7.1 to 7.6 and 11 only.
First write a short plan and submit it with submit_plan if available; wait for my review.
Then build the Host listener, one reader and one writer thread per Viewer using Outbox, the JOIN flow with the exact check order from section 5.8, JOIN_ACCEPT, STATUS, and permissions.py with tests/test_permissions.py (single controller, pending, cancel, revoke, disconnect).
Test with two terminals on 127.0.0.1 only. Report and stop.
```

## Stage 4: Screen sharing
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 4. Read sections 8, 13.4 and 24 only.
Build screen_capture.py (MSS in the capture thread, thumbnail to 1280x720, JPEG quality 65, 5 FPS pacing, size check before handing the frame to any Outbox), send frames to a Viewer, decode with Image.open(...).load() in the reader thread, hand the image to the GUI through a LatestSlot, and show it with aspect ratio preserved.
Report and stop.
```

## Stage 5: Multiple Viewers (plan first)
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 5. Read sections 7.4, 7.6 and 8.4 only.
Plan first (submit_plan if available). Then make two Viewers work at once with independent sessions, enforce MAX_VIEWERS, and prove with a test or a script that a stalled Viewer does not block the other one.
Report and stop.
```

## Stage 6: Remote control (plan first)
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 6. Read sections 6.3, 9 and 9.7 only.
Plan first (submit_plan if available). Then build remote_input.py (RemoteInput with an injectable backend, one input_lock, avoid_points, FAILSAFE True, PAUSE 0, held-input release with the fail-safe suspended), the Viewer-side input capture (clamped button-up, scroll accumulator, keymap), and the control request, approve, deny, revoke and release flow.
Unit tests use a fake backend only. Do NOT grant control or move the real mouse yourself; tell me what to test by hand. Report and stop.
```

## Stage 7: GUI and cleanup
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 7. Read sections 10, 11.3, 11.4, 16 and 25.3 only.
Complete both GUIs, the Host statistics panel (peer ip:port, frames, bytes, skipped frames, FPS, KB/s), the Disconnect Viewer action, the SCREENSHARE_SLOW_VIEWER_MS setting, connection log lines, the section 11.4 close sequence, and the error handling table in section 16.
Report and stop.
```

## Stage 8: Evidence and demo files
```
Follow AGENTS.md. ARCHITECTURE.md is read-only.
Do stage 8. Read sections 18, 19 and 25 only.
Run the Snyk scan on the code and requirements.txt and report the findings (do not auto-upgrade). Fill docs/test_results.md only with results that were really run; leave everything else "not run". Write README.md (setup, run, demo steps) and docs/wireshark_demo.md (capture procedure and filters from section 25.5). Do not tick any checklist item that was not run.
Report and stop.
```
