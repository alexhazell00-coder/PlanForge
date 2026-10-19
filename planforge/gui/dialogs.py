"""Modal dialogs: task editor, generic form, import and export."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from planforge.session import (
    DEPENDENCY_LABELS,
    DEPENDENCY_TYPES,
    ProjectSession,
    SessionError,
    TaskEdit,
    format_money,
    hours_per_point,
)

NO_PREDECESSOR = "(none)"
UNASSIGNED = "(unassigned)"
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


class TaskDialog(_BaseDialog):
    """Edit one task: name, schedule, predecessor, person and estimate."""

    def __init__(self, parent: tk.Misc, session: ProjectSession, task_id: str) -> None:
        task = session.find_task(task_id)
        super().__init__(parent, "Edit Task")
        self.session = session
        self.task_id = task_id
        self.deleted = False
        resources = session.project.resources
        self._resource_ids = {r.name: r.id for r in resources}
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

    def _update_preview(self) -> None:
        if self.method_var.get() != FUNCTION_POINTS:
            self.preview_var.set("Manual duration: scheduled from the duration above.")
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
        self.preview_var.set(f"{hours:,.1f} hours, {format_money(hours * rate, self.session.project.currency)}")

    def _collect(self) -> TaskEdit:
        milestone = self.milestone_var.get()
        dep_label = self.dep_var.get()
        dep_type = next((t for t in DEPENDENCY_TYPES if DEPENDENCY_LABELS[t] == dep_label), "finish_to_start")
        predecessor_name = self.pred_var.get()
        person_name = self.person_var.get()
        fp_points = None
        if self.method_var.get() == FUNCTION_POINTS:
            fp_points = _parse_number(self.points_var.get(), "Function points", allow_zero=True)
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
    """Pick a file, preview what it contains, then import it."""

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
        ttk.Entry(file_row, textvariable=self.path_var, width=48).pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Browse…", command=self._browse).pack(side="left", padx=(6, 0))

        ttk.Label(self.body, text="Format").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Combobox(self.body, textvariable=self.format_var, state="readonly", width=46,
                     values=[label for _fid, label in self.format_choices]).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Button(self.body, text="Check file", command=self._check).grid(row=2, column=1, sticky="w", pady=6)

        self.preview = tk.Text(self.body, width=62, height=12, wrap="word", relief="solid", borderwidth=1,
                               state="disabled")
        self.preview.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        self.ok_button.configure(text="Import", state="disabled")

    def _browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose a project file", filetypes=[
            ("Project files", "*.xml *.gan *.csv *.json *.pfp"),
            ("All files", "*.*"),
        ])
        if path:
            self.path_var.set(path)
            self._check()

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
            self.fail("Choose a file to import.")
            return
        if not Path(path).is_file():
            self.fail("That file does not exist.")
            return
        result = self.session.preview_import(path, format_id=self._format_id())
        lines: list[str] = []
        if result.project is None or not result.success:
            lines.append("This file could not be imported.")
        else:
            summary = result.summary
            lines += [
                f"Format: {result.source_format}",
                f"Project: {summary.name}",
                f"Tasks: {summary.task_count} ({summary.subtask_count} subtasks, {summary.milestone_count} milestones)",
                f"Dependencies: {summary.dependency_count}",
                f"People: {summary.resource_count}",
                f"Assignments: {summary.assignment_count}",
                f"Dates: {summary.start_date or 'not set'} to {summary.finish_date or 'not set'}",
                "",
                "Importing replaces the open project. Save first if you need it.",
            ]
            self._result = result
            self.ok_button.configure(state="normal")
        if result.issues:
            lines.append("")
            lines.append("Messages:")
            lines += [f"  [{i.severity}] {i.message}" for i in result.issues]
        self._write_preview(lines)
        self.fail("" if self._result else "The file has errors. See the messages below.")

    def on_ok(self) -> None:
        if self._result is None:
            return
        try:
            self.session.apply_import(self._result)
        except SessionError as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()


class ExportDialog(_BaseDialog):
    """Choose a format and a destination, then write the project out."""

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
        combo.bind("<<ComboboxSelected>>", lambda _e: self._suggest_path())

        ttk.Label(self.body, text="Save to").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        file_row = ttk.Frame(self.body)
        file_row.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Entry(file_row, textvariable=self.path_var, width=48).pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Browse…", command=self._browse).pack(side="left", padx=(6, 0))
        self.ok_button.configure(text="Export")
        self._suggest_path()

    def _selected(self) -> tuple[str, str]:
        for fid, label, ext in self.choices:
            if label == self.format_var.get():
                return fid, ext
        return self.choices[0][0], self.choices[0][2]

    def _suggest_path(self) -> None:
        _fid, ext = self._selected()
        base = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.session.project.name).strip() or "project"
        self.path_var.set(str(Path.home() / f"{base.replace(' ', '_').lower()}{ext}"))

    def _browse(self) -> None:
        _fid, ext = self._selected()
        path = filedialog.asksaveasfilename(parent=self, title="Export project", initialfile=Path(self.path_var.get()).name,
                                            defaultextension=ext, filetypes=[(ext, f"*{ext}"), ("All files", "*.*")])
        if path:
            self.path_var.set(path)

    def on_ok(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            self.fail("Choose where to save the file.")
            return
        fid, _ext = self._selected()
        try:
            self.session.export_to(path, fid)
        except SessionError as exc:
            self.fail(str(exc))
            return
        self.result = True
        self.destroy()
        messagebox.showinfo("Export complete", f"Saved to:\n{path}", parent=self.master)


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
