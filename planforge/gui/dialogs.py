"""Modal dialogs: task editor, generic form, import and export."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from planforge.config import parse_date_input
from planforge.session import (
    DEPENDENCY_LABELS,
    DEPENDENCY_TYPES,
    ProjectSession,
    SessionError,
    TaskEdit,
    _UNSET_DATE,
    format_money,
    hours_per_point,
)

NO_PREDECESSOR = "(none)"
UNASSIGNED = "(unassigned)"
TOP_LEVEL = "(top level)"
MANUAL = "Manual duration"
FUNCTION_POINTS = "Function points"


class _BaseDialog(tk.Toplevel):
    """Shared window chrome: title, body frame, error line and OK/Cancel buttons."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result: bool = False
        self.body = ttk.Frame(self, padding=16)
        self.body.pack(fill="both", expand=True)
        self.error_var = tk.StringVar()
        self.error_label = ttk.Label(self.body, textvariable=self.error_var, style="Danger.TLabel", wraplength=420)
        self.error_label.grid(row=99, column=0, columnspan=2, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(self, padding=(16, 0, 16, 16))
        buttons.pack(fill="x")
        self.button_row = buttons
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        self.ok_button = ttk.Button(buttons, text="OK", style="Accent.TButton", command=self.on_ok)
        self.ok_button.pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Return>", self._on_return)

    def _on_return(self, event: tk.Event) -> None:
        # Enter in a multi-line notes box inserts a new line; it must not save the dialog.
        if isinstance(getattr(event, "widget", None), tk.Text):
            return
        self.on_ok()

    def show(self) -> bool:
        """Show the dialog, block until closed, and return True if it was saved."""
        self.grab_set()
        self.focus_set()
        self.wait_window(self)
        return self.result

    def on_ok(self) -> None:  # pragma: no cover - overridden
        self.destroy()

    def fail(self, message: str) -> None:
        self.error_var.set(message)


class FormField:
    def __init__(self, key: str, label: str, default: str = "", choices: list[str] | None = None) -> None:
        self.key = key
        self.label = label
        self.default = default
        self.choices = choices


class FormDialog(_BaseDialog):
    """A simple dialog of labelled entries or drop-downs.

    ``submit`` receives the values as strings. Raise ``SessionError`` or
    ``ValueError`` to show a message and keep the dialog open.
    """

    def __init__(self, parent: tk.Misc, title: str, fields: list[FormField],
                 submit: Callable[[dict[str, str]], None]) -> None:
        super().__init__(parent, title)
        self.fields = fields
        self.submit = submit
        self.vars: dict[str, tk.StringVar] = {}
        for row, field in enumerate(fields):
            ttk.Label(self.body, text=field.label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            var = tk.StringVar(value=field.default)
            self.vars[field.key] = var
            if field.choices is not None:
                widget = ttk.Combobox(self.body, textvariable=var, values=field.choices, state="readonly", width=32)
            else:
                widget = ttk.Entry(self.body, textvariable=var, width=34)
            widget.grid(row=row, column=1, sticky="ew", pady=4)
        first_entry = next((w for w in self.body.grid_slaves() if isinstance(w, ttk.Entry)), None)
        if first_entry is not None:
            first_entry.focus_set()

    def on_ok(self) -> None:
        values = {key: var.get() for key, var in self.vars.items()}
        try:
            self.submit(values)
        except (SessionError, ValueError) as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()


class ResourceDialog(_BaseDialog):
    """Create or edit a Work person/group or Material item matching ProjectLibre's Resource Sheet."""

    def __init__(
        self,
        parent: tk.Misc,
        session: ProjectSession,
        resource_id: str | None = None,
        *,
        default_type: str = "work",
        default_parent_id: str | None = None,
    ) -> None:
        existing = session.find_resource(resource_id) if resource_id is not None else None
        title = (
            "Edit Resource"
            if existing is not None
            else ("Add Material" if default_type == "material" else "Add Person / Resource")
        )
        super().__init__(parent, title)
        self.session = session
        self.resource_id = resource_id

        init_type = existing.resource_type if existing is not None else default_type
        if init_type not in {"work", "material"}:
            init_type = "material"

        # Exclude self and descendants from parent choices to prevent cycles
        excluded: set[str] = set()
        if resource_id is not None:
            excluded.add(resource_id)
            changed = True
            while changed:
                changed = False
                for r in session.project.resources:
                    if r.custom_fields.get("parent_id") in excluded and r.id not in excluded:
                        excluded.add(r.id)
                        changed = True

        self._parent_choices: dict[str, str] = {}
        for r in session.project.resources:
            if r.id in excluded:
                continue
            label_key = r.name if r.name not in self._parent_choices else f"{r.name} ({r.id[:6]})"
            self._parent_choices[label_key] = r.id

        cur_parent_id = (
            str(existing.custom_fields["parent_id"])
            if (existing is not None and isinstance(existing.custom_fields.get("parent_id"), str))
            else default_parent_id
        )
        init_parent_label = next(
            (lbl for lbl, rid in self._parent_choices.items() if rid == cur_parent_id),
            TOP_LEVEL,
        )

        row = 0

        def add_row(caption: str, widget: tk.Widget) -> ttk.Label:
            nonlocal row
            lbl = ttk.Label(self.body, text=caption)
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            row += 1
            return lbl

        type_frame = ttk.Frame(self.body)
        self.type_var = tk.StringVar(value=init_type)
        ttk.Radiobutton(type_frame, text="Work (Person / Role)", value="work", variable=self.type_var,
                        command=self._sync_type_fields).pack(side="left")
        ttk.Radiobutton(type_frame, text="Material (Hardware / Consumable)", value="material",
                        variable=self.type_var, command=self._sync_type_fields).pack(side="left", padx=(14, 0))
        add_row("Resource type", type_frame)

        self.name_var = tk.StringVar(value=existing.name if existing else "")
        name_entry = ttk.Entry(self.body, textvariable=self.name_var, width=38)
        add_row("Name", name_entry)

        init_group = str(existing.custom_fields.get("group") or "") if existing else ""
        self.group_var = tk.StringVar(value=init_group)
        add_row("Role / Group", ttk.Entry(self.body, textvariable=self.group_var, width=38))

        init_mat_label = str(existing.custom_fields.get("material_label") or "") if existing else ""
        self.material_label_var = tk.StringVar(value=init_mat_label)
        self.material_label_entry = ttk.Entry(self.body, textvariable=self.material_label_var, width=22)
        self.material_label_caption = add_row("Material label / unit", self.material_label_entry)

        init_initials = str(existing.custom_fields.get("initials") or "") if existing else ""
        self.initials_var = tk.StringVar(value=init_initials)
        self._initials_manual = bool(init_initials)
        add_row("Initials", ttk.Entry(self.body, textvariable=self.initials_var, width=10))
        self.name_var.trace_add("write", self._on_name_changed)

        init_rate = (
            f"{existing.standard_rate:g}"
            if (existing is not None and existing.standard_rate is not None)
            else "0"
        )
        self.rate_var = tk.StringVar(value=init_rate)
        self.rate_label = add_row(
            f"Standard rate ({session.project.currency}/hour)",
            ttk.Entry(self.body, textvariable=self.rate_var, width=16),
        )

        init_max_pct = f"{(existing.max_units * 100):g}" if existing is not None else "100"
        self.max_units_var = tk.StringVar(value=init_max_pct)
        self.max_units_entry = ttk.Entry(self.body, textvariable=self.max_units_var, width=12)
        add_row("Max. units (%)", self.max_units_entry)

        init_hours = f"{float(existing.custom_fields.get('hours_per_day', 8)):g}" if existing else "8"
        self.hours_var = tk.StringVar(value=init_hours)
        self.hours_entry = ttk.Entry(self.body, textvariable=self.hours_var, width=12)
        add_row("Hours per day", self.hours_entry)

        self.parent_var = tk.StringVar(value=init_parent_label)
        add_row(
            "Group under",
            ttk.Combobox(
                self.body,
                textvariable=self.parent_var,
                state="readonly",
                width=36,
                values=[TOP_LEVEL, *self._parent_choices.keys()],
            ),
        )

        self.body.columnconfigure(1, weight=1)
        self._sync_type_fields()
        name_entry.focus_set()

    def _on_name_changed(self, *_args: object) -> None:
        if not self._initials_manual:
            txt = self.name_var.get().strip()
            self.initials_var.set(txt[:1] if txt else "")

    def _sync_type_fields(self) -> None:
        currency = self.session.project.currency
        is_material = self.type_var.get() == "material"
        if is_material:
            self.rate_label.configure(text=f"Standard rate / unit cost ({currency})")
            self.material_label_entry.configure(state="normal")
            self.max_units_entry.configure(state="disabled")
            self.hours_entry.configure(state="disabled")
        else:
            self.rate_label.configure(text=f"Standard rate ({currency}/hour)")
            self.material_label_entry.configure(state="disabled")
            self.max_units_entry.configure(state="normal")
            self.hours_entry.configure(state="normal")

    def on_ok(self) -> None:
        rtype = self.type_var.get()
        try:
            rate = _parse_number(self.rate_var.get() or "0", "Standard rate", allow_zero=True)
            hours = 8.0 if rtype == "material" else _parse_number(self.hours_var.get(), "Hours per day", allow_zero=False)
            max_pct = 100.0 if rtype == "material" else _parse_number(self.max_units_var.get() or "100", "Max. units", allow_zero=True)
            parent_id = self._parent_choices.get(self.parent_var.get()) if self.parent_var.get() != TOP_LEVEL else None
            if self.resource_id is None:
                self.session.add_person(
                    self.name_var.get(),
                    rate,
                    hours,
                    resource_type=rtype,
                    group=self.group_var.get(),
                    material_label=self.material_label_var.get() if rtype == "material" else "",
                    initials=self.initials_var.get(),
                    max_units=max_pct / 100.0,
                    parent_id=parent_id,
                )
            else:
                self.session.update_person(
                    self.resource_id,
                    self.name_var.get(),
                    rate,
                    hours,
                    resource_type=rtype,
                    group=self.group_var.get(),
                    material_label=self.material_label_var.get() if rtype == "material" else "",
                    initials=self.initials_var.get(),
                    max_units=max_pct / 100.0,
                    parent_id=parent_id,
                )
        except (SessionError, ValueError) as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()


class TaskDialog(_BaseDialog):
    """Edit one task: name, schedule, predecessor, person, materials and estimate."""

    def __init__(self, parent: tk.Misc, session: ProjectSession, task_id: str) -> None:
        task = session.find_task(task_id)
        super().__init__(parent, "Edit Task")
        self.session = session
        self.task_id = task_id
        self.deleted = False
        resources = session.project.resources
        self._resource_ids = {r.name: r.id for r in resources if r.resource_type == "work"}
        self._material_ids = {r.name: r.id for r in resources if r.resource_type != "work"}
        self._material_items: list[tuple[str, float]] = [
            (res.id, assign.units) for res, assign in session.material_assignments_of(task_id)
        ]
        self._other_tasks = {t.name: t.id for t in session.project.tasks if t.id != task_id}

        row = 0

        def label(text: str) -> None:
            ttk.Label(self.body, text=text).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)

        def place(widget: tk.Widget) -> None:
            nonlocal row
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            row += 1

        label("Task name")
        self.name_var = tk.StringVar(value=task.name)
        place(ttk.Entry(self.body, textvariable=self.name_var, width=44))

        label("Notes")
        self.notes = tk.Text(self.body, width=44, height=3, wrap="word", relief="solid", borderwidth=1)
        self.notes.insert("1.0", task.description or "")
        place(self.notes)

        self.milestone_var = tk.BooleanVar(value=bool(task.milestone))
        label("Milestone")
        place(ttk.Checkbutton(self.body, variable=self.milestone_var, text="Zero-duration milestone"))

        self._was_pinned = bool(
            (task.constraint_type in {"must_start_on", "start_no_earlier_than"} and task.constraint_date is not None)
            or task.schedule_mode == "manual"
        )
        initial_start = (
            task.constraint_date.isoformat()
            if (self._was_pinned and task.constraint_date is not None)
            else (task.start_date.isoformat() if task.start_date is not None else "")
        )
        self._initial_start_text = initial_start
        self._force_auto_start = False
        label("Start date")
        start_frame = ttk.Frame(self.body)
        self.start_date_var = tk.StringVar(value=initial_start)
        ttk.Entry(start_frame, textvariable=self.start_date_var, width=16).pack(side="left")
        ttk.Button(start_frame, text="Auto", command=self._reset_start_auto).pack(side="left", padx=(6, 0))
        ttk.Label(start_frame, text="YYYY-MM-DD (or Auto)", style="Muted.TLabel").pack(side="left", padx=(8, 0))
        place(start_frame)

        label("Duration (working days)")
        self.duration_var = tk.StringVar(value=_fmt(task.duration if task.duration is not None else 1))
        place(ttk.Entry(self.body, textvariable=self.duration_var, width=12))

        label("Percent complete")
        self.progress_var = tk.StringVar(value=_fmt(task.percent_complete))
        place(ttk.Spinbox(self.body, from_=0, to=100, increment=5, textvariable=self.progress_var, width=10))

        label("Priority (100-1000)")
        self.priority_var = tk.StringVar(value=str(task.priority if task.priority is not None else 500))
        place(ttk.Spinbox(self.body, from_=100, to=1000, increment=50, textvariable=self.priority_var, width=10))

        predecessor = session.predecessor_of(task_id)
        pred_name = next((t.name for t in session.project.tasks if predecessor and t.id == predecessor.predecessor_id), NO_PREDECESSOR)
        label("Predecessor")
        self.pred_var = tk.StringVar(value=pred_name)
        place(ttk.Combobox(self.body, textvariable=self.pred_var, state="readonly", width=42,
                           values=[NO_PREDECESSOR, *self._other_tasks.keys()]))

        dep_type = predecessor.relationship_type if predecessor else "finish_to_start"
        label("Dependency type")
        self.dep_var = tk.StringVar(value=DEPENDENCY_LABELS.get(dep_type, DEPENDENCY_LABELS["finish_to_start"]))
        place(ttk.Combobox(self.body, textvariable=self.dep_var, state="readonly", width=42,
                           values=[DEPENDENCY_LABELS[t] for t in DEPENDENCY_TYPES]))

        label("Lag (working days)")
        self.lag_var = tk.StringVar(value=_fmt(predecessor.lag if predecessor else 0))
        place(ttk.Entry(self.body, textvariable=self.lag_var, width=12))

        assignee = session.assigned_resource_of(task_id)
        label("Assigned person")
        self.person_var = tk.StringVar(value=assignee.name if assignee else UNASSIGNED)
        place(ttk.Combobox(self.body, textvariable=self.person_var, state="readonly", width=42,
                           values=[UNASSIGNED, *self._resource_ids.keys()]))

        label("Materials")
        mat_box = ttk.Frame(self.body)
        mat_top = ttk.Frame(mat_box)
        mat_top.pack(fill="x")
        mat_names = list(self._material_ids.keys())
        self.mat_choice_var = tk.StringVar(value=mat_names[0] if mat_names else "(no materials added yet)")
        ttk.Combobox(
            mat_top,
            textvariable=self.mat_choice_var,
            state="readonly",
            width=24,
            values=mat_names if mat_names else ["(no materials added yet)"],
        ).pack(side="left")
        ttk.Label(mat_top, text="Qty").pack(side="left", padx=(6, 4))
        self.mat_qty_var = tk.StringVar(value="1")
        ttk.Entry(mat_top, textvariable=self.mat_qty_var, width=6).pack(side="left")
        ttk.Button(mat_top, text="Add", command=self._add_selected_material).pack(side="left", padx=(6, 0))
        ttk.Button(mat_top, text="Remove", command=self._remove_selected_material).pack(side="left", padx=(4, 0))
        self.mat_list = tk.Listbox(mat_box, height=3, width=44, exportselection=False, relief="solid", borderwidth=1)
        self.mat_list.pack(fill="x", pady=(4, 0))
        place(mat_box)
        self._refresh_material_list()

        fp_defaults = session.task_fp_defaults(task_id)
        label("Estimate by")
        method_frame = ttk.Frame(self.body)
        self.method_var = tk.StringVar(value=FUNCTION_POINTS if task.function_points else MANUAL)
        ttk.Radiobutton(method_frame, text=MANUAL, value=MANUAL, variable=self.method_var,
                        command=self._update_preview).pack(side="left")
        ttk.Radiobutton(method_frame, text=FUNCTION_POINTS, value=FUNCTION_POINTS, variable=self.method_var,
                        command=self._update_preview).pack(side="left", padx=(12, 0))
        place(method_frame)

        label("FP complexity")
        self.complexity_var = tk.StringVar(value=fp_defaults["complexity"])
        combo = ttk.Combobox(self.body, textvariable=self.complexity_var, state="readonly", width=12,
                             values=["complex", "simple"])
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())
        place(combo)

        label("Function points")
        self.points_var = tk.StringVar(value=_fmt(fp_defaults["points"]) if fp_defaults["points"] is not None else "")
        self.points_var.trace_add("write", lambda *_a: self._update_preview())
        place(ttk.Entry(self.body, textvariable=self.points_var, width=12))

        label("Calculated effort / cost")
        self.preview_var = tk.StringVar(value="")
        place(ttk.Label(self.body, textvariable=self.preview_var, style="Muted.TLabel"))

        self.duration_var.trace_add("write", lambda *_a: self._update_preview())
        self.person_var.trace_add("write", lambda *_a: self._update_preview())
        self.body.columnconfigure(1, weight=1)

        delete = ttk.Button(self.button_row, text="Delete Task", style="Danger.TButton", command=self._delete)
        delete.pack(side="left")
        self._update_preview()

    def _refresh_material_list(self) -> None:
        self.mat_list.delete(0, "end")
        currency = self.session.project.currency
        for mat_id, qty in self._material_items:
            try:
                res = self.session.find_resource(mat_id)
            except SessionError:
                continue
            unit_lbl = str(res.custom_fields.get("material_label") or "").strip()
            line_cost = qty * (res.standard_rate or 0.0) + (res.cost_per_use or 0.0)
            qty_txt = f"{qty:g} {unit_lbl}" if unit_lbl else f"×{qty:g}"
            self.mat_list.insert("end", f"{res.name} ({qty_txt}) — {format_money(line_cost, currency)}")

    def _add_selected_material(self) -> None:
        mat_id = self._material_ids.get(self.mat_choice_var.get())
        if mat_id is None:
            return
        try:
            qty = _parse_number(self.mat_qty_var.get(), "Material quantity", allow_zero=False)
        except ValueError as exc:
            self.fail(str(exc))
            return
        self.error_var.set("")
        updated = False
        for idx, (existing_id, _old_qty) in enumerate(self._material_items):
            if existing_id == mat_id:
                self._material_items[idx] = (mat_id, qty)
                updated = True
                break
        if not updated:
            self._material_items.append((mat_id, qty))
        self._refresh_material_list()
        self._update_preview()

    def _remove_selected_material(self) -> None:
        sel = self.mat_list.curselection()
        if not sel:
            if self._material_items:
                self._material_items.pop()
        else:
            del self._material_items[sel[0]]
        self._refresh_material_list()
        self._update_preview()

    def _material_total_cost(self) -> float:
        total = 0.0
        for mat_id, qty in self._material_items:
            try:
                res = self.session.find_resource(mat_id)
                total += qty * (res.standard_rate or 0.0) + (res.cost_per_use or 0.0)
            except SessionError:
                pass
        return total

    def _update_preview(self) -> None:
        mat_cost = self._material_total_cost()
        currency = self.session.project.currency
        mat_note = f" + {format_money(mat_cost, currency)} materials" if mat_cost > 0 else ""
        if self.method_var.get() != FUNCTION_POINTS:
            self.preview_var.set(f"Manual duration: scheduled from the duration above{mat_note}.")
            return
        resource = self.session.find_resource(self._resource_ids[self.person_var.get()]) \
            if self.person_var.get() in self._resource_ids else None
        try:
            points = float(self.points_var.get())
        except ValueError:
            self.preview_var.set("Enter the function points.")
            return
        if resource is None:
            self.preview_var.set("Choose a person to calculate hours and cost.")
            return
        hours = points * hours_per_point(resource, self.complexity_var.get())
        rate = resource.standard_rate or 0.0
        self.preview_var.set(
            f"{hours:,.1f} hours, {format_money(hours * rate + mat_cost, currency)}"
        )

    def _reset_start_auto(self) -> None:
        self._force_auto_start = True
        self.start_date_var.set("")

    def _collect(self) -> TaskEdit:
        milestone = self.milestone_var.get()
        dep_label = self.dep_var.get()
        dep_type = next((t for t in DEPENDENCY_TYPES if DEPENDENCY_LABELS[t] == dep_label), "finish_to_start")
        predecessor_name = self.pred_var.get()
        person_name = self.person_var.get()
        fp_points = None
        if self.method_var.get() == FUNCTION_POINTS:
            fp_points = _parse_number(self.points_var.get(), "Function points", allow_zero=True)
        raw_start = self.start_date_var.get().strip()
        if not raw_start:
            start_edit = None if (self._force_auto_start or self._was_pinned or self._initial_start_text) else _UNSET_DATE
        elif raw_start == self._initial_start_text and not self._was_pinned and not self._force_auto_start:
            start_edit = _UNSET_DATE
        else:
            start_edit = parse_date_input(raw_start)
        return TaskEdit(
            name=self.name_var.get(),
            description=self.notes.get("1.0", "end").strip(),
            milestone=milestone,
            duration=0.0 if milestone else _parse_number(self.duration_var.get(), "Duration", allow_zero=True),
            percent_complete=_parse_number(self.progress_var.get(), "Percent complete", allow_zero=True),
            priority=int(_parse_number(self.priority_var.get(), "Priority", allow_zero=True)),
            predecessor_id=self._other_tasks.get(predecessor_name) if predecessor_name != NO_PREDECESSOR else None,
            dependency_type=dep_type,
            lag=_parse_number(self.lag_var.get(), "Lag", allow_zero=True, allow_negative=True),
            resource_id=self._resource_ids.get(person_name) if person_name != UNASSIGNED else None,
            fp_complexity=self.complexity_var.get() if fp_points is not None else None,
            fp_points=fp_points,
            start_date=start_edit,
            material_assignments=list(self._material_items),
        )

    def on_ok(self) -> None:
        try:
            edit = self._collect()
            self.session.apply_task_edit(self.task_id, edit)
        except (SessionError, ValueError) as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()

    def _delete(self) -> None:
        task = self.session.find_task(self.task_id)
        if not messagebox.askyesno("Delete task", f"Delete '{task.name}'? Its dependencies and assignments will be removed.",
                                   parent=self):
            return
        self.session.delete_task(self.task_id)
        self.deleted = True
        self.result = True
        self.destroy()


