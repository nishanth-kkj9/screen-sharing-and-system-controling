# Design — Professional `src/` package layout

Date: 2026-11-23
Status: draft, awaiting owner approval
Decision already made with the owner: **approach 3 (full `src/` package layout)**,
accepting that this departs from `ARCHITECTURE_FINAL_v5.md` section 14, which
mandates the current flat structure. The repository is now treated as a portfolio
project, not a course submission checked against section 14.

## 1. Intent and why

The root currently holds 14 flat modules, which is exactly what section 14 of the
spec requires but reads as an unfinished script collection in a portfolio context.
The goal is a structure that reads as a professional Python project at a glance:
a `src/` package, `pyproject.toml` as the single source of truth for metadata and
dependencies, a supported entry point, and tests that import the installed package
instead of hacking `sys.path`.

## 2. Goals

- Move all 14 application modules into `src/screenshare/` as one importable package.
- One entry point story: `screenshare host|viewer` (console script) and
  `python -m screenshare host|viewer`.
- `pyproject.toml` owns metadata, the three runtime dependencies and the build
  configuration; `requirements.txt` is removed.
- Tests import `screenshare.*` directly with no `sys.path` manipulation.
- All 64 tests keep passing; `compileall` stays clean.
- README and docs updated to the new run/setup/test commands.

## 3. Non-goals / anti-goals

- No logic, protocol, GUI or behaviour changes. This is moves + import rewrites only.
- `ARCHITECTURE_FINAL_v5.md` stays byte-identical at the repository root (read-only contract).
- `network-screen-sharing-starter/` stays untouched and in place (provided kit;
  the owner rejected relocating it).
- `demo/transport_demos.py` stays byte-identical at `demo/` — it is standard-library
  only and must never be edited.
