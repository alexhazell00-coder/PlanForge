"""Detailed Help & User Guide tab - explains every top tab and every button."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from planforge.gui.views import BaseView

if TYPE_CHECKING:  # pragma: no cover
    from planforge.gui.app import PlanForgeApp

HELP_SECTIONS: list[tuple[str, str, str]] = [
    (
        "welcome",
        "Welcome to PlanForge",
        (
            "PlanForge is an offline project planner that helps you build a dependency-aware schedule, "
            "assign people with rates and availability, estimate effort with function points, and exchange "
            "projects with Microsoft Project, ProjectLibre, GanttProject and other tools — without vendor lock-in.\n\n"
            "This Help tab is your complete reference. Use the list on the left to jump to any section. "
            "Every button in the app is explained here, and the File Conversion guide shows you exactly how to move "
            "projects between formats in one or two clicks.\n\n"
            "TIP: Press Ctrl+1 .. Ctrl+0 to jump between top tabs, Ctrl+T to cycle themes, and F5 to recalculate the schedule."
        ),
    ),
    (
        "quick_start",
        "Quick Start (60 seconds)",
        (
            "1. Launch PlanForge: double-click PlanForgeLauncher.bat (Windows), PlanForgeLauncher.command (macOS), "
            "or run ./PlanForgeLauncher.sh (Linux).\n"
            "2. You will see a sample project 'Website Redesign & Launch' with 4 tasks already scheduled.\n"
            "3. Open the Tasks tab (Ctrl+2) to edit task names, durations and dependencies.\n"
            "4. Open the People tab to check hourly rates — these drive labour costs.\n"
            "5. Press F5 or click Recalculate to update dates after any change.\n"
            "6. File → Save As… to save a .pfp file. File → Export… to create an XML or GAN for another app.\n\n"
            "Already have a file from another app? Jump to the Convert tab or File → Import… and follow the File Conversion guide below."
        ),
    ),
    (
        "overview",
        "Overview Tab — Project Health at a Glance",
        (
            "Purpose: Gives you a dashboard of the whole project so you can spot problems early.\n\n"
            "What you see:\n"
            "• Metric cards (top row): Tasks, Milestones, Dependencies, Team members, Estimated hours, Estimated cost. "
            "These update instantly when you edit anything.\n"
            "• Project label: Shows project name, start → finish span, and whether dates are scheduled.\n"
            "• Critical path table (left): Lists tasks with zero float — if they slip, the finish date slips. Red in the Timeline.\n"
            "• Team workload table (right): Hours and cost per person, based on assignments × rates.\n\n"
            "Buttons: This tab has no editing buttons — it is read-only. Use Tasks and People to make changes, then return here to see the impact.\n"
            "When to use it: At the start of a review meeting. Check if finish date, total cost, or critical path look right."
        ),
    ),
    (
        "tasks",
        "Tasks Tab — Build Your Work Breakdown",
        (
            "Purpose: Create and organise the full task hierarchy, durations, progress and dependencies.\n\n"
            "Main table columns:\n"
            "• Task (first column): Name with indentation for subtasks. Bold = summary task (has children), Orange = milestone.\n"
            "• Duration: Working days (e.g. '4 d' or 'milestone').\n"
            "• Start / Finish: Scheduled dates (set by the engine from durations, dependencies and calendars).\n"
            "• Done: Percent complete (0-100%).\n"
            "• Predecessor: Name of the one predecessor shown inline (edit to see all).\n"
            "• Person: Assigned team member.\n"
            "• Cost: Estimated labour cost (hours × rate).\n\n"
            "Buttons (top bar, right to left):\n"
            "• + Task (blue): Adds a new task after the current list. Opens the editor automatically so you can name it.\n"
            "• + Milestone: Adds a zero-duration milestone (diamond in Timeline). Use for approvals, releases, deadlines.\n"
            "• Indent: Makes the selected task a child of the task above it. Tip: Select the second task first, then click Indent.\n"
            "• Outdent: Moves the task up one level, placing it after its former parent.\n"
            "• Edit: Opens the task editor for the selected row. You can also double-click a row or press Enter.\n"
            "• Delete: Removes the task; its subtasks move up, and its dependencies/assignments are cleaned up. Confirms first.\n"
            "• Search box (left): Type to filter the list by name. Indentation is flattened while searching.\n\n"
            "Editor tip: Double-click any task to change name, notes, milestone flag, duration, % complete, priority, predecessor, lag, dependency type, assigned person, and function-point estimate."
        ),
    ),
    (
        "timeline",
        "Timeline Tab — Gantt Chart",
        (
            "Purpose: Visual schedule. See when tasks run, which overlap, and where dependencies link.\n\n"
            "How to read it:\n"
            "• Left column: Task names with ▾ for summaries, ◆ for milestones, red for critical-path tasks.\n"
            "• Bars: Blue = normal, Light blue = background, Red = critical path. Progress fill shows % complete.\n"
            "• Diamonds: Milestones.\n"
            "• Summary brackets: Parent tasks that span their children.\n"
            "• Grey shaded columns: Weekends / non-working days (from Settings → Working days).\n"
            "• Red dashed line: Today.\n"
            "• Arrows: Dependencies (FS, SS, FF, SF). Hover logic is visual only; edit arrows in Task editor.\n\n"
            "Buttons:\n"
            "• Days / Weeks / Months (top): Zoom level. Days = 22 px/day (most detail), Weeks = 8 px, Months = 3 px. Pick what fits your project span.\n\n"
            "Navigation:\n"
            "• Mouse wheel = scroll vertically. Shift+wheel = scroll horizontally. Use scrollbars for precise movement.\n"
            "• Chart and name column scroll together.\n"
            "• If you see 'Add tasks with durations…' — add durations or press F5 to schedule."
        ),
    ),
    (
        "people",
        "People Tab — Team & Rates",
        (
            "Purpose: Manage who does the work, their cost, and daily capacity.\n\n"
            "Table columns:\n"
            "• Name: Person's display name.\n"
            "• Rate / hour: Hourly rate in project currency (set in Settings). Changing this recalculates all costs.\n"
            "• Hours / day: How many hours that person can work per working day (e.g. 8, 6 for part-time). Affects capacity but not bar dates directly.\n"
            "• Tasks / Total hours / Total cost: Derived from assignments.\n\n"
            "Buttons:\n"
            "• + Add Person (blue, left): Opens a form for Name, Hourly rate, Hours per day. Rate ≥0, Hours/day must be >0 and ≤24.\n"
            "• Edit: Edits the selected person. Renaming updates everywhere. Changing rate/capacity reflows costs.\n"
            "• Delete: Removes the person and all their assignments after confirmation.\n\n"
            "Double-click a row to edit. Tip: Keep rates realistic — Function Points and manual durations both use rates to compute costs."
        ),
    ),
    (
        "costs",
        "Costs & Workload Tab — Where the Money Goes",
        (
            "Purpose: Labour cost breakdown. Understand who is most loaded and where budget goes.\n\n"
            "Cards (top):\n"
            "• Estimated task cost: Sum of all task estimated_cost fields.\n"
            "• Estimated task hours: Sum of work.\n"
            "• Assigned labour cost: Hours × rate per assignment. Should match estimated cost if assignments are correct.\n\n"
            "Table: One row per person — Rate, Tasks, Hours, Cost, Share (% of total). Use Share to spot over-allocation.\n"
            "Bar chart: Visual cost per person (longest bar = highest cost). Hover not needed — values are labelled.\n\n"
            "No editing buttons here — edit in People or Tasks. This tab is for analysis."
        ),
    ),
    (
        "estimates",
        "Function Points Tab — Estimate Before You Schedule",
        (
            "Purpose: Use function points (like the Simple Function Point Calculator) to estimate hours and cost before creating scheduled tasks.\n\n"
            "Left panel — Estimators:\n"
            "• List of estimator profiles (people doing estimation). Select one to edit its settings/tasks.\n"
            "• + Add Estimator: Provide a name (e.g. 'Alice'). Creates a profile with default rates (30/h, 2.5h per complex FP, 1.0h per simple FP).\n"
            "• Remove: Deletes the selected estimator and their draft tasks.\n\n"
            "Right panel — Settings (top):\n"
            "• Hourly rate / Hours per complex FP / Hours per simple FP: Per-estimator settings. Click Save settings to store.\n\n"
            "Middle — Estimated tasks table:\n"
            "• + Task: Add a feature/task with Name, Complexity (complex/simple), and Function points (whole number).\n"
            "• Edit / Delete: Act on the selected estimated task. Double-click also edits.\n\n"
            "Footer:\n"
            "• Totals line: Live count of tasks, points, hours and cost across all estimators.\n"
            "• Transfer to Project Tasks (blue): Converts every estimator's tasks into real project tasks and merges people by name (updates rate if matching). "
            "After transfer, estimators are cleared and you can see tasks in Tasks/Timeline. This is the main workflow — the button does all grouping, rate reuse, and scheduling.\n\n"
            "Tip: Estimates are kept in memory until you transfer or close PlanForge. Save your project after transferring."
        ),
    ),
    (
        "convert",
        "Convert Tab — Move Projects Between Apps (Step-by-Step)",
        (
            "Purpose: The easiest place to convert file formats. No need to remember menu paths — everything is in one wizard.\n\n"
            "Supported formats (you can Import and Export each):\n"
            "• Microsoft Project XML (MSPDI) .xml — Universal exchange for MS Project + ProjectLibre. Tasks, hierarchy, FS/SS/FF/SF lags, milestones, resources, rates, assignments, calendars.\n"
            "• GanttProject .gan — Native GanttProject format. Nested tasks, dependencies with lag, resources, allocations, calendars.\n"
            "• PlanForge JSON .json — Versioned canonical backup. Perfect round-trip.\n"
            "• PlanForge SQLite .pfp — Offline transactional database (Save/Save As).\n"
            "• CSV Task List .csv — Header-mapped tasks + JSON-in-cell columns for full fidelity.\n"
            "• Simple FP Calculator .json — People, rates and function-point tasks.\n"
            "• Guided: ProjectLibre .pod and MS Project .mpp — Detected with actionable instructions to export XML first. PlanForge explains exactly what to click in the other app.\n\n"
            "How to convert (3 steps):\n"
            "1. Source: Click Browse… → pick your file (e.g. schedule.xml or project.gan). Format is auto-detected from content, not just extension. Click Inspect / or it auto-inspects — you will see Project name, Tasks, Dependencies, People, Assignments, Dates, and any warnings.\n"
            "2. Target: Choose export format from the dropdown (e.g. GanttProject .gan), then click Browse… or Suggest name to pick where to save. Suggested names use your project name plus correct extension.\n"
            "3. Convert: Click Convert / Export. PlanForge validates the generated file by re-importing it internally before touching your disk, then writes atomically (temp file + replace) so you never get a half-written file. On success you get a confirmation with the full path.\n\n"
            "What each button does (Convert tab):\n"
            "• Browse… (Source): Opens a file picker filtered to all supported types. After picking, preview auto-loads.\n"
            "• Format (Source) dropdown: 'Detect automatically' is best. Choose explicit only if detection disagrees with your file.\n"
            "• Inspect / Check file: Re-runs detection and shows summary + messages. Fixes the 'file not found' or 'too large' errors inline.\n"
            "• Format (Target) dropdown: Pick output type. List is same as File → Export… but with clearer names and extensions.\n"
            "• Suggest name: Generates a safe filename from the project name (or source name) + target extension, placed in your home folder. Edit it or Browse to change location.\n"
            "• Browse… (Target): Choose save location. Extension auto-added if missing.\n"
            "• Convert (blue, big): Runs import → validate → export atomically. Needs both a valid source preview and a target path.\n"
            "• Show in folder / Open: (after success) Opens the containing folder or reveals the file. Lets you hand it to the other app immediately.\n"
            "• Clear / Reset: Clears both panels to start another conversion.\n"
            "• Help: Jumps back to this guide.\n\n"
            "Alternative — Menu method:\n"
            "• File → Import… : Pick file → Check → Import. This REPLACES the open project (you will be asked to save first). Then File → Export… → choose format → save. Same engine as Convert tab, but two separate dialogs.\n\n"
            "CLI (no window):\n"
            "  ./bin/planforge --import-file schedule.xml --export-file schedule.gan --export-format ganttproject\n"
            "Use --import-file alone to just inspect a file in the terminal.\n\n"
            "Troubleshooting:\n"
            "• .pod or .mpp file? PlanForge will detect and give exact steps: open in ProjectLibre/MS Project → Save As → XML → import that XML.\n"
            "• 'Could not identify format' → Check extension (.xml .gan .csv .json .pfp) and ensure file is not empty or corrupted.\n"
            "• 'File too large' → Limit is 10 MB for imports; split large portfolios or remove embedded images.\n"
            "• Wrong dates? Check Settings → Start date and Working days, then Recalculate (F5).\n"
            "• CSV looks messy? Use header mapping: first row should contain 'Task'/'Name'/'Title' etc.; PlanForge auto-suggests aliases.\n"
            "• Costs zero? Ensure People have hourly rates and Tasks have assignments or function points."
        ),
    ),
    (
        "summary",
        "Summary Report Tab — Shareable Text",
        (
            "Purpose: Produce a plain-text report you can paste into email, tickets, or documents. No formatting to break.\n\n"
            "Contents: Header with project name, description, author, currency, dates; Key Metrics (tasks, milestones, dependencies, team, hours, cost); Critical Path (or 'None detected'); Team Allocation & Costs (per person hours/cost); generation timestamp.\n\n"
            "Buttons:\n"
            "• Copy Report: Copies the entire text to clipboard. Shows confirmation.\n"
            "• Save as Text… : Prompts for a .txt filename (defaults to project_name_summary.txt). Saves UTF-8.\n"
            "• Refresh: Re-generates from the current project (also happens automatically when you switch to this tab).\n\n"
            "Tip: Use Ctrl+A then Ctrl+C inside the text area for partial copy."
        ),
    ),
    (
        "settings",
        "Settings Tab — Project Metadata & Calendar",
        (
            "Purpose: Global project properties that affect scheduling and display.\n\n"
            "Fields:\n"
            "• Project name: Displayed in window title and reports. Cannot be empty.\n"
            "• Description: Multi-line notes (e.g. scope). Shown in Overview and report.\n"
            "• Start date (YYYY-MM-DD): When the project may start. Leave blank for no constraint. Changing this reschedules every task after Apply.\n"
            "• Currency: GBP, USD, EUR, CAD, AUD. Symbol updates everywhere (costs, report). Default GBP.\n"
            "• Working days: Tick Mon-Sun. Typical Mon-Fri. Unchecked days are non-working (grey in Timeline, skipped by scheduler).\n\n"
            "Button:\n"
            "• Apply Changes (blue): Validates and saves. Invalid date format → error box. No working days → error. On success, reschedules and marks project dirty (title shows *).\n\n"
            "Note: Theme and window prefs are saved separately in ~/.config/PlanForge/PlanForge.conf (managed by PlanForgeLauncher)."
        ),
    ),
    (
        "timeline_details",
        "Timeline Interactions & Details",
        (
            "Already covered mainly in Timeline tab section, but extra details:\n"
            "• Summary tasks are calculated bottom-up: parent start = min(child starts), parent finish = max(child finishes).\n"
            "• Critical path uses forward pass (earliest dates) + backward pass (latest dates + float). Zero float = critical.\n"
            "• Four dependency types: Finish-to-Start (FS, classic), Start-to-Start (SS), Finish-to-Finish (FF), Start-to-Finish (SF), each with lag/lead in working days.\n"
            "• Lag: Delay after predecessor. Negative = lead (overlap).\n"
            "• Capacity: Daily capacity is divided across assigned members; scheduler respects working days and holidays."
        ),
    ),
    (
        "menus_toolbar",
        "Menus, Toolbar & Keyboard Shortcuts",
        (
            "File menu:\n"
            "• New Project (Ctrl+N): Starts a blank project. Asks to save if the current project has unsaved changes.\n"
            "• Open… (Ctrl+O by default): Opens a .pfp PlanForge database. Replaces current project. Open Recent lists the last ten project paths.\n"
            "• Save (Ctrl+S): Saves to current .pfp path, or prompts for Save As if never saved.\n"
            "• Save As… (Ctrl+Shift+S): Choose any .pfp location.\n"
            "• Import… (Ctrl+I): Opens Import dialog — pick file, auto-detect or force format, Check, then Import (replaces project).\n"
            "• Export… (Ctrl+E): Opens Export dialog — pick format, choose destination, Export.\n"
            "• Quit (Ctrl+Q): Closes PlanForge after save prompt if dirty.\n\n"
            "Edit menu:\n"
            "• Undo / Redo: Restore the previous or next complete project snapshot (up to 100 operations). Standard text fields retain their own native editing shortcuts.\n"
            "• Crash recovery: Separate local snapshots are offered on next launch and never overwrite the original project automatically.\n\n"
            "View menu:\n"
            "• Recalculate Schedule (F5): Re-runs scheduling engine without changing data. Use after Settings changes or if dates look stale.\n"
            "• Theme (View menu): Select System Default, Light, Dark, Midnight, High Contrast or Classic. Ctrl+T cycles built-ins. Manage Themes opens local custom-theme editing/import/export.\n"
            "• Workspace Layouts save/apply named tab, zoom and task-column arrangements.\n"
            "• Tools menu: Command Palette (Ctrl+Shift+P), Preferences (date format, columns, recovery, and remappable keys), Function Point Calculator and Import/Export Tools.\n\n"
            "Help menu:\n"
            "• User Guide (this tab) (F1): Jumps to Help tab.\n"
            "• Keyboard Shortcuts (Ctrl+K): Shows this shortcut table.\n"
            "• About PlanForge: Version, credits, and link to docs/interoperability.md.\n\n"
            "Toolbar (top of window, under title):\n"
            "• PlanForge label (left) + New / Open / Save / Import / Export / Recalculate buttons (same as menus, but one click).\n"
            "• Quick Convert (bold blue, if visible): Jumps to Convert tab for one-stop conversion.\n"
            "• Theme selector (right): Cycles through the built-in themes; choose a specific theme in View → Theme.\n\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+N  New   | Ctrl+O  Open   | Ctrl+S  Save   | Ctrl+Shift+S  Save As\n"
            "  Ctrl+Z  Undo | Ctrl+Y  Redo | Ctrl+I  Import | Ctrl+E  Export | F5  Recalculate | Ctrl+T  Cycle theme\n"
            "  Ctrl+1..Ctrl+0  Jump to tab 1..10   | Ctrl+Q  Quit | F1  Help | Ctrl+K  Shortcuts\n"
            "  Ctrl+Shift+P  Command Palette (macOS: use Command instead of Ctrl)\n"
            "  New/Open/Save/Undo/Redo letters can be changed in Tools → Preferences.\n"
            "  In Tasks: Double-click or Enter = Edit | Delete key = Delete | Search box filters live\n"
            "  In People/Estimates: Double-click = Edit\n\n"
            "Status bar (bottom): Shows file path (or 'Not saved yet'), task count, finish date, and 'Unsaved changes' vs 'All changes saved'."
        ),
    ),
    (
        "status",
        "Status & Dirty Handling",
        (
            "Window title shows project name plus ' *' when unsaved (dirty). Status bar at bottom shows:\n"
            "• File location (or 'Not saved to a file yet')\n"
            "• Task count\n"
            "• Finish date or 'not scheduled'\n"
            "• 'Unsaved changes' vs 'All changes saved'\n\n"
            "Whenever you try to New/Open/Import/Quit with unsaved changes, PlanForge asks: Save? Yes/No/Cancel. "
            "Yes = Save then continue, No = discard and continue, Cancel = stay. This protects against accidental loss."
        ),
    ),
    (
        "faq",
        "FAQ & Troubleshooting",
        (
            "Q: I imported a .pod or .mpp and got an error.\n"
            "A: Those are binary proprietary formats. PlanForge detects them and tells you how to export XML from ProjectLibre/MS Project first. Follow those steps.\n\n"
            "Q: My GanttProject .gan lost resources.\n"
            "A: Check that resources have names in GanttProject; unnamed resources are skipped. Re-export after naming them.\n\n"
            "Q: Dates are wrong by one day.\n"
            "A: Check Settings → Working days. If weekends are off but your project includes Saturday work, enable them and Recalculate.\n\n"
            "Q: Import succeeded but preview shows warnings.\n"
            "A: Warnings are non-blocking (e.g. unknown fields stored in extensions). Errors block import. Read the Messages section and fix in source app if needed.\n\n"
            "Q: Export says destination already exists.\n"
            "A: Use Overwrite (dialog asks) or choose a new path. Export is atomic — your old file is not corrupted if export fails.\n\n"
            "Q: CSV import mapped wrong columns.\n"
            "A: Ensure header row uses recognisable names (Task, Name, Start, Finish, Duration, etc.). PlanForge does fuzzy matching; override via column mapping if needed (see csv_adapter.py docs).\n\n"
            "Q: Costs are zero.\n"
            "A: Assign a Person to each Task (Task editor → Assigned person) and ensure that person has a rate (>0).\n\n"
            "Q: I want to automate conversions.\n"
            "A: Use CLI: ./bin/planforge --import-file in.xml --export-file out.gan --export-format ganttproject. Run --help for all formats.\n\n"
            "Q: Where are my files?\n"
            "A: Default suggestions go to your home folder. Use Browse… to pick Downloads, Documents, etc. After Convert, click 'Show in folder' to reveal.\n\n"
            "Still stuck? Open docs/interoperability.md for full spec or file an issue with the file (redact sensitive data)."
        ),
    ),
    (
        "about",
        "About & Credits",
        (
            "PlanForge — Project Planner & Schedule Manager. Offline, no server, no browser. Python + Tkinter. "
            "Integrates the Simple Function Point Calculator (fp_logic.py) so both tools produce identical effort/cost.\n\n"
            "Key docs: README.md (quick start), docs/launcher.md (install), docs/interoperability.md (format specs), schemas/planforge-project-v1.schema.json.\n\n"
            "Launcher: PlanForgeLauncher.py detects OS, creates .venv, installs requirements.txt, and starts the app.\n\n"
            "No third-party runtime dependencies (Tkinter ships with python.org installers; on Linux install python3-tk).\n\n"
            "Tip: This help text is inside the app so it works offline — no internet needed."
        ),
    ),
]

HELP_INDEX = [(sid, title) for sid, title, _body in HELP_SECTIONS]
HELP_BODY = {sid: body for sid, _title, body in HELP_SECTIONS}
HELP_TITLES = {sid: title for sid, title, _body in HELP_SECTIONS}


class HelpView(BaseView):
    """Rich, offline help that explains every tab, button and conversion step."""

    def _build(self) -> None:
        # Title
        self._title("Help & User Guide", "Everything about the top tabs, buttons, and file conversions.")
        # Top quick-action bar
        bar = self._toolbar()
        ttk.Button(bar, text="Open Convert Tab", style="Accent.TButton", command=self._go_convert).pack(side="left")
        ttk.Button(bar, text="Keyboard Shortcuts", command=self._show_shortcuts).pack(side="left", padx=6)
        ttk.Button(bar, text="Show About", command=self._show_about).pack(side="left")
        ttk.Label(bar, text="Tip: F1 opens this help  •  Ctrl+1..0 jumps tabs", style="Muted.TLabel").pack(side="right")

        # Main split: navigation + content
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Left navigation
        nav_frame = ttk.LabelFrame(body, text="Sections", padding=8)
        nav_frame.grid(row=0, column=0, sticky="ns", padx=(0, 10), pady=(8, 0))
        nav_frame.rowconfigure(0, weight=1)

        # Search/filter
        self.search_var = tk.StringVar()
        search_row = ttk.Frame(nav_frame)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Filter:", style="Panel.TLabel").pack(side="left")
        entry = ttk.Entry(search_row, textvariable=self.search_var, width=18)
        entry.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(search_row, text="Clear", command=lambda: self.search_var.set("")).pack(side="left")
        self.search_var.trace_add("write", lambda *_a: self._filter_nav())

        # Listbox with scrollbar
        list_frame = ttk.Frame(nav_frame)
        list_frame.pack(fill="both", expand=True)
        self.nav_list = tk.Listbox(list_frame, height=16, width=30, exportselection=False, relief="flat", borderwidth=0)
        self.nav_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.nav_list.yview)
        scroll.pack(side="right", fill="y")
        self.nav_list.configure(yscrollcommand=scroll.set)
        self.nav_list.bind("<<ListboxSelect>>", self._on_nav_select)
        # Populate
        self._all_items: list[tuple[str, str]] = HELP_INDEX.copy()
        self._filtered: list[tuple[str, str]] = self._all_items.copy()
        self._fill_nav()

        # Buttons under nav
        ttk.Button(nav_frame, text="Go to Overview", command=lambda: self._jump_tab("overview")).pack(fill="x", pady=(8, 2))
        ttk.Button(nav_frame, text="Go to Tasks", command=lambda: self._jump_tab("tasks")).pack(fill="x", pady=2)
        ttk.Button(nav_frame, text="Go to Timeline", command=lambda: self._jump_tab("timeline")).pack(fill="x", pady=2)
        ttk.Button(nav_frame, text="Go to People", command=lambda: self._jump_tab("people")).pack(fill="x", pady=2)
        ttk.Button(nav_frame, text="Go to Convert", style="Accent.TButton", command=self._go_convert).pack(fill="x", pady=(6, 2))

        # Right content: scrollable text
        content_frame = ttk.LabelFrame(body, text="Guide", padding=8)
        content_frame.grid(row=0, column=1, sticky="nsew", pady=(8, 0))
        content_frame.rowconfigure(0, weight=1)
        content_frame.columnconfigure(0, weight=1)

        self.text = tk.Text(content_frame, wrap="word", relief="flat", borderwidth=0, padx=10, pady=8, state="disabled", font=("Helvetica", 10))
        # Use tk scrollbar via ttk
        y_scroll = ttk.Scrollbar(content_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=y_scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(content_frame, orient="horizontal", command=self.text.xview)
        # Text xview is needed for horizontal; but wrap word so not crucial - still pack for completeness
        # self.text.configure(xscrollcommand=x_scroll.set)
        # x_scroll.grid(row=1, column=0, sticky="ew")

        # Prepare tags
        self._setup_tags()

        # Initial selection
        if self._filtered:
            self.nav_list.selection_set(0)
            self._show_section(self._filtered[0][0])

    def _setup_tags(self) -> None:
        p = self.app.palette
        self.text.tag_configure("heading", font=("Helvetica", 14, "bold"), foreground=p["text"], spacing1=10, spacing3=6)
        self.text.tag_configure("sub", font=("Helvetica", 10), foreground=p["text"], spacing1=4, spacing3=8)
        self.text.tag_configure("bullet", lmargin1=18, lmargin2=32, spacing1=2)
        self.text.tag_configure("tip", font=("Helvetica", 10, "italic"), foreground=p["muted"], spacing1=6)
        self.text.tag_configure("table", font=("Courier", 9), spacing1=6, spacing3=6)

    def _fill_nav(self) -> None:
        self.nav_list.delete(0, "end")
        for _sid, title in self._filtered:
            self.nav_list.insert("end", title)

    def _filter_nav(self) -> None:
        needle = self.search_var.get().strip().casefold()
        if not needle:
            self._filtered = self._all_items.copy()
        else:
            self._filtered = [(sid, title) for sid, title in self._all_items if needle in title.casefold() or needle in HELP_BODY[sid].casefold()]
        self._fill_nav()
        if self._filtered:
            self.nav_list.selection_clear(0, "end")
            self.nav_list.selection_set(0)
            self._show_section(self._filtered[0][0])
        else:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", "No matching sections. Clear the filter to see all topics.", ("sub",))
            self.text.configure(state="disabled")

    def _on_nav_select(self, _event=None) -> None:
        sel = self.nav_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._filtered):
            sid = self._filtered[idx][0]
            self._show_section(sid)

    def _show_section(self, sid: str) -> None:
        title = HELP_TITLES.get(sid, sid)
        body = HELP_BODY.get(sid, "")
        p = self.app.palette
        self.text.configure(state="normal", background=p["panel"], foreground=p["text"], insertbackground=p["text"])
        self.text.delete("1.0", "end")
        # Heading
        self.text.insert("end", title + "\n", ("heading",))
        self.text.insert("end", "—" * len(title) + "\n\n", ("tip",))
        # Body: simple formatting – split by lines, detect bullets/tables
        for line in body.split("\n"):
            stripped = line.strip()
            if not stripped:
                self.text.insert("end", "\n")
            elif stripped.startswith("•") or stripped.startswith("- ") or stripped.startswith("  •"):
                self.text.insert("end", line + "\n", ("bullet",))
            elif line.startswith("  ") and ("|" in line or ":" in line and len(line) < 80):
                self.text.insert("end", line + "\n", ("table",))
            else:
                self.text.insert("end", line + "\n", ("sub",))
        # Footer nav hints
        self.text.insert("end", "\n—\n", ("tip",))
        self.text.insert("end", "Tip: Use the left list to jump to any section. Search filters live.", ("tip",))
        self.text.configure(state="disabled")
        self.text.see("1.0")

    def _jump_tab(self, key: str) -> None:
        # Delegate to app
        try:
            idx = next(i for i, (k, _lbl, _cls) in enumerate(self.app.VIEWS if hasattr(self.app, "VIEWS") else [] ) if k == key)
        except StopIteration:
            # Fallback: try views dict order
            keys = list(self.app.views.keys())
            if key in keys:
                idx = keys.index(key)
            else:
                return
        self.app.notebook.select(idx)

    def _go_convert(self) -> None:
        # Find convert tab if exists
        keys = list(self.app.views.keys())
        if "convert" in keys:
            self.app.notebook.select(keys.index("convert"))
        else:
            messagebox.showinfo("Convert", "Use File → Export/Import or see the Convert guide in this help.", parent=self.app)

    def _show_shortcuts(self) -> None:
        body = HELP_BODY.get("menus_toolbar", "")
        # Show in dialog with scroll
        win = tk.Toplevel(self.app)
        win.title("Keyboard Shortcuts")
        win.transient(self.app)
        win.resizable(True, True)
        win.geometry("640x520")
        txt = tk.Text(win, wrap="word", padx=12, pady=8, font=("Helvetica", 10))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        scroll = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        txt.insert("1.0", "Keyboard Shortcuts & Toolbar\n========================\n\n" + body)
        txt.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)
        win.grab_set()
        win.focus_set()

    def _show_about(self) -> None:
        self.app.show_about()

    def refresh(self) -> None:
        # Keep current section but re-apply palette
        p = self.app.palette
        self.text.configure(background=p["panel"], foreground=p["text"])
        self.nav_list.configure(background=p["panel"], foreground=p["text"], selectbackground=p["accent"], selectforeground=p["accent_text"], highlightthickness=0)
        # re-setup tags colors
        self.text.tag_configure("heading", foreground=p["text"])
        self.text.tag_configure("sub", foreground=p["text"])
        self.text.tag_configure("tip", foreground=p["muted"])

    def on_show(self) -> None:
        self.refresh()

__all__ = ["HelpView", "HELP_SECTIONS"]
