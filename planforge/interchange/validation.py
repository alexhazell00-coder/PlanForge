"""Validation for the canonical project model and imported metadata."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable

from planforge.model import (
    Assignment,
    Calendar,
    Dependency,
    Project,
    Resource,
    Task,
    WorkingPeriod,
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors

    def by_code(self, code: str) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.code == code)


_RELATIONSHIP_TYPES = {
    "finish_to_start",
    "start_to_start",
    "finish_to_finish",
    "start_to_finish",
}
_DURATION_UNITS = {
    "minute",
    "hour",
    "day",
    "week",
    "month",
    "elapsed_minute",
    "elapsed_hour",
    "elapsed_day",
    "elapsed_week",
}
_WORK_UNITS = {"minute", "hour", "day", "week"}
_CONSTRAINT_TYPES = {
    None,
    "as_soon_as_possible",
    "as_late_as_possible",
    "must_start_on",
    "must_finish_on",
    "start_no_earlier_than",
    "start_no_later_than",
    "finish_no_earlier_than",
    "finish_no_later_than",
}


def _issue(issues: list[ValidationIssue], severity: str, code: str, path: str, message: str) -> None:
    issues.append(ValidationIssue(severity, code, path, message))


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512 and not any(
        ord(char) < 32 for char in value
    )


def _check_unique_ids(
    records: Iterable[object], *, kind: str, issues: list[ValidationIssue]
) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for index, record in enumerate(records):
        record_id = getattr(record, "id", None)
        path = f"{kind}[{index}].id"
        if not _valid_id(record_id):
            _issue(issues, "error", "id.invalid", path, "ID must be a non-empty string of at most 512 characters.")
            continue
        if record_id in indexed:
            _issue(
                issues,
                "error",
                "id.duplicate",
                path,
                f"Duplicate ID {record_id!r}.",
            )
        else:
            indexed[record_id] = record
    return indexed


def _check_number(
    value: object,
    path: str,
    issues: list[ValidationIssue],
    *,
    allow_none: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _issue(issues, "error", "number.invalid", path, "Expected a finite number.")
        return
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        _issue(issues, "error", "number.invalid", path, "Expected a finite number.")
        return
    if minimum is not None and value < minimum:
        _issue(issues, "error", "number.below_minimum", path, f"Value must be at least {minimum}.")
    if maximum is not None and value > maximum:
        _issue(issues, "error", "number.above_maximum", path, f"Value must be no more than {maximum}.")


def _is_date_only(value: object) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _check_date(value: object, path: str, issues: list[ValidationIssue], *, allow_none: bool = True) -> None:
    if value is None and allow_none:
        return
    if not _is_date_only(value):
        _issue(issues, "error", "date.invalid", path, "Expected a date-only value (YYYY-MM-DD), without a time or timezone.")


def _check_json_value(value: object, path: str, issues: list[ValidationIssue], depth: int = 0) -> None:
    if depth > 64:
        _issue(issues, "error", "metadata.too_deep", path, "Metadata nesting exceeds the limit of 64 levels.")
        return
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _issue(issues, "error", "metadata.non_finite_number", path, "Metadata numbers must be finite.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_json_value(item, f"{path}[{index}]", issues, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _issue(issues, "error", "metadata.key.invalid", path, "Metadata object keys must be strings.")
            else:
                _check_json_value(item, f"{path}.{key}", issues, depth + 1)
        return
    _issue(issues, "error", "metadata.value.invalid", path, f"Unsupported metadata value type: {type(value).__name__}.")


def _check_metadata(
    metadata: dict[str, object], path: str, issues: list[ValidationIssue]
) -> None:
    if not isinstance(metadata, dict):
        _issue(issues, "error", "metadata.object.required", path, "Expected an object of JSON-compatible values.")
        return
    _check_json_value(metadata, path, issues)


def _check_external_ids(external_ids: object, path: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(external_ids, dict):
        _issue(issues, "error", "external_ids.object.required", path, "Expected an object mapping source format names to IDs.")
        return
    for format_name, external_id in external_ids.items():
        if not isinstance(format_name, str) or not format_name.strip():
            _issue(issues, "error", "external_ids.format.invalid", path, "External ID format names must be non-empty strings.")
        if not isinstance(external_id, str) or not external_id:
            _issue(issues, "error", "external_ids.value.invalid", f"{path}.{format_name}", "External IDs must be non-empty strings.")


def _check_working_period(period: WorkingPeriod, path: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(period.start, time) or not isinstance(period.finish, time):
        _issue(issues, "error", "calendar.period.invalid", path, "Working-period boundaries must be local clock times.")
        return
    if period.start.tzinfo is not None or period.finish.tzinfo is not None:
        _issue(issues, "error", "calendar.period.timezone", path, "Calendar working times must be timezone-free local times.")
    if period.start >= period.finish:
        _issue(issues, "error", "calendar.period.order", path, "A working period must finish after it starts.")


def validate_project(project: Project) -> ValidationReport:
    """Return structural, reference, date, and dependency-cycle diagnostics."""

    issues: list[ValidationIssue] = []
    if not isinstance(project, Project):
        return ValidationReport((ValidationIssue("error", "project.type.invalid", "project", "Expected a Project instance."),))

    if not _valid_id(project.id):
        _issue(issues, "error", "project.id.invalid", "project.id", "Project ID must be a non-empty string of at most 512 characters.")
    if not isinstance(project.name, str) or not project.name.strip():
        _issue(issues, "error", "project.name.required", "project.name", "Project name must not be blank.")
    if not isinstance(project.currency, str) or not project.currency.strip() or len(project.currency) > 16:
        _issue(issues, "error", "project.currency.invalid", "project.currency", "Currency must be a non-empty short string code.")
    if project.schedule_mode not in {"auto", "manual"}:
        _issue(issues, "error", "project.schedule_mode.invalid", "project.schedule_mode", "Scheduling mode must be auto or manual.")
    for field_name in ("start_date", "finish_date"):
        _check_date(getattr(project, field_name), f"project.{field_name}", issues)
    if _is_date_only(project.start_date) and _is_date_only(project.finish_date) and project.start_date > project.finish_date:
        _issue(issues, "error", "project.date.order", "project", "Project finish date is before its start date.")
    if project.created_at is not None and not isinstance(project.created_at, datetime):
        _issue(issues, "error", "project.timestamp.invalid", "project.created_at", "Expected an ISO-compatible timestamp.")
    if project.modified_at is not None and not isinstance(project.modified_at, datetime):
        _issue(issues, "error", "project.timestamp.invalid", "project.modified_at", "Expected an ISO-compatible timestamp.")
    _check_external_ids(project.external_ids, "project.external_ids", issues)
    _check_metadata(project.custom_fields, "project.custom_fields", issues)
    _check_metadata(project.extensions, "project.extensions", issues)

    task_by_id = _check_unique_ids(project.tasks, kind="tasks", issues=issues)
    resource_by_id = _check_unique_ids(project.resources, kind="resources", issues=issues)
    calendar_by_id = _check_unique_ids(project.calendars, kind="calendars", issues=issues)
    _check_unique_ids(project.dependencies, kind="dependencies", issues=issues)
    _check_unique_ids(project.assignments, kind="assignments", issues=issues)

    if project.default_calendar_id is not None and project.default_calendar_id not in calendar_by_id:
        _issue(issues, "warning", "calendar.reference.missing", "project.default_calendar_id", "The default calendar ID does not refer to an imported calendar.")

    for index, task in enumerate(project.tasks):
        path = f"tasks[{index}]"
        if not isinstance(task.name, str) or not task.name.strip():
            _issue(issues, "error", "task.name.required", f"{path}.name", "Task name must not be blank.")
        _check_external_ids(task.external_ids, f"{path}.external_ids", issues)
        _check_date(task.start_date, f"{path}.start_date", issues)
        _check_date(task.finish_date, f"{path}.finish_date", issues)
        _check_date(task.deadline, f"{path}.deadline", issues)
        _check_date(task.constraint_date, f"{path}.constraint_date", issues)
        if task.outline_level is not None and (
            isinstance(task.outline_level, bool) or not isinstance(task.outline_level, int) or task.outline_level < 0
        ):
            _issue(issues, "error", "task.outline_level.invalid", f"{path}.outline_level", "Outline level must be a non-negative integer or null.")
        if isinstance(task.order, bool) or not isinstance(task.order, int):
            _issue(issues, "error", "task.order.invalid", f"{path}.order", "Task order must be an integer.")
        if _is_date_only(task.start_date) and _is_date_only(task.finish_date) and task.start_date > task.finish_date:
            _issue(issues, "error", "task.date.order", path, "Task finish date is before its start date.")
        if task.duration_unit not in _DURATION_UNITS:
            _issue(issues, "error", "task.duration_unit.invalid", f"{path}.duration_unit", f"Unsupported duration unit {task.duration_unit!r}.")
        _check_number(task.duration, f"{path}.duration", issues, minimum=0)
        _check_number(task.percent_complete, f"{path}.percent_complete", issues, allow_none=False, minimum=0, maximum=100)
        _check_number(task.priority, f"{path}.priority", issues)
        if task.task_type not in {"task", "milestone", "summary"}:
            _issue(issues, "error", "task.type.invalid", f"{path}.task_type", "Task type must be task, milestone, or summary.")
        if task.milestone and task.task_type not in {"task", "milestone"}:
            _issue(issues, "warning", "task.milestone.type_conflict", path, "Milestone flag conflicts with summary task type.")
        if task.milestone and task.duration not in (None, 0, 0.0):
            _issue(issues, "warning", "task.milestone.duration", f"{path}.duration", "A milestone has a non-zero duration.")
        if task.schedule_mode not in {"auto", "manual"}:
            _issue(issues, "error", "task.schedule_mode.invalid", f"{path}.schedule_mode", "Scheduling mode must be auto or manual.")
        if task.parent_id is not None and task.parent_id not in task_by_id:
            _issue(issues, "error", "task.parent.missing", f"{path}.parent_id", f"Parent task {task.parent_id!r} does not exist.")
        if task.parent_id == task.id:
            _issue(issues, "error", "task.parent.self", f"{path}.parent_id", "A task cannot be its own parent.")
        if task.calendar_id is not None and task.calendar_id not in calendar_by_id:
            _issue(issues, "warning", "calendar.reference.missing", f"{path}.calendar_id", f"Calendar {task.calendar_id!r} is not present in this project.")
        if task.constraint_type not in _CONSTRAINT_TYPES:
            _issue(issues, "warning", "task.constraint.unsupported", f"{path}.constraint_type", f"Unknown constraint type {task.constraint_type!r} is retained but may not be interpretable.")
        if task.work_unit not in _WORK_UNITS:
            _issue(issues, "error", "task.work_unit.invalid", f"{path}.work_unit", f"Unsupported work unit {task.work_unit!r}.")
        for field_name in ("estimated_work", "actual_work", "remaining_work", "estimated_cost", "actual_cost"):
            _check_number(getattr(task, field_name), f"{path}.{field_name}", issues, minimum=0)
        _check_metadata(task.custom_fields, f"{path}.custom_fields", issues)
        _check_metadata(task.extensions, f"{path}.extensions", issues)
        if task.function_points is not None:
            fp = task.function_points
            for category, count in fp.counts.items():
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    _issue(issues, "error", "function_points.count.invalid", f"{path}.function_points.counts.{category}", "Function point counts must be non-negative integers.")
            for category, complexity in fp.complexities.items():
                if not isinstance(complexity, str):
                    _issue(issues, "error", "function_points.complexity.invalid", f"{path}.function_points.complexities.{category}", "Complexity labels must be strings.")
            for field_name in ("function_points", "estimated_hours", "hourly_rate", "estimated_cost"):
                _check_number(getattr(fp, field_name), f"{path}.function_points.{field_name}", issues, minimum=0)
            _check_metadata(fp.extensions, f"{path}.function_points.extensions", issues)

    # Parent relationships form a graph with at most one outgoing edge per
    # task. Walk iteratively so a deep but valid outline cannot hit Python's
    # recursion limit while importing a large project.
    parent_edges = {
        task.id: task.parent_id
        for task in project.tasks
        if task.id in task_by_id and isinstance(task.parent_id, str) and task.parent_id in task_by_id
    }
    hierarchy_state: dict[str, int] = {}
    for start_id in parent_edges:
        if hierarchy_state.get(start_id) == 2:
            continue
        chain: list[str] = []
        position: dict[str, int] = {}
        current_id: str | None = start_id
        while current_id is not None and current_id in parent_edges and hierarchy_state.get(current_id, 0) != 2:
            if current_id in position:
                cycle = chain[position[current_id] :] + [current_id]
                _issue(issues, "error", "task.hierarchy.cycle", "tasks", "Task parent relationship contains a cycle: " + " -> ".join(cycle))
                break
            position[current_id] = len(chain)
            chain.append(current_id)
            hierarchy_state[current_id] = 1
            current_id = parent_edges.get(current_id)
        for task_id in chain:
            hierarchy_state[task_id] = 2

    dependency_ids: set[tuple[str, str, str]] = set()
    successors: dict[str, set[str]] = {}
    for index, dependency in enumerate(project.dependencies):
        path = f"dependencies[{index}]"
        if dependency.predecessor_id not in task_by_id:
            _issue(issues, "error", "dependency.predecessor.missing", f"{path}.predecessor_id", f"Task {dependency.predecessor_id!r} does not exist.")
        if dependency.successor_id not in task_by_id:
            _issue(issues, "error", "dependency.successor.missing", f"{path}.successor_id", f"Task {dependency.successor_id!r} does not exist.")
        if dependency.predecessor_id == dependency.successor_id:
            _issue(issues, "error", "dependency.self", path, "A task cannot depend on itself.")
        if dependency.relationship_type not in _RELATIONSHIP_TYPES:
            _issue(issues, "error", "dependency.type.invalid", f"{path}.relationship_type", f"Unsupported relationship type {dependency.relationship_type!r}.")
        if dependency.lag_unit not in _DURATION_UNITS:
            _issue(issues, "error", "dependency.lag_unit.invalid", f"{path}.lag_unit", f"Unsupported lag unit {dependency.lag_unit!r}.")
        _check_number(dependency.lag, f"{path}.lag", issues, allow_none=False)
        edge = (dependency.predecessor_id, dependency.successor_id, dependency.relationship_type)
        if edge in dependency_ids:
            _issue(issues, "warning", "dependency.duplicate", path, "Duplicate dependency relationship.")
        dependency_ids.add(edge)
        if dependency.predecessor_id in task_by_id and dependency.successor_id in task_by_id:
            successors.setdefault(dependency.predecessor_id, set()).add(dependency.successor_id)

    # Kahn's algorithm reports cycles without recursive traversal. This remains
    # safe for long chains of tens of thousands of tasks.
    indegree = {task_id: 0 for task_id in task_by_id}
    for targets in successors.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(task_id for task_id, count in indegree.items() if count == 0)
    visited_count = 0
    while ready:
        task_id = ready.popleft()
        visited_count += 1
        for successor_id in successors.get(task_id, ()):
            indegree[successor_id] -= 1
            if indegree[successor_id] == 0:
                ready.append(successor_id)
    if visited_count != len(indegree):
        blocked = [task_id for task_id, count in indegree.items() if count > 0]
        example = ", ".join(blocked[:10])
        suffix = "…" if len(blocked) > 10 else ""
        _issue(
            issues,
            "error",
            "dependency.cycle",
            "dependencies",
            f"Dependency graph contains a cycle; tasks blocked by the cyclic component include: {example}{suffix}.",
        )

    for index, resource in enumerate(project.resources):
        path = f"resources[{index}]"
        if not isinstance(resource.name, str) or not resource.name.strip():
            _issue(issues, "error", "resource.name.required", f"{path}.name", "Resource name must not be blank.")
        if resource.resource_type not in {"work", "material", "cost"}:
            _issue(issues, "warning", "resource.type.unknown", f"{path}.resource_type", f"Unknown resource type {resource.resource_type!r} is retained.")
        _check_number(resource.max_units, f"{path}.max_units", issues, allow_none=False, minimum=0)
        for field_name in ("standard_rate", "overtime_rate", "cost_per_use"):
            _check_number(getattr(resource, field_name), f"{path}.{field_name}", issues, minimum=0)
        if resource.calendar_id is not None and resource.calendar_id not in calendar_by_id:
            _issue(issues, "warning", "calendar.reference.missing", f"{path}.calendar_id", f"Calendar {resource.calendar_id!r} is not present in this project.")
        _check_external_ids(resource.external_ids, f"{path}.external_ids", issues)
        _check_metadata(resource.custom_fields, f"{path}.custom_fields", issues)
        _check_metadata(resource.extensions, f"{path}.extensions", issues)
        for availability_index, availability in enumerate(resource.availability):
            availability_path = f"{path}.availability[{availability_index}]"
            _check_date(availability.start_date, f"{availability_path}.start_date", issues, allow_none=False)
            _check_date(availability.finish_date, f"{availability_path}.finish_date", issues, allow_none=False)
            _check_number(availability.units, f"{availability_path}.units", issues, allow_none=False, minimum=0)
            if _is_date_only(availability.start_date) and _is_date_only(availability.finish_date) and availability.start_date > availability.finish_date:
                _issue(issues, "error", "resource.availability.date.order", availability_path, "Availability finish date is before its start date.")
            _check_metadata(availability.extensions, f"{availability_path}.extensions", issues)

    for index, assignment in enumerate(project.assignments):
        path = f"assignments[{index}]"
        if assignment.task_id not in task_by_id:
            _issue(issues, "error", "assignment.task.missing", f"{path}.task_id", f"Task {assignment.task_id!r} does not exist.")
        if assignment.resource_id not in resource_by_id:
            _issue(issues, "error", "assignment.resource.missing", f"{path}.resource_id", f"Resource {assignment.resource_id!r} does not exist.")
        _check_number(assignment.units, f"{path}.units", issues, allow_none=False, minimum=0)
        if assignment.work_unit not in _WORK_UNITS:
            _issue(issues, "error", "assignment.work_unit.invalid", f"{path}.work_unit", f"Unsupported work unit {assignment.work_unit!r}.")
        for field_name in ("work", "actual_work", "remaining_work", "cost", "actual_cost"):
            _check_number(getattr(assignment, field_name), f"{path}.{field_name}", issues, minimum=0)
        _check_date(assignment.start_date, f"{path}.start_date", issues)
        _check_date(assignment.finish_date, f"{path}.finish_date", issues)
        if _is_date_only(assignment.start_date) and _is_date_only(assignment.finish_date) and assignment.start_date > assignment.finish_date:
            _issue(issues, "error", "assignment.date.order", path, "Assignment finish date is before its start date.")
        _check_external_ids(assignment.external_ids, f"{path}.external_ids", issues)
        _check_metadata(assignment.custom_fields, f"{path}.custom_fields", issues)
        _check_metadata(assignment.extensions, f"{path}.extensions", issues)

    for index, calendar in enumerate(project.calendars):
        path = f"calendars[{index}]"
        if not isinstance(calendar.name, str) or not calendar.name.strip():
            _issue(issues, "error", "calendar.name.required", f"{path}.name", "Calendar name must not be blank.")
        seen_weekdays: set[int] = set()
        for day in calendar.working_days:
            if isinstance(day, bool) or not isinstance(day, int) or day < 0 or day > 6:
                _issue(issues, "error", "calendar.working_days.invalid", f"{path}.working_days", "Working days must be integers from 0 (Monday) to 6 (Sunday).")
                break
            if day in seen_weekdays:
                _issue(issues, "error", "calendar.working_days.duplicate", f"{path}.working_days", f"Weekday {day} is listed more than once.")
                break
            seen_weekdays.add(day)
        for weekday, periods in calendar.working_periods.items():
            if isinstance(weekday, bool) or not isinstance(weekday, int) or weekday not in range(7):
                _issue(issues, "error", "calendar.weekday.invalid", f"{path}.working_periods", "Calendar weekdays must be integers from 0 to 6.")
                continue
            previous_finish: time | None = None
            for period_index, period in enumerate(periods):
                period_path = f"{path}.working_periods.{weekday}[{period_index}]"
                _check_working_period(period, period_path, issues)
                _check_metadata(period.extensions, f"{period_path}.extensions", issues)
                if isinstance(period.start, time) and previous_finish is not None and period.start < previous_finish:
                    _issue(issues, "error", "calendar.period.overlap", period_path, "Working periods must be ordered and must not overlap.")
                if isinstance(period.finish, time):
                    previous_finish = period.finish
        for holiday_index, holiday in enumerate(calendar.holidays):
            _check_date(holiday, f"{path}.holidays[{holiday_index}]", issues, allow_none=False)
        for exception_index, exception in enumerate(calendar.exceptions):
            exception_path = f"{path}.exceptions[{exception_index}]"
            _check_date(exception.start_date, f"{exception_path}.start_date", issues, allow_none=False)
            _check_date(exception.finish_date, f"{exception_path}.finish_date", issues, allow_none=False)
            if _is_date_only(exception.start_date) and _is_date_only(exception.finish_date) and exception.start_date > exception.finish_date:
                _issue(issues, "error", "calendar.exception.date.order", exception_path, "Calendar exception finish date is before its start date.")
            for period_index, period in enumerate(exception.working_periods):
                period_path = f"{exception_path}.working_periods[{period_index}]"
                _check_working_period(period, period_path, issues)
                _check_metadata(period.extensions, f"{period_path}.extensions", issues)
            _check_metadata(exception.extensions, f"{exception_path}.extensions", issues)
        _check_external_ids(calendar.external_ids, f"{path}.external_ids", issues)
        _check_metadata(calendar.extensions, f"{path}.extensions", issues)

    return ValidationReport(tuple(issues))


__all__ = ["ValidationIssue", "ValidationReport", "validate_project"]
