# Network-Based Screen Sharing and Remote Control System (VTU BCS502)

Python, Tkinter and TCP. One Host shares its screen with up to two Viewers on the same private LAN or phone hotspot; a Viewer can request mouse and keyboard control and the Host approves, denies or revokes it.

Status: starter pack. Provided and tested: framing, queues, key map, geometry and the transport demo script. Everything else is built stage by stage by the coding agent (see `AGENTS.md` and `docs/AGENT_PROMPTS.md`). The specification is `ARCHITECTURE.md`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python demo/transport_demos.py boundaries
```
