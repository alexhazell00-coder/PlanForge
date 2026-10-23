"""The workspace tabs: Overview, Tasks, People, Costs, Function Points, Report and Settings.

The Timeline tab lives in ``planforge.gui.timeline``. Each view reads from the
shared ``ProjectSession`` in ``refresh()`` and writes through ``app.perform()``,
which reports errors in a message box and then refreshes every view.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any, Callable

from planforge import estimation
from planforge.config import format_date, get_preference, parse_date_input, set_preference
from planforge.gui.dialogs import FormDialog, FormField, ResourceDialog, TaskDialog
from planforge.session import WEEKDAY_NAMES, SessionError, format_money

if TYPE_CHECKING:  # pragma: no cover
    from planforge.gui.app import PlanForgeApp

fp_logic = estimation.fp_logic


class BaseView(ttk.Frame):
    """Common setup for every tab."""

    def __init__(self, parent: tk.Misc, app: PlanForgeApp) -> None:
        super().__init__(parent, padding=16)
        self.app = app
        self.session = app.session
        self._build()

    def _build(self) -> None:  # pragma: no cover - overridden
        pass

    def refresh(self) -> None:  # pragma: no cover - overridden
        pass

    def on_show(self) -> None:
        """Called when the tab is selected. Defaults to a plain refresh."""
        self.refresh()

    def _title(self, text: str, subtitle: str = "") -> ttk.Label:
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text=text, style="Title.TLabel").pack(side="left")
        if subtitle:
            ttk.Label(header, text=subtitle, style="Muted.TLabel").pack(side="left", padx=(12, 0))
        return header

    def _toolbar(self) -> ttk.Frame:
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        return bar


def make_tree(parent: tk.Misc, columns: list[tuple[str, str, int, str]], *, tree_heading: str | None = None,
              tree_width: int = 0, height: int = 12) -> ttk.Treeview:
    """Create a Treeview with a scrollbar. Columns are (id, heading, width, anchor)."""
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    show = "tree headings" if tree_heading else "headings"
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show=show, height=height, selectmode="browse")
    if tree_heading:
        tree.heading("#0", text=tree_heading, anchor="w")
        tree.column("#0", width=tree_width, minwidth=120, stretch=True)
    for col_id, heading, width, anchor in columns:
        tree.heading(col_id, text=heading, anchor=anchor)
        tree.column(col_id, width=width, minwidth=60, anchor=anchor, stretch=col_id == columns[-1][0])
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return tree


def _iso(value: date | None) -> str:
    return format_date(value)


def _num(values: dict[str, str], key: str, label: str, *, minimum: float | None = None,
         strict: bool = False) -> float:
    try:
        number = float(values[key].strip())
    except (KeyError, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if minimum is not None and (number < minimum or (strict and number == minimum)):
        comparison = "greater than zero" if strict else "zero or more"
        raise ValueError(f"{label} must be {comparison}.")
    return number


# ----------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------

class OverviewView(BaseView):
    def _build(self) -> None:
        self.subtitle = self._title("Project Overview")
        self.project_label = ttk.Label(self, style="Muted.TLabel")
        self.project_label.pack(anchor="w", pady=(0, 8))
        self._suggestions_enabled = get_preference("workspace", "show_suggestions", "true").casefold() not in ("false", "0", "no")
        self._dismissed_suggestions = set(filter(None, get_preference("workspace", "dismissed_suggestions", "").split(",")))
        self.suggestions_box = ttk.LabelFrame(self, text="Suggested next steps", padding=(10, 6))
        self.suggestions_box.pack(fill="x", pady=(0, 10))
        self.suggestions = ttk.Frame(self.suggestions_box)
        self.suggestions.pack(side="left", fill="x", expand=True)
        self.suggestions_toggle = ttk.Button(self.suggestions_box, text="Hide", command=self._toggle_suggestions)
        self.suggestions_toggle.pack(side="right", padx=(8, 0))

        cards = ttk.Frame(self)
        cards.pack(fill="x")
        self.metrics: dict[str, tk.StringVar] = {}
        for index, caption in enumerate(["Tasks", "Milestones", "Dependencies", "Team members",
                                         "Estimated hours", "Estimated cost"]):
            card = ttk.Frame(cards, style="Card.TFrame", padding=(14, 10))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            cards.columnconfigure(index, weight=1)
            var = tk.StringVar(value="0")
            self.metrics[caption] = var
            ttk.Label(card, textvariable=var, style="Metric.TLabel").pack(anchor="w")
            ttk.Label(card, text=caption, style="PanelMuted.TLabel").pack(anchor="w")

        lists = ttk.Frame(self)
        lists.pack(fill="both", expand=True, pady=(16, 0))
        lists.columnconfigure(0, weight=3)
        lists.columnconfigure(1, weight=2)

        critical_box = ttk.LabelFrame(lists, text="Critical path (zero float)", padding=10)
        critical_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.critical = make_tree(critical_box, [
            ("start", "Start", 100, "w"), ("finish", "Finish", 100, "w"),
            ("duration", "Duration", 80, "e"),
        ], tree_heading="Task", tree_width=300, height=10)

        team_box = ttk.LabelFrame(lists, text="Team & material costs", padding=10)
        team_box.grid(row=0, column=1, sticky="nsew")
        self.team = make_tree(team_box, [
            ("tasks", "Tasks", 60, "e"), ("hours", "Hours / Qty", 90, "e"), ("cost", "Cost", 110, "e"),
        ], tree_heading="Resource", tree_width=200, height=10)
        lists.rowconfigure(0, weight=1)

    def _toggle_suggestions(self) -> None:
        self._suggestions_enabled = not self._suggestions_enabled
        try:
            set_preference("workspace", "show_suggestions", str(self._suggestions_enabled).lower())
        except OSError:
            pass
        self._refresh_suggestions()

    def _dismiss_suggestion(self, suggestion_id: str) -> None:
        self._dismissed_suggestions.add(suggestion_id)
        try:
            set_preference("workspace", "dismissed_suggestions", ",".join(sorted(self._dismissed_suggestions)))
        except OSError:
            pass
        self._refresh_suggestions()

    def _refresh_suggestions(self) -> None:
        for child in self.suggestions.winfo_children():
            child.destroy()
        if not self._suggestions_enabled:
            self.suggestions_toggle.configure(text="Show")
            ttk.Label(self.suggestions, text="Suggestions are hidden. Show them when useful.",
                      style="Muted.TLabel").pack(anchor="w")
            return
        self.suggestions_toggle.configure(text="Hide")
        session = self.session
        actions: list[tuple[str, str, Callable[[], Any]]] = []
        if not session.project.tasks:
            actions.append(("first_task", "Add your first task", lambda: self.app._run_view_action("tasks", "_add")))
        if session.dirty:
            actions.append(("save", "Save unsaved project changes", self.app.save_project))
        if not session.project.resources:
            actions.append(("team", "Add a team member", lambda: self.app._run_view_action("people", "_add")))
        elif session.project.tasks and not session.project.assignments:
            actions.append(("assignments", "Review task assignments", lambda: self.app.select_tab_by_key("tasks")))
        if len(session.project.tasks) > 1 and not session.project.dependencies:
            actions.append(("dependencies", "Review task dependencies", lambda: self.app.select_tab_by_key("tasks")))
        actions = [item for item in actions if item[0] not in self._dismissed_suggestions][:3]
        if not actions:
            ttk.Label(self.suggestions, text="Everything looks in order — no suggested actions right now.",
                      style="Muted.TLabel").pack(anchor="w")
            return
        for suggestion_id, text, action in actions:
            row = ttk.Frame(self.suggestions)
            row.pack(fill="x", pady=2)
            ttk.Button(row, text=text, command=action).pack(side="left")
            ttk.Button(row, text="Dismiss", command=lambda key=suggestion_id: self._dismiss_suggestion(key)).pack(side="left", padx=6)

    def refresh(self) -> None:
        self._refresh_suggestions()
        ov = self.session.overview()
        self.project_label.configure(text=(
            f"{ov.name}   ·   {_iso(ov.start_date) or 'Start not set'} to {_iso(ov.finish_date) or 'finish not set'}"
        ))
        self.metrics["Tasks"].set(str(ov.task_count))
        self.metrics["Milestones"].set(str(ov.milestone_count))
        self.metrics["Dependencies"].set(str(ov.dependency_count))
        self.metrics["Team members"].set(str(ov.resource_count))
        self.metrics["Estimated hours"].set(f"{ov.total_hours:,.1f}")
        self.metrics["Estimated cost"].set(format_money(ov.total_cost, ov.currency))

        self.critical.delete(*self.critical.get_children())
        for task in ov.critical_tasks:
            self.critical.insert("", "end", text=task.name, values=(
                _iso(task.start_date), _iso(task.finish_date), f"{(task.duration or 0):g} d",
            ))
        if not ov.critical_tasks:
            self.critical.insert("", "end", text="No critical tasks found", values=("", "", ""))

        self.team.delete(*self.team.get_children())
        for w in self.session.person_workloads():
            usage = (
                f"{w.units_total:g}" + (f" {w.material_label}" if w.material_label else "")
                if w.resource_type != "work"
                else f"{w.hours:,.1f} h"
            )
            self.team.insert("", "end", text=w.name, values=(
                w.task_count, usage, format_money(w.cost, ov.currency),
            ))


# ----------------------------------------------------------------------
# Tasks
# ----------------------------------------------------------------------

class TasksView(BaseView):
    def _build(self) -> None:
        self._title("Tasks & Hierarchy", "Double-click a task to edit it.")
        bar = self._toolbar()
        self.search_var = tk.StringVar()
        search = ttk.Entry(bar, textvariable=self.search_var, width=28)
        self.search_entry = search
        search.pack(side="left")
        ttk.Label(bar, text="  Search", style="Muted.TLabel").pack(side="left", before=search)
        self.search_var.trace_add("write", lambda *_a: self.refresh())
        for text, command in [
            ("Indent", self._indent),
            ("Outdent", self._outdent),
            ("+ Milestone", lambda: self._add(milestone=True)),
            ("Edit", self._edit),
            ("Delete", self._delete),
        ]:
            ttk.Button(bar, text=text, command=command).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="+ Task", style="Accent.TButton", command=self._add).pack(side="right", padx=(6, 0))
        self.empty_label = ttk.Label(self, text="", style="Muted.TLabel")
        self.empty_label.pack(anchor="w", pady=(0, 4))

        self._task_column_ids = ("duration", "start", "finish", "progress", "predecessor", "people", "cost")
        self._task_column_labels = ("Duration", "Start", "Finish", "Done", "Predecessor", "Person", "Cost")
        self.tree = make_tree(self, [
            ("duration", "Duration", 90, "e"), ("start", "Start", 100, "w"), ("finish", "Finish", 100, "w"),
            ("progress", "Done", 60, "e"), ("predecessor", "Predecessor", 200, "w"),
            ("people", "Person", 180, "w"), ("cost", "Cost", 100, "e"),
        ], tree_heading="Task", tree_width=340, height=18)
        saved_hidden = set(get_preference("workspace", "hidden_task_columns", "").split(","))
        self._column_vars = {key: tk.BooleanVar(value=key not in saved_hidden)
                             for key in self._task_column_ids}
        self.columns_menu = tk.Menu(self, tearoff=False)
        for key, label in zip(self._task_column_ids, self._task_column_labels):
            self.columns_menu.add_checkbutton(label=label, variable=self._column_vars[key],
                                              command=self._apply_task_columns)
        ttk.Menubutton(bar, text="Columns ▾", menu=self.columns_menu).pack(side="left", padx=(8, 0))
        self._apply_task_columns(save=False)
        self.tree.bind("<Double-1>", lambda _e: self._edit())
        self.tree.bind("<Return>", lambda _e: self._edit())
        self.tree.bind("<Delete>", lambda _e: self._delete())
        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Edit Task…", command=self._edit)
        self.context_menu.add_command(label="Add Subtask…", command=self._add_subtask)
        self.context_menu.add_command(label="Edit Dependencies / Assignment…", command=self._edit)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete Task…", command=self._delete)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Control-Button-1>", self._show_context_menu)

    def _apply_task_columns(self, save: bool = True) -> None:
        visible = [key for key in self._task_column_ids if self._column_vars[key].get()]
        self.tree.configure(displaycolumns=visible)
        if save:
            hidden = [key for key in self._task_column_ids if key not in visible]
            try:
                set_preference("workspace", "hidden_task_columns", ",".join(hidden))
            except OSError:
                self.app.status_var.set("Task columns changed for this session, but the preference could not be saved.")

    def _selected(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _require_selection(self) -> str | None:
        task_id = self._selected()
        if task_id is None:
            messagebox.showinfo("Select a task", "Select a task first.", parent=self.app)
        return task_id

    def _add(self, milestone: bool = False) -> None:
        created: list[str] = []

        def action() -> None:
            task = self.session.add_task("Milestone" if milestone else "New task", milestone=milestone)
            created.append(task.id)

        if self.app.perform(action) and created:
            self.tree.selection_set(created[0])
            self.tree.focus(created[0])
            self._open_editor(created[0])

    def _show_context_menu(self, event: tk.Event) -> str:
        row = self.tree.identify_row(event.y)
        if not row:
            return "break"
        self.tree.selection_set(row)
        self.tree.focus(row)
        self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()
        return "break"

    def _add_subtask(self) -> None:
        parent_id = self._require_selection()
        if not parent_id:
            return
        created: list[str] = []

        def action() -> None:
            task = self.session.add_task("New subtask", parent_id=parent_id)
            created.append(task.id)

        if self.app.perform(action) and created:
            self.tree.selection_set(created[0])
            self.tree.focus(created[0])
            self._open_editor(created[0])

    def select_task_by_id(self, task_id: str) -> None:
        self.search_var.set("")
        self.refresh()
        if self.tree.exists(task_id):
            self.tree.selection_set(task_id)
            self.tree.focus(task_id)
            self.tree.see(task_id)

    def edit_task_by_id(self, task_id: str) -> None:
        self.app.select_tab_by_key("tasks")
        self.select_task_by_id(task_id)
        if self.tree.exists(task_id):
            self._open_editor(task_id)

    def _indent(self) -> None:
        task_id = self._require_selection()
        if task_id:
            self.app.perform(self.session.indent_task, task_id)

    def _outdent(self) -> None:
        task_id = self._require_selection()
        if task_id:
            self.app.perform(self.session.outdent_task, task_id)

    def _edit(self) -> None:
        task_id = self._require_selection()
        if task_id:
            self._open_editor(task_id)

    def _open_editor(self, task_id: str) -> None:
        try:
            dialog = TaskDialog(self.app, self.session, task_id)
        except SessionError as exc:
            messagebox.showerror("PlanForge", str(exc), parent=self.app)
            return
        dialog.show()  # the dialog saves through the session; refresh the views either way
        self.app.refresh_all()

    def _delete(self) -> None:
        task_id = self._require_selection()
        if not task_id:
            return
        task = self.session.find_task(task_id)
        if messagebox.askyesno("Delete task", f"Delete '{task.name}'?", parent=self.app):
            self.app.perform(self.session.delete_task, task_id)

    def refresh(self) -> None:
        p = self.app.palette
        selected = self._selected()
        self.tree.tag_configure("summary", font=("Helvetica", 10, "bold"))
        self.tree.tag_configure("critical", foreground=p["danger"])
        self.tree.tag_configure("milestone", foreground=p["milestone"])
        self.tree.delete(*self.tree.get_children())

        needle = self.search_var.get().strip().casefold()
        rows = self.session.task_rows()
        visible_count = 0
        for row in rows:
            task = row.task
            if needle and needle not in task.name.casefold():
                continue
            tags = []
            if row.is_summary:
                tags.append("summary")
            if task.custom_fields.get("is_critical"):
                tags.append("critical")
            if task.milestone or task.task_type == "milestone":
                tags.append("milestone")
            duration = "milestone" if (task.milestone or task.task_type == "milestone") else f"{(task.duration or 0):g} d"
            res_summary = self.session.task_resource_names(task.id)
            cost = format_money(task.estimated_cost, self.session.project.currency) if task.estimated_cost else ""
            # With a search active the list is flat, so indentation is shown in the name instead.
            parent = task.parent_id if (task.parent_id and not needle) else ""
            text = task.name if not needle else "    " * row.depth + task.name
            self.tree.insert(parent, "end", iid=task.id, text=text, open=True, tags=tuple(tags), values=(
                duration, _iso(task.start_date), _iso(task.finish_date),
                f"{task.percent_complete:.0f}%", self.session.predecessor_names(task.id),
                res_summary, cost,
            ))
            visible_count += 1
        if not visible_count:
            self.empty_label.configure(text=("No tasks match this search." if rows else
                                             "No tasks yet — add a task or milestone to start planning."))
        else:
            self.empty_label.configure(text="")
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)


# ----------------------------------------------------------------------
# People & Materials (Resource Sheet)
# ----------------------------------------------------------------------

class PeopleView(BaseView):
    def _build(self) -> None:
        self._title(
            "People & Materials",
            "Team roles (Work) and equipment/consumables (Material) with hierarchy, units and rates.",
        )
        bar = self._toolbar()
        ttk.Button(bar, text="+ Add Person", style="Accent.TButton", command=self._add).pack(side="left")
        ttk.Button(bar, text="+ Add Material", command=self._add_material).pack(side="left", padx=6)
        ttk.Button(bar, text="Indent", command=self._indent).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Outdent", command=self._outdent).pack(side="left", padx=6)
        ttk.Button(bar, text="Edit", command=self._edit).pack(side="left")
        ttk.Button(bar, text="Delete", command=self._delete).pack(side="left", padx=(6, 0))
        self.empty_label = ttk.Label(self, text="", style="Muted.TLabel")
        self.empty_label.pack(anchor="w", pady=(0, 4))
        self.tree = make_tree(self, [
            ("role", "Role / Group", 190, "w"),
            ("type", "Type", 85, "w"),
            ("material_label", "Material Label", 105, "w"),
            ("initials", "Initials", 65, "w"),
            ("max_units", "Max. Units", 90, "e"),
            ("rate", "Standard Rate", 130, "e"),
            ("tasks", "Tasks", 65, "e"),
            ("cost", "Total Cost", 120, "e"),
        ], tree_heading="Resource Name", tree_width=260, height=16)
        self.tree.bind("<Double-1>", lambda _e: self._edit())
        self.tree.bind("<Return>", lambda _e: self._edit())
        self.tree.bind("<Delete>", lambda _e: self._delete())
        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Edit Resource…", command=self._edit)
        self.context_menu.add_command(label="Add Sub-item (Person)…", command=lambda: self._add(under_selected=True))
        self.context_menu.add_command(label="Add Sub-item (Material)…", command=lambda: self._add_material(under_selected=True))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Indent", command=self._indent)
        self.context_menu.add_command(label="Outdent", command=self._outdent)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Remove Resource…", command=self._delete)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Control-Button-1>", self._show_context_menu)

    def _show_context_menu(self, event: tk.Event) -> str:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.context_menu.tk_popup(event.x_root, event.y_root)
            self.context_menu.grab_release()
        return "break"

    def _selected(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _add(self, *, under_selected: bool = False) -> None:
        parent_id = self._selected() if under_selected else None
        dialog = ResourceDialog(self.app, self.session, default_type="work", default_parent_id=parent_id)
        if dialog.show():
            self.app.refresh_all()

    def _add_material(self, *, under_selected: bool = False) -> None:
        parent_id = self._selected() if under_selected else None
        dialog = ResourceDialog(self.app, self.session, default_type="material", default_parent_id=parent_id)
        if dialog.show():
            self.app.refresh_all()

    def _indent(self) -> None:
        resource_id = self._selected()
        if resource_id is None:
            messagebox.showinfo("Select a resource", "Select a person or material first.", parent=self.app)
            return
        self.app.perform(self.session.indent_resource, resource_id)

    def _outdent(self) -> None:
        resource_id = self._selected()
        if resource_id is None:
            messagebox.showinfo("Select a resource", "Select a person or material first.", parent=self.app)
            return
        self.app.perform(self.session.outdent_resource, resource_id)

    def _edit(self) -> None:
        resource_id = self._selected()
        if resource_id is None:
            messagebox.showinfo("Select a resource", "Select a person or material first.", parent=self.app)
            return
        dialog = ResourceDialog(self.app, self.session, resource_id=resource_id)
        if dialog.show():
            self.app.refresh_all()

    def _delete(self) -> None:
        resource_id = self._selected()
        if resource_id is None:
            return
        resource = self.session.find_resource(resource_id)
        if messagebox.askyesno("Delete resource", f"Remove {resource.name}? Any assignments for it will be removed too.",
                               parent=self.app):
            self.app.perform(self.session.delete_person, resource_id)

    def refresh(self) -> None:
        p = self.app.palette
        selected = self._selected()
        self.tree.tag_configure("summary", font=("Helvetica", 10, "bold"))
        self.tree.tag_configure("material", foreground=p.get("accent", p["text"]))
        self.tree.delete(*self.tree.get_children())
        currency = self.session.project.currency
        workloads = self.session.person_workloads()
        for w in workloads:
            is_material = w.resource_type != "work"
            type_label = "Material" if w.resource_type == "material" else ("Cost" if w.resource_type == "cost" else "Work")
            max_u = "" if is_material else f"{w.max_units * 100:.0f}%"
            if w.rate is None:
                rate_str = "not set"
            elif is_material:
                rate_str = format_money(w.rate, currency)
            else:
                rate_str = f"{format_money(w.rate, currency)}/hour"
            tags: list[str] = []
            if w.is_summary:
                tags.append("summary")
            if is_material:
                tags.append("material")
            parent_iid = w.parent_id if (w.parent_id and self.tree.exists(w.parent_id)) else ""
            self.tree.insert(parent_iid, "end", iid=w.resource_id, text=w.name, open=True, tags=tuple(tags), values=(
                w.group,
                type_label,
                w.material_label if is_material else "",
                w.initials,
                max_u,
                rate_str,
                w.task_count,
                format_money(w.cost, currency),
            ))
        self.empty_label.configure(
            text="" if workloads else "No resources yet — add a person or material item to plan workload and costs."
        )
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)


# ----------------------------------------------------------------------
# Costs & workload
# ----------------------------------------------------------------------

class CostsView(BaseView):
    def _build(self) -> None:
        self._title("Costs & Workload Analysis", "Labour (hourly work) and Material (unit/equipment) cost breakdown.")
        cards = ttk.Frame(self)
        cards.pack(fill="x")
        self.cards: dict[str, tk.StringVar] = {}
        for index, caption in enumerate([
            "Estimated task cost",
            "Assigned labour cost",
            "Material cost",
            "Estimated task hours",
        ]):
            card = ttk.Frame(cards, style="Card.TFrame", padding=(14, 10))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            cards.columnconfigure(index, weight=1)
            var = tk.StringVar(value="")
            self.cards[caption] = var
            ttk.Label(card, textvariable=var, style="Metric.TLabel").pack(anchor="w")
            ttk.Label(card, text=caption, style="PanelMuted.TLabel").pack(anchor="w")

        self.tree = make_tree(self, [
            ("type", "Type", 85, "w"),
            ("rate", "Standard Rate", 125, "e"),
            ("tasks", "Tasks", 65, "e"),
            ("usage", "Hours / Qty", 110, "e"),
            ("cost", "Cost", 120, "e"),
            ("share", "Share", 75, "e"),
        ], tree_heading="Resource", tree_width=240, height=8)

        chart_box = ttk.LabelFrame(self, text="Cost by resource (people & materials)", padding=8)
        chart_box.pack(fill="both", expand=True, pady=(12, 0))
        self.chart = tk.Canvas(chart_box, height=180, highlightthickness=0)
        self.chart.pack(fill="both", expand=True)
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())
        self._workloads: list = []

    def refresh(self) -> None:
        currency = self.session.project.currency
        ov = self.session.overview()
        self.cards["Estimated task cost"].set(format_money(ov.total_cost, currency))
        self.cards["Estimated task hours"].set(f"{ov.total_hours:,.1f} h")
        self._workloads = self.session.person_workloads()
        labour_cost = sum(w.cost for w in self._workloads if w.resource_type == "work")
        material_cost = sum(w.cost for w in self._workloads if w.resource_type != "work")
        total_cost = labour_cost + material_cost
        self.cards["Assigned labour cost"].set(format_money(labour_cost, currency))
        self.cards["Material cost"].set(format_money(material_cost, currency))

        self.tree.delete(*self.tree.get_children())
        for w in self._workloads:
            is_material = w.resource_type != "work"
            type_lbl = "Material" if w.resource_type == "material" else ("Cost" if w.resource_type == "cost" else "Work")
            rate_txt = (
                "not set"
                if w.rate is None
                else (format_money(w.rate, currency) if is_material else f"{format_money(w.rate, currency)}/hour")
            )
            usage_txt = (
                f"{w.units_total:g}" + (f" {w.material_label}" if w.material_label else "")
                if is_material
                else f"{w.hours:,.1f} h"
            )
            share = (w.cost / total_cost * 100) if total_cost else 0.0
            self.tree.insert("", "end", text=w.name, values=(
                type_lbl,
                rate_txt,
                w.task_count,
                usage_txt,
                format_money(w.cost, currency),
                f"{share:.0f}%",
            ))
        self._draw_chart()

    def _draw_chart(self) -> None:
        p = self.app.palette
        c = self.chart
        c.configure(background=p["panel"])
        c.delete("all")
        width = max(c.winfo_width(), 200)
        if not self._workloads:
            c.create_text(12, 20, text="No people yet.", anchor="w", fill=p["muted"])
            return
        label_w = 180
        bar_area = max(width - label_w - 130, 80)
        top_cost = max((w.cost for w in self._workloads), default=0.0) or 1.0
        row_h = 28
        currency = self.session.project.currency
        for index, w in enumerate(self._workloads):
            y = 10 + index * row_h
            c.create_text(8, y + row_h / 2, text=w.name, anchor="w", fill=p["text"])
            length = bar_area * (w.cost / top_cost)
            c.create_rectangle(label_w, y + 6, label_w + max(length, 2), y + row_h - 6, fill=p["bar_done"], outline="")
            c.create_text(label_w + length + 8, y + row_h / 2, text=format_money(w.cost, currency),
                          anchor="w", fill=p["muted"])
        c.configure(height=max(20 + len(self._workloads) * row_h, 60))


# ----------------------------------------------------------------------
# Function Points estimator
# ----------------------------------------------------------------------

class EstimatorView(BaseView):
    def _build(self) -> None:
        self._title("Function Point Calculator Integration",
                    "Estimates use the same maths as the Simple Function Point Calculator.")
        self.selected: int | None = None
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Estimators", padding=10)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.listbox = tk.Listbox(left, height=14, width=24, exportselection=False, relief="flat", borderwidth=0)
        self.listbox.pack(fill="both", expand=True)
        self.empty_label = ttk.Label(left, text="", style="Muted.TLabel", wraplength=180)
        self.empty_label.pack(anchor="w", pady=(4, 0))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        ttk.Button(left, text="+ Add Estimator", command=self._add_estimator).pack(fill="x", pady=(8, 4))
        ttk.Button(left, text="Remove", style="Danger.TButton", command=self._remove_estimator).pack(fill="x")

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        settings = ttk.LabelFrame(right, text="Estimator settings", padding=10)
        settings.pack(fill="x")
        self.rate_var = tk.StringVar()
        self.complex_var = tk.StringVar()
        self.simple_var = tk.StringVar()
        for col, (caption, var) in enumerate([("Hourly rate", self.rate_var),
                                              ("Hours per complex FP", self.complex_var),
                                              ("Hours per simple FP", self.simple_var)]):
            ttk.Label(settings, text=caption, style="Panel.TLabel").grid(row=0, column=col * 2, sticky="w", padx=(0, 6))
            ttk.Entry(settings, textvariable=var, width=8).grid(row=0, column=col * 2 + 1, sticky="w", padx=(0, 16))
        ttk.Button(settings, text="Save settings", command=self._save_settings).grid(row=0, column=6, sticky="e")

        tasks_box = ttk.LabelFrame(right, text="Estimated tasks", padding=10)
        tasks_box.pack(fill="both", expand=True, pady=(12, 0))
        bar = ttk.Frame(tasks_box)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="+ Task", command=self._add_task).pack(side="left")
        ttk.Button(bar, text="Edit", command=self._edit_task).pack(side="left", padx=6)
        ttk.Button(bar, text="Delete", command=self._delete_task).pack(side="left")
        self.tree = make_tree(tasks_box, [
            ("type", "Type", 80, "w"), ("points", "Points", 80, "e"),
            ("hours", "Hours", 90, "e"), ("cost", "Cost", 110, "e"),
        ], tree_heading="Task", tree_width=280, height=8)
        self.tree.bind("<Double-1>", lambda _e: self._edit_task())

        footer = ttk.Frame(right)
        footer.pack(fill="x", pady=(12, 0))
        self.totals_var = tk.StringVar()
        ttk.Label(footer, textvariable=self.totals_var, style="Heading.TLabel").pack(side="left")
        ttk.Button(footer, text="Transfer to Project Tasks", style="Accent.TButton",
                   command=self._transfer).pack(side="right")
        ttk.Label(right, style="Muted.TLabel", text=(
            "Estimators are kept until you transfer them or close PlanForge. "
            "Transferring adds each estimate as a scheduled task and merges people by name.")
        ).pack(anchor="w", pady=(8, 0))

    # --- helpers
    def _person(self) -> dict | None:
        if self.selected is None or self.selected >= len(self.session.estimators):
            return None
        return self.session.estimators[self.selected]

    def _on_select(self, _event: Any = None) -> None:
        sel = self.listbox.curselection()
        self.selected = sel[0] if sel else None
        self.refresh()

    def _add_estimator(self) -> None:
        def submit(values: dict[str, str]) -> None:
            self.session.add_estimator(values["name"])
            self.selected = len(self.session.estimators) - 1

        if FormDialog(self.app, "Add Estimator", [FormField("name", "Estimator name")], submit).show():
            self.app.refresh_all()

    def _remove_estimator(self) -> None:
        person = self._person()
        if person is None:
            return
        if messagebox.askyesno("Remove estimator", f"Remove {person['name']} and their estimated tasks?",
                               parent=self.app):
            del self.session.estimators[self.selected]
            self.selected = None
            self.app.refresh_all()

    def _save_settings(self) -> None:
        person = self._person()
        if person is None:
            messagebox.showinfo("Add an estimator", "Add or select an estimator first.", parent=self.app)
            return
        try:
            person["hourly_rate"] = fp_logic.parse_positive_number(self.rate_var.get(), "Hourly rate")
            person["hours_per_complex_point"] = fp_logic.parse_positive_number(
                self.complex_var.get(), "Hours per complex function point")
            person["hours_per_simple_point"] = fp_logic.parse_positive_number(
                self.simple_var.get(), "Hours per simple function point")
        except ValueError as exc:
            messagebox.showerror("Check the settings", str(exc), parent=self.app)
            return
        self.refresh()

    def _task_fields(self, name: str = "", task_type: str = "complex", points: str = "") -> list[FormField]:
        return [
            FormField("name", "Feature or task name", name),
            FormField("type", "Complexity", task_type, choices=list(estimation.TASK_TYPES)),
            FormField("points", "Function points (whole number)", points),
        ]

    def _add_task(self) -> None:
        person = self._person()
        if person is None:
            messagebox.showinfo("Add an estimator", "Add an estimator first.", parent=self.app)
            return

        def submit(values: dict[str, str]) -> None:
            points = fp_logic.parse_point_count(values["points"], "Function points")
            person["tasks"].append(fp_logic.clean_task({"name": values["name"], "type": values["type"],
                                                        "points": points}, "Task"))

        if FormDialog(self.app, "Add Estimated Task", self._task_fields(), submit).show():
            self.app.refresh_all()

    def _selected_task_index(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _edit_task(self) -> None:
        person = self._person()
        index = self._selected_task_index()
        if person is None or index is None:
            messagebox.showinfo("Select a task", "Select an estimated task first.", parent=self.app)
            return
        task = person["tasks"][index]

        def submit(values: dict[str, str]) -> None:
            points = fp_logic.parse_point_count(values["points"], "Function points")
            person["tasks"][index] = fp_logic.clean_task({"name": values["name"], "type": values["type"],
                                                          "points": points}, "Task")

        fields = self._task_fields(task["name"], task["type"], str(task["points"]))
        if FormDialog(self.app, "Edit Estimated Task", fields, submit).show():
            self.app.refresh_all()

    def _delete_task(self) -> None:
        person = self._person()
        index = self._selected_task_index()
        if person is None or index is None:
            return
        del person["tasks"][index]
        self.app.refresh_all()

    def _transfer(self) -> None:
        if not self.session.estimators:
            messagebox.showinfo("Nothing to transfer", "Add an estimator and at least one task first.",
                                parent=self.app)
            return
        counts: list[int] = []

        def action() -> None:
            counts.append(self.session.transfer_estimates())

        if self.app.perform(action):
            self.session.clear_estimators()
            self.selected = None
            self.app.refresh_all()
            messagebox.showinfo("Transferred", f"Added {counts[0]} estimated task(s) to the project schedule.",
                                parent=self.app)

    # --- rendering
    def refresh(self) -> None:
        p = self.app.palette
        self.listbox.configure(background=p["panel"], foreground=p["text"], selectbackground=p["accent"],
                               selectforeground=p["accent_text"], highlightthickness=0)
        self.listbox.delete(0, "end")
        for person in self.session.estimators:
            self.listbox.insert("end", person["name"])
        self.empty_label.configure(text="" if self.session.estimators else "No estimators yet. Add one to calculate function-point effort.")
        if self.selected is not None and self.selected < len(self.session.estimators):
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(self.selected)
        else:
            self.selected = None

        self.tree.delete(*self.tree.get_children())
        person = self._person()
        currency = self.session.project.currency
        if person is None:
            self.rate_var.set("")
            self.complex_var.set("")
            self.simple_var.set("")
        else:
            self.rate_var.set(f"{person['hourly_rate']:g}")
            self.complex_var.set(f"{person['hours_per_complex_point']:g}")
            self.simple_var.set(f"{person['hours_per_simple_point']:g}")
            for index, task in enumerate(person["tasks"]):
                row = fp_logic.task_row(task, person)
                self.tree.insert("", "end", iid=str(index), text=task["name"], values=(
                    task["type"], task["points"], f"{row['hours']:,.1f}", format_money(row["cost"], currency),
                ))
        totals = self.session.estimator_totals()
        self.totals_var.set(
            f"{totals['task_count']} tasks · {totals['complex_points'] + totals['simple_points']} points · "
            f"{totals['total_hours']:,.1f} hours · {format_money(totals['total_cost'], currency)}"
        )


# ----------------------------------------------------------------------
# Summary report
# ----------------------------------------------------------------------

class ReportView(BaseView):
    def _build(self) -> None:
        self._title("Project Summary Report", "Plain text, ready to paste into email or a document.")
        bar = self._toolbar()
        ttk.Button(bar, text="Copy Report", command=self._copy).pack(side="left")
        ttk.Button(bar, text="Save as Text…", style="Accent.TButton", command=self._save).pack(side="left", padx=6)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="none", relief="flat", borderwidth=0, padx=12, pady=12,
                            font=("Courier", 11), state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def refresh(self) -> None:
        p = self.app.palette
        self.text.configure(background=p["panel"], foreground=p["text"], insertbackground=p["text"],
                            state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.session.summary_report_text())
        self.text.configure(state="disabled")

    def _copy(self) -> None:
        text = self.text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", "Report copied to the clipboard.", parent=self.app)

    def _save(self) -> None:
        name = "".join(c if c.isalnum() else "_" for c in self.session.project.name).strip("_") or "project"
        path = filedialog.asksaveasfilename(parent=self.app, title="Save report", defaultextension=".txt",
                                            initialfile=f"{name}_summary.txt",
                                            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(self.text.get("1.0", "end-1c") + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self.app)


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------

class SettingsView(BaseView):
    def _build(self) -> None:
        self._title("Project Settings")
        form = ttk.Frame(self)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar()
        self.start_var = tk.StringVar()
        self.currency_var = tk.StringVar()
        self.day_vars = [tk.BooleanVar(value=False) for _ in WEEKDAY_NAMES]
        self._modified = False
        self._loading = False
        self._loaded_project_id: str | None = None
        for var in (self.name_var, self.start_var, self.currency_var, *self.day_vars):
            var.trace_add("write", lambda *_a: self._mark_modified())

        ttk.Label(form, text="Project name").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        name_entry = ttk.Entry(form, textvariable=self.name_var, width=50)
        name_entry.grid(row=0, column=1, sticky="ew", pady=6)
        name_entry.bind("<Return>", lambda _e: self._apply())

        ttk.Label(form, text="Description").grid(row=1, column=0, sticky="nw", padx=(0, 12), pady=6)
        self.description = tk.Text(form, height=3, width=50, wrap="word", relief="solid", borderwidth=1)
        self.description.grid(row=1, column=1, sticky="ew", pady=6)
        self.description.bind("<<Modified>>", self._on_text_modified)

        ttk.Label(form, text="Start date (YYYY-MM-DD)").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=6)
        start_row = ttk.Frame(form)
        start_row.grid(row=2, column=1, sticky="w", pady=6)
        self.start_entry = ttk.Entry(start_row, textvariable=self.start_var, width=16)
        self.start_entry.pack(side="left")
        self.start_entry.bind("<Return>", lambda _e: self._apply())
        ttk.Button(start_row, text="Today", command=lambda: self.start_var.set(date.today().isoformat())).pack(
            side="left", padx=(6, 0)
        )

        ttk.Label(form, text="Currency").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Combobox(form, textvariable=self.currency_var, state="readonly", width=10,
                     values=list(self._currencies())).grid(row=3, column=1, sticky="w", pady=6)

        ttk.Label(form, text="Working days").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=6)
        days = ttk.Frame(form)
        days.grid(row=4, column=1, sticky="w", pady=6)
        for index, (name, var) in enumerate(zip(WEEKDAY_NAMES, self.day_vars)):
            ttk.Checkbutton(days, text=name, variable=var).pack(side="left", padx=(0, 10))

        action_bar = ttk.Frame(self)
        action_bar.pack(anchor="w", pady=16)
        ttk.Button(action_bar, text="Apply Changes", style="Accent.TButton", command=self._apply).pack(side="left")
        self.feedback_var = tk.StringVar(value="")
        ttk.Label(action_bar, textvariable=self.feedback_var, style="Muted.TLabel").pack(side="left", padx=(12, 0))
        ttk.Label(self, style="Muted.TLabel", text=(
            "Changing the start date or working days reschedules every task. "
            "Appearance and workspace preferences are stored separately in your per-user settings.")
        ).pack(anchor="w")

    @staticmethod
    def _currencies() -> tuple[str, ...]:
        from planforge.session import CURRENCIES
        return CURRENCIES

    def on_show(self) -> None:
        if not self._modified or self._loaded_project_id != self.session.project.id:
            self._load()

    def refresh(self) -> None:
        # Reload whenever there are no unsaved form edits or another project was opened.
        if not self._modified or self._loaded_project_id != self.session.project.id:
            self._load()

    def _mark_modified(self) -> None:
        if not self._loading:
            self._modified = True
            self.feedback_var.set("")

    def _on_text_modified(self, _event: Any = None) -> None:
        if self.description.edit_modified():
            self.description.edit_modified(False)
            self._mark_modified()

    def _load(self) -> None:
        p = self.session.project
        self._loading = True
        try:
            self.name_var.set(p.name)
            self.description.delete("1.0", "end")
            self.description.insert("1.0", p.description or "")
            self.description.edit_modified(False)
            self.start_var.set(p.start_date.isoformat() if p.start_date else "")
            self.currency_var.set(p.currency)
            working = set(p.calendars[0].working_days) if p.calendars else {0, 1, 2, 3, 4}
            for index, var in enumerate(self.day_vars):
                var.set(index in working)
            self._loaded_project_id = p.id
        finally:
            self._loading = False
        self._modified = False

    def commit_pending(self, *, show_errors: bool = False) -> bool:
        """Apply unsaved form edits when switching tabs or saving the project."""
        if not self._modified or self._loaded_project_id != self.session.project.id:
            return True
        return self._apply(show_errors=show_errors)

    def _apply(self, *, show_errors: bool = True) -> bool:
        start_text = self.start_var.get().strip()
        try:
            start = parse_date_input(start_text)
        except ValueError:
            if show_errors:
                messagebox.showerror(
                    "Check the start date",
                    "Enter a valid date such as 2026-10-19 or DD/MM/YYYY.",
                    parent=self.app,
                )
            return False
        working = [index for index, var in enumerate(self.day_vars) if var.get()]
        self._modified = False
        if not self.app.perform(
            self.session.update_settings,
            name=self.name_var.get(),
            description=self.description.get("1.0", "end").strip(),
            start_date=start,
            currency=self.currency_var.get(),
            working_days=working,
            show_errors=show_errors,
        ):
            self._modified = True
            return False
        shown_date = format_date(self.session.project.start_date) or "not set"
        self.feedback_var.set(f"Applied — start date: {shown_date}")
        return True


__all__ = [
    "BaseView",
    "CostsView",
    "EstimatorView",
    "OverviewView",
    "PeopleView",
    "ReportView",
    "SettingsView",
    "TasksView",
    "make_tree",
]
