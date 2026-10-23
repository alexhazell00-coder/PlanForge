"""The open project and every operation performed on it.

The Tkinter views (``planforge.gui``) call these methods and never change the
data model directly. Each mutation reschedules the project and marks it dirty,
so the views only need to redraw from the current state. Nothing here depends
on a display, which keeps the workflows testable.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from planforge import estimation
from planforge.interchange import (
    ImportResult,
    InterchangeManager,
    ProjectSummary,
    ValidationIssue,
    summarize_project,
)
from planforge.interchange.fp_adapter import import_bytes as fp_import_bytes
from planforge.model import (
    Assignment,
    Calendar,
    Dependency,
    FunctionPointEstimate,
    Project,
    Resource,
    Task,
    new_id,
)
from planforge.scheduling.engine import schedule_project
from planforge.storage.sqlite_store import load_project_from_pfp, save_project_to_pfp

DEPENDENCY_TYPES = ("finish_to_start", "start_to_start", "finish_to_finish", "start_to_finish")
DEPENDENCY_LABELS = {
    "finish_to_start": "Finish-to-Start (FS)",
    "start_to_start": "Start-to-Start (SS)",
    "finish_to_finish": "Finish-to-Finish (FF)",
    "start_to_finish": "Start-to-Finish (SF)",
}
CURRENCIES = ("GBP", "USD", "EUR", "CAD", "AUD")
CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "$", "AUD": "$"}
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEFAULT_HOURS_PER_DAY = 8.0
DEFAULT_HOURLY_RATE = 30.0
PFP_EXTENSION = ".pfp"


class SessionError(Exception):
    """A problem the user should see as a message box, not a crash."""


@dataclass(slots=True)
class TaskRow:
    """One line of the task hierarchy, in display order."""

    task: Task
    depth: int
    is_summary: bool


_UNSET_DATE: Any = object()


@dataclass(slots=True)
class TaskEdit:
    """Everything the task editor can change in one save."""

    name: str
    description: str = ""
    milestone: bool = False
    duration: float = 1.0
    percent_complete: float = 0.0
    priority: int = 500
    predecessor_id: str | None = None
    dependency_type: str = "finish_to_start"
    lag: float = 0.0
    resource_id: str | None = None
    # Function-point estimate. Leave ``fp_points`` as None to use the manual duration.
    fp_complexity: str | None = None
    fp_points: float | None = None
    # Optional explicit start date: omit to preserve current scheduling behavior,
    # pass ``None`` to reset to automatic scheduling, or pass a ``date`` to pin it.
    start_date: Any = _UNSET_DATE
    # Optional material assignments: list of ``(resource_id, quantity)`` pairs.
    # Leave ``None`` to preserve existing material assignments on the task.
    material_assignments: list[tuple[str, float]] | None = None


@dataclass(slots=True)
class Overview:
    name: str
    start_date: date | None
    finish_date: date | None
    task_count: int
    milestone_count: int
    dependency_count: int
    resource_count: int
    total_hours: float
    total_cost: float
    currency: str
    critical_tasks: list[Task]
    material_count: int = 0
    labour_cost: float = 0.0
    material_cost: float = 0.0


@dataclass(slots=True)
class PersonWorkload:
    resource_id: str
    name: str
    rate: float | None
    hours_per_day: float
    task_count: int
    hours: float
    cost: float
    resource_type: str = "work"
    group: str = ""
    material_label: str = ""
    initials: str = ""
    max_units: float = 1.0
    units_total: float = 0.0
    parent_id: str | None = None
    depth: int = 0
    is_summary: bool = False


def format_money(amount: float, currency: str) -> str:
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"


def create_new_project() -> Project:
    """Create a blank project for the user's New Project action."""
    return Project(
        name="Untitled project",
        start_date=date.today(),
        currency="GBP",
        calendars=[Calendar(name="Standard Working Week", working_days=[0, 1, 2, 3, 4])],
    )


def create_default_project() -> Project:
    """Create the sample project shown on first launch."""
    today = date.today()
    p_id = new_id()
    t1, t2, t3, t4 = (new_id() for _ in range(4))
    r1, r2 = new_id(), new_id()
    return Project(
        id=p_id,
        name="Website Redesign & Launch",
        description="Comprehensive website overhaul with user authentication and billing integration.",
        author="PlanForge Project Manager",
        start_date=today,
        currency="GBP",
        resources=[
            Resource(
                id=r1,
                name="Alice (Lead Engineer)",
                standard_rate=45.0,
                custom_fields={"hours_per_day": 8.0, "hours_per_complex_point": 2.5, "hours_per_simple_point": 1.0},
            ),
            Resource(
                id=r2,
                name="Bob (Designer & Frontend)",
                standard_rate=35.0,
                custom_fields={"hours_per_day": 8.0, "hours_per_complex_point": 3.0, "hours_per_simple_point": 1.2},
            ),
        ],
        tasks=[
            Task(id=t1, name="UI/UX Architecture & Wireframing", order=0, duration=4.0, percent_complete=100.0,
                 priority=600, estimated_work=32.0, estimated_cost=1120.0),
            Task(id=t2, name="Frontend Implementation", order=1, duration=6.0, percent_complete=50.0,
                 priority=500, estimated_work=48.0, estimated_cost=1680.0),
            Task(id=t3, name="Authentication & Security Backend", order=2, duration=5.0, percent_complete=20.0,
                 priority=700, estimated_work=40.0, estimated_cost=1800.0),
            Task(id=t4, name="Beta Release Sign-off", order=3, duration=0.0, percent_complete=0.0,
                 milestone=True, task_type="milestone"),
        ],
        dependencies=[
            Dependency(id=new_id(), predecessor_id=t1, successor_id=t2, relationship_type="finish_to_start", lag=0.0),
            Dependency(id=new_id(), predecessor_id=t1, successor_id=t3, relationship_type="start_to_start", lag=1.0),
            Dependency(id=new_id(), predecessor_id=t2, successor_id=t4, relationship_type="finish_to_start", lag=0.0),
            Dependency(id=new_id(), predecessor_id=t3, successor_id=t4, relationship_type="finish_to_start", lag=0.0),
        ],
        assignments=[
            Assignment(id=new_id(), task_id=t1, resource_id=r2, units=1.0, work=32.0, cost=1120.0),
            Assignment(id=new_id(), task_id=t2, resource_id=r2, units=1.0, work=48.0, cost=1680.0),
            Assignment(id=new_id(), task_id=t3, resource_id=r1, units=1.0, work=40.0, cost=1800.0),
        ],
        calendars=[Calendar(id=new_id(), name="Standard Working Week", working_days=[0, 1, 2, 3, 4])],
    )


