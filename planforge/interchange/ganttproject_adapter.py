"""GanttProject (.gan) XML interchange adapter.

Parses and generates GanttProject XML project files (.gan), preserving task
hierarchies, dates, durations, dependencies, milestones, resources,
allocations, and calendars.
"""

from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
from datetime import date, datetime, time
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
    Project,
    Resource,
    Task,
    WorkingPeriod,
    new_id,
)

FORMAT_ID = "ganttproject"
FORMAT_NAME = "GanttProject (.gan)"
MAX_IMPORT_BYTES = 50 * 1024 * 1024

# GanttProject dependency types:
# 1: Start-to-Start (SS)
# 2: Finish-to-Start (FS)
# 3: Finish-to-Finish (FF)
# 4: Start-to-Finish (SF)
_GAN_TO_RELATIONSHIP = {
    1: "start_to_start",
    2: "finish_to_start",
    3: "finish_to_finish",
    4: "start_to_finish",
}

_RELATIONSHIP_TO_GAN = {
    "start_to_start": 1,
    "finish_to_start": 2,
    "finish_to_finish": 3,
    "start_to_finish": 4,
}


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)


def _strip_ns(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if _strip_ns(child.tag) == name:
            return child
    return None


def _find_all_children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _strip_ns(child.tag) == name]


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    val = value.strip()
    try:
        return date.fromisoformat(val)
    except ValueError:
        return None


