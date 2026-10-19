"""Small, explicit project model used by the interoperability layer.

Dates on projects and tasks are date-only values. This deliberately avoids
implicit timezone conversion when exchanging schedules between applications.
The model contains no scheduling engine: imported dates are retained as given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import TypeAlias
from uuid import uuid4

JsonPrimitive: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


def new_id() -> str:
    """Return a portable, stable-format identifier for a newly created record."""

    return str(uuid4())


def _weekday_periods() -> dict[int, list["WorkingPeriod"]]:
    return {
        weekday: [
            WorkingPeriod(time(8, 0), time(12, 0)),
            WorkingPeriod(time(13, 0), time(17, 0)),
        ]
        for weekday in range(5)
    }


@dataclass(slots=True)
class WorkingPeriod:
    """Local wall-clock working interval within a calendar day."""

    start: time
    finish: time
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class CalendarException:
    """An inclusive date range that overrides a calendar's normal week."""

    start_date: date
    finish_date: date
    working: bool = False
    working_periods: list[WorkingPeriod] = field(default_factory=list)
    name: str | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class AvailabilityPeriod:
    """Resource availability for an inclusive date range; units use 1.0 = 100%."""

    start_date: date
    finish_date: date
    units: float = 1.0
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class Calendar:
    """A calendar definition. Weekdays use ISO numbering: Monday is zero."""

    id: str = field(default_factory=new_id)
    name: str = "Standard"
    external_ids: dict[str, str] = field(default_factory=dict)
    working_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    working_periods: dict[int, list[WorkingPeriod]] = field(default_factory=_weekday_periods)
    holidays: list[date] = field(default_factory=list)
    exceptions: list[CalendarException] = field(default_factory=list)
    timezone: str | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class FunctionPointEstimate:
    """Function Point Calculator inputs and derived values for a task.

    ``counts`` and ``complexities`` are keyed by the calculator's stable
    category names (for example ``external_inputs``). Unknown categories are
    retained rather than rewritten or dropped.
    """

    counts: dict[str, int] = field(default_factory=dict)
    complexities: dict[str, str] = field(default_factory=dict)
    function_points: float | None = None
    estimated_hours: float | None = None
    hourly_rate: float | None = None
    estimated_cost: float | None = None
    currency: str | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class Task:
    """A task, milestone or summary row in a project plan."""

    id: str = field(default_factory=new_id)
    name: str = "Untitled task"
    description: str = ""
    external_ids: dict[str, str] = field(default_factory=dict)
    parent_id: str | None = None
    outline_level: int | None = None
    order: int = 0
    start_date: date | None = None
    finish_date: date | None = None
    duration: float | None = None
    duration_unit: str = "day"
    percent_complete: float = 0.0
    priority: int | None = None
    milestone: bool = False
    task_type: str = "task"
    schedule_mode: str = "auto"
    calendar_id: str | None = None
    deadline: date | None = None
    constraint_type: str | None = None
    constraint_date: date | None = None
    estimated_work: float | None = None
    actual_work: float | None = None
    remaining_work: float | None = None
    work_unit: str = "hour"
    estimated_cost: float | None = None
    actual_cost: float | None = None
    custom_fields: dict[str, JsonValue] = field(default_factory=dict)
    function_points: FunctionPointEstimate | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class Dependency:
    """A directed relationship from ``predecessor_id`` to ``successor_id``."""

    id: str = field(default_factory=new_id)
    predecessor_id: str = ""
    successor_id: str = ""
    relationship_type: str = "finish_to_start"
    lag: float = 0.0
    lag_unit: str = "day"
    external_ids: dict[str, str] = field(default_factory=dict)
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class Resource:
    """A named project resource, separate from its task assignments."""

    id: str = field(default_factory=new_id)
    name: str = "Unnamed resource"
    external_ids: dict[str, str] = field(default_factory=dict)
    resource_type: str = "work"
    max_units: float = 1.0
    standard_rate: float | None = None
    standard_rate_unit: str = "hour"
    overtime_rate: float | None = None
    overtime_rate_unit: str = "hour"
    cost_per_use: float | None = None
    calendar_id: str | None = None
    availability: list[AvailabilityPeriod] = field(default_factory=list)
    notes: str = ""
    custom_fields: dict[str, JsonValue] = field(default_factory=dict)
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class Assignment:
    """The allocation of a resource to a task."""

    id: str = field(default_factory=new_id)
    task_id: str = ""
    resource_id: str = ""
    units: float = 1.0
    work: float | None = None
    work_unit: str = "hour"
    actual_work: float | None = None
    remaining_work: float | None = None
    cost: float | None = None
    actual_cost: float | None = None
    start_date: date | None = None
    finish_date: date | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    custom_fields: dict[str, JsonValue] = field(default_factory=dict)
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(slots=True)
class Project:
    """Canonical interchange project.

    The model is intentionally an exchange contract, not a replacement for
    PlanForge's (absent in this checkout) persistence or scheduling classes.
    """

    id: str = field(default_factory=new_id)
    name: str = "Untitled project"
    description: str = ""
    author: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    modified_at: datetime | None = None
    start_date: date | None = None
    finish_date: date | None = None
    schedule_mode: str = "auto"
    default_calendar_id: str | None = None
    currency: str = "GBP"
    status: str | None = None
    custom_fields: dict[str, JsonValue] = field(default_factory=dict)
    extensions: dict[str, JsonValue] = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    calendars: list[Calendar] = field(default_factory=list)


__all__ = [
    "Assignment",
    "AvailabilityPeriod",
    "Calendar",
    "CalendarException",
    "Dependency",
    "FunctionPointEstimate",
    "JsonPrimitive",
    "JsonValue",
    "Project",
    "Resource",
    "Task",
    "WorkingPeriod",
    "new_id",
]
