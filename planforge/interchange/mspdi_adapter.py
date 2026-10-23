"""Microsoft Project XML (MSPDI) and ProjectLibre XML interchange adapter.

Parses and generates Microsoft Project XML Data Interchange format (MSPDI),
the universal interchange standard supported by Microsoft Project, ProjectLibre,
GanttProject, and Primavera.
"""

from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

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
    new_id,
)

FORMAT_ID = "microsoft-project-xml"
FORMAT_NAME = "Microsoft Project XML / ProjectLibre XML"
MAX_IMPORT_BYTES = 50 * 1024 * 1024
MSPDI_NAMESPACE = "http://schemas.microsoft.com/project"

_DURATION_REGEX = re.compile(
    r"^P(?:(?P<weeks>\d+(?:\.\d+)?)W)?(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

# MSPDI dependency type mapping:
# 0: Finish-to-Finish (FF)
# 1: Finish-to-Start (FS)
# 2: Start-to-Finish (SF)
# 3: Start-to-Start (SS)
_MSPDI_TO_RELATIONSHIP = {
    0: "finish_to_finish",
    1: "finish_to_start",
    2: "start_to_finish",
    3: "start_to_start",
}

_RELATIONSHIP_TO_MSPDI = {
    "finish_to_finish": 0,
    "finish_to_start": 1,
    "start_to_finish": 2,
    "start_to_start": 3,
}

# MSPDI constraint types:
# 0 = As Soon As Possible
# 1 = As Late As Possible
# 2 = Must Start On
# 3 = Must Finish On
# 4 = Start No Earlier Than
# 5 = Start No Later Than
# 6 = Finish No Earlier Than
# 7 = Finish No Later Than
_MSPDI_TO_CONSTRAINT = {
    0: "as_soon_as_possible",
    1: "as_late_as_possible",
    2: "must_start_on",
    3: "must_finish_on",
    4: "start_no_earlier_than",
    5: "start_no_later_than",
    6: "finish_no_earlier_than",
    7: "finish_no_later_than",
}

_CONSTRAINT_TO_MSPDI = {v: k for k, v in _MSPDI_TO_CONSTRAINT.items()}

# MSPDI weekday (1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat) to ISO weekday (0=Mon .. 6=Sun)
_MSPDI_TO_ISO_WEEKDAY = {
    2: 0,  # Monday
    3: 1,  # Tuesday
    4: 2,  # Wednesday
    5: 3,  # Thursday
    6: 4,  # Friday
    7: 5,  # Saturday
    1: 6,  # Sunday
}
_ISO_TO_MSPDI_WEEKDAY = {v: k for k, v in _MSPDI_TO_ISO_WEEKDAY.items()}


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)


def _strip_ns(tag: str) -> str:
    """Return tag name without XML namespace prefix."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_child(element: ET.Element, name: str) -> ET.Element | None:
    """Find direct child element by local name, ignoring namespaces."""
    for child in element:
        if _strip_ns(child.tag) == name:
            return child
    return None


def _find_all_children(element: ET.Element, name: str) -> list[ET.Element]:
    """Find all direct child elements by local name, ignoring namespaces."""
    return [child for child in element if _strip_ns(child.tag) == name]


def _parse_mspdi_clock_time(raw: str | None, *, is_end: bool = False) -> tuple[time, bool] | None:
    """Parse an MSPDI ``FromTime``/``ToTime`` value into a naive local clock time.

    Returns ``(parsed_time, ended_at_24h)``. In ProjectLibre and Microsoft Project
    XML, ``ToTime`` of ``00:00:00`` (or ``24:00:00``) denotes end-of-day midnight
    (24:00) rather than 00:00 at the start of the same day.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[1]
    for tz_sep in ("Z", "+", "-"):
        if tz_sep in text:
            text = text.split(tz_sep, 1)[0]
    if text.startswith("24:00"):
        return (time(23, 59, 59), True) if is_end else (time(0, 0, 0), False)
    try:
        parsed = time.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None
    if is_end and parsed == time(0, 0, 0):
        return (time(23, 59, 59), True)
    return (parsed, False)


def _parse_mspdi_working_times(wtimes_el: ET.Element | None) -> list[WorkingPeriod]:
    """Normalize ProjectLibre/MS Project ``WorkingTimes`` into ordered valid intervals."""
    if wtimes_el is None:
        return []
    intervals: list[tuple[time, time]] = []
    for wt_el in _find_all_children(wtimes_el, "WorkingTime"):
        start_parsed = _parse_mspdi_clock_time(_text_of(wt_el, "FromTime"), is_end=False)
        end_parsed = _parse_mspdi_clock_time(_text_of(wt_el, "ToTime"), is_end=True)
        if start_parsed is None or end_parsed is None:
            continue
        p_start, _ = start_parsed
        p_finish, ended_midnight = end_parsed
        if p_start == p_finish and not ended_midnight:
            # Skip zero-length placeholder slots without failing import.
            continue
        if p_finish < p_start:
            # Overnight shift spanning midnight (e.g. 22:00 -> 06:00).
            if p_finish > time(0, 0, 0):
                intervals.append((time(0, 0, 0), p_finish))
            if p_start < time(23, 59, 59):
                intervals.append((p_start, time(23, 59, 59)))
        elif p_start < p_finish:
            intervals.append((p_start, p_finish))

    if not intervals:
        return []
    intervals.sort(key=lambda pair: (pair[0], pair[1]))
    merged: list[tuple[time, time]] = [intervals[0]]
    for cur_start, cur_end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if cur_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, cur_end))
        else:
            merged.append((cur_start, cur_end))
    return [WorkingPeriod(start, finish) for start, finish in merged]


