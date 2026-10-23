# PlanForge — Project Planner & Schedule Manager

![Your icon](docs/icon_transparent_background.png)

PlanForge is an offline project planning, scheduling, and estimation application with comprehensive interoperability across **ProjectLibre**, **Microsoft Project**, **GanttProject**, and the **Simple Function Point Calculator**.

You create a project, assign people with rates and daily availability, estimate tasks (via function points or manual work hours), and PlanForge builds a dependency-aware schedule with critical path analysis. You can inspect the schedule as an interactive Gantt chart, analyze costs and workloads, track completion, and exchange files across applications without vendor lock-in.

It integrates directly with the **Simple Function Point Calculator** (`fp_logic.py`), reusing its math without duplication so both tools produce identical effort and cost calculations.

---

## Start Here

| System | Launch PlanForge |
| --- | --- |
| **Windows 10/11** | Double-click **`PlanForgeLauncher.bat`** |
| **Linux** | Run **`./PlanForgeLauncher.sh`** |
| **macOS** | Double-click **`PlanForgeLauncher.command`**, or run `./PlanForgeLauncher.sh` |
| **Any system** | `python PlanForgeLauncher.py` (or `python3`) |

The launcher detects your operating system, prepares a project-local `.venv`,
installs any declared dependencies and starts the application. The older
`run.bat`, `run.sh` and `run.command` files are kept as compatibility wrappers
and do the same thing.

---

## Key Features

- **Interoperability Across Standard Formats:**
  - **Microsoft Project XML / MSPDI (`.xml`):** Lossless round-trip with Microsoft Project and ProjectLibre Desktop.
  - **ProjectLibre (`.xml` / `.pod`):** Full project interchange via standard XML, with built-in sniffer and guidance for native `.pod` files.
  - **GanttProject (`.gan`):** Direct import and export preserving nested tasks, dependencies with lag, resources, allocations, and calendars.
  - **Simple Function Point Calculator (`.json`):** Seamless estimation import, live calculator in UI, and export.
  - **CSV Task Lists (`.csv`):** Import unfamiliar CSV files with header mapping; export with rich JSON-in-cell columns.
  - **PlanForge JSON (`.json`):** Versioned, schema-validated JSON format for backups and system integrations.
  - **PlanForge SQLite (`.pfp`):** Standard SQLite database format with atomic saves and schema backups.
- **Dependency-Aware Scheduling Engine (`planforge/scheduling/engine.py`):**
  - Forward pass for earliest dates; backward pass for latest dates and float.
  - Identifies critical path tasks (zero float).
  - Four dependency relationships: Finish-to-Start (FS), Start-to-Start (SS), Finish-to-Finish (FF), Start-to-Finish (SF) with lag/lead.
  - Working days, non-working days, and project holidays.
  - Daily capacity divided across assigned team members.
  - Bottom-up summary task rollup.
- **Native Desktop Workspace (`planforge/gui/`, Tkinter):**
  - **Overview:** Metric cards, schedule span, critical path bottlenecks, team workload progress.
  - **Tasks:** Hierarchical table with indent/outdent, duration, progress bars, predecessors, and people.
  - **Timeline (Gantt Chart):** Visual bars, milestone diamonds, summary brackets, SVG dependency link arrows, weekend shading, day/week/month zoom.
  - **People:** Team management, roles, hourly rates, daily capacity.
  - **Costs & Workload:** Labour expenditure breakdowns, rate weighting, person-by-person workload sharing.
  - **Function Point Calculator:** Built-in FP estimation with instant transfer to project tasks.
  - **Summary Report:** Readable text report with clipboard copy and `.txt` export.
  - **Project Settings:** Project metadata, start date, currency, and working calendars.
  - **Theme Library:** Choose System Default, Light, Dark, Midnight, High Contrast or Classic; duplicate and edit supported colors; import/export validated JSON themes locally. Theme choices persist per user and work offline.
  - **Command Palette:** Search implemented commands with `Ctrl+Shift+P`; use arrow keys, Enter and Escape without the mouse.
  - **Context Actions & Suggestions:** Right-click tasks or Gantt rows for relevant actions. The Overview suggests state-based next steps, which can be dismissed or hidden.
  - **Workspace Preferences:** Persist Gantt zoom, task-column visibility, suggestion visibility, and ISO/UK/US/long date display independently from project data. Save named layouts with a tab, zoom, and column configuration.
  - **Undo/Redo & Recovery:** Undo and redo up to 100 project changes. Local crash-recovery snapshots are offered on next launch and never overwrite the source project until explicitly saved.
  - **Recent Projects:** Open the latest ten projects from File → Open Recent; clear the local history at any time.
  - **Keyboard Navigation:** `Ctrl+1` to `Ctrl+0` switch tabs; remap New, Open, Save, Undo, and Redo key letters in Preferences. macOS uses Command for these shortcuts.