def import_bytes(data: bytes, *, source_name: str | None = None) -> ImportResult:
    """Import a GanttProject (.gan) XML document."""
    path_name = source_name or "gan"
    if not data or not data.strip():
        return ImportResult(FORMAT_ID, None, (_issue("error", "gan.empty", path_name, "GanttProject file is empty."),))
    if len(data) > MAX_IMPORT_BYTES:
        return ImportResult(
            FORMAT_ID,
            None,
            (_issue("error", "gan.too_large", path_name, f"File exceeds maximum size of {MAX_IMPORT_BYTES} bytes."),),
        )

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return ImportResult(FORMAT_ID, None, (_issue("error", "gan.parse_error", path_name, f"Malformed XML: {exc}"),))
    except Exception as exc:
        return ImportResult(FORMAT_ID, None, (_issue("error", "gan.error", path_name, f"Failed to parse XML: {exc}"),))

    if _strip_ns(root.tag) != "project":
        return ImportResult(
            FORMAT_ID,
            None,
            (_issue("error", "gan.root_invalid", path_name, f"Root element must be <project>, got <{root.tag}>"),),
        )

    issues: list[ValidationIssue] = []

    proj_name = root.attrib.get("name") or (source_name.rsplit(".", 1)[0] if source_name else "GanttProject Plan")
    desc_elem = _find_child(root, "description")
    proj_desc = (desc_elem.text or "").strip() if desc_elem is not None else ""

    view_date_str = root.attrib.get("view-date")
    start_date = _parse_iso_date(view_date_str)

    # 1. Calendars & Holidays
    working_days = [0, 1, 2, 3, 4]  # Mon-Fri
    holidays: list[date] = []

    cals_elem = _find_child(root, "calendars")
    if cals_elem is not None:
        day_types_elem = _find_child(cals_elem, "day-types")
        if day_types_elem is not None:
            def_week_elem = _find_child(day_types_elem, "default-week")
            if def_week_elem is not None:
                # In GanttProject default-week: 0 is working, 1 is non-working
                wd_keys = [("mon", 0), ("tue", 1), ("wed", 2), ("thu", 3), ("fri", 4), ("sat", 5), ("sun", 6)]
                parsed_wd = []
                for attr, iso_num in wd_keys:
                    val = def_week_elem.attrib.get(attr)
                    if val == "0":
                        parsed_wd.append(iso_num)
                if parsed_wd:
                    working_days = parsed_wd

        for date_el in _find_all_children(cals_elem, "date"):
            if date_el.attrib.get("type") in ("HOLIDAY", "NEUTRAL"):
                try:
                    y = int(date_el.attrib["year"])
                    m = int(date_el.attrib["month"])
                    d = int(date_el.attrib["date"])
                    holidays.append(date(y, m, d))
                except (KeyError, ValueError):
                    pass

    cal_obj = Calendar(
        id=new_id(),
        name="Default",
        working_days=working_days,
        holidays=holidays,
    )
    calendars = [cal_obj]

    # 2. Resources
    resources: list[Resource] = []
    res_gan_to_id: dict[str, str] = {}
    res_elem = _find_child(root, "resources")
    if res_elem is not None:
        for r_el in _find_all_children(res_elem, "resource"):
            r_id = r_el.attrib.get("id")
            r_name = r_el.attrib.get("name")
            if not r_id or not r_name:
                continue

            rate_val: float | None = None
            rate_el = _find_child(r_el, "rate")
            if rate_el is not None:
                rate_str = rate_el.attrib.get("value")
                if rate_str:
                    try:
                        rate_val = float(rate_str)
                    except ValueError:
                        pass

            notes_parts = []
            phone = r_el.attrib.get("phone")
            if phone:
                notes_parts.append(f"Phone: {phone}")
            contacts = r_el.attrib.get("contacts")
            if contacts:
                notes_parts.append(f"Contacts: {contacts}")
            role = r_el.attrib.get("function")
            if role:
                notes_parts.append(f"Role: {role}")

            res = Resource(
                id=new_id(),
                name=r_name,
                external_ids={"ganttproject:id": r_id},
                standard_rate=rate_val,
                notes="; ".join(notes_parts),
                calendar_id=cal_obj.id,
            )
            resources.append(res)
            res_gan_to_id[r_id] = res.id

    # 3. Tasks & Hierarchy
    tasks: list[Task] = []
    task_gan_to_id: dict[str, str] = {}
    raw_dependencies: list[tuple[str, str, int, float]] = []  # (pred_gan_id, succ_gan_id, type_int, diff)

    tasks_elem = _find_child(root, "tasks")

    def parse_task_element(t_el: ET.Element, parent_id: str | None = None, outline_level: int = 1, order_start: int = 0) -> int:
        nonlocal tasks, task_gan_to_id, raw_dependencies
        t_id = t_el.attrib.get("id")
        if not t_id:
            return order_start

        name = t_el.attrib.get("name") or f"Task {t_id}"
        is_meeting = t_el.attrib.get("meeting") == "true"
        start = _parse_iso_date(t_el.attrib.get("start"))

        dur_str = t_el.attrib.get("duration")
        try:
            dur = float(dur_str) if dur_str is not None else 1.0
        except ValueError:
            dur = 1.0

        if is_meeting:
            dur = 0.0

        comp_str = t_el.attrib.get("complete")
        try:
            complete = float(comp_str) if comp_str is not None else 0.0
        except ValueError:
            complete = 0.0

        notes_el = _find_child(t_el, "notes")
        notes = (notes_el.text or "").strip() if notes_el is not None else ""

        cost_val: float | None = None
        cost_str = t_el.attrib.get("cost-manual-value")
        if cost_str:
            try:
                cost_val = float(cost_str)
            except ValueError:
                pass

        # Check child tasks
        child_elems = _find_all_children(t_el, "task")
        is_summary = bool(child_elems)

        task = Task(
            id=new_id(),
            name=name,
            description=notes,
            external_ids={"ganttproject:id": t_id},
            parent_id=parent_id,
            outline_level=outline_level,
            order=order_start,
            start_date=start,
            duration=dur,
            duration_unit="day",
            percent_complete=complete,
            milestone=is_meeting,
            task_type="milestone" if is_meeting else ("summary" if is_summary else "task"),
            estimated_cost=cost_val,
        )
        tasks.append(task)
        task_gan_to_id[t_id] = task.id
        current_order = order_start + 1

        # Dependencies: in GanttProject, <depend id="SUCC_ID"/> inside task P means P is predecessor and SUCC_ID is successor
        for dep_el in _find_all_children(t_el, "depend"):
            succ_id = dep_el.attrib.get("id")
            if succ_id:
                t_type_str = dep_el.attrib.get("type")
                try:
                    t_type_int = int(t_type_str) if t_type_str is not None else 2
                except ValueError:
                    t_type_int = 2
                diff_str = dep_el.attrib.get("difference")
                try:
                    diff_val = float(diff_str) if diff_str is not None else 0.0
                except ValueError:
                    diff_val = 0.0
                raw_dependencies.append((t_id, succ_id, t_type_int, diff_val))

        # Recursively parse child subtasks
        for child_el in child_elems:
            current_order = parse_task_element(child_el, parent_id=task.id, outline_level=outline_level + 1, order_start=current_order)

        return current_order

    if tasks_elem is not None:
        order = 0
        for child_el in _find_all_children(tasks_elem, "task"):
            order = parse_task_element(child_el, parent_id=None, outline_level=1, order_start=order)

    # 4. Resolve Dependencies
    dependencies: list[Dependency] = []
    for pred_gan_id, succ_gan_id, type_int, diff_val in raw_dependencies:
        if pred_gan_id in task_gan_to_id and succ_gan_id in task_gan_to_id:
            pred_id = task_gan_to_id[pred_gan_id]
            succ_id = task_gan_to_id[succ_gan_id]
            rel_type = _GAN_TO_RELATIONSHIP.get(type_int, "finish_to_start")
            dependencies.append(
                Dependency(
                    id=new_id(),
                    predecessor_id=pred_id,
                    successor_id=succ_id,
                    relationship_type=rel_type,
                    lag=diff_val,
                    lag_unit="day",
                    external_ids={"ganttproject:pred": pred_gan_id, "ganttproject:succ": succ_gan_id},
                )
            )

    # 5. Allocations
    assignments: list[Assignment] = []
    alloc_elem = _find_child(root, "allocations")
    if alloc_elem is not None:
        for a_el in _find_all_children(alloc_elem, "allocation"):
            t_gan = a_el.attrib.get("task-id")
            r_gan = a_el.attrib.get("resource-id")
            if not t_gan or not r_gan or t_gan not in task_gan_to_id or r_gan not in res_gan_to_id:
                continue

            load_str = a_el.attrib.get("load")
            try:
                load_pct = float(load_str) if load_str is not None else 100.0
                units = load_pct / 100.0
            except ValueError:
                units = 1.0

            assignments.append(
                Assignment(
                    id=new_id(),
                    task_id=task_gan_to_id[t_gan],
                    resource_id=res_gan_to_id[r_gan],
                    units=units,
                    external_ids={"ganttproject:task-id": t_gan, "ganttproject:resource-id": r_gan},
                )
            )

    # Compute project start/finish from tasks if needed
    task_starts = [t.start_date for t in tasks if t.start_date]
    if task_starts and not start_date:
        start_date = min(task_starts)

    project = Project(
        id=new_id(),
        name=proj_name,
        description=proj_desc,
        start_date=start_date,
        default_calendar_id=cal_obj.id,
        tasks=tasks,
        dependencies=dependencies,
        resources=resources,
        assignments=assignments,
        calendars=calendars,
    )

    report = validate_project(project)
    return ImportResult(FORMAT_ID, project, tuple(issues) + report.issues)