def _parse_numeric_rate(raw: str | None) -> float | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        val = float(text)
        return max(0.0, val) if math.isfinite(val) else None
    except ValueError:
        cleaned = re.sub(r"[^0-9.\-+eE]", "", text.split("/")[0].replace(",", ""))
        if not cleaned:
            return None
        try:
            val = float(cleaned)
            return max(0.0, val) if math.isfinite(val) else None
        except ValueError:
            return None


def _text_of(element: ET.Element, name: str) -> str | None:
    child = _find_child(element, name)
    if child is not None and child.text is not None:
        val = child.text.strip()
        return val if val else None
    return None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    val = value.strip()
    if "T" in val:
        val = val.split("T", 1)[0]
    elif " " in val:
        val = val.split(" ", 1)[0]
    try:
        return date.fromisoformat(val)
    except ValueError:
        return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    val = value.strip()
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        try:
            d = date.fromisoformat(val)
            return datetime.combine(d, time(0, 0))
        except ValueError:
            return None


def _parse_mspdi_duration(value: str | None, hours_per_day: float = 8.0) -> tuple[float | None, str]:
    """Parse an MSPDI duration (e.g. PT40H0M0S or PT8H or numeric) into (value, unit)."""
    if not value:
        return None, "day"
    val = value.strip()
    match = _DURATION_REGEX.match(val)
    if match:
        parts = match.groupdict()
        weeks = float(parts.get("weeks") or 0.0)
        days = float(parts.get("days") or 0.0)
        hours = float(parts.get("hours") or 0.0)
        minutes = float(parts.get("minutes") or 0.0)
        seconds = float(parts.get("seconds") or 0.0)
        total_hours = (weeks * 5.0 * hours_per_day) + (days * hours_per_day) + hours + (minutes / 60.0) + (seconds / 3600.0)
        if hours_per_day > 0 and total_hours >= hours_per_day and (total_hours % hours_per_day == 0):
            return total_hours / hours_per_day, "day"
        return total_hours, "hour"
    try:
        num = float(val)
        return num, "day"
    except ValueError:
        return None, "day"


def _format_mspdi_duration(val: float | None, unit: str = "day", hours_per_day: float = 8.0) -> str:
    """Format duration as MSPDI ISO duration string PT#H#M#S."""
    if val is None or val < 0:
        return "PT0H0M0S"
    if unit == "day":
        hours = val * hours_per_day
    elif unit == "week":
        hours = val * 5.0 * hours_per_day
    elif unit == "minute":
        hours = val / 60.0
    else:  # hour or other
        hours = val

    total_seconds = int(round(hours * 3600))
    h = total_seconds // 3600
    rem = total_seconds % 3600
    m = rem // 60
    s = rem % 60
    return f"PT{h}H{m}M{s}S"


def _format_mspdi_work(val: float | None, unit: str = "hour") -> str:
    """Format work as MSPDI ISO duration string PT#H#M#S."""
    if val is None or val < 0:
        return "PT0H0M0S"
    if unit == "day":
        hours = val * 8.0
    elif unit == "week":
        hours = val * 40.0
    elif unit == "minute":
        hours = val / 60.0
    else:
        hours = val

    total_seconds = int(round(hours * 3600))
    h = total_seconds // 3600
    rem = total_seconds % 3600
    m = rem // 60
    s = rem % 60
    return f"PT{h}H{m}M{s}S"