class ImportDialog(_BaseDialog):
    """Pick a file, preview what it contains, then import it.

    Improvements: auto-detect hint, live validation, format description, help link,
    and clearer messaging for .pod/.mpp guidance.
    """

    def __init__(self, parent: tk.Misc, session: ProjectSession) -> None:
        super().__init__(parent, "Import Project")
        self.session = session
        self._result = None
        self.path_var = tk.StringVar()
        self.format_choices = [("auto", "Detect automatically")] + [
            (fid, label) for fid, label, _ext in session.format_choices("import")
        ]
        self.format_var = tk.StringVar(value=self.format_choices[0][1])

        ttk.Label(self.body, text="File").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        file_row = ttk.Frame(self.body)
        file_row.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Entry(file_row, textvariable=self.path_var, width=42).pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Browse…", command=self._browse).pack(side="left", padx=(6, 0))
        ttk.Button(file_row, text="Clear", command=lambda: (self.path_var.set(""), self._check())).pack(side="left", padx=(6, 0))

        ttk.Label(self.body, text="Format").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        fmt_combo = ttk.Combobox(self.body, textvariable=self.format_var, state="readonly", width=44,
                     values=[label for _fid, label in self.format_choices])
        fmt_combo.grid(row=1, column=1, sticky="ew", pady=4)
        fmt_combo.bind("<<ComboboxSelected>>", lambda _e: self._check())

        # Format hint
        self.format_hint = ttk.Label(self.body, text="Auto-detect uses file content, not just extension — recommended.", style="Muted.TLabel", wraplength=380)
        self.format_hint.grid(row=2, column=1, sticky="w", pady=(0, 2))

        # Action row: Check + Help
        action_row = ttk.Frame(self.body)
        action_row.grid(row=3, column=1, sticky="w", pady=4)
        ttk.Button(action_row, text="Check file", style="Accent.TButton", command=self._check).pack(side="left")
        ttk.Button(action_row, text="Help", command=self._open_help).pack(side="left", padx=6)
        ttk.Label(action_row, text="Browse auto-checks • Import replaces open project", style="Muted.TLabel").pack(side="left", padx=8)

        self.preview = tk.Text(self.body, width=62, height=12, wrap="word", relief="solid", borderwidth=1,
                               state="disabled", font=("Courier", 9))
        self.preview.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.ok_button.configure(text="Import", state="disabled")
        # Show initial hint
        self._write_preview([
            "Choose a file to preview:",
            "• Supported: .xml (MS Project / ProjectLibre), .gan (GanttProject), .csv, .json, .pfp",
            "• .pod / .mpp will show instructions to export XML first (those formats are binary and unsafe to convert directly).",
            "",
            "Tip: All conversions are validated before saving. For one-step conversion, try the Convert tab.",
            "Click Browse… to begin."
        ])

    def _browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose a project file", filetypes=[
            ("Project files", "*.xml *.gan *.csv *.json *.pfp"),
            ("All files", "*.*"),
        ])
        if path:
            self.path_var.set(path)
            self._check()

    def _open_help(self) -> None:
        # Try to jump to help in main app
        try:
            app = self.master  # type: ignore[attr-defined]
            # Walk up to find PlanForgeApp
            cur = self
            while cur is not None and not hasattr(cur, "select_tab_by_key"):
                cur = getattr(cur, "master", None)
            if cur and hasattr(cur, "open_convert_help"):
                self.destroy()
                cur.open_convert_help()
                return
        except Exception:
            pass
        messagebox.showinfo("Import Help", "See the Convert tab or Help tab for the full conversion guide:\n1. Browse → Check → Import (replaces project)\n2. Then File → Export → choose format → save\n\nFor .pod/.mpp: open in ProjectLibre/MS Project → Save As → XML → import that XML.", parent=self)

    def _format_id(self) -> str | None:
        for fid, label in self.format_choices:
            if label == self.format_var.get():
                return None if fid == "auto" else fid
        return None

    def _write_preview(self, lines: list[str]) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", "\n".join(lines))
        self.preview.configure(state="disabled")

    def _check(self) -> None:
        path = self.path_var.get().strip()
        self._result = None
        self.ok_button.configure(state="disabled")
        if not path:
            self.fail("Choose a file to import — use Browse… or type a path.")
            self._write_preview(["No file chosen.", "", "Click Browse… to select a file from ProjectLibre, MS Project, GanttProject, or a previous PlanForge export."])
            return
        if not Path(path).is_file():
            self.fail("That file does not exist. Check the path.")
            self._write_preview([f"File not found:\n{path}", "", "Use Browse… to locate the correct file."])
            return
        result = self.session.preview_import(path, format_id=self._format_id())
        lines: list[str] = []
        if result.project is None or not result.success:
            lines.append("This file could not be imported.")
            lines.append("")
            # Surface the most helpful message first
            if result.issues:
                lines.append("Details:")
                lines += [f"  • {i.message}" for i in result.issues]
            else:
                lines.append("Unknown error. Try opening the file in its original app and exporting to XML.")
        else:
            summary = result.summary
            lines += [
                f"✓ Format detected: {result.source_format}",
                f"Project: {summary.name}",
                f"Tasks: {summary.task_count} ({summary.subtask_count} subtasks, {summary.milestone_count} milestones)",
                f"Dependencies: {summary.dependency_count}",
                f"People: {summary.resource_count}",
                f"Assignments: {summary.assignment_count}",
                f"Dates: {summary.start_date or 'not set'} to {summary.finish_date or 'not set'}",
                "",
                "✓ Ready to import. Click Import to replace the open project.",
                "Tip: Save the current project first if you need it (File → Save As…).",
            ]
            self._result = result
            self.ok_button.configure(state="normal")
        if result.issues and result.success:
            lines.append("")
            lines.append("Messages (warnings included):")
            lines += [f"  [{i.severity}] {i.message}" for i in result.issues]
        self._write_preview(lines)
        self.fail("" if self._result else "The file has errors. See the preview for details.")

    def on_ok(self) -> None:
        if self._result is None:
            self.fail("Click Check file first to validate.")
            return
        try:
            self.session.apply_import(self._result)
        except SessionError as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()