def export_project(project: Project) -> ExportResult:
    """Export a PlanForge Project to GanttProject (.gan) XML format."""
    validation = validate_project(project)
    if not validation.valid:
        return ExportResult(FORMAT_ID, None, validation.issues)

    root = ET.Element("project")
    root.attrib["name"] = project.name
    root.attrib["company"] = ""
    root.attrib["webLink"] = ""
    view_date = project.start_date or (project.tasks[0].start_date if project.tasks and project.tasks[0].start_date else date.today())
    root.attrib["view-date"] = view_date.isoformat()
    root.attrib["version"] = "3.2.3240"
    root.attrib["locale"] = "en"

    desc_elem = ET.SubElement(root, "description")
    if project.description:
        desc_elem.text = project.description

    # Calendars
    cals_elem = ET.SubElement(root, "calendars")
    day_types_elem = ET.SubElement(cals_elem, "day-types")
    ET.SubElement(day_types_elem, "day-type", {"id": "0"})
    ET.SubElement(day_types_elem, "day-type", {"id": "1"})

    cal = project.calendars[0] if project.calendars else Calendar()
    def_week_attribs = {"id": "1", "name": "default"}
    # In GanttProject: 0 is working, 1 is non-working
    iso_to_name = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
    for iso_num, name in iso_to_name.items():
        def_week_attribs[name] = "0" if iso_num in cal.working_days else "1"

    ET.SubElement(day_types_elem, "default-week", def_week_attribs)

    for hol in cal.holidays:
        ET.SubElement(cals_elem, "date", {"year": str(hol.year), "month": str(hol.month), "date": str(hol.day), "type": "HOLIDAY"})

    # Index tasks and predecessors
    task_id_to_gan: dict[str, str] = {}
    for idx, t in enumerate(project.tasks):
        task_id_to_gan[t.id] = str(idx)

    # In GanttProject: dependencies go inside predecessor task: <depend id="SUCC_ID"/>
    succs_by_pred: dict[str, list[Dependency]] = {}
    for dep in project.dependencies:
        succs_by_pred.setdefault(dep.predecessor_id, []).append(dep)

    tasks_elem = ET.SubElement(root, "tasks", {"empty-milestones": "true"})

    # Group by parent
    children_by_parent: dict[str | None, list[Task]] = {}
    for t in project.tasks:
        children_by_parent.setdefault(t.parent_id, []).append(t)

    def write_task_tree(parent_element: ET.Element, task_list: list[Task]) -> None:
        for t in task_list:
            gan_id = task_id_to_gan[t.id]
            is_m = t.milestone or t.task_type == "milestone"

            # Duration in working days
            dur_days = 0 if is_m else int(round(t.duration if t.duration is not None else 1.0))
            if t.duration_unit == "hour" and not is_m:
                dur_days = max(1, int(round((t.duration or 8.0) / 8.0)))

            start_str = t.start_date.isoformat() if t.start_date else view_date.isoformat()
            t_attribs = {
                "id": gan_id,
                "name": t.name,
                "meeting": "true" if is_m else "false",
                "start": start_str,
                "duration": str(dur_days),
                "complete": str(int(round(t.percent_complete))),
                "expand": "true",
            }
            if t.estimated_cost is not None:
                t_attribs["cost-manual-value"] = f"{t.estimated_cost:.2f}"

            t_elem = ET.SubElement(parent_element, "task", t_attribs)

            if t.description:
                n_el = ET.SubElement(t_elem, "notes")
                n_el.text = t.description

            # Dependencies where t is predecessor
            for dep in succs_by_pred.get(t.id, []):
                succ_gan = task_id_to_gan.get(dep.successor_id)
                if succ_gan:
                    type_num = _RELATIONSHIP_TO_GAN.get(dep.relationship_type, 2)
                    ET.SubElement(
                        t_elem,
                        "depend",
                        {"id": succ_gan, "type": str(type_num), "difference": str(int(round(dep.lag))), "hardness": "Strong"},
                    )

            # Recurse children
            children = children_by_parent.get(t.id, [])
            if children:
                write_task_tree(t_elem, children)

    # Top-level tasks
    top_level = children_by_parent.get(None, [])
    write_task_tree(tasks_elem, top_level)

    # Resources
    res_elem = ET.SubElement(root, "resources")
    res_id_to_gan: dict[str, str] = {}
    for idx, r in enumerate(project.resources):
        r_gan = str(idx)
        res_id_to_gan[r.id] = r_gan
        r_el = ET.SubElement(res_elem, "resource", {"id": r_gan, "name": r.name, "contacts": "", "phone": ""})
        if r.standard_rate is not None:
            ET.SubElement(r_el, "rate", {"name": "standard", "value": f"{r.standard_rate:.2f}"})

    # Allocations
    alloc_elem = ET.SubElement(root, "allocations")
    for a in project.assignments:
        t_gan = task_id_to_gan.get(a.task_id)
        r_gan = res_id_to_gan.get(a.resource_id)
        if t_gan and r_gan:
            load = str(round(a.units * 100.0, 1))
            ET.SubElement(alloc_elem, "allocation", {"task-id": t_gan, "resource-id": r_gan, "load": load})

    output_stream = io.BytesIO()
    tree = ET.ElementTree(root)
    tree.write(output_stream, encoding="utf-8", xml_declaration=True)
    xml_bytes = output_stream.getvalue()

    return ExportResult(FORMAT_ID, xml_bytes, validation.issues)


__all__ = [
    "FORMAT_ID",
    "FORMAT_NAME",
    "MAX_IMPORT_BYTES",
    "export_project",
    "import_bytes",
]
