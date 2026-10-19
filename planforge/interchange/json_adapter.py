"""Versioned PlanForge JSON interchange adapter (standard library only)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time
from typing import Any

from planforge.interchange.results import ExportResult, ImportResult
from planforge.interchange.validation import ValidationIssue, validate_project
from planforge.model import (
    Assignment,
    AvailabilityPeriod,
    Calendar,
    CalendarException,
    Dependency,
    FunctionPointEstimate,
    Project,
    Resource,
    Task,
    WorkingPeriod,
)

FORMAT_ID = "planforge-json"
FORMAT_NAME = "PlanForge JSON"
CURRENT_SCHEMA_VERSION = 1
MAX_IMPORT_BYTES = 50 * 1024 * 1024
_UNKNOWN_FIELDS_NAMESPACE = "org.planforge.interchange:unknown-fields"
_UNKNOWN_ROOT_NAMESPACE = "org.planforge.interchange:unknown-root-fields"


class DocumentError(ValueError):
    """A document shape or field value cannot be interpreted safely."""


def _error(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue("error", code, path, message)


def _warning(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue("warning", code, path, message)


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DocumentError(f"{path}: expected a JSON object with string keys")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise DocumentError(f"{path}: expected a JSON array")
    return value


def _string(value: Any, path: str, *, optional: bool = False, default: str | None = None) -> str | None:
    if value is None and optional:
        return None
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise DocumentError(f"{path}: expected a string")
    return value


def _bool(value: Any, path: str, *, default: bool | None = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise DocumentError(f"{path}: expected a boolean")
    return value


def _integer(value: Any, path: str, *, optional: bool = False, default: int | None = None) -> int | None:
    if value is None and optional:
        return None
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentError(f"{path}: expected an integer")
    return value


def _number(value: Any, path: str, *, optional: bool = False, default: float | None = None) -> float | None:
    if value is None and optional:
        return None
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DocumentError(f"{path}: expected a finite number")
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        raise DocumentError(f"{path}: expected a finite number") from None
    if not math.isfinite(converted):
        raise DocumentError(f"{path}: expected a finite number")
    return converted


def _date(value: Any, path: str, *, optional: bool = True) -> date | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise DocumentError(f"{path}: expected an ISO date string (YYYY-MM-DD)")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DocumentError(f"{path}: invalid ISO date {value!r}") from exc
    if parsed.isoformat() != value:
        raise DocumentError(f"{path}: expected date-only YYYY-MM-DD, got {value!r}")
    return parsed


def _datetime(value: Any, path: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DocumentError(f"{path}: expected an ISO timestamp string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DocumentError(f"{path}: invalid ISO timestamp {value!r}") from exc


def _time(value: Any, path: str) -> time:
    if not isinstance(value, str):
        raise DocumentError(f"{path}: expected an ISO local time string")
    try:
        result = time.fromisoformat(value)
    except ValueError as exc:
        raise DocumentError(f"{path}: invalid local time {value!r}") from exc
    return result


def _string_map(value: Any, path: str) -> dict[str, str]:
    obj = _object(value, path)
    out: dict[str, str] = {}
    for key, item in obj.items():
        if not isinstance(item, str):
            raise DocumentError(f"{path}.{key}: expected a string")
        out[key] = item
    return out


def _json_map(value: Any, path: str) -> dict[str, Any]:
    return _object(value, path)


def _extra_fields(obj: dict[str, Any], known: set[str]) -> dict[str, Any]:
    return {key: value for key, value in obj.items() if key not in known}


def _with_unknown_fields(
    explicit_extensions: dict[str, Any], unknown: dict[str, Any]
) -> dict[str, Any]:
    extensions = dict(explicit_extensions)
    if unknown:
        previous = extensions.get(_UNKNOWN_FIELDS_NAMESPACE)
        if previous is None:
            extensions[_UNKNOWN_FIELDS_NAMESPACE] = unknown
        elif isinstance(previous, dict):
            # Preserve both sets rather than overwriting an existing namespace.
            merged = dict(previous)
            for key, value in unknown.items():
                if key not in merged:
                    merged[key] = value
                else:
                    merged[f"imported_duplicate:{key}"] = value
            extensions[_UNKNOWN_FIELDS_NAMESPACE] = merged
        else:
            extensions[f"{_UNKNOWN_FIELDS_NAMESPACE}:additional"] = unknown
    return extensions


def _extensions(obj: dict[str, Any], path: str) -> dict[str, Any]:
    value = obj.get("extensions", {})
    return _json_map(value, f"{path}.extensions")


def _parse_working_period(value: Any, path: str) -> WorkingPeriod:
    obj = _object(value, path)
    known = {"start", "finish", "extensions"}
    return WorkingPeriod(
        start=_time(obj.get("start"), f"{path}.start"),
        finish=_time(obj.get("finish"), f"{path}.finish"),
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_exception(value: Any, path: str) -> CalendarException:
    obj = _object(value, path)
    known = {"start_date", "finish_date", "working", "working_periods", "name", "extensions"}
    periods = [
        _parse_working_period(item, f"{path}.working_periods[{index}]")
        for index, item in enumerate(_list(obj.get("working_periods", []), f"{path}.working_periods"))
    ]
    extensions = _with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known))
    name = obj.get("name")
    if name is not None and not isinstance(name, str):
        raise DocumentError(f"{path}.name: expected a string or null")
    return CalendarException(
        start_date=_date(obj.get("start_date"), f"{path}.start_date", optional=False),  # type: ignore[arg-type]
        finish_date=_date(obj.get("finish_date"), f"{path}.finish_date", optional=False),  # type: ignore[arg-type]
        working=_bool(obj.get("working", False), f"{path}.working", default=False),
        working_periods=periods,
        name=name,
        extensions=extensions,
    )


def _parse_calendar(value: Any, path: str) -> Calendar:
    obj = _object(value, path)
    known = {
        "id", "name", "external_ids", "working_days", "working_periods", "holidays",
        "exceptions", "timezone", "extensions",
    }
    periods_obj = _object(obj.get("working_periods", {}), f"{path}.working_periods")
    periods: dict[int, list[WorkingPeriod]] = {}
    for weekday_key, period_values in periods_obj.items():
        try:
            weekday = int(weekday_key)
        except ValueError as exc:
            raise DocumentError(f"{path}.working_periods: weekday keys must be 0 through 6") from exc
        periods[weekday] = [
            _parse_working_period(item, f"{path}.working_periods.{weekday_key}[{index}]")
            for index, item in enumerate(_list(period_values, f"{path}.working_periods.{weekday_key}"))
        ]
    working_days = [
        _integer(item, f"{path}.working_days[{index}]")
        for index, item in enumerate(_list(obj.get("working_days", [0, 1, 2, 3, 4]), f"{path}.working_days"))
    ]
    holidays = [
        _date(item, f"{path}.holidays[{index}]", optional=False)
        for index, item in enumerate(_list(obj.get("holidays", []), f"{path}.holidays"))
    ]
    exceptions = [
        _parse_exception(item, f"{path}.exceptions[{index}]")
        for index, item in enumerate(_list(obj.get("exceptions", []), f"{path}.exceptions"))
    ]
    timezone = obj.get("timezone")
    if timezone is not None and not isinstance(timezone, str):
        raise DocumentError(f"{path}.timezone: expected a string or null")
    name = _string(obj.get("name", "Standard"), f"{path}.name")
    calendar_id = _string(obj.get("id"), f"{path}.id")
    return Calendar(
        id=calendar_id or "",
        name=name or "",
        external_ids=_string_map(obj.get("external_ids", {}), f"{path}.external_ids"),
        working_days=[int(day) for day in working_days if day is not None],
        working_periods=periods,
        holidays=[day for day in holidays if day is not None],
        exceptions=exceptions,
        timezone=timezone,
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_function_points(value: Any, path: str) -> FunctionPointEstimate | None:
    if value is None:
        return None
    obj = _object(value, path)
    known = {"counts", "complexities", "function_points", "estimated_hours", "hourly_rate", "estimated_cost", "currency", "extensions"}
    counts_obj = _object(obj.get("counts", {}), f"{path}.counts")
    counts = {
        key: _integer(count, f"{path}.counts.{key}")  # type: ignore[misc]
        for key, count in counts_obj.items()
    }
    complexities_obj = _object(obj.get("complexities", {}), f"{path}.complexities")
    complexities: dict[str, str] = {}
    for key, complexity in complexities_obj.items():
        if not isinstance(complexity, str):
            raise DocumentError(f"{path}.complexities.{key}: expected a string")
        complexities[key] = complexity
    currency = obj.get("currency")
    if currency is not None and not isinstance(currency, str):
        raise DocumentError(f"{path}.currency: expected a string or null")
    return FunctionPointEstimate(
        counts=counts,  # type: ignore[arg-type]
        complexities=complexities,
        function_points=_number(obj.get("function_points"), f"{path}.function_points", optional=True),
        estimated_hours=_number(obj.get("estimated_hours"), f"{path}.estimated_hours", optional=True),
        hourly_rate=_number(obj.get("hourly_rate"), f"{path}.hourly_rate", optional=True),
        estimated_cost=_number(obj.get("estimated_cost"), f"{path}.estimated_cost", optional=True),
        currency=currency,
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_task(value: Any, path: str) -> Task:
    obj = _object(value, path)
    known = {
        "id", "name", "description", "external_ids", "parent_id", "outline_level", "order",
        "start_date", "finish_date", "duration", "duration_unit", "percent_complete", "priority",
        "milestone", "task_type", "schedule_mode", "calendar_id", "deadline", "constraint_type",
        "constraint_date", "estimated_work", "actual_work", "remaining_work", "work_unit",
        "estimated_cost", "actual_cost", "custom_fields", "function_points", "extensions",
    }
    string_fields = ("id", "name", "description", "duration_unit", "task_type", "schedule_mode", "work_unit")
    strings = {key: _string(obj.get(key), f"{path}.{key}", default={"name": "", "description": "", "duration_unit": "day", "task_type": "task", "schedule_mode": "auto", "work_unit": "hour"}.get(key)) for key in string_fields}
    for key in ("parent_id", "calendar_id", "constraint_type"):
        if obj.get(key) is not None and not isinstance(obj.get(key), str):
            raise DocumentError(f"{path}.{key}: expected a string or null")
    return Task(
        id=strings["id"] or "",
        name=strings["name"] or "",
        description=strings["description"] or "",
        external_ids=_string_map(obj.get("external_ids", {}), f"{path}.external_ids"),
        parent_id=obj.get("parent_id"),
        outline_level=_integer(obj.get("outline_level"), f"{path}.outline_level", optional=True),
        order=_integer(obj.get("order", 0), f"{path}.order", default=0) or 0,
        start_date=_date(obj.get("start_date"), f"{path}.start_date"),
        finish_date=_date(obj.get("finish_date"), f"{path}.finish_date"),
        duration=_number(obj.get("duration"), f"{path}.duration", optional=True),
        duration_unit=strings["duration_unit"] or "day",
        percent_complete=_number(obj.get("percent_complete", 0), f"{path}.percent_complete", default=0) or 0,
        priority=_integer(obj.get("priority"), f"{path}.priority", optional=True),
        milestone=_bool(obj.get("milestone", False), f"{path}.milestone", default=False),
        task_type=strings["task_type"] or "task",
        schedule_mode=strings["schedule_mode"] or "auto",
        calendar_id=obj.get("calendar_id"),
        deadline=_date(obj.get("deadline"), f"{path}.deadline"),
        constraint_type=obj.get("constraint_type"),
        constraint_date=_date(obj.get("constraint_date"), f"{path}.constraint_date"),
        estimated_work=_number(obj.get("estimated_work"), f"{path}.estimated_work", optional=True),
        actual_work=_number(obj.get("actual_work"), f"{path}.actual_work", optional=True),
        remaining_work=_number(obj.get("remaining_work"), f"{path}.remaining_work", optional=True),
        work_unit=strings["work_unit"] or "hour",
        estimated_cost=_number(obj.get("estimated_cost"), f"{path}.estimated_cost", optional=True),
        actual_cost=_number(obj.get("actual_cost"), f"{path}.actual_cost", optional=True),
        custom_fields=_json_map(obj.get("custom_fields", {}), f"{path}.custom_fields"),
        function_points=_parse_function_points(obj.get("function_points"), f"{path}.function_points"),
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_dependency(value: Any, path: str) -> Dependency:
    obj = _object(value, path)
    known = {"id", "predecessor_id", "successor_id", "relationship_type", "lag", "lag_unit", "external_ids", "extensions"}
    for key in ("id", "predecessor_id", "successor_id", "relationship_type", "lag_unit"):
        if key in obj and not isinstance(obj[key], str):
            raise DocumentError(f"{path}.{key}: expected a string")
    return Dependency(
        id=obj.get("id", ""),
        predecessor_id=obj.get("predecessor_id", ""),
        successor_id=obj.get("successor_id", ""),
        relationship_type=obj.get("relationship_type", "finish_to_start"),
        lag=_number(obj.get("lag", 0), f"{path}.lag", default=0) or 0,
        lag_unit=obj.get("lag_unit", "day"),
        external_ids=_string_map(obj.get("external_ids", {}), f"{path}.external_ids"),
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_availability(value: Any, path: str) -> AvailabilityPeriod:
    obj = _object(value, path)
    known = {"start_date", "finish_date", "units", "extensions"}
    return AvailabilityPeriod(
        start_date=_date(obj.get("start_date"), f"{path}.start_date", optional=False),  # type: ignore[arg-type]
        finish_date=_date(obj.get("finish_date"), f"{path}.finish_date", optional=False),  # type: ignore[arg-type]
        units=_number(obj.get("units", 1), f"{path}.units", default=1) or 0,
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_resource(value: Any, path: str) -> Resource:
    obj = _object(value, path)
    known = {
        "id", "name", "external_ids", "resource_type", "max_units", "standard_rate", "standard_rate_unit",
        "overtime_rate", "overtime_rate_unit", "cost_per_use", "calendar_id", "availability", "notes",
        "custom_fields", "extensions",
    }
    for key in ("id", "name", "resource_type", "standard_rate_unit", "overtime_rate_unit", "notes"):
        if key in obj and not isinstance(obj[key], str):
            raise DocumentError(f"{path}.{key}: expected a string")
    calendar_id = obj.get("calendar_id")
    if calendar_id is not None and not isinstance(calendar_id, str):
        raise DocumentError(f"{path}.calendar_id: expected a string or null")
    availability = [
        _parse_availability(item, f"{path}.availability[{index}]")
        for index, item in enumerate(_list(obj.get("availability", []), f"{path}.availability"))
    ]
    return Resource(
        id=obj.get("id", ""),
        name=obj.get("name", ""),
        external_ids=_string_map(obj.get("external_ids", {}), f"{path}.external_ids"),
        resource_type=obj.get("resource_type", "work"),
        max_units=_number(obj.get("max_units", 1), f"{path}.max_units", default=1) or 0,
        standard_rate=_number(obj.get("standard_rate"), f"{path}.standard_rate", optional=True),
        standard_rate_unit=obj.get("standard_rate_unit", "hour"),
        overtime_rate=_number(obj.get("overtime_rate"), f"{path}.overtime_rate", optional=True),
        overtime_rate_unit=obj.get("overtime_rate_unit", "hour"),
        cost_per_use=_number(obj.get("cost_per_use"), f"{path}.cost_per_use", optional=True),
        calendar_id=calendar_id,
        availability=availability,
        notes=obj.get("notes", ""),
        custom_fields=_json_map(obj.get("custom_fields", {}), f"{path}.custom_fields"),
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _parse_assignment(value: Any, path: str) -> Assignment:
    obj = _object(value, path)
    known = {
        "id", "task_id", "resource_id", "units", "work", "work_unit", "actual_work", "remaining_work", "cost",
        "actual_cost", "start_date", "finish_date", "external_ids", "custom_fields", "extensions",
    }
    for key in ("id", "task_id", "resource_id", "work_unit"):
        if key in obj and not isinstance(obj[key], str):
            raise DocumentError(f"{path}.{key}: expected a string")
    return Assignment(
        id=obj.get("id", ""),
        task_id=obj.get("task_id", ""),
        resource_id=obj.get("resource_id", ""),
        units=_number(obj.get("units", 1), f"{path}.units", default=1) or 0,
        work=_number(obj.get("work"), f"{path}.work", optional=True),
        work_unit=obj.get("work_unit", "hour"),
        actual_work=_number(obj.get("actual_work"), f"{path}.actual_work", optional=True),
        remaining_work=_number(obj.get("remaining_work"), f"{path}.remaining_work", optional=True),
        cost=_number(obj.get("cost"), f"{path}.cost", optional=True),
        actual_cost=_number(obj.get("actual_cost"), f"{path}.actual_cost", optional=True),
        start_date=_date(obj.get("start_date"), f"{path}.start_date"),
        finish_date=_date(obj.get("finish_date"), f"{path}.finish_date"),
        external_ids=_string_map(obj.get("external_ids", {}), f"{path}.external_ids"),
        custom_fields=_json_map(obj.get("custom_fields", {}), f"{path}.custom_fields"),
        extensions=_with_unknown_fields(_extensions(obj, path), _extra_fields(obj, known)),
    )


def _migrate_v0(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate the documented, unversioned pre-release JSON draft to schema 1."""

    migrated = dict(document)
    if "project" not in migrated and ("name" in migrated or "tasks" in migrated):
        root_project_fields = {
            "id", "name", "description", "author", "external_ids", "created_at", "modified_at", "start_date",
            "finish_date", "schedule_mode", "default_calendar_id", "currency", "status",
            "custom_fields", "extensions", "tasks", "dependencies", "resources", "assignments", "calendars",
        }
        project = {key: value for key, value in migrated.items() if key in root_project_fields}
        migrated = {key: value for key, value in migrated.items() if key not in root_project_fields}
        migrated["project"] = project
    migrated.setdefault("format", "planforge-project")
    migrated["schema_version"] = CURRENT_SCHEMA_VERSION
    project_data = migrated.get("project")
    if isinstance(project_data, dict):
        for collection in ("tasks", "dependencies", "resources", "assignments", "calendars"):
            project_data.setdefault(collection, [])
        project_data.setdefault("custom_fields", {})
        project_data.setdefault("extensions", {})
    return migrated


