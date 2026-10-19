# PlanForge

> **Checkout status (2026-10-19):** this repository revision does not contain
> the PlanForge desktop application or its project-storage code. The product
> description below documents the intended application; the runnable source,
> launchers, and original tests are absent from this checkout. The currently
> implemented interoperability foundation is documented in
> [`docs/interoperability.md`](docs/interoperability.md) and is not wired into
> the desktop UI.

PlanForge is an offline desktop project planner. You create a project, add
people with rates and availability, estimate tasks (by function points or by
hand), and PlanForge builds a dependency-aware schedule. You can view the
schedule as an interactive Gantt chart, see labour costs and workload, track
progress, and save, reopen and export your work.

It is built on the Simple Function Point Calculator. The calculator's maths
(`fp_logic.py`) is reused, not copied, so the two programs give the same
hours for the same inputs.

There is no account, no cloud service and no subscription. Everything stays
on your computer.

## Contents

- [Quick start](#quick-start)
- [What you can do](#what-you-can-do)
- [Your project file](#your-project-file)
- [Working with the schedule](#working-with-the-schedule)
- [How the schedule is calculated](#how-the-schedule-is-calculated)
- [How estimates and costs are calculated](#how-estimates-and-costs-are-calculated)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Importing and exporting](#importing-and-exporting)
- [Autosave, recovery and backups](#autosave-recovery-and-backups)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)

## Quick start

The desktop application launchers and entry points described in the original
product notes are not included in this checkout. The available Python package
is the standalone interoperability library; it requires Python 3.10 or newer
and has no third-party dependencies.

Run its tests with:

    python3 -m unittest discover -v

See [`docs/interoperability.md`](docs/interoperability.md) for import/export
examples. Do not use the desktop-app launch commands in older copies of this
document until the application source has been restored.

## What you can do

PlanForge has five pages, shown in the left-hand list (or **View** menu,
`Ctrl+1` to `Ctrl+5`):

| Page | What it shows |
| --- | --- |
| **Tasks** | A table of every task with its type, method, hours, cost, dates, float, progress, priority, status, deadline and people. Add tasks, milestones, sub-tasks and summary tasks, and reorder or indent them. |
| **Timeline** | An interactive Gantt chart. Bars, summary brackets, dependency arrows, milestones, weekend shading and holidays. You can move, resize and link tasks by dragging (see [Working with the schedule](#working-with-the-schedule)). |
| **People** | Your team: name, role, hourly rate, hours per day, and availability. |
| **Costs and workload** | Labour cost, hours and workload per person and per task. |
| **Summary** | A readable text report of the project. You can export it as a text file. |

### Tasks

Each task can be one of three types:

- **Task:** has work, duration and people.
- **Milestone:** a zero-length point in time, such as a release or sign-off.
- **Summary:** groups sub-tasks. Its dates come from its children, and it
  cannot be dragged on the Gantt chart.

Each task estimate can use one of two methods:

- **Function points:** enter the function point counts (external inputs,
  outputs, enquiries, files and interfaces) and their complexity. PlanForge
  converts them to hours using the calculator's rules.
- **Manual:** type the hours directly.

You can also set a priority, status, progress percentage, deadline, and
the people assigned to the task, each with an allocation percentage.

### People

Each person has an hourly rate, the hours they work per day, and an
allocation percentage per task. Rates feed the labour costs. Hours per day
and allocation feed the schedule (see below).

### Project settings

**Edit > Project settings** (`Ctrl+,`) sets the project name, description,
currency code, start date, working days (for example Monday to Friday),
holidays, and the default hours per working day.

## Your project file

Projects are saved as `.pfp` files. A `.pfp` file is a standard SQLite
database, so you can inspect it with any SQLite tool. Each file records a
schema version. When you open a file made by an older version of PlanForge,
PlanForge first saves a backup copy of it and then upgrades the file. An
older file is never overwritten without a backup.

Saving is atomic: PlanForge writes to a temporary file and then replaces the
old file in one step. If something goes wrong part-way through, your previous
file is left intact.

PlanForge will not save a project that has validation problems. It lists the
problems so you can fix them.

## Working with the schedule

Open the **Timeline** page to see the schedule.

- **Move a task:** drag the bar left or right. This sets a "start no earlier
  than" date on the task. It does not change the task's estimate.
- **Change a task's length:** drag its right edge. This sets a fixed
  duration in working days. It does not change the estimate either.
- **Link two tasks:** drag the round handle on one task onto another. This
  creates a finish-to-start dependency. For the other three types, and for
  lags, use the link dialog (from the task editor).
- **Edit a task:** double-click its bar.

Moving a task cannot place it before its predecessors finish. If you try to
drag a task earlier than its dependencies allow, the schedule keeps it at the
earliest valid date. Summary tasks cannot be dragged.

PlanForge refuses a link that would create a loop, such as A depends on B
and B depends on A. It tells you which link was refused.

Every change can be undone and redone with `Ctrl+Z` and `Ctrl+Y` (or
`Ctrl+Shift+Z`).

## How the schedule is calculated

These are the rules PlanForge uses. They are also documented in the code
(`planforge/scheduling/engine.py`).

- **Duration:** a task's work hours are divided by its daily capacity, and
  the result is rounded up to whole working days. Daily capacity is the sum,
  over its assigned people, of (allocation % × that person's hours per day).
  A task with nobody assigned uses the project's default hours per working
  day, and the schedule says so.
- **Working days:** only the working days you set are counted. Holidays are
  skipped. A lag of 2 means two working days, not two calendar days.
- **Dependencies:** PlanForge supports four types. Finish-to-start (the usual
  one), start-to-start, finish-to-finish and start-to-finish. Each can have a
  lag, in working days. A negative lag (a lead) that would start a task before
  the project start is limited to the project start, and the schedule reports
  it.
- **Forward and backward pass:** the forward pass finds the earliest start and
  finish for each task. The backward pass finds the latest finish that does
  not delay the project.
- **Float and the critical path:** float is the latest start minus the
  earliest start. Tasks with zero float form the critical path.
- **Summary tasks** take the earliest start and latest finish of their
  children. They have no float of their own.
- **Over-allocation:** if a person is assigned more work than they have
  capacity for, PlanForge reports it. It does not move tasks to fix it.
  Resource levelling is not done (see [Limitations](#limitations)).
- **Progress:** progress is shown and tracked, but it does not change the
  schedule yet. Every task is scheduled at its full duration from the start
  date.

## How estimates and costs are calculated

- **Function points:** hours come from the calculator's own functions, so
  PlanForge and the calculator give the same hours for the same inputs.
- **Splitting work between people:** when several people work on a task,
  the hours are divided in proportion to their allocation. For example, two
  people at 100% each take half the hours. This is the same convention that
  Microsoft Project and ProjectLibre use.
- **Labour cost:** the hours each person does, multiplied by that person's
  hourly rate.
- **Actual hours and actual cost:** these are recorded separately from the
  estimate, so you can compare plan and actual.
- **Earned hours and remaining hours:** earned hours are the estimate
  multiplied by progress %. Remaining hours are the rest.
- **Summary tasks** add up their sub-tasks. Totals count each leaf task
  once, so nothing is counted twice.
- **Unknown values are shown as unknown.** If a value cannot be worked out
  yet (for example, a function-point task with no estimator, or a manual task
  with no hours typed in), PlanForge shows it as blank with a plain-language
  warning. It does not silently replace it with zero.

Your original estimate inputs are never overwritten. When you change a
setting, such as an hourly rate or the working days, the derived values are
recalculated from your inputs.

## Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| New project | `Ctrl+N` |
| Open | `Ctrl+O` |
| Save | `Ctrl+S` |
| Save as | `Ctrl+Shift+S` |
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Y` or `Ctrl+Shift+Z` |
| Project settings | `Ctrl+,` |
| Tasks page | `Ctrl+1` |
| Timeline page | `Ctrl+2` |
| People page | `Ctrl+3` |
| Costs and workload page | `Ctrl+4` |
| Summary page | `Ctrl+5` |
| Quit | `Ctrl+Q` |

## Importing and exporting

The standalone interoperability package currently implements these adapters:

| Format | Adapter import | Adapter export | Adapter round-trip tested | External-application round-trip tested |
| --- | --- | --- | --- | --- |
| PlanForge JSON (`.json`, schema v1) | Yes | Yes | Yes | No |
| PlanForge CSV template (`.csv`) | Yes | Yes | Yes | No |
| Mapped CSV task lists (`.csv`) | Yes | N/A | Mapping/import tested | No |
| PlanForge project (`.pfp`) | No | No | No | No |
| Calculator JSON | No | No | No | No |
| Microsoft Project XML / ProjectLibre XML | No | No | No | No |
| ProjectLibre POD (`.pod`) | No | No | No | No |
| Microsoft Project MPP (`.mpp`) | No | No | No | No |
| GanttProject GAN (`.gan`) | No | No | No | No |

The JSON adapter uses a versioned, explicit project interchange model. The
CSV template uses one row per task and optional JSON-in-cell columns for
relationships, resources, assignments, calendars, and custom data. Plain CSV
files are not assumed to contain complete scheduling information. Unknown
JSON fields and unmapped CSV columns are retained where possible, and invalid
references are reported. See [`docs/interoperability.md`](docs/interoperability.md)
for the schema, mappings, limitations, and programmatic API.

These are backend adapters only. This checkout has no desktop file menu,
`.pfp` persistence, Function Point Calculator adapter, or external-application
round-trip validation. Do not treat the adapters as integrated desktop import
or export until the missing application source is restored.

## Autosave, recovery and backups

- **Recovery copies:** two seconds after you stop making changes, PlanForge
  writes a recovery copy of your unsaved work. These are stored in your
  user data folder, not next to your project. If PlanForge closes unexpectedly,
  the next time it starts it offers to restore the recovery copy.
  - Windows: `%LOCALAPPDATA%\PlanForge\Recovery`
  - macOS: `~/Library/Application Support/PlanForge/Recovery`
  - Linux: `~/.local/share/planforge/Recovery` (or `$XDG_DATA_HOME/planforge/Recovery`)
- **Backups on save:** each time you save, PlanForge copies the previous
  file into a folder named `<project name> backups` next to your project.
  Automatic backups are kept for the 20 most recent saves.
- **Recovery copies are removed** when you save, or when your changes are
  undone back to the saved state. Your project file is never deleted by
  PlanForge.

## Limitations

These are known limits in the current version:

- **No resource levelling.** Over-allocation is reported, not resolved.
- **Progress does not drive the schedule.** A task with 50% progress is still
  scheduled at its full duration.
- **Only one date constraint exists: "start no earlier than".** There is no
  "must finish by" constraint. A deadline is checked, and a task that finishes
  after its deadline is reported as a warning. The deadline does not change
  the schedule.
- **Gantt links are finish-to-start only.** The link dialog creates all four
  dependency types, with lags.
- **No PDF export.**
- **No ProjectLibre or Microsoft Project import or export.**
- **Calculator export can lose data** that the calculator cannot store. You
  are warned about each item.
- **Single user.** PlanForge does not support several people editing the same
  project at the same time.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| "Python 3.10 or newer was not found" | Install Python 3.10 or newer from python.org (on Windows, tick "Add python.exe to PATH"), then run the launcher again. |
| "Could not create the .venv folder" | On Debian or Ubuntu, install `python3-venv`, then run the launcher again. |
| "The packages could not be installed" | Check your internet connection and run the launcher again. The launcher log has pip's full output. |
| "Permission denied" when running `./run.sh` | Run `chmod +x run.sh` once. |
| Something fails after a Python upgrade | Run `python launcher.py --recreate-venv`. |
| A problem not listed here | Run `python launcher.py --check` from a terminal and read the message. |

Use **File > Save as...** to keep a copy of your project before trying
anything risky.

## For developers

- **Available source in this checkout:** `planforge/model.py` and
  `planforge/interchange/` implement a standalone exchange contract, JSON/CSV
  adapters, validation, registry, and comparisons. The desktop application,
  SQLite storage, scheduling engine, Function Point Calculator integration,
  UI, and launcher files described elsewhere in this README are not included.
- **Interoperability notes:** see [`docs/interoperability.md`](docs/interoperability.md)
  and [`schemas/planforge-project-v1.schema.json`](schemas/planforge-project-v1.schema.json).
- **Tests:** run `python3 -m unittest discover -v` from the project root.
- **Dependencies:** the current interoperability package uses only the Python
  standard library (Python 3.10+). There is no `requirements.txt` in this
  checkout.

## Status

PlanForge is under active development. The desktop app has been tested on
Linux. It has not yet been tested on Windows or macOS, so `run.bat` and the
macOS launcher path are unverified. Packaged installers for Windows, Linux
and macOS are not available yet.