- **No server, no browser:** PlanForge is a desktop application. Everything runs in one Python process with the standard library's Tkinter window.

---

## Quick Start

### 1. Launch the Application

Use the launcher for your system from [Start Here](#start-here). It detects the
operating system, finds Python 3.10+, creates a project-local `.venv`, installs
any dependencies declared in `requirements.txt` and starts PlanForge. No
packages are installed globally and no administrator rights are needed.

On Windows the launcher normally uses `pythonw.exe`, so there is no console
window during use; first-time setup reports progress in a small window and
errors appear in dialogs. Projects can be passed through, for example
`PlanForgeLauncher.bat my_project.pfp` or `./PlanForgeLauncher.sh my_project.pfp`.

Check the environment without changing anything:

```bash
./PlanForgeLauncher.sh --check          # Linux/macOS
PlanForgeLauncher.bat --check           # Windows
```

If Python or Tkinter is missing, the launcher prints the exact package or
installer to use. See [`docs/launcher.md`](docs/launcher.md) for per-platform
instructions, exit codes, logs and troubleshooting.

PlanForge itself runs on Python 3.10+ without any third-party library
dependencies. The window uses Tkinter, which ships with the python.org
installers on Windows and macOS and is a system package on Linux:

- **Debian and Ubuntu:** `sudo apt install python3-tk`
- **Arch Linux:** `sudo pacman -S tk`
- **Fedora:** `sudo dnf install python3-tkinter`

If you already manage your own Python environment, the original entry points
continue to work:

```bash
./bin/planforge
python3 -m planforge
```

To open a project straight away, pass its `.pfp` file:

```bash
./bin/planforge my_project.pfp
```

### 2. Command-Line File Conversion

PlanForge can convert projects between supported formats directly from the command line:

```bash
# Convert ProjectLibre XML to GanttProject
./bin/planforge --import-file schedule.xml --export-file schedule.gan --export-format ganttproject

# Convert GanttProject to Microsoft Project XML
./bin/planforge --import-file schedule.gan --export-file schedule.xml --export-format microsoft-project-xml

# Inspect any project file
./bin/planforge --import-file my_project.json
```

These flags run without opening a window.

### 3. Run the Automated Tests

Run the full automated test suite (including interchange, round-trip, scheduling engine, and UI workflows):

```bash
python3 -m unittest discover tests -v
```

Run the Function Point Calculator math tests:

```bash
PYTHONPATH=function-point-calculator/function-point-calculator-main python3 -m unittest discover function-point-calculator/function-point-calculator-main -p "test_fp_logic.py"
```

---

## Interoperability Guide

Detailed format specifications and round-trip verification are documented in [`docs/interoperability.md`](docs/interoperability.md).

The primary interchange workflow is:

```
Existing Software (ProjectLibre / MS Project / GanttProject)
            ↓ (Export XML / GAN)
        PlanForge (Import, Schedule, Estimate, Edit)
            ↓ (Export XML / GAN)
Existing Software (Reopen and continue)
```

### Supported Format Matrix

| Format | Import | Export | Description |
| --- | --- | --- | --- |
| **Microsoft Project XML (`.xml`)** | Yes | Yes | Universal MSPDI XML supported by MS Project, ProjectLibre, and GanttProject |
| **ProjectLibre Desktop (`.xml`)** | Yes | Yes | Full project interchange via ProjectLibre-compatible MSPDI XML |
| **GanttProject (`.gan`)** | Yes | Yes | Native XML format with tasks, hierarchy, dependencies, rates, and allocations |
| **Simple FP Calculator (`.json`)** | Yes | Yes | Estimator people, hourly rates, complex/simple points, hours, and costs |
| **CSV Task List (`.csv`)** | Yes | Yes | Structured task table with column mapping and JSON-in-cell relations |
| **PlanForge JSON (`.json`)** | Yes | Yes | Canonical, versioned JSON schema backup |
| **PlanForge SQLite (`.pfp`)** | Yes | Yes | Offline transactional SQLite database |
| **ProjectLibre Native (`.pod`)** | Guided | Guided | Binary Java serialization stream. Sniffed with actionable guidance to export XML. |
| **Microsoft Project Native (`.mpp`)** | Guided | Guided | Proprietary OLE binary format. Sniffed with actionable guidance to export XML. |

---

## Architecture & Code Structure

```
PlanForge/
├── PlanForgeLauncher.py        # Universal OS detection, .venv setup and startup
├── PlanForgeLauncher.bat       # Windows double-click entry point
├── PlanForgeLauncher.sh        # Linux/macOS entry point
├── PlanForgeLauncher.command   # macOS Finder entry point
├── run.bat                     # Compatibility wrapper for PlanForgeLauncher.bat
├── run.sh                      # Compatibility wrapper for PlanForgeLauncher.sh
├── run.command                 # Compatibility wrapper for PlanForgeLauncher.command
├── requirements.txt            # Runtime dependency manifest (stdlib-only today)
├── bin/
│   └── planforge               # Manual entry point for existing environments
├── docs/
│   ├── launcher.md             # Launcher guide, platform notes and exit codes
│   └── interoperability.md     # Detailed interoperability specifications
├── function-point-calculator/  # Integrated Simple Function Point Calculator
│   └── function-point-calculator-main/
│       ├── fp_logic.py         # Shared FP math and validation engine
│       └── test_fp_logic.py    # FP unit tests
├── planforge/
│   ├── __init__.py
│   ├── __main__.py             # Desktop entry point and CLI conversion
│   ├── config.py               # Theme preference in PlanForge.conf
│   ├── estimation.py           # Bridge to the Function Point Calculator maths
│   ├── model.py                # Canonical project data model
│   ├── session.py              # Open project and every operation on it (no GUI code)
│   ├── gui/                    # Tkinter desktop interface
│   │   ├── app.py              # Main window, menus, shortcuts, file actions
│   │   ├── theme.py            # Light and dark palettes and ttk styles
│   │   ├── views.py            # Overview, Tasks, People, Costs, Function Points, Report, Settings
│   │   ├── timeline.py         # Gantt chart drawn on a Canvas
│   │   └── dialogs.py          # Task editor, forms, import and export dialogs
│   ├── interchange/            # Modular format adapters
│   │   ├── registry.py         # Format registry, sniffers, atomic file operations
│   │   ├── mspdi_adapter.py    # Microsoft Project & ProjectLibre XML adapter
│   │   ├── ganttproject_adapter.py # GanttProject .gan adapter
│   │   ├── fp_adapter.py       # Function Point Calculator JSON adapter
│   │   ├── csv_adapter.py      # CSV adapter with header mapping
│   │   ├── json_adapter.py     # PlanForge JSON adapter
│   │   ├── validation.py       # Model integrity & circularity checks
│   │   ├── comparison.py       # Round-trip difference classifier
│   │   └── results.py          # Summary and result containers
│   ├── scheduling/
│   │   └── engine.py           # Forward/backward pass, float, capacity, calendars
│   └── storage/
│       └── sqlite_store.py     # Transactional .pfp SQLite storage
├── schemas/
│   └── planforge-project-v1.schema.json # JSON Schema Draft 2020-12
└── tests/
    ├── fixtures/               # Real project file fixtures (.xml, .gan, .json)
    ├── test_launcher.py        # Launcher platform, venv, locking, path and startup tests
    ├── test_interchange.py     # Comprehensive adapter & round-trip tests
    ├── test_session.py         # Workflow tests for projects, tasks, people, estimates, files (no display needed)
    └── test_gui.py             # Window smoke tests (skipped unless Tk and a display are available)
```

---

## License

PlanForge is free and open-source software. All standard library code has zero runtime third-party dependencies.
