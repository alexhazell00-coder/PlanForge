"""Adapter for Simple Function Point Calculator JSON project files.

Integrates the Simple Function Point Calculator with PlanForge's project model,
converting people into PlanForge resources and estimated tasks into PlanForge
tasks with attached FunctionPointEstimate data, calculated hours and costs.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Import fp_logic from function-point-calculator submodule/directory (supports PyInstaller _MEIPASS)
_ROOT_CANDIDATES = (
    Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None,
    Path(__file__).resolve().parents[2],
)
for _root in _ROOT_CANDIDATES:
    if _root is not None:
        _fp_candidate = _root / "function-point-calculator" / "function-point-calculator-main"
        if _fp_candidate.is_dir():
            _FP_DIR = _fp_candidate
            break
else:
    _FP_DIR = Path(__file__).resolve().parents[2] / "function-point-calculator" / "function-point-calculator-main"

if str(_FP_DIR) not in sys.path:
    sys.path.insert(0, str(_FP_DIR))

try:
    import fp_logic
except ImportError:
    fp_logic = None  # Fallback handled safely

from planforge.interchange.results import ExportResult, ImportResult
from planforge.interchange.validation import ValidationIssue, validate_project
from planforge.model import (
    Assignment,
    FunctionPointEstimate,
    Project,
    Resource,
    Task,
    new_id,
)

FORMAT_ID = "function-point-json"
FORMAT_NAME = "Function Point Calculator JSON"
MAX_IMPORT_BYTES = 50 * 1024 * 1024


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)


def is_function_point_json(data: bytes) -> bool:
    """Sniff if data is a Simple Function Point Calculator JSON file."""
    try:
        text = data.decode("utf-8-sig")
        if not text.lstrip().startswith("{"):
            return False
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            if parsed.get("application") == "Simple Function Point Calculator":
                return True
            if "people" in parsed and isinstance(parsed["people"], list):
                if parsed["people"] and "hours_per_complex_point" in parsed["people"][0]:
                    return True
    except Exception:
        pass
    return False


def import_bytes(data: bytes, *, source_name: str | None = None) -> ImportResult:
    """Import Simple Function Point Calculator JSON file."""
    path_name = source_name or "fp_json"
    if not data or not data.strip():
        return ImportResult(FORMAT_ID, None, (_issue("error", "fp.empty", path_name, "File is empty."),))

    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except Exception as exc:
        return ImportResult(FORMAT_ID, None, (_issue("error", "fp.parse_error", path_name, f"Invalid JSON: {exc}"),))

    if not isinstance(doc, dict):
        return ImportResult(FORMAT_ID, None, (_issue("error", "fp.shape", path_name, "Root must be a JSON object."),))

    raw_people = doc.get("people", [])
    if not isinstance(raw_people, list):
        return ImportResult(FORMAT_ID, None, (_issue("error", "fp.people_invalid", path_name, "'people' must be a list."),))

    cleaned_people = []
    if fp_logic is not None:
        try:
            for idx, p in enumerate(raw_people):
                cleaned_people.append(fp_logic.clean_person(p, f"Person {idx + 1}"))
        except Exception as exc:
            return ImportResult(FORMAT_ID, None, (_issue("error", "fp.validation_error", path_name, str(exc)),))
    else:
        cleaned_people = raw_people

    proj_name = source_name.rsplit(".", 1)[0] if source_name else "Function Point Estimation Plan"
    resources: list[Resource] = []
    tasks: list[Task] = []
    assignments: list[Assignment] = []

    order = 0
    start_date = date.today()

    for p in cleaned_people:
        p_name = p.get("name", "Unnamed Person")
        rate = float(p.get("hourly_rate", 25.0))
        c_rate = float(p.get("hours_per_complex_point", 2.5))
        s_rate = float(p.get("hours_per_simple_point", 1.0))

        res = Resource(
            id=new_id(),
            name=p_name,
            standard_rate=rate,
            custom_fields={
                "hours_per_complex_point": c_rate,
                "hours_per_simple_point": s_rate,
            },
        )
        resources.append(res)

        p_tasks = p.get("tasks", [])
        for t_data in p_tasks:
            t_name = t_data.get("name", "Task")
            t_type = t_data.get("type", "complex")
            t_pts = int(t_data.get("points", 0))

            if fp_logic is not None:
                calc = fp_logic.task_row(t_data, p)
                hours = calc["hours"]
                cost = calc["cost"]
            else:
                per_pt = c_rate if t_type == "complex" else s_rate
                hours = t_pts * per_pt
                cost = hours * rate

            fp_est = FunctionPointEstimate(
                counts={"function_points": t_pts},
                complexities={"type": t_type},
                function_points=float(t_pts),
                estimated_hours=hours,
                hourly_rate=rate,
                estimated_cost=cost,
                currency="GBP",
            )

            dur_days = max(1.0, math.ceil(hours / 8.0)) if hours > 0 else 0.0

            task = Task(
                id=new_id(),
                name=t_name,
                order=order,
                start_date=start_date,
                duration=dur_days,
                duration_unit="day",
                estimated_work=hours,
                work_unit="hour",
                estimated_cost=cost,
                function_points=fp_est,
            )
            tasks.append(task)

            assignments.append(
                Assignment(
                    id=new_id(),
                    task_id=task.id,
                    resource_id=res.id,
                    units=1.0,
                    work=hours,
                    work_unit="hour",
                    cost=cost,
                )
            )
            order += 1

    project = Project(
        id=new_id(),
        name=proj_name,
        start_date=start_date,
        currency="GBP",
        tasks=tasks,
        resources=resources,
        assignments=assignments,
    )

    report = validate_project(project)
    return ImportResult(FORMAT_ID, project, report.issues)


def export_project(project: Project) -> ExportResult:
    """Export PlanForge Project to Simple Function Point Calculator JSON format."""
    validation = validate_project(project)
    if not validation.valid:
        return ExportResult(FORMAT_ID, None, validation.issues)

    # Map task assignments to resources
    task_resource: dict[str, Resource] = {}
    res_by_id = {r.id: r for r in project.resources}
    for a in project.assignments:
        if a.resource_id in res_by_id and a.task_id not in task_resource:
            task_resource[a.task_id] = res_by_id[a.resource_id]

    people_map: dict[str, dict[str, Any]] = {}
    for r in project.resources:
        c_rate = 2.5
        s_rate = 1.0
        if "hours_per_complex_point" in r.custom_fields:
            try:
                c_rate = float(r.custom_fields["hours_per_complex_point"])  # type: ignore[arg-type]
            except (ValueError, TypeError):
                pass
        if "hours_per_simple_point" in r.custom_fields:
            try:
                s_rate = float(r.custom_fields["hours_per_simple_point"])  # type: ignore[arg-type]
            except (ValueError, TypeError):
                pass

        people_map[r.id] = {
            "name": r.name,
            "hourly_rate": r.standard_rate if r.standard_rate is not None else 30.0,
            "hours_per_complex_point": c_rate,
            "hours_per_simple_point": s_rate,
            "tasks": [],
        }

    # Default person if tasks have no assigned resource
    default_person_id = "default"
    people_map[default_person_id] = {
        "name": "General Team",
        "hourly_rate": 30.0,
        "hours_per_complex_point": 2.5,
        "hours_per_simple_point": 1.0,
        "tasks": [],
    }

    for t in project.tasks:
        res = task_resource.get(t.id)
        target_pid = res.id if res and res.id in people_map else default_person_id

        # Determine task type and points
        if t.function_points and t.function_points.complexities.get("type"):
            t_type = t.function_points.complexities["type"]
            t_pts = int(t.function_points.function_points or t.function_points.counts.get("function_points", 0))
        elif t.estimated_work is not None:
            # Estimate points from work
            target_p = people_map[target_pid]
            per_pt = target_p["hours_per_simple_point"]
            t_type = "simple"
            t_pts = max(1, int(round(t.estimated_work / per_pt)))
        else:
            t_type = "simple"
            t_pts = 1

        people_map[target_pid]["tasks"].append({
            "name": t.name,
            "type": t_type,
            "points": t_pts,
        })

    # Filter out empty default person if not needed
    people_list = [p for pid, p in people_map.items() if pid != default_person_id or p["tasks"]]

    doc = {
        "application": "Simple Function Point Calculator",
        "format_version": 3,
        "saved": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "people": people_list,
    }

    json_bytes = json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")
    return ExportResult(FORMAT_ID, json_bytes, validation.issues)


__all__ = [
    "FORMAT_ID",
    "FORMAT_NAME",
    "MAX_IMPORT_BYTES",
    "export_project",
    "import_bytes",
    "is_function_point_json",
]