def migrate_document(document: Any) -> tuple[dict[str, Any], int, list[ValidationIssue]]:
    """Upgrade a JSON document to the current version without mutating it."""

    if not isinstance(document, dict):
        raise DocumentError("$: expected a JSON object")
    version = document.get("schema_version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise DocumentError("$.schema_version: expected a non-negative integer")
    if version > CURRENT_SCHEMA_VERSION:
        raise DocumentError(
            f"$.schema_version: version {version} is newer than the supported version {CURRENT_SCHEMA_VERSION}"
        )
    issues: list[ValidationIssue] = []
    migrated = dict(document)
    if version == 0:
        migrated = _migrate_v0(migrated)
        issues.append(_warning("json.schema.migrated", "$.schema_version", "Unversioned PlanForge JSON was migrated to schema version 1."))
    return migrated, CURRENT_SCHEMA_VERSION, issues


def _project_from_document(document: dict[str, Any]) -> tuple[Project, list[ValidationIssue]]:
    if document.get("format") != "planforge-project":
        raise DocumentError("$.format: expected 'planforge-project'")
    if document.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise DocumentError(f"$.schema_version: expected {CURRENT_SCHEMA_VERSION}")
    raw_project = _object(document.get("project"), "$.project")
    known = {
        "id", "name", "description", "author", "external_ids", "created_at", "modified_at", "start_date", "finish_date",
        "schedule_mode", "default_calendar_id", "currency", "status", "custom_fields", "extensions",
        "tasks", "dependencies", "resources", "assignments", "calendars",
    }
    issues: list[ValidationIssue] = []
    for item_name, parser in (
        ("tasks", _parse_task),
        ("dependencies", _parse_dependency),
        ("resources", _parse_resource),
        ("assignments", _parse_assignment),
        ("calendars", _parse_calendar),
    ):
        values = _list(raw_project.get(item_name, []), f"$.project.{item_name}")
        parsed = [parser(value, f"$.project.{item_name}[{index}]") for index, value in enumerate(values)]
        if item_name == "tasks":
            tasks = parsed
        elif item_name == "dependencies":
            dependencies = parsed
        elif item_name == "resources":
            resources = parsed
        elif item_name == "assignments":
            assignments = parsed
        else:
            calendars = parsed

    for key in ("id", "name", "description", "schedule_mode", "currency"):
        if key in raw_project and not isinstance(raw_project[key], str):
            raise DocumentError(f"$.project.{key}: expected a string")
    for key in ("author", "default_calendar_id", "status"):
        if raw_project.get(key) is not None and not isinstance(raw_project[key], str):
            raise DocumentError(f"$.project.{key}: expected a string or null")

    project_extensions = _with_unknown_fields(
        _extensions(raw_project, "$.project"), _extra_fields(raw_project, known)
    )
    unknown_root = _extra_fields(document, {"format", "schema_version", "project"})
    if unknown_root:
        prior_root = project_extensions.get(_UNKNOWN_ROOT_NAMESPACE)
        if prior_root is None:
            project_extensions[_UNKNOWN_ROOT_NAMESPACE] = unknown_root
        else:
            project_extensions[f"{_UNKNOWN_ROOT_NAMESPACE}:additional"] = unknown_root
        issues.append(_warning(
            "json.root_fields.unknown_preserved",
            "$",
            "Unknown root fields were preserved in project.extensions.",
        ))
    unknown_project = _extra_fields(raw_project, known)
    if unknown_project:
        issues.append(_warning(
            "json.project_fields.unknown_preserved",
            "$.project",
            "Unknown project fields were preserved in project.extensions.",
        ))

    project = Project(
        id=raw_project.get("id", ""),
        name=raw_project.get("name", ""),
        description=raw_project.get("description", ""),
        author=raw_project.get("author"),
        external_ids=_string_map(raw_project.get("external_ids", {}), "$.project.external_ids"),
        created_at=_datetime(raw_project.get("created_at"), "$.project.created_at"),
        modified_at=_datetime(raw_project.get("modified_at"), "$.project.modified_at"),
        start_date=_date(raw_project.get("start_date"), "$.project.start_date"),
        finish_date=_date(raw_project.get("finish_date"), "$.project.finish_date"),
        schedule_mode=raw_project.get("schedule_mode", "auto"),
        default_calendar_id=raw_project.get("default_calendar_id"),
        currency=raw_project.get("currency", "GBP"),
        status=raw_project.get("status"),
        custom_fields=_json_map(raw_project.get("custom_fields", {}), "$.project.custom_fields"),
        extensions=project_extensions,
        tasks=tasks,
        dependencies=dependencies,
        resources=resources,
        assignments=assignments,
        calendars=calendars,
    )
    return project, issues


def _date_string(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    from datetime import timedelta

    return value.isoformat().replace("+00:00", "Z") if value.utcoffset() == timedelta(0) else value.isoformat()


def _time_string(value: time) -> str:
    return value.isoformat(timespec="seconds")


def _period_to_document(period: WorkingPeriod) -> dict[str, Any]:
    return {
        "start": _time_string(period.start),
        "finish": _time_string(period.finish),
        "extensions": period.extensions,
    }


def _calendar_to_document(calendar: Calendar) -> dict[str, Any]:
    return {
        "id": calendar.id,
        "name": calendar.name,
        "external_ids": dict(calendar.external_ids),
        "working_days": list(calendar.working_days),
        "working_periods": {
            str(day): [_period_to_document(period) for period in periods]
            for day, periods in sorted(calendar.working_periods.items())
        },
        "holidays": [_date_string(holiday) for holiday in calendar.holidays],
        "exceptions": [
            {
                "start_date": _date_string(exception.start_date),
                "finish_date": _date_string(exception.finish_date),
                "working": exception.working,
                "working_periods": [_period_to_document(period) for period in exception.working_periods],
                "name": exception.name,
                "extensions": exception.extensions,
            }
            for exception in calendar.exceptions
        ],
        "timezone": calendar.timezone,
        "extensions": calendar.extensions,
    }


def _task_to_document(task: Task) -> dict[str, Any]:
    function_points = None
    if task.function_points is not None:
        function_points = {
            "counts": task.function_points.counts,
            "complexities": task.function_points.complexities,
            "function_points": task.function_points.function_points,
            "estimated_hours": task.function_points.estimated_hours,
            "hourly_rate": task.function_points.hourly_rate,
            "estimated_cost": task.function_points.estimated_cost,
            "currency": task.function_points.currency,
            "extensions": task.function_points.extensions,
        }
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "external_ids": task.external_ids,
        "parent_id": task.parent_id,
        "outline_level": task.outline_level,
        "order": task.order,
        "start_date": _date_string(task.start_date),
        "finish_date": _date_string(task.finish_date),
        "duration": task.duration,
        "duration_unit": task.duration_unit,
        "percent_complete": task.percent_complete,
        "priority": task.priority,
        "milestone": task.milestone,
        "task_type": task.task_type,
        "schedule_mode": task.schedule_mode,
        "calendar_id": task.calendar_id,
        "deadline": _date_string(task.deadline),
        "constraint_type": task.constraint_type,
        "constraint_date": _date_string(task.constraint_date),
        "estimated_work": task.estimated_work,
        "actual_work": task.actual_work,
        "remaining_work": task.remaining_work,
        "work_unit": task.work_unit,
        "estimated_cost": task.estimated_cost,
        "actual_cost": task.actual_cost,
        "custom_fields": task.custom_fields,
        "function_points": function_points,
        "extensions": task.extensions,
    }


def _resource_to_document(resource: Resource) -> dict[str, Any]:
    return {
        "id": resource.id,
        "name": resource.name,
        "external_ids": resource.external_ids,
        "resource_type": resource.resource_type,
        "max_units": resource.max_units,
        "standard_rate": resource.standard_rate,
        "standard_rate_unit": resource.standard_rate_unit,
        "overtime_rate": resource.overtime_rate,
        "overtime_rate_unit": resource.overtime_rate_unit,
        "cost_per_use": resource.cost_per_use,
        "calendar_id": resource.calendar_id,
        "availability": [
            {
                "start_date": _date_string(period.start_date),
                "finish_date": _date_string(period.finish_date),
                "units": period.units,
                "extensions": period.extensions,
            }
            for period in resource.availability
        ],
        "notes": resource.notes,
        "custom_fields": resource.custom_fields,
        "extensions": resource.extensions,
    }


def _assignment_to_document(assignment: Assignment) -> dict[str, Any]:
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
        "start_date": _date_string(assignment.start_date),
        "finish_date": _date_string(assignment.finish_date),
        "external_ids": assignment.external_ids,
        "custom_fields": assignment.custom_fields,
        "extensions": assignment.extensions,
    }


