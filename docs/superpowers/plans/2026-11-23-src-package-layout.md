# Professional `src/` Package Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all 13 application modules into `src/screenshare/` as one importable package with `pyproject.toml`, a console-script entry point, and tests that import the package directly — no logic changes.

**Architecture:** Flat root modules become `src/screenshare/*` with absolute intra-package imports (`from screenshare import config` keeps every `config.PORT` call site untouched). `pip install -e .` puts the package on the path, so `sys.path` hacks in tests disappear. Entry: `screenshare host|viewer` console script and `python -m screenshare`.

**Tech Stack:** Python 3.10+ (venv at `.venv`, cp315), setuptools (src layout), unittest, Tkinter/mss/Pillow/PyAutoGUI (unchanged bounds).

**Spec:** `docs/superpowers/specs/2026-11-23-src-package-layout-design.md` (design doc, owner-approved; it departs from `ARCHITECTURE_FINAL_v5.md` §14 by owner decision).

## Global Constraints

- **No git repository exists.** There are no commit steps; each task ends with its verification gate instead.
- Run everything through `.venv\Scripts\python.exe` (cwd = repository root).
- No logic/behaviour changes: moves + import rewrites + entry-point wiring only.
- Byte-identical, never edited, hash-gated: `ARCHITECTURE_FINAL_v5.md`, `demo/transport_demos.py`, everything under `network-screen-sharing-starter/`.
- Dependency bounds verbatim: `mss>=10.2,<11`, `Pillow>=10.0`, `PyAutoGUI>=0.9.54`.
- Test suite binds real TCP port 5000: no live Host may be running while tests run.
- Package name `screenshare`; import style `from screenshare import <module>` for module imports, `from screenshare.<module> import <name>` for symbol imports.
- Test count must stay **64** (`Ran 64 tests ... OK`).

## Review Focus

1. **Missed import after the move** (top-level *or* function-level — `gui.py:515` has `from server import HostServer` inside `run_host()`): a missed one is an ImportError at runtime, not compile time. Pinned by Task 3's import-all gate and Task 4's full suite; final grep in Task 6.
2. **Tests run without the editable install** → every test fails with `ModuleNotFoundError: screenshare`. Pinned: Task 2 installs, Task 4 step 1 re-verifies `pip show screenshare` before running the suite.
3. **Chooser path breaks when `gui` import moves inside `main()`** — `_launch()` (module level) also calls `gui.run_host()`; a local import in `main()` alone gives NameError when the user picks a button. Pinned: Task 5 imports `gui` inside *both* `main()` and `_launch()`, verified by the Task 7 live smoke of the chooser.
4. **Console script argv**: setuptools calls `main()` with zero args; a `main(argv)` signature crashes the shipped command. Pinned: Task 5 signature `main(argv=None)` + `python -c "import screenshare.app"` + Task 7 smoke of `screenshare host`.
5. **Protected-file drift**: a careless `Move-Item` or edit touches the spec/demo/starter kit. Pinned: Task 1 records SHA-256 baselines; Task 7 re-hashes and diffs.

---

### Task 1: Baseline capture

**Files:** none created; read-only.