- No `LICENSE` (choosing a licence is the owner's call, not this change).
- No git init, no CI workflow (there is no repository yet; CI can come later with git).
- No renaming of modules, classes or functions.

## 4. Target structure

```text
network-screen-sharing/
├── pyproject.toml              # NEW: metadata, deps, console script, setuptools src layout
├── README.md                   # UPDATED: tree, setup, run and test commands
├── ARCHITECTURE_FINAL_v5.md    # UNCHANGED (read-only spec)
├── .gitignore                  # UPDATED: add build/ dist/ *.egg-info/
├── src/
│   └── screenshare/
│       ├── __init__.py         # NEW: __version__ = "0.1.0"
│       ├── __main__.py         # NEW: python -m screenshare -> app.main()
│       ├── app.py              # MOVED from root
│       ├── config.py           # MOVED
│       ├── protocol.py         # MOVED
│       ├── server.py           # MOVED
│       ├── client.py           # MOVED
│       ├── screen_capture.py   # MOVED
│       ├── latest_slot.py      # MOVED
│       ├── outbox.py           # MOVED
│       ├── permissions.py      # MOVED
│       ├── keymap.py           # MOVED
│       ├── geometry.py         # MOVED
│       ├── remote_input.py     # MOVED
│       └── gui.py              # MOVED
├── tests/                      # STAYS; imports become screenshare.*, sys.path hacks removed
│   ├── __init__.py
│   ├── test_all.py
│   ├── test_protocol.py
│   └── test_permissions.py
├── demo/
│   └── transport_demos.py      # UNCHANGED
├── docs/                       # run commands updated; recorded outputs kept as history
│   ├── wireshark_demo.md
│   └── test_results.md
└── network-screen-sharing-starter/   # UNCHANGED
```

Removed: `requirements.txt` (dependencies live in `pyproject.toml`),
`app.py` at root (becomes `src/screenshare/app.py`).

## 5. Key decisions (the how)

1. **Package name:** `screenshare`. Short, matches the domain, no collision with
   the starter kit folder.
2. **Import style:** absolute within the package — `from screenshare import config`,
   `from screenshare.outbox import Outbox`. Relative imports were considered and
   rejected: absolute makes every dependency greppable and works identically from
   tests, `python -m`, and the console script.
3. **Rewrite map (every intra-project import):**
   - `import config` / `import protocol` / `import screen_capture` →
     `from screenshare import config` etc.
   - `from latest_slot import LatestSlot` → `from screenshare.latest_slot import LatestSlot`
     (same pattern for `outbox`, `permissions`, `remote_input`, `geometry`, `keymap`).
   - `import client as client_mod` (gui.py) → `from screenshare import client as client_mod`.
   - `gui.py:515` has a **function-level** `from server import HostServer`
     inside `run_host()` → `from screenshare.server import HostServer`
     (easy to miss in a top-level-only rewrite; grep for `from server` after
     the move).
   - `demo/transport_demos.py`: no change (stdlib only).
4. **Entry point:** `app.py` keeps `main()`, with the signature relaxed to
   `main(argv=None)` so the console script (called with zero arguments) works;
   `python -m` passes `sys.argv`. It sets process-DPI awareness first, then
   imports `gui` **inside `main()`** (replacing today's top-level import with
   `# noqa: E402`), then parses `host`/`viewer`. `__main__.py` is two lines calling
   `app.main()`. `pyproject.toml` declares
   `screenshare = "screenshare.app:main"`.
   `python app.py host` stops working; README documents the two new commands.
   **No-argument behaviour is unchanged:** it opens the Tk mode-chooser window
   exactly as today (README documents this; the spec's one-line usage print was
   never implemented and is not introduced by this change — behaviour changes
   are a non-goal).
5. **Editable install:** setup step becomes
   `.venv\Scripts\python.exe -m pip install -e .` into the existing project-local
   `.venv`. Tests and app then import `screenshare` from `src/` without path hacks.
6. **Tests:** drop the `sys.path.insert(...)` lines and rewrite
   `import protocol as P` → `import screenshare.protocol as P`,
   `from server import PermissionManager, HostServer` →
   `from screenshare.server import PermissionManager, HostServer`, etc.
   Test command stays `.venv\Scripts\python.exe -m unittest discover -s tests`.
   `tests/__init__.py` stays (unittest discovery needs it).
7. **`config` reload test:** `SlowViewerSetting` uses `importlib.reload(config)` on
   `screenshare.config` — works unchanged after the import rewrite.
8. **`server.PermissionManager` re-export** stays exactly as-is (only its import
   line changes), so test imports keep one source of truth.
9. **`requirements.txt` removed.** `pyproject.toml [project.dependencies]` keeps
   the same bounds: `mss>=10.2,<11`, `Pillow>=10.0`, `PyAutoGUI>=0.9.54`.
   Snyk SCA later scans the `pyproject.toml` instead.
10. **Docs:** README gets the new tree and commands. `docs/test_results.md` keeps
    every recorded output verbatim (honest history) and gains one line noting the
    commands were re-run under the new layout. Historical transcripts are not rewritten.

## 6. Constraints

- Windows-only runtime (Tk, PyAutoGUI, mss); verification runs through
  `.venv\Scripts\python.exe`.
- The 64-test suite binds real TCP port 5000; no live Host may be running during it.
- The starter kit and `demo/` must remain byte-identical (SHA-256 checked before
  and after the move).
- `ARCHITECTURE_FINAL_v5.md` must remain byte-identical.

## 7. Verification (done criteria)

1. `git`-less SHA check: `ARCHITECTURE_FINAL_v5.md`, `demo/transport_demos.py`,
   `network-screen-sharing-starter/**` hashes unchanged (recorded before the move).
2. `.venv\Scripts\python.exe -m pip install -e .` succeeds.
3. `.venv\Scripts\python.exe -m unittest discover -s tests` → `Ran 64 tests ... OK`.
4. `.venv\Scripts\python.exe -m compileall -q src tests demo` → exit 0.
5. Import check: `.venv\Scripts\python.exe -c "import screenshare.app"` exits 0.
   (A no-argument run is deliberately NOT part of automation: it opens the Tk
   chooser and would block; see decision 4.)
6. **Live GUI smoke of both entry points** (manual, this machine, port 5000 free):
   `.venv\Scripts\screenshare.exe host` and
   `.venv\Scripts\python.exe -m screenshare viewer` each start, show their window,
   connect over loopback, and quit cleanly with exit code 0. This is the only
   check that exercises the new wiring (console script → `main()` → DPI call →
   `gui` import inside `main()` → `run_host()`), which unit tests never touch.
7. No module remains at the repository root except `demo/transport_demos.py`
   (kept by design); `sys.path.insert` absent from all tests.

## 8. Risks

- Editable install could interact badly with the existing `.venv` if setuptools is
  missing — mitigation: `pip install -e .` bootstraps its own build deps; if it
  fails, fall back to adding `src/` via a `.pth` file and report.
- Stale path references in docs after the move — mitigation: grep for
  `python app.py`, `requirements.txt`, and root-module names after the change.
- The temporary GUI check script (`%TEMP%\gui_stats_check.py`) inserts the old
  root path; it lives outside the repo and will be re-pointed only if re-run.
