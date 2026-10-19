"""Mapped UTF-8 CSV task-list adapter.

The default template is one row per task. Project-level objects and custom
fields use documented JSON-in-cell columns, so CSV can retain more than a
plain task-name export without pretending that ordinary CSV has native
scheduling semantics.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from planforge.interchange.json_adapter import (
    _parse_assignment,
    _parse_calendar,
    _parse_dependency,
    _parse_function_points,
    _parse_resource,
    _with_unknown_fields,
)
from planforge.interchange.results import ExportResult, ImportResult
from planforge.interchange.validation import ValidationIssue, validate_project
from planforge.model import Assignment, Dependency, Project, Resource, Task

FORMAT_ID = "csv"
FORMAT_NAME = "CSV task list"
MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_IMPORT_ROWS = 250_000

# The template is also the documented CSV contract. JSON-in-cell columns are
# compact structured values, quoted according to RFC 4180 by csv.writer.
CSV_COLUMNS = (
    "project_id",
    "project_name",
    "project_description",
    "project_author",
    "project_external_ids_json",
    "project_created_at",
    "project_modified_at",
    "project_start_date",
    "project_finish_date",
    "project_schedule_mode",
    "project_default_calendar_id",
    "project_currency",
    "project_status",
    "project_custom_fields_json",
    "project_extensions_json",
    "resources_json",
    "calendars_json",
    "task_id",
    "task_name",
    "description",
    "parent_id",
    "outline_level",
    "order",
    "start_date",
    "finish_date",
    "duration",
    "duration_unit",
    "percent_complete",
    "priority",
    "milestone",
    "task_type",
    "schedule_mode",
    "calendar_id",
    "deadline",
    "constraint_type",
    "constraint_date",
    "estimated_work",
    "actual_work",
    "remaining_work",
    "work_unit",
    "estimated_cost",
    "actual_cost",
    "dependencies_json",
    "assignments_json",
    "task_external_ids_json",
    "custom_fields_json",
    "function_points_json",
    "task_extensions_json",
)

_PROJECT_FIELDS = {
    "project_id", "project_name", "project_description", "project_author", "project_external_ids_json", "project_created_at", "project_modified_at",
    "project_start_date", "project_finish_date", "project_schedule_mode", "project_default_calendar_id", "project_currency",
    "project_status", "project_custom_fields_json", "project_extensions_json", "resources_json", "calendars_json",
}
_TASK_FIELDS = set(CSV_COLUMNS) - _PROJECT_FIELDS

# Header aliases are intentionally conservative and deterministic. Importers
# can override any field through CsvImportOptions.column_mapping.
_HEADER_ALIASES = {
    "id": "task_id",
    "uid": "task_id",
    "taskid": "task_id",
    "task_id": "task_id",
    "task": "task_name",
    "taskname": "task_name",
    "task_name": "task_name",
    "name": "task_name",
    "title": "task_name",
    "activity": "task_name",
    "item": "task_name",
    "subject": "task_name",
    "description": "description",
    "notes": "description",
    "details": "description",
    "parent": "parent_id",
    "parentid": "parent_id",
    "parent_id": "parent_id",
    "outlinelevel": "outline_level",
    "outline_level": "outline_level",
    "order": "order",
    "sequence": "order",
    "start": "start_date",
    "startdate": "start_date",
    "start_date": "start_date",
    "begin": "start_date",
    "from": "start_date",
    "finish": "finish_date",
    "end": "finish_date",
    "enddate": "finish_date",
    "finishdate": "finish_date",
    "finish_date": "finish_date",
    "to": "finish_date",
    "due": "finish_date",
    "duedate": "finish_date",
    "duration": "duration",
    "durationunit": "duration_unit",
    "duration_unit": "duration_unit",
    "percentcomplete": "percent_complete",
    "percent_complete": "percent_complete",
    "percent": "percent_complete",
    "complete": "percent_complete",
    "completion": "percent_complete",
    "done": "percent_complete",
    "progress": "percent_complete",
    "priority": "priority",
    "milestone": "milestone",
    "type": "task_type",
    "tasktype": "task_type",
    "task_type": "task_type",
    "schedulingmode": "schedule_mode",
    "schedule_mode": "schedule_mode",
    "deadline": "deadline",
    "constraint": "constraint_type",
    "constrainttype": "constraint_type",
    "constraint_type": "constraint_type",
    "constraintdate": "constraint_date",
    "constraint_date": "constraint_date",
    "estimatedwork": "estimated_work",
    "estimated_work": "estimated_work",
    "work": "estimated_work",
    "effort": "estimated_work",
    "hours": "estimated_work",
    "actualwork": "actual_work",
    "actual_work": "actual_work",
    "remainingwork": "remaining_work",
    "remaining_work": "remaining_work",
    "workunit": "work_unit",
    "work_unit": "work_unit",
    "estimatedcost": "estimated_cost",
    "estimated_cost": "estimated_cost",
    "cost": "estimated_cost",
    "budget": "estimated_cost",
    "actualcost": "actual_cost",
    "actual_cost": "actual_cost",
    "dependencies": "dependencies_json",
    "predecessors": "predecessors",
    "depends": "predecessors",
    "depends_on": "predecessors",
    "resources": "resource_names",
    "resource": "resource_names",
    "resource_names": "resource_names",
    "assigned_to": "resource_names",
    "assignee": "resource_names",
    "owner": "resource_names",
    "people": "resource_names",
    "staff": "resource_names",
    "assignments": "assignments_json",
    "resources_json": "resources_json",
    "currency": "project_currency",
    "project_name": "project_name",
    "project_id": "project_id",
}

_TARGET_ALIASES = {
    "id": "task_id",
    "name": "task_name",
    "task": "task_name",
    "dependencies": "dependencies_json",
    "resources": "resource_names",
    "resource": "resource_names",
    "predecessors": "predecessors",
    "custom_fields": "custom_fields_json",
    "function_points": "function_points_json",
    "extensions": "task_extensions_json",
}


def _normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().casefold()).strip("_")


def _target_name(target: str) -> str:
    normalized = _normalize_header(target)
    return _TARGET_ALIASES.get(normalized, normalized)


@dataclass(frozen=True, slots=True)
class CsvImportOptions:
    """CSV mapping. ``column_mapping`` maps PlanForge target -> source header."""

    column_mapping: Mapping[str, str] = field(default_factory=dict)
    delimiter: str | None = None
    project_name: str | None = None


def suggest_column_mapping(headers: list[str]) -> dict[str, str]:
    """Suggest a target-to-header mapping based on common header aliases."""

    mapping: dict[str, str] = {}
    seen_targets: set[str] = set()
    for header in headers:
        normalized = _normalize_header(header)
        target = _HEADER_ALIASES.get(normalized)
        if target and target not in seen_targets:
            mapping[target] = header
            seen_targets.add(target)
    # Exact template project fields are also recognized even when not aliased.
    for header in headers:
        normalized = _normalize_header(header)
        if normalized in _PROJECT_FIELDS and normalized not in seen_targets:
            mapping[normalized] = header
            seen_targets.add(normalized)
        elif normalized in _TASK_FIELDS and normalized not in seen_targets:
            mapping[normalized] = header
            seen_targets.add(normalized)
    return mapping


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)


def _json_loads(value: str, path: str) -> Any:
    def reject_constant(token: str) -> None:
        raise ValueError(f"non-standard JSON number {token}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = item
        return result

    try:
        return json.loads(value, parse_constant=reject_constant, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{path}: invalid JSON in CSV cell: {exc}") from exc


def _parse_date(value: str | None, path: str) -> date | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{path}: expected an ISO date (YYYY-MM-DD), got {text!r}") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{path}: expected date-only YYYY-MM-DD, got {text!r}")
    return parsed


def _parse_datetime(value: str | None, path: str) -> datetime | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ValueError(f"{path}: expected an ISO timestamp, got {text!r}") from exc


def _parse_number(value: str | None, path: str, *, percent: bool = False) -> float | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if percent and text.endswith("%"):
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{path}: expected a number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{path}: value must be finite")
    return number


def _parse_integer(value: str | None, path: str) -> int | None:
    number = _parse_number(value, path)
    if number is None:
        return None
    if not number.is_integer():
        raise ValueError(f"{path}: expected a whole number, got {value!r}")
    return int(number)


def _parse_bool(value: str | None, path: str, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"true", "yes", "y", "1", "milestone"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    raise ValueError(f"{path}: expected true/false, yes/no, or 1/0, got {value!r}")


def _cell(row: Mapping[str, str | None], mapping: Mapping[str, str], target: str) -> str | None:
    header = mapping.get(target)
    if header is None:
        return None
    return row.get(header)


def _json_cell(row: Mapping[str, str | None], mapping: Mapping[str, str], target: str, default: Any) -> Any:
    raw = _cell(row, mapping, target)
    return default if raw is None or not raw.strip() else _json_loads(raw, target)


def _make_id(prefix: str, source_digest: str, row_number: int | str) -> str:
    return str(uuid5(NAMESPACE_URL, f"planforge:csv:{source_digest}:{prefix}:{row_number}"))


def _date_text(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _assignment_to_dict(assignment: Assignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "task_id": assignment.task_id,
        "resource_id": assignment.resource_id,
        "units": assignment.units,
        "work": assignment.work,
        "work_unit": assignment.work_unit,
        "actual_work": assignment.actual_work,
        "remaining_work": assignment.remaining_work,
        "cost": assignment.cost,
        "actual_cost": assignment.actual_cost,
        "start_date": _date_text(assignment.start_date) or None,
        "finish_date": _date_text(assignment.finish_date) or None,
        "external_ids": assignment.external_ids,
        "custom_fields": assignment.custom_fields,
        "extensions": assignment.extensions,
    }


def _project_resources_to_dict(project: Project) -> list[dict[str, Any]]:
    from planforge.interchange.json_adapter import _resource_to_document

    return [_resource_to_document(resource) for resource in project.resources]


def _project_calendars_to_dict(project: Project) -> list[dict[str, Any]]:
    from planforge.interchange.json_adapter import _calendar_to_document

    return [_calendar_to_document(calendar) for calendar in project.calendars]


def _record_conflicts(
    records: list[dict[str, str | None]],
    mapping: Mapping[str, str],
    target: str,
    path: str,
    issues: list[ValidationIssue],
) -> str | None:
    values = []
    for row in records:
        value = _cell(row, mapping, target)
        if value is not None and value.strip():
            if value not in values:
                values.append(value)
    if len(values) > 1:
        issues.append(_issue(
            "warning", "csv.project_value.conflict", path,
            f"Conflicting values were found for {target}; the first non-empty value {values[0]!r} was used.",
        ))
    return values[0] if values else None


def _mapping_for(headers: list[str], options: CsvImportOptions) -> tuple[dict[str, str], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    suggestions = suggest_column_mapping(headers)
    mapping = dict(suggestions)
    header_lookup = {_normalize_header(header): header for header in headers}
    allowed = set(CSV_COLUMNS) | {"resource_names", "predecessors"}
    for raw_target, source_header in options.column_mapping.items():
        target = _target_name(raw_target)
        if target not in allowed:
            issues.append(_issue("error", "csv.mapping.target.invalid", "column_mapping", f"Unknown PlanForge field {raw_target!r}."))
            continue
        if not isinstance(source_header, str):
            issues.append(_issue("error", "csv.mapping.header.invalid", f"column_mapping.{raw_target}", "Mapped source header must be a string."))
            continue
        actual_header = header_lookup.get(_normalize_header(source_header))
        if actual_header is None:
            issues.append(_issue("error", "csv.mapping.header.missing", f"column_mapping.{raw_target}", f"Source column {source_header!r} was not found."))
            continue
        mapping[target] = actual_header
    return mapping, issues


def _parse_simple_resource_names(
    names_text: str,
    task_id: str,
    source_digest: str,
    row_number: int,
    resources_by_id: dict[str, Resource],
    issues: list[ValidationIssue],
) -> list[Assignment]:
    # A plain CSV resource column cannot encode delimiters within names. The
    # JSON-in-cell assignments_json column is the loss-minimizing alternative.
    names = [name.strip() for name in re.split(r"[;|]", names_text) if name.strip()]
    assignments: list[Assignment] = []
    by_name = {resource.name.casefold(): resource for resource in resources_by_id.values()}
    for name in names:
        key = name.casefold()
        resource = by_name.get(key)
        if resource is None:
            resource = Resource(id=_make_id("resource-" + key, source_digest, row_number), name=name)
            resources_by_id[resource.id] = resource
            by_name[key] = resource
        assignments.append(Assignment(task_id=task_id, resource_id=resource.id, units=1.0))
    if names:
        issues.append(_issue(
            "warning", "csv.resource_names.assumed_identity", f"tasks[{row_number}].resource_names",
            "Resource names were grouped within this imported CSV because no resource IDs were supplied; review them before merging with another project.",
        ))
    return assignments


def import_bytes(
    data: bytes,
    *,
    options: CsvImportOptions | None = None,
    source_name: str | None = None,
) -> ImportResult:
    """Read a UTF-8 CSV file, optionally using caller-provided column mapping."""

    options = options or CsvImportOptions()
    if not isinstance(data, bytes):
        return ImportResult(FORMAT_ID, None, (_issue("error", "file.data.invalid", "$", "Input must be bytes."),))
    if len(data) > MAX_IMPORT_BYTES:
        return ImportResult(FORMAT_ID, None, (_issue("error", "file.too_large", "$", f"File exceeds the {MAX_IMPORT_BYTES}-byte import limit."),))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportResult(FORMAT_ID, None, (_issue("error", "csv.encoding.invalid", "$", "CSV input must be UTF-8 encoded."),))
    if not text.strip():
        return ImportResult(FORMAT_ID, None, (_issue("error", "csv.empty", "$", "The CSV file is empty."),))

    delimiter = options.delimiter
    if delimiter is not None and (len(delimiter) != 1 or delimiter in {"\r", "\n", '"'}):
        return ImportResult(FORMAT_ID, None, (_issue("error", "csv.delimiter.invalid", "$", "Delimiter must be one ordinary character."),))
    if delimiter is None:
        try:
            dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        raw_headers = reader.fieldnames
        if not raw_headers:
            return ImportResult(FORMAT_ID, None, (_issue("error", "csv.header.missing", "$", "A header row is required. Use the field-mapping workflow for unfamiliar CSV files."),))
        headers = [str(header) for header in raw_headers]
        normalized_headers = [_normalize_header(header) for header in headers]
        if len(normalized_headers) != len(set(normalized_headers)):
            return ImportResult(FORMAT_ID, None, (_issue("error", "csv.header.duplicate", "$", "CSV contains duplicate or ambiguous column headers."),))
        rows: list[dict[str, str | None]] = []
        for row_index, row in enumerate(reader):
            if row_index >= MAX_IMPORT_ROWS:
                return ImportResult(FORMAT_ID, None, (_issue(
                    "error", "csv.too_many_rows", "$",
                    f"CSV exceeds the {MAX_IMPORT_ROWS}-row import limit.",
                ),))
            if None in row:
                return ImportResult(FORMAT_ID, None, (_issue("error", "csv.row.too_many_fields", f"line {reader.line_num}", "Row has more values than the header."),))
            rows.append({str(key): value for key, value in row.items() if key is not None})
    except csv.Error as exc:
        return ImportResult(FORMAT_ID, None, (_issue("error", "csv.parse.invalid", "$", f"Malformed CSV: {exc}"),))

    mapping, mapping_issues = _mapping_for(headers, options)
    if any(issue.severity == "error" for issue in mapping_issues):
        return ImportResult(FORMAT_ID, None, tuple(mapping_issues))
    if "task_name" not in mapping:
        return ImportResult(FORMAT_ID, None, tuple(mapping_issues) + (_issue(
            "error", "csv.mapping.task_name.required", "column_mapping",
            "No task-name column was detected. Map a column to task_name before importing.",
        ),))

    digest = hashlib.sha256(data).hexdigest()
    issues = list(mapping_issues)
    nonempty_rows = [row for row in rows if any(value not in (None, "") for value in row.values())]
    project_scalar_targets = (
        "project_id", "project_name", "project_description", "project_author", "project_created_at",
        "project_modified_at", "project_start_date", "project_finish_date", "project_schedule_mode",
        "project_default_calendar_id", "project_currency", "project_status",
    )
    project_values = {
        target: _record_conflicts(nonempty_rows, mapping, target, f"project.{target}", issues)
        for target in project_scalar_targets
    }
    fallback_name = options.project_name
    if not fallback_name and source_name:
        fallback_name = source_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    project_name = project_values["project_name"] or fallback_name or "Imported CSV project"
    project_id = project_values["project_id"] or str(uuid5(NAMESPACE_URL, f"planforge:csv:project:{digest}"))

    try:
        project_created = _parse_datetime(project_values["project_created_at"], "project_created_at")
        project_modified = _parse_datetime(project_values["project_modified_at"], "project_modified_at")
        project_start = _parse_date(project_values["project_start_date"], "project_start_date")
        project_finish = _parse_date(project_values["project_finish_date"], "project_finish_date")
        project_external_ids = _json_loads(_record_conflicts(nonempty_rows, mapping, "project_external_ids_json", "project.external_ids", issues) or "{}", "project_external_ids_json")
        project_custom_fields = _json_loads(_record_conflicts(nonempty_rows, mapping, "project_custom_fields_json", "project.custom_fields", issues) or "{}", "project_custom_fields_json")
        project_extensions = _json_loads(_record_conflicts(nonempty_rows, mapping, "project_extensions_json", "project.extensions", issues) or "{}", "project_extensions_json")
        calendars_value = _json_loads(_record_conflicts(nonempty_rows, mapping, "calendars_json", "project.calendars", issues) or "[]", "calendars_json")
        resources_value = _json_loads(_record_conflicts(nonempty_rows, mapping, "resources_json", "project.resources", issues) or "[]", "resources_json")
    except ValueError as exc:
        return ImportResult(FORMAT_ID, None, tuple(issues) + (_issue("error", "csv.value.invalid", "$", str(exc)),))

    if not isinstance(project_external_ids, dict) or not isinstance(project_custom_fields, dict) or not isinstance(project_extensions, dict):
        return ImportResult(FORMAT_ID, None, tuple(issues) + (_issue("error", "csv.project.json_column.invalid", "project", "Project external IDs, custom fields, and extensions columns must contain JSON objects."),))
    if not isinstance(calendars_value, list) or not isinstance(resources_value, list):
        return ImportResult(FORMAT_ID, None, tuple(issues) + (_issue("error", "csv.project.json_column.invalid", "project", "calendars_json and resources_json must contain JSON arrays."),))

    try:
        calendars = []
        for index, item in enumerate(calendars_value):
            if isinstance(item, dict) and not item.get("id"):
                item = {**item, "id": _make_id("calendar", digest, index)}
            calendars.append(_parse_calendar(item, f"calendars_json[{index}]"))
        resources = []
        for index, item in enumerate(resources_value):
            if isinstance(item, dict) and not item.get("id"):
                item = {**item, "id": _make_id("resource", digest, index)}
            resources.append(_parse_resource(item, f"resources_json[{index}]"))
    except (ValueError, TypeError) as exc:
        return ImportResult(FORMAT_ID, None, tuple(issues) + (_issue("error", "csv.project.json_column.invalid", "project", str(exc)),))
    resources_by_id = {resource.id: resource for resource in resources}
    if len(resources_by_id) != len(resources):
        issues.append(_issue("error", "csv.resource.id.duplicate", "resources_json", "Duplicate resource IDs were found."))

    tasks: list[Task] = []
    dependencies: list[Dependency] = []
    assignments: list[Assignment] = []
    used_headers = set(mapping.values())
    unmapped_headers = [header for header in headers if header not in used_headers]
    if unmapped_headers:
        issues.append(_issue(
            "warning", "csv.columns.unmapped", "columns",
            "Unmapped columns will be retained on each task as text metadata: " + ", ".join(unmapped_headers),
        ))

    try:
        for row_index, row in enumerate(rows):
            task_name = _cell(row, mapping, "task_name")
            if task_name is None or not task_name.strip():
                # A metadata-only row is valid (and is used for an empty project).
                continue
            task_id_raw = _cell(row, mapping, "task_id")
            task_id = task_id_raw if task_id_raw and task_id_raw.strip() else _make_id("task", digest, row_index)
            if not task_id_raw or not task_id_raw.strip():
                issues.append(_issue("warning", "csv.task.id.generated", f"rows[{row_index}].task_id", "A stable task ID was generated because the CSV had no task ID value."))
            parent_id = _cell(row, mapping, "parent_id")
            parent_id = parent_id if parent_id and parent_id.strip() else None
            type_raw = _cell(row, mapping, "task_type")
            schedule_mode_raw = _cell(row, mapping, "schedule_mode")
            duration_unit_raw = _cell(row, mapping, "duration_unit")
            work_unit_raw = _cell(row, mapping, "work_unit")
            task_order = _parse_integer(_cell(row, mapping, "order"), f"rows[{row_index}].order")
            if task_order is None:
                task_order = row_index
            calendar_id = _cell(row, mapping, "calendar_id")
            if not calendar_id or not calendar_id.strip():
                calendar_id = None
            constraint_type = _cell(row, mapping, "constraint_type")
            if not constraint_type or not constraint_type.strip():
                constraint_type = None
            task = Task(
                id=task_id,
                name=task_name,
                description=_cell(row, mapping, "description") or "",
                parent_id=parent_id,
                outline_level=_parse_integer(_cell(row, mapping, "outline_level"), f"rows[{row_index}].outline_level"),
                order=task_order,
                start_date=_parse_date(_cell(row, mapping, "start_date"), f"rows[{row_index}].start_date"),
                finish_date=_parse_date(_cell(row, mapping, "finish_date"), f"rows[{row_index}].finish_date"),
                duration=_parse_number(_cell(row, mapping, "duration"), f"rows[{row_index}].duration"),
                duration_unit=(duration_unit_raw or "day").strip().lower(),
                percent_complete=_parse_number(_cell(row, mapping, "percent_complete"), f"rows[{row_index}].percent_complete", percent=True) or 0.0,
                priority=_parse_integer(_cell(row, mapping, "priority"), f"rows[{row_index}].priority"),
                milestone=_parse_bool(_cell(row, mapping, "milestone"), f"rows[{row_index}].milestone"),
                task_type=(type_raw or "task").strip().lower(),
                schedule_mode=(schedule_mode_raw or "auto").strip().lower(),
                calendar_id=calendar_id,
                deadline=_parse_date(_cell(row, mapping, "deadline"), f"rows[{row_index}].deadline"),
                constraint_type=constraint_type,
                constraint_date=_parse_date(_cell(row, mapping, "constraint_date"), f"rows[{row_index}].constraint_date"),
                estimated_work=_parse_number(_cell(row, mapping, "estimated_work"), f"rows[{row_index}].estimated_work"),
                actual_work=_parse_number(_cell(row, mapping, "actual_work"), f"rows[{row_index}].actual_work"),
                remaining_work=_parse_number(_cell(row, mapping, "remaining_work"), f"rows[{row_index}].remaining_work"),
                work_unit=(work_unit_raw or "hour").strip().lower(),
                estimated_cost=_parse_number(_cell(row, mapping, "estimated_cost"), f"rows[{row_index}].estimated_cost"),
                actual_cost=_parse_number(_cell(row, mapping, "actual_cost"), f"rows[{row_index}].actual_cost"),
            )
            task.external_ids = _json_cell(row, mapping, "task_external_ids_json", {})
            task.custom_fields = _json_cell(row, mapping, "custom_fields_json", {})
            task.function_points = _parse_function_points(
                _json_cell(row, mapping, "function_points_json", None),
                f"rows[{row_index}].function_points_json",
            )
            task_extensions = _json_cell(row, mapping, "task_extensions_json", {})
            if not isinstance(task.external_ids, dict) or not isinstance(task.custom_fields, dict) or not isinstance(task_extensions, dict):
                raise ValueError(f"rows[{row_index}]: JSON metadata columns must contain objects")
            # Unknown columns are retained, including empty values only when the
            # column was intentionally populated (empty is meaningful in some exports).
            unknown_values = {
                header: row.get(header)
                for header in unmapped_headers
                if row.get(header) not in (None, "")
            }
            task.extensions = _with_unknown_fields(
                task_extensions,
                {"org.planforge.csv:unmapped_columns": unknown_values} if unknown_values else {},
            )
            tasks.append(task)

            dependency_values = _json_cell(row, mapping, "dependencies_json", [])
            if not isinstance(dependency_values, list):
                raise ValueError(f"rows[{row_index}].dependencies_json: expected a JSON array")
            for dependency_index, dependency_value in enumerate(dependency_values):
                if isinstance(dependency_value, str):
                    dependency_value = {"predecessor_id": dependency_value}
                if not isinstance(dependency_value, dict):
                    raise ValueError(f"rows[{row_index}].dependencies_json[{dependency_index}]: expected an object or predecessor ID string")
                if "successor_id" not in dependency_value:
                    dependency_value = {**dependency_value, "successor_id": task.id}
                if not dependency_value.get("id"):
                    dependency_value = {
                        **dependency_value,
                        "id": _make_id("dependency", digest, f"{row_index}:{dependency_index}"),
                    }
                dependencies.append(_parse_dependency(dependency_value, f"rows[{row_index}].dependencies_json[{dependency_index}]"))

            legacy_predecessors = _cell(row, mapping, "predecessors")
            if legacy_predecessors and legacy_predecessors.strip():
                for predecessor_id in re.split(r"[;|]", legacy_predecessors):
                    predecessor_id = predecessor_id.strip()
                    if predecessor_id:
                        dependencies.append(Dependency(
                            predecessor_id=predecessor_id,
                            successor_id=task.id,
                            relationship_type="finish_to_start",
                            lag=0,
                            lag_unit="day",
                        ))
                issues.append(_issue(
                    "warning", "csv.dependencies.assumed_finish_to_start", f"rows[{row_index}].predecessors",
                    "Predecessor IDs were interpreted as finish-to-start links with zero lag.",
                ))

            assignment_values = _json_cell(row, mapping, "assignments_json", [])
            if not isinstance(assignment_values, list):
                raise ValueError(f"rows[{row_index}].assignments_json: expected a JSON array")
            for assignment_index, assignment_value in enumerate(assignment_values):
                if not isinstance(assignment_value, dict):
                    raise ValueError(f"rows[{row_index}].assignments_json[{assignment_index}]: expected an object")
                resource_value = assignment_value.get("resource")
                if isinstance(resource_value, dict) and not resource_value.get("id"):
                    resource_value = {
                        **resource_value,
                        "id": _make_id("assignment-resource", digest, f"{row_index}:{assignment_index}"),
                    }
                    assignment_value = {**assignment_value, "resource": resource_value}
                if resource_value is not None:
                    resource = _parse_resource(resource_value, f"rows[{row_index}].assignments_json[{assignment_index}].resource")
                    previous = resources_by_id.get(resource.id)
                    if previous is not None and previous != resource:
                        raise ValueError(f"resource ID {resource.id!r} has conflicting definitions")
                    resources_by_id[resource.id] = resource
                    assignment_value = {key: value for key, value in assignment_value.items() if key != "resource"}
                    assignment_value.setdefault("resource_id", resource.id)
                resource_id = assignment_value.get("resource_id")
                if not isinstance(resource_id, str) or not resource_id:
                    resource_name = assignment_value.get("resource_name")
                    if not isinstance(resource_name, str) or not resource_name.strip():
                        raise ValueError(f"rows[{row_index}].assignments_json[{assignment_index}]: resource_id or resource_name is required")
                    name_key = resource_name.strip().casefold()
                    existing = next((item for item in resources_by_id.values() if item.name.casefold() == name_key), None)
                    resource = existing or Resource(id=_make_id("resource-" + name_key, digest, "name"), name=resource_name.strip())
                    resources_by_id[resource.id] = resource
                    assignment_value = {**assignment_value, "resource_id": resource.id}
                assignment_value = {**assignment_value, "task_id": task.id}
                if not assignment_value.get("id"):
                    assignment_value = {
                        **assignment_value,
                        "id": _make_id("assignment", digest, f"{row_index}:{assignment_index}"),
                    }
                assignments.append(_parse_assignment(assignment_value, f"rows[{row_index}].assignments_json[{assignment_index}]"))

            resource_names = _cell(row, mapping, "resource_names")
            if resource_names and resource_names.strip() and not assignment_values:
                assignments.extend(_parse_simple_resource_names(
                    resource_names, task.id, digest, row_index, resources_by_id, issues,
                ))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return ImportResult(FORMAT_ID, None, tuple(issues) + (_issue("error", "csv.value.invalid", "$", str(exc)),))

    project = Project(
        id=project_id,
        name=project_name if project_name.strip() else "Imported CSV project",
        description=project_values["project_description"] or "",
        author=project_values["project_author"],
        external_ids=project_external_ids,
        created_at=project_created,
        modified_at=project_modified,
        start_date=project_start,
        finish_date=project_finish,
        schedule_mode=(project_values["project_schedule_mode"] or "auto").strip().lower(),
        default_calendar_id=project_values["project_default_calendar_id"],
        currency=project_values["project_currency"] if project_values["project_currency"] and project_values["project_currency"].strip() else "GBP",
        status=project_values["project_status"],
        custom_fields=project_custom_fields,
        extensions=project_extensions,
        tasks=tasks,
        dependencies=dependencies,
        resources=list(resources_by_id.values()),
        assignments=assignments,
        calendars=calendars,
    )
    issues.extend(validate_project(project).issues)
    return ImportResult(FORMAT_ID, project, tuple(issues))


def _date_value(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _datetime_value(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat().replace("+00:00", "Z") if value.utcoffset() == timedelta(0) else value.isoformat()


def _project_metadata(project: Project) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "project_name": project.name,
        "project_description": project.description,
        "project_author": project.author or "",
        "project_external_ids_json": _json_text(project.external_ids),
        "project_created_at": _datetime_value(project.created_at),
        "project_modified_at": _datetime_value(project.modified_at),
        "project_start_date": _date_value(project.start_date),
        "project_finish_date": _date_value(project.finish_date),
        "project_schedule_mode": project.schedule_mode,
        "project_default_calendar_id": project.default_calendar_id or "",
        "project_currency": project.currency,
        "project_status": project.status or "",
        "project_custom_fields_json": _json_text(project.custom_fields),
        "project_extensions_json": _json_text(project.extensions),
        "resources_json": _json_text(_project_resources_to_dict(project)),
        "calendars_json": _json_text(_project_calendars_to_dict(project)),
    }


def _row_for_task(project: Project, task: Task, dependencies: list[Dependency], assignments: list[Assignment]) -> dict[str, Any]:
    from planforge.interchange.json_adapter import _task_to_document

    task_data = _task_to_document(task)
    fp = task_data["function_points"]
    return {
        "task_id": task.id,
        "task_name": task.name,
        "description": task.description,
        "parent_id": task.parent_id or "",
        "outline_level": "" if task.outline_level is None else task.outline_level,
        "order": task.order,
        "start_date": _date_value(task.start_date),
        "finish_date": _date_value(task.finish_date),
        "duration": "" if task.duration is None else task.duration,
        "duration_unit": task.duration_unit,
        "percent_complete": task.percent_complete,
        "priority": "" if task.priority is None else task.priority,
        "milestone": "true" if task.milestone else "false",
        "task_type": task.task_type,
        "schedule_mode": task.schedule_mode,
        "calendar_id": task.calendar_id or "",
        "deadline": _date_value(task.deadline),
        "constraint_type": task.constraint_type or "",
        "constraint_date": _date_value(task.constraint_date),
        "estimated_work": "" if task.estimated_work is None else task.estimated_work,
        "actual_work": "" if task.actual_work is None else task.actual_work,
        "remaining_work": "" if task.remaining_work is None else task.remaining_work,
        "work_unit": task.work_unit,
        "estimated_cost": "" if task.estimated_cost is None else task.estimated_cost,
        "actual_cost": "" if task.actual_cost is None else task.actual_cost,
        "dependencies_json": _json_text([
            {
                "id": item.id,
                "predecessor_id": item.predecessor_id,
                "successor_id": item.successor_id,
                "relationship_type": item.relationship_type,
                "lag": item.lag,
                "lag_unit": item.lag_unit,
                "external_ids": item.external_ids,
                "extensions": item.extensions,
            }
            for item in dependencies
        ]),
        "assignments_json": _json_text([
            _assignment_to_dict(item) for item in assignments
        ]),
        "task_external_ids_json": _json_text(task.external_ids),
        "custom_fields_json": _json_text(task.custom_fields),
        "function_points_json": "" if fp is None else _json_text(fp),
        "task_extensions_json": _json_text(task.extensions),
    }


def export_project(project: Project, *, spreadsheet_safe: bool = False) -> ExportResult:
    """Export a project as the PlanForge CSV template.

    CSV lacks native project/resource/calendar entities. This template uses
    JSON-in-cell columns for those structures and retains the normal tabular
    task columns. Set ``spreadsheet_safe`` to prefix formula-like string cells
    with an apostrophe before opening the output in a spreadsheet program.
    """

    report = validate_project(project)
    if report.errors:
        return ExportResult(FORMAT_ID, None, report.issues)
    tasks = list(project.tasks)
    dependencies_by_successor: dict[str, list[Dependency]] = {}
    for dependency in project.dependencies:
        dependencies_by_successor.setdefault(dependency.successor_id, []).append(dependency)
    assignments_by_task: dict[str, list[Assignment]] = {}
    for assignment in project.assignments:
        assignments_by_task.setdefault(assignment.task_id, []).append(assignment)

    rows: list[dict[str, Any]] = []
    if tasks:
        for index, task in enumerate(tasks):
            row = _row_for_task(
                project,
                task,
                dependencies_by_successor.get(task.id, []),
                assignments_by_task.get(task.id, []),
            )
            if index == 0:
                row.update(_project_metadata(project))
            rows.append(row)
    else:
        row = {column: "" for column in CSV_COLUMNS}
        row.update(_project_metadata(project))
        rows.append(row)

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        if spreadsheet_safe:
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
                    row[key] = "'" + value
        writer.writerow(row)
    return ExportResult(FORMAT_ID, stream.getvalue().encode("utf-8"), report.issues)


__all__ = [
    "CSV_COLUMNS",
    "FORMAT_ID",
    "FORMAT_NAME",
    "MAX_IMPORT_BYTES",
    "MAX_IMPORT_ROWS",
    "CsvImportOptions",
    "export_project",
    "import_bytes",
    "suggest_column_mapping",
]