**Interfaces:**
- Consumes: nothing.
- Produces: recorded baseline (kept in this plan's execution notes / temp file): test result line, SHA-256 of the three protected targets.

- [ ] **Step 1: Run the test baseline**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests`
Expected: `Ran 64 tests ... OK` (if it fails, STOP — fix the baseline first; never attribute a pre-existing failure to this work)

- [ ] **Step 2: Record protected-file hashes**

Run:
```powershell
Get-FileHash ARCHITECTURE_FINAL_v5.md, demo\transport_demos.py -Algorithm SHA256
Get-ChildItem -Recurse -File network-screen-sharing-starter | Get-FileHash -Algorithm SHA256
```
Expected: output saved to `C:\Users\Nishanth\AppData\Local\Temp\opencode\protected_hashes_before.txt` (redirect with `| Out-File`). These exact values are re-checked in Task 7 Step 1.

---

### Task 2: Package scaffolding (`pyproject.toml`, empty package, editable install)

**Files:**
- Create: `pyproject.toml`
- Create: `src/screenshare/__init__.py`
- Modify: `.gitignore` (append build artifacts)
- Delete: `requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: importable empty package `screenshare` (`screenshare.__version__ == "0.1.0"`); project metadata/deps now live in `pyproject.toml [project]`; console-script declaration `screenshare = "screenshare.app:main"` (module lands in Task 5).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "screenshare"
version = "0.1.0"
description = "Network-based screen sharing and remote control over TCP"
requires-python = ">=3.10"
dependencies = [
    "mss>=10.2,<11",
    "Pillow>=10.0",
    "PyAutoGUI>=0.9.54",
]

[project.scripts]
screenshare = "screenshare.app:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write `src/screenshare/__init__.py`**

Single line: `__version__ = "0.1.0"`

- [ ] **Step 3: Append to `.gitignore`**

```
build/
dist/
*.egg-info/
```

- [ ] **Step 4: Delete `requirements.txt`**

Run: `Remove-Item requirements.txt`
Rationale (design decision 9): dependencies now live in `pyproject.toml` only.

- [ ] **Step 5: Editable install**

Run: `.venv\Scripts\python.exe -m pip install -e .`
Expected: succeeds; `mss`/`Pillow`/`PyAutoGUI` already satisfied (or installed from the same bounds).

- [ ] **Step 6: Verify package import**

Run: `.venv\Scripts\python.exe -c "import screenshare; print(screenshare.__version__)"`
Expected: `0.1.0`, exit 0.

---

### Task 3: Move 12 modules into the package and rewrite source imports

**Files:**
- Move (root → `src/screenshare/`): `config.py`, `protocol.py`, `server.py`, `client.py`, `screen_capture.py`, `latest_slot.py`, `outbox.py`, `permissions.py`, `keymap.py`, `geometry.py`, `remote_input.py`, `gui.py`
- Modify: import lines in each moved file per the map below
- NOT moved here: `app.py` (Task 5 owns it)

**Interfaces:**
- Consumes: `screenshare` package from Task 2.
- Produces: `screenshare.server.HostServer`, `screenshare.server.PermissionManager` (re-export kept), `screenshare.client.ViewerClient`, `screenshare.protocol`, `screenshare.config`, etc. — every name tests import in Task 4.

Import rewrite map (only these lines change; bodies untouched):

| File | Old | New |
|---|---|---|
| `config.py` | `from protocol import HEADER, ...` | `from screenshare.protocol import HEADER, ...` |
| `server.py` | `import config` / `import protocol` / `import screen_capture` | `from screenshare import config` / `protocol` / `screen_capture` |
| `server.py` | `from outbox import Outbox` | `from screenshare.outbox import Outbox` |
| `server.py` | `from permissions import PermissionManager` | `from screenshare.permissions import PermissionManager` |
| `server.py` | `from remote_input import RemoteInput` | `from screenshare.remote_input import RemoteInput` |
| `client.py` | `import config` / `import protocol` / `import screen_capture` | `from screenshare import config` / `protocol` / `screen_capture` |
| `client.py` | `from latest_slot import LatestSlot` | `from screenshare.latest_slot import LatestSlot` |
| `client.py` | `from outbox import Outbox` | `from screenshare.outbox import Outbox` |
| `screen_capture.py` | `import config` | `from screenshare import config` |
| `gui.py` | `import client as client_mod` | `from screenshare import client as client_mod` |
| `gui.py` | `import config` | `from screenshare import config` |
| `gui.py` | `from geometry import widget_to_norm` | `from screenshare.geometry import widget_to_norm` |
| `gui.py` | `from keymap import tk_keysym_to_wire` | `from screenshare.keymap import tk_keysym_to_wire` |
| `gui.py` (inside `run_host()`, ~line 515) | `from server import HostServer` | `from screenshare.server import HostServer` |
| `remote_input.py` | `from keymap import ALLOWED_KEYS` | `from screenshare.keymap import ALLOWED_KEYS` |
| `remote_input.py` | `from geometry import norm_to_pixel, avoid_points` | `from screenshare.geometry import norm_to_pixel, avoid_points` |

Untouched: `keymap.py`, `geometry.py`, `latest_slot.py`, `outbox.py`, `permissions.py`, `protocol.py` (no intra-project imports), `demo/transport_demos.py` (stdlib only).

- [ ] **Step 1: Move the 12 files**

Run: `Move-Item config.py, protocol.py, server.py, client.py, screen_capture.py, latest_slot.py, outbox.py, permissions.py, keymap.py, geometry.py, remote_input.py, gui.py -Destination src\screenshare\`
Expected: root `.py` files remaining = `app.py` only.

- [ ] **Step 2: Apply the import rewrite map**

Edit each listed file exactly as mapped. Keep every other line byte-identical.

- [ ] **Step 3: Compile check**

Run: `.venv\Scripts\python.exe -m compileall -q src`
Expected: exit 0.

- [ ] **Step 4: Import-all gate**

Run:
```powershell
.venv\Scripts\python.exe -c "from screenshare import config, protocol, server, client, screen_capture, latest_slot, outbox, permissions, keymap, geometry, remote_input, gui; print('IMPORT-ALL OK')"
```
Expected: `IMPORT-ALL OK`, exit 0 (this fails on any missed import, including the function-level one — but see Step 5 for the grep that catches imports inside functions the import statement above would still miss only if module-level import fails; `gui` imports `server` lazily, so Step 5 is mandatory).

- [ ] **Step 5: Grep for leftover flat imports**

Run: `rg "^(import (config|protocol|server|client|screen_capture|latest_slot|outbox|permissions|keymap|geometry|remote_input)|from (config|protocol|server|client|screen_capture|latest_slot|outbox|permissions|keymap|geometry|remote_input) import)" src`
Expected: no matches. Then `rg "from server import" src` → exactly one hit, `src/screenshare/gui.py`, already rewritten to `from screenshare.server import HostServer`.

---

### Task 4: Rewrite the three test files → 64 tests green

**Files:**
- Modify: `tests/test_all.py`, `tests/test_protocol.py`, `tests/test_permissions.py`

**Interfaces:**
- Consumes: package imports from Task 3 (`screenshare.server.PermissionManager`, `screenshare.outbox.Outbox`, `screenshare.protocol`, …).
- Produces: suite runnable with plain `unittest discover` and no `sys.path` manipulation — the state every later verification assumes.

- [ ] **Step 1: Verify the editable install is visible**

Run: `.venv\Scripts\python.exe -m pip show screenshare`
Expected: `Location: ...src` (editable). If missing, re-run Task 2 Step 5 before continuing.

- [ ] **Step 2: Rewrite imports in `tests/test_all.py`**

- Delete the `sys.path.insert(...)` line.
- `import protocol as P` → `import screenshare.protocol as P`
- `from latest_slot import LatestSlot` → `from screenshare.latest_slot import LatestSlot`
- `from keymap import tk_keysym_to_wire, ALLOWED_KEYS` → `from screenshare.keymap import ...`
- `from geometry import norm_to_pixel, avoid_points, widget_to_norm` → `from screenshare.geometry import ...`
- `from outbox import Outbox` → `from screenshare.outbox import Outbox`
- Drop `os`/`sys` from the top import line only if `rg "\bos\.|\bsys\." tests/test_all.py` shows no other use.

- [ ] **Step 3: Rewrite imports in `tests/test_protocol.py`**

- Delete the `sys.path.insert(...)` line (and `os`/`sys` imports if now unused).
- `import protocol as P` → `import screenshare.protocol as P`

- [ ] **Step 4: Rewrite imports in `tests/test_permissions.py`**

- Delete the `sys.path.insert(...)` line (and `os` import if now unused).
- `from remote_input import RemoteInput, RESULT_OK, RESULT_NOT_CONTROLLER, RESULT_REJECTED` → `from screenshare.remote_input import ...`
- `from server import PermissionManager, HostServer` → `from screenshare.server import PermissionManager, HostServer`
- Any in-test `import client as client_mod` / `import protocol` / `from outbox import Outbox` (there are several inside test methods) → `from screenshare import client as client_mod`, `from screenshare import protocol`, `from screenshare.outbox import Outbox`. Grep first: `rg "^\s*(import|from) (client|protocol|server|outbox|remote_input)" tests/`.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests`
Expected: `Ran 64 tests ... OK`

- [ ] **Step 6: Confirm no path hacks remain**

Run: `rg "sys.path" tests/`
Expected: no matches.

---

### Task 5: Entry points — `app.py` moves, `__main__.py`, console script

**Files:**
- Move: `app.py` → `src/screenshare/app.py`
- Create: `src/screenshare/__main__.py`
- Modify: `src/screenshare/app.py` (signature + gui import location)

**Interfaces:**
- Consumes: `screenshare.gui.run_host()` / `run_viewer()` from Task 3; console-script declaration from Task 2.
- Produces: `screenshare.app.main(argv=None)` — called by both `__main__.py` and the `screenshare` console script with zero arguments.

- [ ] **Step 1: Move `app.py`**

Run: `Move-Item app.py -Destination src\screenshare\`
Expected: no `.py` files left at repository root (except under `src/`, `tests/`, `demo/`, starter kit).

- [ ] **Step 2: Rewrite `main` and the gui import**

In `src/screenshare/app.py`:

1. Signature: `def main(argv):` → `def main(argv=None):` with first line `argv = sys.argv if argv is None else argv`.
2. Delete the top-level `import gui  # noqa: E402 ...` line.
3. Inside `main()`, before any use of `gui`: `from screenshare import gui`.
4. Inside `_launch()`, before its `gui.run_host()`/`gui.run_viewer()` calls: `from screenshare import gui` (module-level function — it cannot see `main()`'s local name; see Review Focus 3).
5. `import tkinter  # noqa: E402` and `import sys  # noqa: E402` stay where they are (they still follow the ctypes block).

- [ ] **Step 3: Write `src/screenshare/__main__.py`**

```python
from screenshare.app import main

main()
```

- [ ] **Step 4: Import check**

Run: `.venv\Scripts\python.exe -c "import screenshare.app; print('ENTRY OK')"`
Expected: `ENTRY OK`, exit 0.

- [ ] **Step 5: Confirm console script exists**

Run: `Test-Path .venv\Scripts\screenshare.exe`
Expected: `True`. (If `False`, re-run `.venv\Scripts\python.exe -m pip install -e .`.)

Do NOT run `screenshare` with no arguments here — it opens the Tk chooser and blocks (by design). The live smoke is Task 7.

---

### Task 6: Documentation sync

**Files:**
- Modify: `README.md` (tree, setup, run, tests sections)
- Modify: `docs/test_results.md` (append one short section; historical transcripts untouched)

**Interfaces:**
- Consumes: final layout from Tasks 3–5.
- Produces: docs that match reality; grep-clean of stale commands.

- [ ] **Step 1: Rewrite README "Project structure" tree**

New tree: `pyproject.toml`, `src/screenshare/` listing `__init__.py`, `__main__.py`, `app.py`, `config.py`, `protocol.py`, `server.py`, `client.py`, `screen_capture.py`, `latest_slot.py`, `outbox.py`, `permissions.py`, `keymap.py`, `geometry.py`, `remote_input.py`, `gui.py`, plus unchanged `demo/`, `tests/` (4 files), `docs/`, `README.md`, `.gitignore`, `ARCHITECTURE_FINAL_v5.md`, `network-screen-sharing-starter/`. Note `requirements.txt` removed (deps in `pyproject.toml`).

- [ ] **Step 2: Rewrite README Setup**

Replace the `pip install -r requirements.txt` step with:
`.venv\Scripts\python.exe -m pip install -e .`

- [ ] **Step 3: Rewrite README run commands**

- `.\.venv\Scripts\screenshare.exe host` (or `python -m screenshare host`)
- `.\.venv\Scripts\screenshare.exe viewer` (or `python -m screenshare viewer`)
- No arguments → Tk mode chooser (unchanged behaviour).
- Keep `python demo/transport_demos.py ...` as-is (still correct).

- [ ] **Step 4: Update README test section**

State the prerequisite (`pip install -e .` once) and keep the command
`.venv\Scripts\python.exe -m unittest discover -s tests` and the 64-test breakdown.

- [ ] **Step 5: Append layout note to `docs/test_results.md`**

New final section `## 12. Source layout moved to src/ package` — one paragraph: date, why (portfolio structure, owner decision vs spec §14), what moved, commands re-run with results (`Ran 64 tests ... OK`, import gates, live smoke), and a line that earlier sections' transcripts are historical (recorded under the flat layout).

- [ ] **Step 6: Grep for stale references**

Run: `rg -n "python app\.py|requirements\.txt|-r requirements" README.md docs/`
Expected: only historical mentions inside `docs/test_results.md` transcripts (allowed) — fix any in README or in non-transcript prose.

---

### Task 7: Final verification (all done criteria from the design, §7)

**Files:** none modified; read-only checks + one live smoke.

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: evidence for the report.

- [ ] **Step 1: Protected-file hash diff**

Run: re-run the Task 1 Step 2 commands, save to `protected_hashes_after.txt`, diff against the before file.
Expected: zero differences.

- [ ] **Step 2: Full suite + compile**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests` then `.venv\Scripts\python.exe -m compileall -q src tests demo`
Expected: `Ran 64 tests ... OK`; compileall exit 0.

- [ ] **Step 3: Structure listing**

Run: `Get-ChildItem -File | Select-Object -ExpandProperty Name` and `Get-ChildItem src\screenshare | Select-Object -ExpandProperty Name`
Expected: root files = `.gitignore`, `README.md`, `ARCHITECTURE_FINAL_v5.md`, `pyproject.toml` (no stray `.py`); package = 15 files (13 modules + `__init__.py` + `__main__.py`).

- [ ] **Step 4: Live GUI smoke — both entry points (manual, port 5000 free)**

1. `.venv\Scripts\screenshare.exe host` → Host window opens, listening state, code shown. Start a viewer with `.venv\Scripts\python.exe -m screenshare viewer`, connect over `127.0.0.1`, frames appear. Close both, exit code 0 for each.
2. Re-run 1 with the forms swapped (`python -m screenshare host`, `screenshare.exe viewer`) so both launchers are exercised.
3. Also open the chooser (bare `screenshare` with no args), click each button once, confirm the right window opens (Review Focus 3), close it.

Expected: all windows construct and exit 0; no traceback on either console.

- [ ] **Step 5: Final grep sweep**

Run: `rg "sys\.path" tests/ src/` and `rg "^(import|from) (config|protocol|server|client|screen_capture|latest_slot|outbox|permissions|keymap|geometry|remote_input)\b" src/ tests/`
Expected: no matches anywhere.
