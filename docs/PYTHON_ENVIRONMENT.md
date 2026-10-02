# System Tracker Python Environment

## Purpose

The Python environment is machine-local. Do not synchronize `.venv` through
cloud-synced folders or Git.

## Two environments

| Project | Location | Dependencies |
|---|---|---|
| **System Tracker** (this repo) | `System_Tracker\.venv` | `aw-client`, `openai`, `Pillow`, `tzdata` (`openai` is only used by the iPhone ingest step; `Pillow` by the iPhone and Habit screenshot ingest steps) |
| **Desktop Tracker Collector** | `Desktop Tracker Collector\.venv` | `aw-client`, `tzdata` only — no `openai`, no dependency on System Tracker |

The desktop PC needs **only** the Desktop Tracker Collector environment to
collect ActivityWatch data. The full System Tracker environment is used on the
laptop / central machine for import, integration, and analysis.

## Python baseline

Each machine has its own Python installation and project-local `.venv`. The
version and base interpreter may differ between machines; create the `.venv`
from a valid interpreter present on the machine where the code runs.

- Laptop / central: Python 3.13+ (`System_Tracker\.venv`).
- Desktop: Python 3.14.x (any local interpreter).

`import_desktop_activitywatch.py` and `desktop_export_contract.py` are
stdlib-only so the import step never depends on the collector's environment.

## Setup

```powershell
# System Tracker (laptop / central)
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Desktop Tracker Collector (desktop) — see that project's scripts\setup_desktop.ps1
```