def import_bytes(data: bytes, *, source_name: str | None = None) -> ImportResult:
    """Import a Microsoft Project / ProjectLibre XML (MSPDI) document."""
    path_name = source_name or "xml"
    if not data or not data.strip():
        return ImportResult(FORMAT_ID, None, (_issue("error", "xml.empty", path_name, "XML file is empty."),))
    if len(data) > MAX_IMPORT_BYTES:
        return ImportResult(
            FORMAT_ID,
            None,
            (_issue("error", "xml.too_large", path_name, f"File exceeds maximum size of {MAX_IMPORT_BYTES} bytes."),),
        )

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return ImportResult(FORMAT_ID, None, (_issue("error", "xml.parse_error", path_name, f"Malformed XML: {exc}"),))
    except Exception as exc:
        return ImportResult(FORMAT_ID, None, (_issue("error", "xml.error", path_name, f"Failed to parse XML: {exc}"),))

    if _strip_ns(root.tag) != "Project":
        return ImportResult(
            FORMAT_ID,
            None,
            (_issue("error", "mspdi.root_invalid", path_name, f"Root element must be <Project>, got <{root.tag}>"),),
        )

    issues: list[ValidationIssue] = []

    # Project metadata
    proj_name = _text_of(root, "Name") or _text_of(root, "Title") or (source_name.rsplit(".", 1)[0] if source_name else "Imported Project")
    proj_desc = _text_of(root, "Comments") or _text_of(root, "Subject") or ""
    proj_author = _text_of(root, "Author") or _text_of(root, "Manager")
    created_at = _parse_iso_datetime(_text_of(root, "CreationDate"))
    modified_at = _parse_iso_datetime(_text_of(root, "LastSaved"))
    start_date = _parse_iso_date(_text_of(root, "StartDate"))
    finish_date = _parse_iso_date(_text_of(root, "FinishDate"))
    currency = _text_of(root, "CurrencyCode") or "GBP"

    # Daily hours
    minutes_per_day_str = _text_of(root, "MinutesPerDay")
    try:
        minutes_per_day = float(minutes_per_day_str) if minutes_per_day_str else 480.0
    except ValueError:
        minutes_per_day = 480.0
    hours_per_day = max(1.0, minutes_per_day / 60.0)

    # 1. Calendars
    calendars: list[Calendar] = []
    cal_uid_to_id: dict[str, str] = {}
    default_calendar_id: str | None = None

    cals_elem = _find_child(root, "Calendars")
    if cals_elem is not None:
        for cal_el in _find_all_children(cals_elem, "Calendar"):
            cal_uid = _text_of(cal_el, "UID")
            cal_name = _text_of(cal_el, "Name") or "Standard"
            is_base = _text_of(cal_el, "IsBaseCalendar") == "1"

            working_days: list[int] = []
            working_periods: dict[int, list[WorkingPeriod]] = {}
            weekdays_el = _find_child(cal_el, "WeekDays")
            if weekdays_el is not None:
                for wd_el in _find_all_children(weekdays_el, "WeekDay"):
                    day_type_str = _text_of(wd_el, "DayType")
                    day_working_str = _text_of(wd_el, "DayWorking")
                    if not day_type_str:
                        continue
                    try:
                        day_type = int(day_type_str)
                    except ValueError:
                        continue
                    iso_wd = _MSPDI_TO_ISO_WEEKDAY.get(day_type)
                    if iso_wd is None:
                        continue

                    is_working = day_working_str == "1"
                    if is_working:
                        working_days.append(iso_wd)
                        periods = _parse_mspdi_working_times(_find_child(wd_el, "WorkingTimes"))
                        if not periods:
                            periods = [WorkingPeriod(time(8, 0), time(12, 0)), WorkingPeriod(time(13, 0), time(17, 0))]
                        working_periods[iso_wd] = periods

            if not working_days:
                working_days = [0, 1, 2, 3, 4]
            working_days.sort()

            calendar_obj = Calendar(
                id=new_id(),
                name=cal_name,
                external_ids={"mspdi:UID": cal_uid} if cal_uid else {},
                working_days=working_days,
                working_periods=working_periods,
            )
            calendars.append(calendar_obj)
            if cal_uid:
                cal_uid_to_id[cal_uid] = calendar_obj.id
            if is_base and default_calendar_id is None:
                default_calendar_id = calendar_obj.id

    if not default_calendar_id and calendars:
        default_calendar_id = calendars[0].id

    # 2. Resources
    resources: list[Resource] = []
    res_uid_to_id: dict[str, str] = {}
    res_outline_stack: dict[int, str] = {}
    res_elem = _find_child(root, "Resources")
    if res_elem is not None:
        for r_el in _find_all_children(res_elem, "Resource"):
            r_uid = _text_of(r_el, "UID")
            r_name = _text_of(r_el, "Name")
            if not r_name:
                continue  # skip unallocated / placeholder resources

            r_type_code = _text_of(r_el, "Type")
            # In MSPDI: 1=work, 0=material, 2=cost
            r_type = "material" if r_type_code == "0" else ("cost" if r_type_code == "2" else "work")

            max_units_str = _text_of(r_el, "MaxUnits")
            try:
                max_units = max(0.0, float(max_units_str)) if max_units_str is not None else 1.0
            except ValueError:
                max_units = 1.0

            std_rate = _parse_numeric_rate(_text_of(r_el, "StandardRate"))
            ot_rate = _parse_numeric_rate(_text_of(r_el, "OvertimeRate"))
            cost_per_use = _parse_numeric_rate(_text_of(r_el, "CostPerUse"))

            notes = _text_of(r_el, "Notes") or ""
            cal_uid_ref = _text_of(r_el, "CalendarUID")
            res_cal_id = cal_uid_to_id.get(cal_uid_ref) if cal_uid_ref else None

            res_custom: dict[str, Any] = {}
            group_text = (_text_of(r_el, "Group") or "").strip()
            if group_text:
                res_custom["group"] = group_text
            initials_text = (_text_of(r_el, "Initials") or "").strip()
            if initials_text:
                res_custom["initials"] = initials_text
            mat_label = (_text_of(r_el, "MaterialLabel") or "").strip()
            if mat_label:
                res_custom["material_label"] = mat_label

            res_level_str = _text_of(r_el, "OutlineLevel")
            res_level = 1
            if res_level_str:
                try:
                    res_level = max(1, int(res_level_str))
                except ValueError:
                    res_level = 1
            if res_level > 1 and (res_level - 1) in res_outline_stack:
                res_custom["parent_id"] = res_outline_stack[res_level - 1]

            rate_unit = mat_label if (r_type == "material" and mat_label) else ("unit" if r_type == "material" else "hour")

            res_obj = Resource(
                id=new_id(),
                name=r_name,
                external_ids={"mspdi:UID": r_uid} if r_uid else {},
                resource_type=r_type,
                max_units=max_units,
                standard_rate=std_rate,
                standard_rate_unit=rate_unit,
                overtime_rate=ot_rate,
                cost_per_use=cost_per_use,
                calendar_id=res_cal_id,
                notes=notes,
                custom_fields=res_custom,
            )
            resources.append(res_obj)
            res_outline_stack[res_level] = res_obj.id
            for deeper in list(res_outline_stack.keys()):
                if deeper > res_level:
                    del res_outline_stack[deeper]
            if r_uid:
                res_uid_to_id[r_uid] = res_obj.id

    # 3. Tasks & Hierarchy
    tasks: list[Task] = []
    task_uid_to_id: dict[str, str] = {}
    dependencies: list[Dependency] = []
    tasks_elem = _find_child(root, "Tasks")

    # Map outline levels to find parent_id
    outline_stack: dict[int, str] = {}
    raw_predecessor_links: list[tuple[str, ET.Element]] = []

    if tasks_elem is not None:
        raw_tasks = _find_all_children(tasks_elem, "Task")
        order = 0
        for t_el in raw_tasks:
            t_uid = _text_of(t_el, "UID")
            if not t_uid:
                continue

            # Check if this is the UID 0 project summary task
            outline_level_str = _text_of(t_el, "OutlineLevel")
            is_summary = _text_of(t_el, "Summary") == "1"
            try:
                outline_level = int(outline_level_str) if outline_level_str is not None else 1
            except ValueError:
                outline_level = 1

            if t_uid == "0" and outline_level == 0:
                # Root summary task representing the project itself
                summary_start = _parse_iso_date(_text_of(t_el, "Start"))
                summary_finish = _parse_iso_date(_text_of(t_el, "Finish"))
                if summary_start and not start_date:
                    start_date = summary_start
                if summary_finish and not finish_date:
                    finish_date = summary_finish
                continue

            t_name = _text_of(t_el, "Name") or f"Task {t_uid}"
            t_notes = _text_of(t_el, "Notes") or ""
            t_start = _parse_iso_date(_text_of(t_el, "Start"))
            t_finish = _parse_iso_date(_text_of(t_el, "Finish"))
            if t_start and t_finish and t_finish < t_start:
                t_finish = t_start

            t_duration_raw = _text_of(t_el, "Duration")
            duration_val, duration_unit = _parse_mspdi_duration(t_duration_raw, hours_per_day)

            # Milestones in MSPDI: Milestone tag == 1, or duration is 0
            is_milestone = _text_of(t_el, "Milestone") == "1"
            if is_milestone:
                duration_val = 0.0
                duration_unit = "day"

            pct_str = _text_of(t_el, "PercentComplete")
            try:
                pct_complete = float(pct_str) if pct_str is not None else 0.0
            except ValueError:
                pct_complete = 0.0

            priority_str = _text_of(t_el, "Priority")
            priority: int | None = None
            if priority_str:
                try:
                    priority = int(priority_str)
                except ValueError:
                    pass

            work_str = _text_of(t_el, "Work")
            est_work, work_unit = _parse_mspdi_duration(work_str, hours_per_day)

            act_work_str = _text_of(t_el, "ActualWork")
            act_work, _ = _parse_mspdi_duration(act_work_str, hours_per_day)

            rem_work_str = _text_of(t_el, "RemainingWork")
            rem_work, _ = _parse_mspdi_duration(rem_work_str, hours_per_day)

            cost_str = _text_of(t_el, "Cost")
            est_cost: float | None = None
            if cost_str:
                try:
                    est_cost = float(cost_str)
                except ValueError:
                    pass

            act_cost_str = _text_of(t_el, "ActualCost")
            act_cost: float | None = None
            if act_cost_str:
                try:
                    act_cost = float(act_cost_str)
                except ValueError:
                    pass

            # Constraints
            c_type_code = _text_of(t_el, "ConstraintType")
            constraint_type = None
            if c_type_code:
                try:
                    c_int = int(c_type_code)
                    constraint_type = _MSPDI_TO_CONSTRAINT.get(c_int)
                except ValueError:
                    pass

            c_date = _parse_iso_date(_text_of(t_el, "ConstraintDate"))
            deadline = _parse_iso_date(_text_of(t_el, "Deadline"))

            # Determine parent_id from outline_level
            parent_id = None
            if outline_level > 1:
                parent_id = outline_stack.get(outline_level - 1)

            task_obj = Task(
                id=new_id(),
                name=t_name,
                description=t_notes,
                external_ids={"mspdi:UID": t_uid},
                parent_id=parent_id,
                outline_level=outline_level,
                order=order,
                start_date=t_start,
                finish_date=t_finish,
                duration=duration_val,
                duration_unit=duration_unit,
                percent_complete=pct_complete,
                priority=priority,
                milestone=is_milestone,
                task_type="milestone" if is_milestone else ("summary" if is_summary else "task"),
                schedule_mode="manual" if _text_of(t_el, "Manual") == "1" else "auto",
                deadline=deadline,
                constraint_type=constraint_type,
                constraint_date=c_date,
                estimated_work=est_work,
                actual_work=act_work,
                remaining_work=rem_work,
                work_unit=work_unit,
                estimated_cost=est_cost,
                actual_cost=act_cost,
            )
            tasks.append(task_obj)
            task_uid_to_id[t_uid] = task_obj.id
            outline_stack[outline_level] = task_obj.id
            # Clean up deeper outline levels
            for deeper in list(outline_stack.keys()):
                if deeper > outline_level:
                    del outline_stack[deeper]

            order += 1

            # Save predecessor links for resolution after all tasks are indexed
            for pred_el in _find_all_children(t_el, "PredecessorLink"):
                raw_predecessor_links.append((task_obj.id, pred_el))

    # Resolve dependencies
    for succ_id, pred_el in raw_predecessor_links:
        pred_uid = _text_of(pred_el, "PredecessorUID")
        if not pred_uid or pred_uid not in task_uid_to_id:
            issues.append(
                _issue("warning", "mspdi.dependency.unknown_predecessor", f"Task[{succ_id}]", f"Unknown predecessor UID {pred_uid}")
            )
            continue
        pred_id = task_uid_to_id[pred_uid]

        type_str = _text_of(pred_el, "Type")
        try:
            type_int = int(type_str) if type_str is not None else 1
        except ValueError:
            type_int = 1
        rel_type = _MSPDI_TO_RELATIONSHIP.get(type_int, "finish_to_start")

        lag_str = _text_of(pred_el, "LinkLag")
        lag_val = 0.0
        lag_unit = "day"
        if lag_str:
            try:
                # LinkLag in MSPDI is represented in tenths of a minute (e.g., 4800 = 480 min = 8 hr = 1 day)
                tenths = float(lag_str)
                lag_minutes = tenths / 10.0
                lag_val = round(lag_minutes / (hours_per_day * 60.0), 3)
            except ValueError:
                # Or check if it's an ISO duration
                d_val, d_u = _parse_mspdi_duration(lag_str, hours_per_day)
                if d_val is not None:
                    lag_val = d_val
                    lag_unit = d_u

        dependencies.append(
            Dependency(
                id=new_id(),
                predecessor_id=pred_id,
                successor_id=succ_id,
                relationship_type=rel_type,
                lag=lag_val,
                lag_unit=lag_unit,
                external_ids={"mspdi:PredecessorUID": pred_uid},
            )
        )

    # 4. Assignments
    res_obj_by_id = {r.id: r for r in resources}
    assignments: list[Assignment] = []
    assign_elem = _find_child(root, "Assignments")
    if assign_elem is not None:
        for a_el in _find_all_children(assign_elem, "Assignment"):
            t_uid = _text_of(a_el, "TaskUID")
            r_uid = _text_of(a_el, "ResourceUID")
            if not t_uid or not r_uid or t_uid not in task_uid_to_id or r_uid not in res_uid_to_id:
                continue

            task_id = task_uid_to_id[t_uid]
            res_id = res_uid_to_id[r_uid]
            res_ref = res_obj_by_id.get(res_id)

            units_str = _text_of(a_el, "Units")
            try:
                units = max(0.0, float(units_str)) if units_str is not None else 1.0
            except ValueError:
                units = 1.0

            work_str = _text_of(a_el, "Work")
            work_val, work_u = _parse_mspdi_duration(work_str, hours_per_day)

            act_work_str = _text_of(a_el, "ActualWork")
            act_work_val, _ = _parse_mspdi_duration(act_work_str, hours_per_day)

            rem_work_str = _text_of(a_el, "RemainingWork")
            rem_work_val, _ = _parse_mspdi_duration(rem_work_str, hours_per_day)

            cost_val = _parse_numeric_rate(_text_of(a_el, "Cost"))
            if cost_val is None and res_ref is not None and res_ref.resource_type == "material":
                if res_ref.standard_rate is not None or res_ref.cost_per_use is not None:
                    cost_val = units * (res_ref.standard_rate or 0.0) + (res_ref.cost_per_use or 0.0)

            act_cost_val = _parse_numeric_rate(_text_of(a_el, "ActualCost"))

            a_start = _parse_iso_date(_text_of(a_el, "Start"))
            a_finish = _parse_iso_date(_text_of(a_el, "Finish"))
            if a_start and a_finish and a_finish < a_start:
                a_finish = a_start

            assignments.append(
                Assignment(
                    id=new_id(),
                    task_id=task_id,
                    resource_id=res_id,
                    units=units,
                    work=work_val,
                    work_unit=work_u,
                    actual_work=act_work_val,
                    remaining_work=rem_work_val,
                    cost=cost_val,
                    actual_cost=act_cost_val,
                    start_date=a_start,
                    finish_date=a_finish,
                    external_ids={"mspdi:TaskUID": t_uid, "mspdi:ResourceUID": r_uid},
                )
            )

    if start_date and finish_date and finish_date < start_date:
        task_finishes = [t.finish_date for t in tasks if t.finish_date]
        finish_date = max([start_date, *task_finishes])

    project = Project(
        id=new_id(),
        name=proj_name,
        description=proj_desc,
        author=proj_author,
        created_at=created_at,
        modified_at=modified_at,
        start_date=start_date,
        finish_date=finish_date,
        currency=currency,
        default_calendar_id=default_calendar_id,
        tasks=tasks,
        dependencies=dependencies,
        resources=resources,
        assignments=assignments,
        calendars=calendars,
    )

    report = validate_project(project)
    all_issues = tuple(issues) + report.issues
    return ImportResult(FORMAT_ID, project, all_issues)