def project_to_document(project: Project) -> dict[str, Any]:
    """Convert a validated project to the documented version 1 JSON shape."""

    return {
        "format": "planforge-project",
        "schema_version": CURRENT_SCHEMA_VERSION,
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "author": project.author,
            "external_ids": project.external_ids,
            "created_at": _datetime_string(project.created_at),
            "modified_at": _datetime_string(project.modified_at),
            "start_date": _date_string(project.start_date),
            "finish_date": _date_string(project.finish_date),
            "schedule_mode": project.schedule_mode,
            "default_calendar_id": project.default_calendar_id,
            "currency": project.currency,
            "status": project.status,
            "custom_fields": project.custom_fields,
            "extensions": project.extensions,
            "tasks": [_task_to_document(task) for task in project.tasks],
            "dependencies": [
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
                for item in project.dependencies
            ],
            "resources": [_resource_to_document(item) for item in project.resources],
            "assignments": [_assignment_to_document(item) for item in project.assignments],
            "calendars": [_calendar_to_document(item) for item in project.calendars],
        },
    }


def _reject_constant(value: str) -> None:
    raise DocumentError(f"$: non-standard JSON numeric value {value!r} is not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DocumentError(f"$: duplicate JSON object key {key!r}")
        result[key] = value
    return result


def import_bytes(data: bytes, *, source_name: str | None = None) -> ImportResult:
    """Parse and validate PlanForge JSON without changing application state."""

    if not isinstance(data, bytes):
        return ImportResult(FORMAT_ID, None, (_error("file.data.invalid", "$", "Input must be bytes."),))
    if len(data) > MAX_IMPORT_BYTES:
        return ImportResult(FORMAT_ID, None, (_error("file.too_large", "$", f"File exceeds the {MAX_IMPORT_BYTES}-byte import limit."),))
    try:
        text = data.decode("utf-8-sig")
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
        migrated, version, migration_issues = migrate_document(parsed)
        project, parse_issues = _project_from_document(migrated)
    except UnicodeDecodeError:
        return ImportResult(FORMAT_ID, None, (_error("json.encoding.invalid", "$", "PlanForge JSON must be UTF-8 encoded."),))
    except json.JSONDecodeError as exc:
        return ImportResult(FORMAT_ID, None, (_error("json.parse.invalid", f"line {exc.lineno}, column {exc.colno}", exc.msg),))
    except (DocumentError, RecursionError, ValueError, TypeError) as exc:
        message = str(exc) or "The JSON document could not be interpreted."
        return ImportResult(FORMAT_ID, None, (_error("json.document.invalid", "$", message),))

    report = validate_project(project)
    issues = migration_issues + parse_issues + list(report.issues)
    return ImportResult(FORMAT_ID, project, tuple(issues), version)


def export_project(project: Project) -> ExportResult:
    """Serialize a project to version 1 JSON; invalid projects are not exported."""

    report = validate_project(project)
    if report.errors:
        return ExportResult(FORMAT_ID, None, report.issues)
    try:
        document = project_to_document(project)
        text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        data = text.encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        return ExportResult(FORMAT_ID, None, report.issues + (_error("json.export.failed", "$", str(exc)),))
    return ExportResult(FORMAT_ID, data, report.issues)


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "FORMAT_ID",
    "FORMAT_NAME",
    "MAX_IMPORT_BYTES",
    "export_project",
    "import_bytes",
    "migrate_document",
    "project_to_document",
]