class ExportDialog(_BaseDialog):
    """Choose a format and a destination, then write the project out.
    Improvements: format description, smarter default path, open-folder help.
    """

    def __init__(self, parent: tk.Misc, session: ProjectSession) -> None:
        super().__init__(parent, "Export Project")
        self.session = session
        self.choices = session.format_choices("export")
        self.format_var = tk.StringVar(value=self.choices[0][1])
        self.path_var = tk.StringVar()

        ttk.Label(self.body, text="Format").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        combo = ttk.Combobox(self.body, textvariable=self.format_var, state="readonly", width=46,
                             values=[label for _fid, label, _ext in self.choices])
        combo.grid(row=0, column=1, sticky="ew", pady=4)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_format_changed())

        self.desc_var = tk.StringVar()
        ttk.Label(self.body, textvariable=self.desc_var, style="Muted.TLabel", wraplength=420, justify="left").grid(row=1, column=1, sticky="w", pady=(0, 6))

        ttk.Label(self.body, text="Save to").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        file_row = ttk.Frame(self.body)
        file_row.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Entry(file_row, textvariable=self.path_var, width=42).pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Browse…", command=self._browse).pack(side="left", padx=(6, 0))
        ttk.Button(file_row, text="Suggest", command=self._suggest_path).pack(side="left", padx=(6, 0))

        hint = ttk.Label(self.body, text="Tip: Export is validated and atomic (no half-files). Check the Convert tab for one-step import→export.", style="Muted.TLabel", wraplength=420)
        hint.grid(row=3, column=1, sticky="w", pady=(4, 0))

        self.ok_button.configure(text="Export")
        self._on_format_changed()
        self._suggest_path()

    def _selected(self) -> tuple[str, str]:
        for fid, label, ext in self.choices:
            if label == self.format_var.get():
                return fid, ext
        return self.choices[0][0], self.choices[0][2]

    def _on_format_changed(self) -> None:
        fid, _ext = self._selected()
        # Find description from registry if available
        try:
            fmt = self.session.manager.registry.get(fid)
            desc = fmt.description if fmt else ""
        except Exception:
            desc = ""
        if not desc:
            # fallback
            desc = {"microsoft-project-xml": "XML for MS Project / ProjectLibre",
                    "ganttproject": "GanttProject .gan with tasks & allocations",
                    "csv": "CSV task table with JSON-in-cell extensions",
                    "planforge-json": "PlanForge canonical JSON backup",
                    "pfp": "PlanForge SQLite database"}.get(fid, "")
        self.desc_var.set(desc)
        # Only auto-suggest if path is empty or looks like a previous suggestion (in home)
        current = self.path_var.get().strip()
        if not current or current.startswith(str(Path.home())):
            self._suggest_path()

    def _suggest_path(self) -> None:
        _fid, ext = self._selected()
        base = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.session.project.name).strip() or "project"
        filename = f"{base.replace(' ', '_').lower()}{ext}"
        # Prefer current file's directory, then source directory, then home
        try:
            if self.session.file_path and self.session.file_path.parent.exists():
                target = self.session.file_path.parent / filename
            else:
                target = Path.home() / filename
        except Exception:
            target = Path.home() / filename
        self.path_var.set(str(target))

    def _browse(self) -> None:
        _fid, ext = self._selected()
        path = filedialog.asksaveasfilename(parent=self, title="Export project", initialfile=Path(self.path_var.get()).name,
                                            defaultextension=ext, filetypes=[(ext, f"*{ext}"), ("All files", "*.*")])
        if path:
            # Ensure extension
            if ext and not path.lower().endswith(ext.lower()):
                path = path + ext
            self.path_var.set(path)

    def on_ok(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            self.fail("Choose where to save the file (Browse… or Suggest).")
            return
        fid, ext = self._selected()
        if ext and not path.lower().endswith(ext.lower()):
            path = path + ext
            self.path_var.set(path)
        try:
            self.session.export_to(path, fid)
        except SessionError as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()
        # Offer to show in folder
        if messagebox.askyesno("Export complete", f"Saved to:\n{path}\n\nShow in folder?", parent=self.master):
            try:
                import subprocess, sys, os
                folder = Path(path).parent
                if sys.platform == "win32":
                    os.startfile(str(folder))  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(folder)])
                else:
                    subprocess.Popen(["xdg-open", str(folder)])
            except Exception:
                pass
        else:
            messagebox.showinfo("Export complete", f"Saved to:\n{path}\nFormat: {fid}", parent=self.master)


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


def _parse_number(text: str, label: str, *, allow_zero: bool = False, allow_negative: bool = False) -> float:
    try:
        value = float(str(text).strip())
    except ValueError:
        raise SessionError(f"{label} must be a number.") from None
    if not allow_negative and value < 0:
        raise SessionError(f"{label} cannot be negative.")
    if not allow_zero and value == 0:
        raise SessionError(f"{label} must be greater than zero.")
    return value


__all__ = ["ExportDialog", "FormDialog", "FormField", "ImportDialog", "TaskDialog", "FUNCTION_POINTS", "MANUAL"]