def export_project(project: Project) -> ExportResult:
    """Export a PlanForge Project to Microsoft Project / ProjectLibre XML (MSPDI)."""
    validation = validate_project(project)
    if not validation.valid:
        return ExportResult(FORMAT_ID, None, validation.issues)

    ET.register_namespace("", MSPDI_NAMESPACE)
    root = ET.Element(f"{{{MSPDI_NAMESPACE}}}Project")

    # Project metadata
    def add_sub(parent: ET.Element, name: str, text: str | None) -> ET.Element:
        elem = ET.SubElement(parent, f"{{{MSPDI_NAMESPACE}}}{name}")
        if text is not None:
            elem.text = text
        return elem

    add_sub(root, "SaveVersion", "14")
    add_sub(root, "Name", project.name)
    add_sub(root, "Title", project.name)
    if project.description:
        add_sub(root, "Comments", project.description)
    if project.author:
        add_sub(root, "Author", project.author)

    created_iso = (project.created_at or datetime.now()).isoformat()
    add_sub(root, "CreationDate", created_iso)
    add_sub(root, "LastSaved", (project.modified_at or datetime.now()).isoformat())

    # Schedule dates
    if project.start_date:
        add_sub(root, "StartDate", f"{project.start_date.isoformat()}T08:00:00")
    if project.finish_date:
        add_sub(root, "FinishDate", f"{project.finish_date.isoformat()}T17:00:00")

    add_sub(root, "ScheduleFromStart", "1")
    add_sub(root, "DefaultStartTime", "08:00:00")
    add_sub(root, "DefaultFinishTime", "17:00:00")
    add_sub(root, "MinutesPerDay", "480")
    add_sub(root, "MinutesPerWeek", "2400")
    add_sub(root, "DaysPerMonth", "20")
    add_sub(root, "DefaultTaskType", "0")
    add_sub(root, "DefaultFixedCostAccrual", "3")
    add_sub(root, "DefaultStandardRate", "0")
    add_sub(root, "DefaultOvertimeRate", "0")
    add_sub(root, "CurrencyDigits", "2")
    add_sub(root, "CurrencyCode", project.currency or "GBP")
    add_sub(root, "CurrencySymbol", "£" if project.currency == "GBP" else ("$" if project.currency == "USD" else "€"))

    # 1. Calendars
    cals_elem = add_sub(root, "Calendars", None)
    cal_id_to_uid: dict[str, str] = {}
    cal_counter = 1
    for cal in project.calendars:
        cal_uid = str(cal_counter)
        cal_id_to_uid[cal.id] = cal_uid
        cal_counter += 1

        cal_el = add_sub(cals_elem, "Calendar", None)
        add_sub(cal_el, "UID", cal_uid)
        add_sub(cal_el, "Name", cal.name)
        is_base = "1" if (cal.id == project.default_calendar_id or cal_counter == 2) else "0"
        add_sub(cal_el, "IsBaseCalendar", is_base)

        weekdays_el = add_sub(cal_el, "WeekDays", None)
        # All 7 days in MSPDI (1=Sun .. 7=Sat)
        for mspdi_day in range(1, 8):
            iso_day = _MSPDI_TO_ISO_WEEKDAY[mspdi_day]
            is_working = iso_day in cal.working_days
            wd_el = add_sub(weekdays_el, "WeekDay", None)
            add_sub(wd_el, "DayType", str(mspdi_day))
            add_sub(wd_el, "DayWorking", "1" if is_working else "0")
            if is_working:
                periods = cal.working_periods.get(iso_day, [])
                if periods:
                    wtimes_el = add_sub(wd_el, "WorkingTimes", None)
                    for period in periods:
                        wt_el = add_sub(wtimes_el, "WorkingTime", None)
                        add_sub(wt_el, "FromTime", period.start.isoformat())
                        add_sub(wt_el, "ToTime", period.finish.isoformat())

    # Ensure at least one calendar exists
    if not project.calendars:
        cal_el = add_sub(cals_elem, "Calendar", None)
        add_sub(cal_el, "UID", "1")
        add_sub(cal_el, "Name", "Standard")
        add_sub(cal_el, "IsBaseCalendar", "1")
        weekdays_el = add_sub(cal_el, "WeekDays", None)
        for mspdi_day in range(1, 8):
            iso_day = _MSPDI_TO_ISO_WEEKDAY[mspdi_day]
            is_working = iso_day in (0, 1, 2, 3, 4)
            wd_el = add_sub(weekdays_el, "WeekDay", None)
            add_sub(wd_el, "DayType", str(mspdi_day))
            add_sub(wd_el, "DayWorking", "1" if is_working else "0")
            if is_working:
                wtimes_el = add_sub(wd_el, "WorkingTimes", None)
                wt1 = add_sub(wtimes_el, "WorkingTime", None)
                add_sub(wt1, "FromTime", "08:00:00")
                add_sub(wt1, "ToTime", "12:00:00")
                wt2 = add_sub(wtimes_el, "WorkingTime", None)
                add_sub(wt2, "FromTime", "13:00:00")
                add_sub(wt2, "ToTime", "17:00:00")

    # 2. Tasks & Hierarchy calculation
    tasks_elem = add_sub(root, "Tasks", None)

    # Calculate hierarchy outline levels
    parent_map: dict[str, str | None] = {t.id: t.parent_id for t in project.tasks}
    children_map: dict[str, list[str]] = {}
    for t in project.tasks:
        if t.parent_id:
            children_map.setdefault(t.parent_id, []).append(t.id)

    def get_level(task_id: str) -> int:
        lvl = 1
        curr = parent_map.get(task_id)
        visited = set()
        while curr and curr not in visited:
            visited.add(curr)
            lvl += 1
            curr = parent_map.get(curr)
        return lvl

    # Index tasks
    task_id_to_uid: dict[str, str] = {}
    task_counter = 1
    for t in project.tasks:
        task_id_to_uid[t.id] = str(task_counter)
        task_counter += 1

    # Map predecessors: successor_id -> list[Dependency]
    preds_by_succ: dict[str, list[Dependency]] = {}
    for dep in project.dependencies:
        preds_by_succ.setdefault(dep.successor_id, []).append(dep)

    for idx, t in enumerate(project.tasks, start=1):
        t_el = add_sub(tasks_elem, "Task", None)
        t_uid = task_id_to_uid[t.id]
        add_sub(t_el, "UID", t_uid)
        add_sub(t_el, "ID", str(idx))
        add_sub(t_el, "Name", t.name)
        if t.description:
            add_sub(t_el, "Notes", t.description)
        add_sub(t_el, "Active", "1")
        add_sub(t_el, "Manual", "1" if t.schedule_mode == "manual" else "0")
        add_sub(t_el, "Type", "0")
        add_sub(t_el, "IsNull", "0")

        lvl = t.outline_level or get_level(t.id)
        add_sub(t_el, "OutlineLevel", str(lvl))

        if t.priority is not None:
            add_sub(t_el, "Priority", str(t.priority))
        else:
            add_sub(t_el, "Priority", "500")

        if t.start_date:
            add_sub(t_el, "Start", f"{t.start_date.isoformat()}T08:00:00")
        if t.finish_date:
            add_sub(t_el, "Finish", f"{t.finish_date.isoformat()}T17:00:00")

        is_m = t.milestone or t.task_type == "milestone"
        is_s = t.id in children_map or t.task_type == "summary"

        add_sub(t_el, "Milestone", "1" if is_m else "0")
        add_sub(t_el, "Summary", "1" if is_s else "0")

        dur_str = _format_mspdi_duration(0.0 if is_m else t.duration, t.duration_unit)
        add_sub(t_el, "Duration", dur_str)
        add_sub(t_el, "DurationFormat", "21")  # days

        if t.estimated_work is not None:
            add_sub(t_el, "Work", _format_mspdi_work(t.estimated_work, t.work_unit))
        if t.actual_work is not None:
            add_sub(t_el, "ActualWork", _format_mspdi_work(t.actual_work, t.work_unit))
        if t.remaining_work is not None:
            add_sub(t_el, "RemainingWork", _format_mspdi_work(t.remaining_work, t.work_unit))

        pct = int(round(t.percent_complete))
        add_sub(t_el, "PercentComplete", str(pct))
        add_sub(t_el, "PercentWorkComplete", str(pct))

        if t.estimated_cost is not None:
            add_sub(t_el, "Cost", f"{t.estimated_cost:.2f}")
        if t.actual_cost is not None:
            add_sub(t_el, "ActualCost", f"{t.actual_cost:.2f}")

        if t.deadline:
            add_sub(t_el, "Deadline", f"{t.deadline.isoformat()}T17:00:00")

        if t.constraint_type:
            c_code = _CONSTRAINT_TO_MSPDI.get(t.constraint_type, 0)
            add_sub(t_el, "ConstraintType", str(c_code))
            if t.constraint_date:
                add_sub(t_el, "ConstraintDate", f"{t.constraint_date.isoformat()}T08:00:00")

        # Predecessor links
        for dep in preds_by_succ.get(t.id, []):
            pred_uid = task_id_to_uid.get(dep.predecessor_id)
            if not pred_uid:
                continue
            p_link = add_sub(t_el, "PredecessorLink", None)
            add_sub(p_link, "PredecessorUID", pred_uid)
            dep_type = _RELATIONSHIP_TO_MSPDI.get(dep.relationship_type, 1)
            add_sub(p_link, "Type", str(dep_type))
            add_sub(p_link, "CrossProject", "0")
            # Lag: MSPDI stores in tenths of a minute
            lag_days = dep.lag
            if dep.lag_unit == "hour":
                lag_days = dep.lag / 8.0
            elif dep.lag_unit == "minute":
                lag_days = dep.lag / 480.0
            tenths_min = int(round(lag_days * 8.0 * 60.0 * 10.0))
            add_sub(p_link, "LinkLag", str(tenths_min))
            add_sub(p_link, "LagFormat", "7")  # days

    # 3. Resources
    res_elem = add_sub(root, "Resources", None)
    res_id_to_uid: dict[str, str] = {}
    res_parent_map: dict[str, str | None] = {
        r.id: (str(r.custom_fields["parent_id"]) if isinstance(r.custom_fields.get("parent_id"), str) else None)
        for r in project.resources
    }

    def get_res_level(res_id: str) -> int:
        lvl = 1
        curr = res_parent_map.get(res_id)
        seen: set[str] = set()
        while curr and curr not in seen and curr in res_parent_map:
            seen.add(curr)
            lvl += 1
            curr = res_parent_map.get(curr)
        return lvl

    res_counter = 1
    for r in project.resources:
        r_uid = str(res_counter)
        res_id_to_uid[r.id] = r_uid
        res_counter += 1

        r_el = add_sub(res_elem, "Resource", None)
        add_sub(r_el, "UID", r_uid)
        add_sub(r_el, "ID", r_uid)
        add_sub(r_el, "Name", r.name)
        initials_val = r.custom_fields.get("initials")
        if isinstance(initials_val, str) and initials_val.strip():
            add_sub(r_el, "Initials", initials_val.strip())
        group_val = r.custom_fields.get("group")
        if isinstance(group_val, str) and group_val.strip():
            add_sub(r_el, "Group", group_val.strip())
        res_lvl = get_res_level(r.id)
        if res_lvl > 1:
            add_sub(r_el, "OutlineLevel", str(res_lvl))
        # Type: 1=work, 0=material, 2=cost
        type_num = "0" if r.resource_type == "material" else ("2" if r.resource_type == "cost" else "1")
        add_sub(r_el, "Type", type_num)
        mat_label_val = r.custom_fields.get("material_label")
        if isinstance(mat_label_val, str) and mat_label_val.strip():
            add_sub(r_el, "MaterialLabel", mat_label_val.strip())
        add_sub(r_el, "IsNull", "0")
        add_sub(r_el, "MaxUnits", str(r.max_units))
        if r.standard_rate is not None:
            add_sub(r_el, "StandardRate", f"{r.standard_rate:.2f}")
            add_sub(r_el, "StandardRateFormat", "8" if r.resource_type == "material" else "2")
        if r.overtime_rate is not None:
            add_sub(r_el, "OvertimeRate", f"{r.overtime_rate:.2f}")
        if r.cost_per_use is not None:
            add_sub(r_el, "CostPerUse", f"{r.cost_per_use:.2f}")
        if r.notes:
            add_sub(r_el, "Notes", r.notes)
        if r.calendar_id and r.calendar_id in cal_id_to_uid:
            add_sub(r_el, "CalendarUID", cal_id_to_uid[r.calendar_id])
        elif project.calendars:
            add_sub(r_el, "CalendarUID", "1")

    # 4. Assignments
    assign_elem = add_sub(root, "Assignments", None)
    assign_counter = 1
    for a in project.assignments:
        t_uid = task_id_to_uid.get(a.task_id)
        r_uid = res_id_to_uid.get(a.resource_id)
        if not t_uid or not r_uid:
            continue

        a_uid = str(assign_counter)
        assign_counter += 1

        a_el = add_sub(assign_elem, "Assignment", None)
        add_sub(a_el, "UID", a_uid)
        add_sub(a_el, "TaskUID", t_uid)
        add_sub(a_el, "ResourceUID", r_uid)
        add_sub(a_el, "Units", str(a.units))
        if a.work is not None:
            add_sub(a_el, "Work", _format_mspdi_work(a.work, a.work_unit))
        if a.actual_work is not None:
            add_sub(a_el, "ActualWork", _format_mspdi_work(a.actual_work, a.work_unit))
        if a.remaining_work is not None:
            add_sub(a_el, "RemainingWork", _format_mspdi_work(a.remaining_work, a.work_unit))
        if a.cost is not None:
            add_sub(a_el, "Cost", f"{a.cost:.2f}")
        if a.actual_cost is not None:
            add_sub(a_el, "ActualCost", f"{a.actual_cost:.2f}")
        if a.start_date:
            add_sub(a_el, "Start", f"{a.start_date.isoformat()}T08:00:00")
        if a.finish_date:
            add_sub(a_el, "Finish", f"{a.finish_date.isoformat()}T17:00:00")

    output_stream = io.BytesIO()
    tree = ET.ElementTree(root)
    tree.write(output_stream, encoding="utf-8", xml_declaration=True)
    xml_bytes = output_stream.getvalue()

    return ExportResult(FORMAT_ID, xml_bytes, validation.issues)


__all__ = [
    "FORMAT_ID",
    "FORMAT_NAME",
    "MAX_IMPORT_BYTES",
    "MSPDI_NAMESPACE",
    "export_project",
    "import_bytes",
]
