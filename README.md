# PlanForge — Project Planner & Schedule Manager

PlanForge is an offline project planning, scheduling, and estimation application with comprehensive interoperability across **ProjectLibre**, **Microsoft Project**, **GanttProject**, and the **Simple Function Point Calculator**.

You create a project, assign people with rates and daily availability, estimate tasks (via function points or manual work hours), and PlanForge builds a dependency-aware schedule with critical path analysis. You can inspect the schedule as an interactive Gantt chart, analyze costs and workloads, track completion, and exchange files across applications without vendor lock-in.

It integrates directly with the **Simple Function Point Calculator** (`fp_logic.py`), reusing its math without duplication so both tools produce identical effort and cost calculations.

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
- **Interactive UI/UX Workspace (`planforge/ui/`):**
  - **Overview:** Metric cards, schedule span, critical path bottlenecks, team workload progress.
  - **Tasks:** Hierarchical table with indent/outdent, duration, progress bars, predecessors, and people.
  - **Timeline (Gantt Chart):** Visual bars, milestone diamonds, summary brackets, SVG dependency link arrows, weekend shading, day/week/month zoom.
  - **People:** Team management, roles, hourly rates, daily capacity.
  - **Costs & Workload:** Labour expenditure breakdowns, rate weighting, person-by-person workload sharing.
  - **Function Point Calculator:** Built-in FP estimation with instant transfer to project tasks.
  - **Summary Report:** Readable text report with clipboard copy and `.txt` export.
  - **Project Settings:** Project metadata, start date, currency, and working calendars.
  - **Light & Dark Theme:** System-aware, configurable in `.config/PlanForge/PlanForge.conf`.
  - **Keyboard Navigation:** `Ctrl+1` through `Ctrl+5`, `Ctrl+S`, `Ctrl+N`.

---

## Quick Start

### 1. Launch the Application

PlanForge runs on Python 3.10+ without any third-party library dependencies.

Start the application server:

```bash
./bin/planforge --port 8080
```

or via Python module:

```bash
python3 -m planforge --port 8080
```

Open your web browser at `http://localhost:8080` (or use the sandbox live preview URL).

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
├── bin/
│   └── planforge               # Executable application launcher
├── docs/
│   └── interoperability.md     # Detailed interoperability specifications
├── function-point-calculator/  # Integrated Simple Function Point Calculator
│   └── function-point-calculator-main/
│       ├── fp_logic.py         # Shared FP math and validation engine
│       └── test_fp_logic.py    # FP unit tests
├── planforge/
│   ├── __init__.py
│   ├── __main__.py             # CLI entry point
│   ├── model.py                # Canonical project data model
│   ├── server.py               # Application server & REST API
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
│   ├── storage/
│   │   └── sqlite_store.py     # Transactional .pfp SQLite storage
│   └── ui/                     # Design-system UI assets
│       ├── index.html          # Clean, semantic SPA markup
│       ├── style.css           # CSS design system (Light/Dark themes)
│       └── app.js              # View router, interactive Gantt, FP sync
├── schemas/
│   └── planforge-project-v1.schema.json # JSON Schema Draft 2020-12
└── tests/
    ├── fixtures/               # Real project file fixtures (.xml, .gan, .json)
    ├── test_interchange.py     # Comprehensive adapter & round-trip tests
    └── test_server_and_ui.py   # Full 15 UI/UX workflow integration tests
```

---

## License

PlanForge is free and open-source software. All standard library code has zero runtime third-party dependencies.