class ProjectSession:
    """Holds the open project, its file location, and unsaved-change state."""

    def __init__(self, project: Project | None = None) -> None:
        self.manager = InterchangeManager()
        self.project: Project = schedule_project(project or create_default_project())
        self.file_path: Path | None = None
        self.dirty = False
        # Function Point estimators are kept in memory until transferred, as in earlier versions.
        self.estimators: list[dict] = []
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._history_limit = 100
        self._history_snapshot = self._capture_state()

    def _capture_state(self) -> dict:
        return {
            "project": deepcopy(self.project),
            "file_path": self.file_path,
            "dirty": self.dirty,
            "estimators": deepcopy(self.estimators),
        }

    def _record_history_change(self) -> None:
        self._undo_stack.append(self._history_snapshot)
        if len(self._undo_stack) > self._history_limit:
            del self._undo_stack[0]
        self._redo_stack.clear()
        self._history_snapshot = self._capture_state()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def _restore_state(self, snapshot: dict) -> None:
        self.project = schedule_project(deepcopy(snapshot["project"]))
        self._normalize_hierarchy()
        self.file_path = snapshot["file_path"]
        self.dirty = snapshot["dirty"]
        self.estimators = deepcopy(snapshot["estimators"])
        self._history_snapshot = self._capture_state()

    def undo(self) -> None:
        """Restore the previous complete project snapshot."""
        if not self._undo_stack:
            raise SessionError("There is nothing to undo.")
        self._redo_stack.append(self._capture_state())
        self._restore_state(self._undo_stack.pop())

    def redo(self) -> None:
        """Restore the next complete project snapshot."""
        if not self._redo_stack:
            raise SessionError("There is nothing to redo.")
        self._undo_stack.append(self._capture_state())
        if len(self._undo_stack) > self._history_limit:
            del self._undo_stack[0]
        self._restore_state(self._redo_stack.pop())

    # ------------------------------------------------------------------
    # Lifecycle: new, open, save, import, export
    # ------------------------------------------------------------------

    def new_project(self) -> None:
        self._replace(create_new_project(), file_path=None, dirty=False)

    def open_pfp(self, path: str | Path) -> None:
        try:
            project = load_project_from_pfp(path)
        except Exception as exc:  # the storage layer raises several error types
            raise SessionError(f"Could not open {Path(path).name}: {exc}") from exc
        self._replace(project, file_path=Path(path), dirty=False)

    def restore_recovery(self, snapshot_path: str | Path, source_path: str | Path | None = None) -> None:
        """Restore a crash-recovery copy as unsaved work tied to its original file when available."""
        try:
            project = load_project_from_pfp(snapshot_path)
        except Exception as exc:
            raise SessionError(f"Could not restore recovery snapshot: {exc}") from exc
        target = Path(source_path) if source_path is not None and Path(source_path).exists() else None
        self._replace(project, file_path=target, dirty=True)

    def save(self, path: str | Path | None = None) -> Path:
        """Save as a ``.pfp`` file. Uses the current file when ``path`` is omitted."""
        target = Path(path) if path is not None else self.file_path
        if target is None:
            raise SessionError("Choose a file name to save this project.")
        if target.suffix.lower() != PFP_EXTENSION:
            target = target.with_suffix(PFP_EXTENSION)
        try:
            save_project_to_pfp(self.project, target)
        except Exception as exc:
            raise SessionError(f"Could not save {target.name}: {exc}") from exc
        self.file_path = target
        self.dirty = False
        saved_project = deepcopy(self.project)
        saved_path = self.file_path
        for snapshot in (*self._undo_stack, *self._redo_stack):
            snapshot["dirty"] = not (snapshot["project"] == saved_project and snapshot["file_path"] == saved_path)
        self._history_snapshot = self._capture_state()
        return target

    def preview_import(self, path: str | Path, format_id: str | None = None) -> ImportResult:
        """Read and check a file from another application without changing the project.

        ``format_id`` forces a format; ``None`` auto-detects it from the file contents.
        """
        source = Path(path)
        if format_id is None and source.suffix.casefold() == PFP_EXTENSION and source.is_file():
            try:
                project = load_project_from_pfp(source)
            except Exception as exc:
                return ImportResult(
                    "pfp",
                    None,
                    (ValidationIssue("error", "pfp.read.failed", str(source), str(exc)),),
                )
            return ImportResult("pfp", project)
        return self.manager.import_file(path, format_id=format_id)

    def recalculate(self) -> None:
        """Recompute dates, float and the critical path without changing any data."""
        self._normalize_hierarchy()
        schedule_project(self.project)

    def apply_import(self, result: ImportResult) -> None:
        if not result.success or result.project is None:
            details = "; ".join(issue.message for issue in result.errors) or "Unknown error."
            raise SessionError(f"Import failed: {details}")
        # An imported project has not been saved as .pfp yet, so it starts dirty.
        self._replace(result.project, file_path=None, dirty=True)

    def export_to(self, path: str | Path, format_id: str) -> None:
        if format_id == "pfp":
            self.save_copy(path)
            return
        result = self.manager.export_file(self.project, format_id, path, overwrite=True)
        if not result.success:
            details = "; ".join(issue.message for issue in result.errors) or "Unknown error."
            raise SessionError(f"Export failed: {details}")

    def save_copy(self, path: str | Path) -> None:
        """Write a ``.pfp`` copy without changing the current file location."""
        try:
            save_project_to_pfp(self.project, Path(path))
        except Exception as exc:
            raise SessionError(f"Could not save {Path(path).name}: {exc}") from exc

    def format_choices(self, direction: str) -> list[tuple[str, str, str]]:
        """Return ``(format_id, label, extension)`` for ``"import"`` or ``"export"``."""
        registry = self.manager.registry
        formats = registry.import_formats() if direction == "import" else registry.export_formats()
        choices = []
        for fmt in formats:
            extension = fmt.extensions[0] if fmt.extensions else ""
            choices.append((fmt.id, fmt.name, extension))
        if direction == "export":
            choices.append(("pfp", "PlanForge SQLite database (.pfp)", PFP_EXTENSION))
        return choices

    def _replace(self, project: Project, *, file_path: Path | None, dirty: bool) -> None:
        self.project = schedule_project(project)
        self._normalize_hierarchy()
        self.file_path = file_path
        self.dirty = dirty
        self._record_history_change()

    def _changed(self) -> None:
        self._normalize_hierarchy()
        schedule_project(self.project)
        self.dirty = True
        self._record_history_change()

    # ------------------------------------------------------------------
    # Task hierarchy
    # ------------------------------------------------------------------

    def _normalize_hierarchy(self) -> None:
        """Make parent links valid, then store tasks in outline order with levels set."""
        tasks = self.project.tasks
        ids = {t.id for t in tasks}
        for t in tasks:
            if t.parent_id not in ids or t.parent_id == t.id:
                t.parent_id = None

        children: dict[str | None, list[Task]] = defaultdict(list)
        for t in sorted(tasks, key=lambda item: item.order):
            children[t.parent_id].append(t)

        ordered: list[Task] = []
        visited: set[str] = set()

        def walk(parent_id: str | None, depth: int) -> None:
            for child in children.get(parent_id, []):
                if child.id in visited:
                    continue
                visited.add(child.id)
                child.outline_level = depth + 1
                ordered.append(child)
                walk(child.id, depth + 1)

        walk(None, 0)
        for t in tasks:  # any task caught in a parent cycle becomes a top-level task
            if t.id not in visited:
                t.parent_id = None
                walk(None, 0)

        for index, t in enumerate(ordered):
            t.order = index
        self.project.tasks[:] = ordered

    def task_rows(self) -> list[TaskRow]:
        summary_ids = {t.parent_id for t in self.project.tasks if t.parent_id}
        return [
            TaskRow(task=t, depth=(t.outline_level or 1) - 1, is_summary=t.id in summary_ids)
            for t in self.project.tasks
        ]

    def find_task(self, task_id: str) -> Task:
        for t in self.project.tasks:
            if t.id == task_id:
                return t
        raise SessionError("That task no longer exists.")

    def find_resource(self, resource_id: str) -> Resource:
        for r in self.project.resources:
            if r.id == resource_id:
                return r
        raise SessionError("That person no longer exists.")

    def add_task(self, name: str = "New task", *, milestone: bool = False, parent_id: str | None = None) -> Task:
        name = _clean_text(name, "Task name")
        if parent_id is not None:
            self.find_task(parent_id)
        next_order = max((t.order for t in self.project.tasks), default=-1) + 1
        task = Task(
            name=name,
            order=next_order,
            parent_id=parent_id,
            duration=0.0 if milestone else 1.0,
            milestone=milestone,
            task_type="milestone" if milestone else "task",
        )
        self.project.tasks.append(task)
        self._changed()
        return task

    def indent_task(self, task_id: str) -> None:
        """Make the task a subtask of the sibling directly above it."""
        task = self.find_task(task_id)
        siblings = [t for t in self.project.tasks if t.parent_id == task.parent_id]
        index = next(i for i, t in enumerate(siblings) if t.id == task_id)
        if index == 0:
            raise SessionError("There is no task above this one to indent under.")
        task.parent_id = siblings[index - 1].id
        self._changed()

    def outdent_task(self, task_id: str) -> None:
        """Move the task up one level, placing it directly after its former parent."""
        task = self.find_task(task_id)
        if task.parent_id is None:
            raise SessionError("This task is already at the top level.")
        parent = self.find_task(task.parent_id)
        task.parent_id = parent.parent_id
        task.order = parent.order + 0.5  # sorts just after the former parent
        self._changed()

    def delete_task(self, task_id: str) -> None:
        task = self.find_task(task_id)
        for child in self.project.tasks:
            if child.parent_id == task_id:
                child.parent_id = task.parent_id
        self.project.tasks.remove(task)
        self.project.dependencies = [
            d for d in self.project.dependencies if task_id not in (d.predecessor_id, d.successor_id)
        ]
        self.project.assignments = [a for a in self.project.assignments if a.task_id != task_id]
        self._changed()

    def is_summary(self, task_id: str) -> bool:
        return any(t.parent_id == task_id for t in self.project.tasks)

    def predecessor_of(self, task_id: str) -> Dependency | None:
        for dep in self.project.dependencies:
            if dep.successor_id == task_id:
                return dep
        return None

    def assigned_resource_of(self, task_id: str) -> Resource | None:
        res_by_id = {r.id: r for r in self.project.resources}
        for a in self.project.assignments:
            if a.task_id == task_id:
                r = res_by_id.get(a.resource_id)
                if r is not None and r.resource_type == "work":
                    return r
        return None

    def material_assignments_of(self, task_id: str) -> list[tuple[Resource, Assignment]]:
        res_by_id = {r.id: r for r in self.project.resources}
        items: list[tuple[Resource, Assignment]] = []
        for a in self.project.assignments:
            if a.task_id == task_id:
                r = res_by_id.get(a.resource_id)
                if r is not None and r.resource_type != "work":
                    items.append((r, a))
        return items

    def task_resource_names(self, task_id: str) -> str:
        parts: list[str] = []
        person = self.assigned_resource_of(task_id)
        if person is not None:
            parts.append(person.name)
        for mat, assign in self.material_assignments_of(task_id):
            label = str(mat.custom_fields.get("material_label") or "").strip()
            qty = assign.units
            qty_str = f"{qty:g}" if qty != 1.0 or label else ""
            if qty_str and label:
                parts.append(f"{mat.name} ({qty_str} {label})")
            elif qty_str:
                parts.append(f"{mat.name} ×{qty_str}")
            else:
                parts.append(mat.name)
        return ", ".join(parts)

    def predecessor_names(self, task_id: str) -> str:
        dep = self.predecessor_of(task_id)
        if dep is None:
            return ""
        for t in self.project.tasks:
            if t.id == dep.predecessor_id:
                return t.name
        return ""

    def apply_task_edit(self, task_id: str, edit: TaskEdit) -> None:
        """Validate and save the task editor's values, then reschedule."""
        task = self.find_task(task_id)
        name = _clean_text(edit.name, "Task name")
        if not 0 <= edit.percent_complete <= 100:
            raise SessionError("Percent complete must be between 0 and 100.")
        if not 100 <= edit.priority <= 1000:
            raise SessionError("Priority must be between 100 and 1000.")
        if not edit.milestone and edit.duration < 0:
            raise SessionError("Duration cannot be negative.")
        if edit.predecessor_id is not None:
            if edit.predecessor_id == task_id:
                raise SessionError("A task cannot depend on itself.")
            self.find_task(edit.predecessor_id)
        if edit.dependency_type not in DEPENDENCY_TYPES:
            raise SessionError("Unknown dependency type.")
        if edit.resource_id is not None:
            resource = self.find_resource(edit.resource_id)
        else:
            resource = None

        validated_materials: list[tuple[Resource, float]] | None = None
        if edit.material_assignments is not None:
            validated_materials = []
            for mat_id, raw_qty in edit.material_assignments:
                mat_res = self.find_resource(mat_id)
                if raw_qty is None or not math.isfinite(raw_qty) or raw_qty <= 0:
                    raise SessionError(f"Quantity for '{mat_res.name}' must be greater than zero.")
                validated_materials.append((mat_res, float(raw_qty)))

        if edit.start_date is not _UNSET_DATE:
            if edit.start_date is None:
                task.constraint_type = None
                task.constraint_date = None
                task.schedule_mode = "auto"
            elif isinstance(edit.start_date, date) and not isinstance(edit.start_date, datetime):
                task.constraint_type = "must_start_on"
                task.constraint_date = edit.start_date
                task.schedule_mode = "auto"
            else:
                raise SessionError("Invalid task start date.")

        task.name = name
        task.description = edit.description.strip()
        task.milestone = edit.milestone
        task.task_type = "milestone" if edit.milestone else ("summary" if self.is_summary(task_id) else "task")
        task.duration = 0.0 if edit.milestone else float(edit.duration)
        task.percent_complete = float(edit.percent_complete)
        task.priority = int(edit.priority)

        rate = resource.standard_rate if resource and resource.standard_rate is not None else DEFAULT_HOURLY_RATE
        hours_per_day = _hours_per_day(resource) if resource else DEFAULT_HOURS_PER_DAY
        work_hours: float | None = None
        cost: float | None = None

        if edit.fp_points is not None:
            if resource is None:
                raise SessionError("Choose a person before estimating with function points.")
            if edit.fp_complexity not in estimation.TASK_TYPES:
                raise SessionError("Choose a complexity for the function points.")
            if edit.fp_points < 0 or not math.isfinite(edit.fp_points):
                raise SessionError("Function points must be zero or more.")
            per_point = hours_per_point(resource, edit.fp_complexity)
            work_hours = edit.fp_points * per_point
            cost = work_hours * rate
            task.function_points = _fp_estimate(edit, work_hours, rate, self.project.currency)
            task.estimated_work = work_hours
            task.estimated_cost = cost
            if not edit.milestone:
                task.duration = float(max(1, math.ceil(work_hours / DEFAULT_HOURS_PER_DAY)))
        else:
            task.function_points = None

        self.project.dependencies = [d for d in self.project.dependencies if d.successor_id != task_id]
        if edit.predecessor_id is not None:
            self.project.dependencies.append(Dependency(
                id=new_id(),
                predecessor_id=edit.predecessor_id,
                successor_id=task_id,
                relationship_type=edit.dependency_type,
                lag=float(edit.lag),
                lag_unit="day",
            ))

        res_by_id = {r.id: r for r in self.project.resources}
        preserved_non_work = (
            [
                a for a in self.project.assignments
                if a.task_id == task_id and res_by_id.get(a.resource_id) is not None and res_by_id[a.resource_id].resource_type != "work"
            ]
            if validated_materials is None
            else []
        )
        self.project.assignments = [a for a in self.project.assignments if a.task_id != task_id]
        if resource is not None:
            if work_hours is None:
                work_hours = task.duration * hours_per_day if task.duration else 0.0
                cost = work_hours * rate
            self.project.assignments.append(Assignment(
                id=new_id(),
                task_id=task_id,
                resource_id=resource.id,
                units=1.0,
                work=work_hours,
                cost=cost,
            ))

        mat_total_cost = 0.0
        if validated_materials is not None:
            for mat_res, qty in validated_materials:
                line_cost = qty * (mat_res.standard_rate or 0.0) + (mat_res.cost_per_use or 0.0)
                mat_total_cost += line_cost
                self.project.assignments.append(Assignment(
                    id=new_id(),
                    task_id=task_id,
                    resource_id=mat_res.id,
                    units=qty,
                    work=0.0,
                    cost=line_cost,
                ))
        else:
            for existing_mat in preserved_non_work:
                mat_res = res_by_id[existing_mat.resource_id]
                mat_total_cost += (
                    existing_mat.cost
                    if existing_mat.cost is not None
                    else existing_mat.units * (mat_res.standard_rate or 0.0) + (mat_res.cost_per_use or 0.0)
                )
                self.project.assignments.append(existing_mat)

        if edit.fp_points is None:
            task.estimated_work = work_hours
            if cost is not None or validated_materials or preserved_non_work:
                task.estimated_cost = (cost or 0.0) + mat_total_cost
            else:
                task.estimated_cost = None
        elif mat_total_cost > 0:
            task.estimated_cost = (cost or 0.0) + mat_total_cost

        self._normalize_hierarchy()
        schedule_project(self.project)
        if edit.start_date is not _UNSET_DATE and isinstance(edit.start_date, date):
            task_starts = [t.start_date for t in self.project.tasks if t.start_date]
            if task_starts:
                self.project.start_date = min(task_starts)
                if self.project.finish_date and self.project.finish_date < self.project.start_date:
                    self.project.finish_date = self.project.start_date
        self.dirty = True
        self._record_history_change()

    def task_fp_defaults(self, task_id: str) -> dict:
        """Return the stored function-point values for a task, if it has any."""
        task = self.find_task(task_id)
        fp = task.function_points
        if fp is None:
            return {"points": None, "complexity": "complex"}
        complexity = fp.complexities.get("type", "complex")
        return {"points": fp.function_points, "complexity": complexity}

    # ------------------------------------------------------------------
    # People & Materials
    # ------------------------------------------------------------------

    def _normalize_resource_hierarchy(self) -> dict[str, tuple[int, bool]]:
        """Validate resource parent links and return ``{id: (depth, is_summary)}``."""
        resources = self.project.resources
        ids = {r.id for r in resources}
        for r in resources:
            pid = r.custom_fields.get("parent_id")
            if not isinstance(pid, str) or pid not in ids or pid == r.id:
                r.custom_fields.pop("parent_id", None)

        children: dict[str | None, list[Resource]] = defaultdict(list)
        for r in resources:
            pid = r.custom_fields.get("parent_id")
            children[pid if isinstance(pid, str) else None].append(r)

        ordered: list[Resource] = []
        visited: set[str] = set()
        depths: dict[str, int] = {}

        def walk(parent_id: str | None, depth: int) -> None:
            for child in children.get(parent_id, []):
                if child.id in visited:
                    continue
                visited.add(child.id)
                depths[child.id] = depth
                ordered.append(child)
                walk(child.id, depth + 1)

        walk(None, 0)
        for r in resources:
            if r.id not in visited:
                r.custom_fields.pop("parent_id", None)
                children[None].append(r)
                walk(None, 0)

        self.project.resources[:] = ordered
        summary_ids = {
            str(r.custom_fields["parent_id"])
            for r in ordered
            if isinstance(r.custom_fields.get("parent_id"), str)
        }
        return {r.id: (depths.get(r.id, 0), r.id in summary_ids) for r in ordered}

    def add_person(
        self,
        name: str,
        rate: float,
        hours_per_day: float = DEFAULT_HOURS_PER_DAY,
        *,
        resource_type: str = "work",
        group: str = "",
        material_label: str = "",
        initials: str = "",
        max_units: float = 1.0,
        parent_id: str | None = None,
    ) -> Resource:
        name = _clean_text(name, "Name")
        rtype = resource_type if resource_type in {"work", "material", "cost"} else "work"
        if rtype == "work":
            rate, hours_per_day = _check_rate_and_hours(rate, hours_per_day)
        else:
            if rate is None or not math.isfinite(rate) or rate < 0:
                raise SessionError("Unit cost must be a number of zero or more.")
            hours_per_day = DEFAULT_HOURS_PER_DAY
        if max_units is None or not math.isfinite(max_units) or max_units < 0:
            raise SessionError("Max units must be zero or more.")
        if parent_id is not None:
            self.find_resource(parent_id)

        custom: dict[str, Any] = {}
        if rtype == "work":
            custom["hours_per_day"] = hours_per_day
        clean_group = (group or "").strip()
        clean_label = (material_label or "").strip()
        clean_initials = (initials or "").strip() or name[0]
        if clean_group:
            custom["group"] = clean_group
        if rtype == "material" and clean_label:
            custom["material_label"] = clean_label
        if clean_initials:
            custom["initials"] = clean_initials
        if parent_id is not None:
            custom["parent_id"] = parent_id

        rate_unit = clean_label if (rtype == "material" and clean_label) else ("unit" if rtype == "material" else "hour")
        resource = Resource(
            name=name,
            resource_type=rtype,
            max_units=float(max_units) if rtype == "work" else 1.0,
            standard_rate=float(rate),
            standard_rate_unit=rate_unit,
            custom_fields=custom,
        )
        self.project.resources.append(resource)
        self._normalize_resource_hierarchy()
        self._changed()
        return resource

    def add_material(
        self,
        name: str,
        rate: float,
        *,
        material_label: str = "",
        group: str = "",
        initials: str = "",
        parent_id: str | None = None,
    ) -> Resource:
        """Create a material/equipment resource with optional unit label and group."""
        return self.add_person(
            name,
            rate,
            resource_type="material",
            group=group,
            material_label=material_label,
            initials=initials,
            parent_id=parent_id,
        )

    def update_person(
        self,
        resource_id: str,
        name: str,
        rate: float,
        hours_per_day: float = DEFAULT_HOURS_PER_DAY,
        *,
        resource_type: str | None = None,
        group: str | None = None,
        material_label: str | None = None,
        initials: str | None = None,
        max_units: float | None = None,
        parent_id: Any = _UNSET_DATE,
    ) -> None:
        resource = self.find_resource(resource_id)
        name = _clean_text(name, "Name")
        rtype = resource_type if resource_type in {"work", "material", "cost"} else resource.resource_type
        if rtype == "work":
            rate, hours_per_day = _check_rate_and_hours(rate, hours_per_day)
            resource.custom_fields["hours_per_day"] = hours_per_day
            resource.custom_fields.pop("material_label", None)
            resource.standard_rate_unit = "hour"
        else:
            if rate is None or not math.isfinite(rate) or rate < 0:
                raise SessionError("Unit cost must be a number of zero or more.")
            if material_label is not None:
                clean_label = material_label.strip()
                if clean_label:
                    resource.custom_fields["material_label"] = clean_label
                else:
                    resource.custom_fields.pop("material_label", None)
            lbl = str(resource.custom_fields.get("material_label") or "").strip()
            resource.standard_rate_unit = lbl or "unit"

        if max_units is not None:
            if not math.isfinite(max_units) or max_units < 0:
                raise SessionError("Max units must be zero or more.")
            resource.max_units = float(max_units) if rtype == "work" else 1.0
        if group is not None:
            clean_group = group.strip()
            if clean_group:
                resource.custom_fields["group"] = clean_group
            else:
                resource.custom_fields.pop("group", None)
        if initials is not None:
            clean_init = initials.strip()
            if clean_init:
                resource.custom_fields["initials"] = clean_init
            else:
                resource.custom_fields.pop("initials", None)
        if parent_id is not _UNSET_DATE:
            if parent_id is None:
                resource.custom_fields.pop("parent_id", None)
            else:
                if parent_id == resource_id:
                    raise SessionError("A resource cannot be inside itself.")
                self.find_resource(parent_id)
                resource.custom_fields["parent_id"] = parent_id

        resource.name = name
        resource.resource_type = rtype
        resource.standard_rate = float(rate)

        # Keep existing assignment costs synchronized with updated rate
        affected_tasks: set[str] = set()
        for a in self.project.assignments:
            if a.resource_id == resource.id:
                affected_tasks.add(a.task_id)
                if rtype == "work":
                    a.cost = (a.work or 0.0) * (resource.standard_rate or 0.0)
                else:
                    a.work = 0.0
                    a.cost = a.units * (resource.standard_rate or 0.0) + (resource.cost_per_use or 0.0)
        res_by_id = {r.id: r for r in self.project.resources}
        for t in self.project.tasks:
            if t.id in affected_tasks:
                t_assigns = [a for a in self.project.assignments if a.task_id == t.id]
                t.estimated_cost = sum(a.cost or 0.0 for a in t_assigns) if t_assigns else None
                t.estimated_work = sum(
                    a.work or 0.0
                    for a in t_assigns
                    if res_by_id.get(a.resource_id) is None or res_by_id[a.resource_id].resource_type == "work"
                ) or None

        self._normalize_resource_hierarchy()
        self._changed()

    def indent_resource(self, resource_id: str) -> None:
        """Make the resource a child of the sibling directly above it."""
        self._normalize_resource_hierarchy()
        resource = self.find_resource(resource_id)
        cur_parent = resource.custom_fields.get("parent_id")
        siblings = [r for r in self.project.resources if r.custom_fields.get("parent_id") == cur_parent]
        index = next(i for i, r in enumerate(siblings) if r.id == resource_id)
        if index == 0:
            raise SessionError("There is no row above this one to indent under.")
        resource.custom_fields["parent_id"] = siblings[index - 1].id
        self._normalize_resource_hierarchy()
        self._changed()

    def outdent_resource(self, resource_id: str) -> None:
        """Move the resource up one outline level."""
        self._normalize_resource_hierarchy()
        resource = self.find_resource(resource_id)
        cur_parent_id = resource.custom_fields.get("parent_id")
        if not isinstance(cur_parent_id, str):
            raise SessionError("This resource is already at the top level.")
        parent = self.find_resource(cur_parent_id)
        grandparent = parent.custom_fields.get("parent_id")
        if isinstance(grandparent, str):
            resource.custom_fields["parent_id"] = grandparent
        else:
            resource.custom_fields.pop("parent_id", None)
        # Position directly after the former parent's subtree
        subtree_ids = {parent.id}
        changed = True
        while changed:
            changed = False
            for r in self.project.resources:
                if r.custom_fields.get("parent_id") in subtree_ids and r.id not in subtree_ids:
                    subtree_ids.add(r.id)
                    changed = True
        subtree_ids.discard(resource.id)
        without = [r for r in self.project.resources if r.id != resource.id]
        last_idx = max(i for i, r in enumerate(without) if r.id in subtree_ids)
        without.insert(last_idx + 1, resource)
        self.project.resources[:] = without
        self._normalize_resource_hierarchy()
        self._changed()

    def delete_person(self, resource_id: str) -> None:
        resource = self.find_resource(resource_id)
        parent_id = resource.custom_fields.get("parent_id")
        for child in self.project.resources:
            if child.custom_fields.get("parent_id") == resource_id:
                if isinstance(parent_id, str):
                    child.custom_fields["parent_id"] = parent_id
                else:
                    child.custom_fields.pop("parent_id", None)
        affected_tasks = {a.task_id for a in self.project.assignments if a.resource_id == resource_id}
        self.project.resources.remove(resource)
        self.project.assignments = [a for a in self.project.assignments if a.resource_id != resource_id]
        for t in self.project.tasks:
            if t.id in affected_tasks:
                remaining = [a for a in self.project.assignments if a.task_id == t.id]
                t.estimated_cost = sum(a.cost or 0.0 for a in remaining) if remaining else None
        self._normalize_resource_hierarchy()
        self._changed()

    def person_workloads(self) -> list[PersonWorkload]:
        hierarchy = self._normalize_resource_hierarchy()
        rows: list[PersonWorkload] = []
        for r in self.project.resources:
            assigned = [a for a in self.project.assignments if a.resource_id == r.id]
            rate = r.standard_rate
            if r.resource_type == "work":
                hours = sum(a.work or 0.0 for a in assigned)
                units_total = sum(a.units for a in assigned)
                cost = sum(
                    a.cost if a.cost is not None else (a.work or 0.0) * (rate or 0.0)
                    for a in assigned
                )
            else:
                hours = 0.0
                units_total = sum(a.units for a in assigned)
                cost = sum(
                    a.cost if a.cost is not None else (a.units * (rate or 0.0) + (r.cost_per_use or 0.0))
                    for a in assigned
                )
            depth, is_summary = hierarchy.get(r.id, (0, False))
            parent_id = r.custom_fields.get("parent_id")
            rows.append(PersonWorkload(
                resource_id=r.id,
                name=r.name,
                rate=rate,
                hours_per_day=_hours_per_day(r) if r.resource_type == "work" else 0.0,
                task_count=len(assigned),
                hours=hours,
                cost=cost,
                resource_type=r.resource_type,
                group=str(r.custom_fields.get("group") or ""),
                material_label=str(r.custom_fields.get("material_label") or ""),
                initials=str(r.custom_fields.get("initials") or (r.name[:1] if r.name else "")),
                max_units=r.max_units,
                units_total=units_total,
                parent_id=parent_id if isinstance(parent_id, str) else None,
                depth=depth,
                is_summary=is_summary,
            ))
        return rows

    # ------------------------------------------------------------------
    # Project settings
    # ------------------------------------------------------------------

    def update_settings(
        self,
        *,
        name: str,
        description: str,
        start_date: date | None,
        currency: str,
        working_days: Sequence[int],
    ) -> None:
        name = _clean_text(name, "Project name")
        if currency not in CURRENCIES:
            raise SessionError(f"Currency must be one of: {', '.join(CURRENCIES)}.")
        days = sorted(set(int(d) for d in working_days))
        if not days or any(d < 0 or d > 6 for d in days):
            raise SessionError("Select at least one working day.")
        old_start = self.project.start_date
        if old_start is not None and start_date is not None and start_date != old_start:
            delta = start_date - old_start
            for task in self.project.tasks:
                if task.constraint_date is not None:
                    task.constraint_date = task.constraint_date + delta
                if task.schedule_mode == "manual":
                    if task.start_date is not None:
                        task.start_date = task.start_date + delta
                    if task.finish_date is not None:
                        task.finish_date = task.finish_date + delta
        elif start_date is None and old_start is not None:
            for task in self.project.tasks:
                if task.constraint_date == old_start:
                    task.constraint_date = None
                    task.constraint_type = None
        self.project.name = name
        self.project.description = description.strip()
        self.project.start_date = start_date
        self.project.currency = currency
        if self.project.calendars:
            self.project.calendars[0].working_days = days
        else:
            self.project.calendars.append(Calendar(name="Standard Working Week", working_days=days))
        self._changed()

    def rename_project(self, name: str) -> None:
        self.project.name = _clean_text(name, "Project name")
        self._changed()

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def overview(self) -> Overview:
        critical = [t for t in self.project.tasks if t.custom_fields.get("is_critical")]
        workloads = self.person_workloads()
        labour_cost = sum(w.cost for w in workloads if w.resource_type == "work")
        material_cost = sum(w.cost for w in workloads if w.resource_type != "work")
        task_est_cost = sum(t.estimated_cost or 0.0 for t in self.project.tasks)
        total_hours = sum(t.estimated_work or 0.0 for t in self.project.tasks)
        total_cost = max(task_est_cost, labour_cost + material_cost)
        work_count = sum(1 for r in self.project.resources if r.resource_type == "work")
        material_count = sum(1 for r in self.project.resources if r.resource_type != "work")
        return Overview(
            name=self.project.name,
            start_date=self.project.start_date,
            finish_date=self.project.finish_date,
            task_count=len(self.project.tasks),
            milestone_count=sum(1 for t in self.project.tasks if t.milestone or t.task_type == "milestone"),
            dependency_count=len(self.project.dependencies),
            resource_count=work_count,
            total_hours=total_hours,
            total_cost=total_cost,
            currency=self.project.currency,
            critical_tasks=critical,
            material_count=material_count,
            labour_cost=labour_cost,
            material_cost=material_cost,
        )

    def summary(self) -> ProjectSummary:
        return summarize_project(self.project)

    def summary_report_text(self, now: datetime | None = None) -> str:
        """Plain-text report, the same layout as the earlier web summary."""
        p = self.project
        symbol = CURRENCY_SYMBOLS.get(p.currency, p.currency)
        ov = self.overview()
        lines = [
            "PLANFORGE PROJECT SUMMARY REPORT",
            "=================================",
            f"Project Name: {p.name}",
            f"Description:  {p.description or 'None'}",
            f"Author:       {p.author or 'PlanForge'}",
            f"Currency:     {p.currency} ({symbol})",
            f"Start Date:   {_iso_or_unset(p.start_date)}",
            f"Finish Date:  {_iso_or_unset(p.finish_date)}",
            "",
            "KEY METRICS",
            "-----------",
            f"Total Tasks:        {len(p.tasks)}",
            f"Milestones:         {sum(1 for t in p.tasks if t.milestone)}",
            f"Dependencies:       {len(p.dependencies)}",
            f"Team Members:       {ov.resource_count}",
            f"Materials / Items:  {ov.material_count}",
            f"Estimated Hours:    {ov.total_hours:g} hours",
            f"Total Labour Cost:  {symbol}{ov.labour_cost if ov.labour_cost else ov.total_cost - ov.material_cost:,.2f}",
            f"Material Cost:      {symbol}{ov.material_cost:,.2f}",
            f"Total Project Cost: {symbol}{ov.total_cost:,.2f}",
            "",
            "CRITICAL PATH",
            "-------------",
        ]
        critical = [t for t in p.tasks if t.custom_fields.get("is_critical")]
        if critical:
            for t in critical:
                lines.append(f" * [{_iso_or_unset(t.start_date)} -> {_iso_or_unset(t.finish_date)}] "
                             f"{t.name} ({(t.duration or 1):g}d)")
        else:
            lines.append(" None detected or project not scheduled.")
        workloads = self.person_workloads()
        people_rows = [w for w in workloads if w.resource_type == "work"]
        material_rows = [w for w in workloads if w.resource_type != "work"]
        lines += ["", "TEAM ALLOCATION & COSTS", "-----------------------"]
        for w in people_rows:
            role_suffix = f" ({w.group})" if w.group else ""
            lines.append(f" * {w.name + role_suffix:<28}: {w.hours:>5g} hrs | {symbol}{w.cost:,.2f}")
        if material_rows:
            lines += ["", "MATERIALS & EQUIPMENT COSTS", "---------------------------"]
            for m in material_rows:
                unit_lbl = f" {m.material_label}" if m.material_label else ""
                lines.append(
                    f" * {m.name:<28}: {m.units_total:>5g}{unit_lbl} @ {symbol}{(m.rate or 0.0):,.2f} | {symbol}{m.cost:,.2f}"
                )
        lines += ["", f"Report generated on {(now or datetime.now()).isoformat(timespec='seconds')}"]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Function Point estimators
    # ------------------------------------------------------------------

    def add_estimator(self, name: str) -> dict:
        name = _clean_text(name, "Estimator name")
        person = estimation.fp_logic.make_person(name, DEFAULT_HOURLY_RATE, 2.5, 1.0)
        self.estimators.append(person)
        return person

    def estimator_totals(self) -> dict:
        totals = {"task_count": 0, "complex_points": 0, "simple_points": 0, "total_hours": 0.0, "total_cost": 0.0}
        for person in self.estimators:
            row = estimation.fp_logic.person_totals(person)
            for key in totals:
                totals[key] += row[key]
        return totals

    def transfer_estimates(self) -> int:
        """Copy every estimator's tasks into the project as scheduled tasks. Returns the task count."""
        if not self.estimators:
            raise SessionError("Add an estimator and at least one task before transferring.")
        try:
            cleaned = [estimation.fp_logic.clean_person(p, f"Estimator {i + 1}") for i, p in enumerate(self.estimators)]
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        document = {
            "application": estimation.FP_APP_NAME,
            "format_version": estimation.FP_FILE_FORMAT_VERSION,
            "saved": datetime.now().isoformat(),
            "people": cleaned,
        }
        imported = fp_import_bytes(json.dumps(document).encode("utf-8"))
        if not imported.success or imported.project is None:
            details = "; ".join(issue.message for issue in imported.errors)
            raise SessionError(f"Transfer failed: {details}")

        proj = self.project
        resource_by_name = {r.name.casefold(): r for r in proj.resources}
        id_map: dict[str, str] = {}
        for resource in imported.project.resources:
            existing = resource_by_name.get(resource.name.casefold())
            if existing is not None:
                id_map[resource.id] = existing.id
                if resource.standard_rate is not None:
                    existing.standard_rate = resource.standard_rate
            else:
                proj.resources.append(resource)
                resource_by_name[resource.name.casefold()] = resource
                id_map[resource.id] = resource.id

        start_order = len(proj.tasks)
        for index, task in enumerate(imported.project.tasks):
            task.order = start_order + index
            proj.tasks.append(task)
        for assignment in imported.project.assignments:
            assignment.resource_id = id_map.get(assignment.resource_id, assignment.resource_id)
            proj.assignments.append(assignment)

        self._changed()
        return len(imported.project.tasks)

    def clear_estimators(self) -> None:
        self.estimators.clear()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _clean_text(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise SessionError(f"{label} cannot be empty.")
    return text


def _check_rate_and_hours(rate: float, hours_per_day: float) -> tuple[float, float]:
    if rate is None or not math.isfinite(rate) or rate < 0:
        raise SessionError("Hourly rate must be a number of zero or more.")
    if hours_per_day is None or not math.isfinite(hours_per_day) or not 0 < hours_per_day <= 24:
        raise SessionError("Hours per day must be greater than 0 and no more than 24.")
    return float(rate), float(hours_per_day)


def _hours_per_day(resource: Resource | None) -> float:
    if resource is None:
        return DEFAULT_HOURS_PER_DAY
    try:
        value = float(resource.custom_fields.get("hours_per_day", DEFAULT_HOURS_PER_DAY))
    except (TypeError, ValueError):
        return DEFAULT_HOURS_PER_DAY
    return value if value > 0 else DEFAULT_HOURS_PER_DAY


def hours_per_point(resource: Resource, complexity: str) -> float:
    key = "hours_per_complex_point" if complexity == "complex" else "hours_per_simple_point"
    default = 2.5 if complexity == "complex" else 1.0
    try:
        return float(resource.custom_fields.get(key, default))
    except (TypeError, ValueError):
        return default


def _fp_estimate(edit: TaskEdit, hours: float, rate: float, currency: str) -> FunctionPointEstimate:
    return FunctionPointEstimate(
        counts={"function_points": int(edit.fp_points or 0)},
        complexities={"type": edit.fp_complexity or "complex"},
        function_points=float(edit.fp_points or 0),
        estimated_hours=hours,
        hourly_rate=rate,
        estimated_cost=hours * rate,
        currency=currency,
    )


def _iso_or_unset(value: date | None) -> str:
    return value.isoformat() if value else "Not set"


__all__ = [
    "CURRENCIES",
    "CURRENCY_SYMBOLS",
    "DEPENDENCY_LABELS",
    "DEPENDENCY_TYPES",
    "Overview",
    "PersonWorkload",
    "ProjectSession",
    "SessionError",
    "TaskEdit",
    "TaskRow",
    "WEEKDAY_NAMES",
    "create_default_project",
    "create_new_project",
    "format_money",
]
