"""HTTP application server and REST API for PlanForge.

Serves the modern single-page desktop/web UI and provides endpoints for project
management, schedule calculation, Function Point estimation, and multi-format
import/export workflows without external third-party dependencies.
"""

from __future__ import annotations

import cgi
import configparser
import json
import mimetypes
import os
import sys
import tempfile
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from planforge.interchange import (
    CsvImportOptions,
    FormatRegistry,
    InterchangeManager,
    summarize_project,
    validate_project,
)
from planforge.interchange.json_adapter import (
    export_project as project_to_json,
    import_bytes as project_from_json,
)
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

# Path to config file
CONFIG_DIR = Path.home() / ".config" / "PlanForge"
CONFIG_FILE = CONFIG_DIR / "PlanForge.conf"
UI_DIR = Path(__file__).resolve().parent / "ui"

# FP Logic import
_FP_DIR = Path(__file__).resolve().parents[1] / "function-point-calculator" / "function-point-calculator-main"
if str(_FP_DIR) not in sys.path:
    sys.path.insert(0, str(_FP_DIR))

try:
    import fp_logic
except ImportError:
    fp_logic = None


def get_default_project() -> Project:
    """Create a default sample project for new sessions."""
    p_id = new_id()
    t1_id = new_id()
    t2_id = new_id()
    t3_id = new_id()
    t4_id = new_id()
    r1_id = new_id()
    r2_id = new_id()

    today = date.today()

    return Project(
        id=p_id,
        name="Website Redesign & Launch",
        description="Comprehensive website overhaul with user authentication and billing integration.",
        author="PlanForge Project Manager",
        start_date=today,
        currency="GBP",
        resources=[
            Resource(
                id=r1_id,
                name="Alice (Lead Engineer)",
                standard_rate=45.0,
                custom_fields={"hours_per_day": 8.0, "hours_per_complex_point": 2.5, "hours_per_simple_point": 1.0},
            ),
            Resource(
                id=r2_id,
                name="Bob (Designer & Frontend)",
                standard_rate=35.0,
                custom_fields={"hours_per_day": 8.0, "hours_per_complex_point": 3.0, "hours_per_simple_point": 1.2},
            ),
        ],
        tasks=[
            Task(
                id=t1_id,
                name="UI/UX Architecture & Wireframing",
                order=0,
                duration=4.0,
                duration_unit="day",
                percent_complete=100.0,
                priority=600,
                estimated_work=32.0,
                work_unit="hour",
                estimated_cost=1120.0,
            ),
            Task(
                id=t2_id,
                name="Frontend Implementation",
                order=1,
                duration=6.0,
                duration_unit="day",
                percent_complete=50.0,
                priority=500,
                estimated_work=48.0,
                work_unit="hour",
                estimated_cost=1680.0,
            ),
            Task(
                id=t3_id,
                name="Authentication & Security Backend",
                order=2,
                duration=5.0,
                duration_unit="day",
                percent_complete=20.0,
                priority=700,
                estimated_work=40.0,
                work_unit="hour",
                estimated_cost=1800.0,
            ),
            Task(
                id=t4_id,
                name="Beta Release Sign-off",
                order=3,
                duration=0.0,
                duration_unit="day",
                percent_complete=0.0,
                milestone=True,
                task_type="milestone",
            ),
        ],
        dependencies=[
            Dependency(id=new_id(), predecessor_id=t1_id, successor_id=t2_id, relationship_type="finish_to_start", lag=0.0),
            Dependency(id=new_id(), predecessor_id=t1_id, successor_id=t3_id, relationship_type="start_to_start", lag=1.0),
            Dependency(id=new_id(), predecessor_id=t2_id, successor_id=t4_id, relationship_type="finish_to_start", lag=0.0),
            Dependency(id=new_id(), predecessor_id=t3_id, successor_id=t4_id, relationship_type="finish_to_start", lag=0.0),
        ],
        assignments=[
            Assignment(id=new_id(), task_id=t1_id, resource_id=r2_id, units=1.0, work=32.0, cost=1120.0),
            Assignment(id=new_id(), task_id=t2_id, resource_id=r2_id, units=1.0, work=48.0, cost=1680.0),
            Assignment(id=new_id(), task_id=t3_id, resource_id=r1_id, units=1.0, work=40.0, cost=1800.0),
        ],
        calendars=[Calendar(id=new_id(), name="Standard Working Week", working_days=[0, 1, 2, 3, 4])],
    )


class PlanForgeState:
    """In-memory active project state."""

    def __init__(self) -> None:
        self.project: Project = schedule_project(get_default_project())
        self.manager = InterchangeManager()
        self.last_saved_path: str | None = None


_STATE = PlanForgeState()


def get_theme_setting() -> str:
    """Read theme from .config/PlanForge/PlanForge.conf or default to light."""
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        try:
            parser.read(str(CONFIG_FILE))
            return parser.get("view", "theme", fallback="light")
        except Exception:
            pass
    return "light"


def set_theme_setting(theme: str) -> None:
    """Write theme to .config/PlanForge/PlanForge.conf."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        try:
            parser.read(str(CONFIG_FILE))
        except Exception:
            pass
    if not parser.has_section("view"):
        parser.add_section("view")
    parser.set("view", "theme", theme)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        parser.write(f)


class PlanForgeRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler supporting UI static files and REST API endpoints."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def end_headers(self) -> None:
        # Enable CORS and permit preview iframe embedding
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/health":
            self._send_json({"status": "ok", "app": "PlanForge", "time": datetime.now().isoformat()})
            return

        if path == "/api/project":
            res = project_to_json(_STATE.project)
            payload = json.loads(res.data.decode("utf-8")) if res.data else {}
            summary = summarize_project(_STATE.project)
            self._send_json({
                "project": payload.get("project", {}),
                "summary": {
                    "name": summary.name,
                    "task_count": summary.task_count,
                    "subtask_count": summary.subtask_count,
                    "dependency_count": summary.dependency_count,
                    "resource_count": summary.resource_count,
                    "assignment_count": summary.assignment_count,
                    "milestone_count": summary.milestone_count,
                    "start_date": summary.start_date.isoformat() if summary.start_date else None,
                    "finish_date": summary.finish_date.isoformat() if summary.finish_date else None,
                },
                "last_saved_path": _STATE.last_saved_path,
            })
            return

        if path == "/api/config":
            self._send_json({"theme": get_theme_setting()})
            return

        if path == "/api/formats":
            registry = _STATE.manager.registry
            import_formats = [{"id": f.id, "name": f.name, "extensions": list(f.extensions), "description": f.description} for f in registry.import_formats()]
            export_formats = [{"id": f.id, "name": f.name, "extensions": list(f.extensions), "description": f.description} for f in registry.export_formats()]
            self._send_json({"import_formats": import_formats, "export_formats": export_formats})
            return

        # Serve UI static files
        super().do_GET()

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        if path == "/api/config":
            try:
                data = json.loads(raw_body.decode("utf-8"))
                theme = data.get("theme", "light")
                set_theme_setting(theme)
                self._send_json({"status": "ok", "theme": theme})
            except Exception as e:
                self._send_error(str(e))
            return

        if path == "/api/project/new":
            _STATE.project = schedule_project(get_default_project())
            _STATE.last_saved_path = None
            self._send_json({"status": "ok", "message": "New project created."})
            return

        if path == "/api/project/open":
            try:
                # Expects binary .pfp content or multipart
                with tempfile.NamedTemporaryFile(suffix=".pfp", delete=False) as tmp:
                    tmp.write(raw_body)
                    tmp_path = tmp.name
                opened = load_project_from_pfp(tmp_path)
                os.unlink(tmp_path)
                _STATE.project = schedule_project(opened)
                self._send_json({"status": "ok", "message": f"Opened project '{opened.name}'."})
            except Exception as exc:
                self._send_error(str(exc))
            return

        if path == "/api/project/schedule":
            _STATE.project = schedule_project(_STATE.project)
            self._send_json({"status": "ok", "message": "Schedule recalculated."})
            return

        if path == "/api/project":
            try:
                doc = json.loads(raw_body.decode("utf-8"))
                wrapper = {"format": "planforge-project", "schema_version": 1, "project": doc}
                import_res = project_from_json(json.dumps(wrapper).encode("utf-8"))
                if not import_res.success or import_res.project is None:
                    err_msgs = [i.message for i in import_res.errors]
                    self._send_error("; ".join(err_msgs), status=HTTPStatus.BAD_REQUEST)
                    return

                _STATE.project = schedule_project(import_res.project)
                self._send_json({"status": "ok", "message": "Project updated."})
            except Exception as exc:
                self._send_error(str(exc))
            return

        if path == "/api/import/preview":
            # Detect format and produce preview summary
            try:
                data = json.loads(raw_body.decode("utf-8"))
                file_content = data.get("content", "")
                filename = data.get("filename", "file.xml")
                raw_bytes = file_content.encode("utf-8") if isinstance(file_content, str) else b""

                detection = _STATE.manager.registry.detect(raw_bytes, filename)
                format_id = detection.format_id

                if not format_id:
                    issues = [{"severity": i.severity, "code": i.code, "message": i.message} for i in detection.issues]
                    self._send_json({"success": False, "format_id": None, "issues": issues})
                    return

                importer = _STATE.manager.registry.importer(format_id)
                res = importer(raw_bytes, source_name=filename)
                issues = [{"severity": i.severity, "code": i.code, "message": i.message} for i in res.issues]

                if not res.success or res.project is None:
                    self._send_json({"success": False, "format_id": format_id, "issues": issues})
                    return

                summary = summarize_project(res.project)
                fmt_def = _STATE.manager.registry.get(format_id)
                self._send_json({
                    "success": True,
                    "format_id": format_id,
                    "format_name": fmt_def.name if fmt_def else format_id,
                    "summary": {
                        "name": summary.name,
                        "task_count": summary.task_count,
                        "subtask_count": summary.subtask_count,
                        "dependency_count": summary.dependency_count,
                        "resource_count": summary.resource_count,
                        "assignment_count": summary.assignment_count,
                        "milestone_count": summary.milestone_count,
                        "start_date": summary.start_date.isoformat() if summary.start_date else None,
                        "finish_date": summary.finish_date.isoformat() if summary.finish_date else None,
                    },
                    "issues": issues,
                })
            except Exception as exc:
                self._send_error(str(exc))
            return

        if path == "/api/import/confirm":
            try:
                data = json.loads(raw_body.decode("utf-8"))
                file_content = data.get("content", "")
                filename = data.get("filename", "file.xml")
                raw_bytes = file_content.encode("utf-8") if isinstance(file_content, str) else b""

                detection = _STATE.manager.registry.detect(raw_bytes, filename)
                format_id = detection.format_id or data.get("format_id")
                if not format_id:
                    self._send_error("Could not detect file format.", status=HTTPStatus.BAD_REQUEST)
                    return

                importer = _STATE.manager.registry.importer(format_id)
                res = importer(raw_bytes, source_name=filename)
                if not res.success or res.project is None:
                    errs = "; ".join(i.message for i in res.errors)
                    self._send_error(f"Import failed: {errs}", status=HTTPStatus.BAD_REQUEST)
                    return

                _STATE.project = schedule_project(res.project)
                _STATE.last_saved_path = None
                self._send_json({
                    "status": "ok",
                    "message": f"Successfully imported {res.project.name} from {format_id}.",
                    "warnings": [i.message for i in res.warnings],
                })
            except Exception as exc:
                self._send_error(str(exc))
            return

        if path == "/api/export":
            try:
                data = json.loads(raw_body.decode("utf-8"))
                format_id = data.get("format_id", "microsoft-project-xml")

                if format_id == "pfp":
                    # Export SQLite .pfp database
                    with tempfile.NamedTemporaryFile(suffix=".pfp", delete=False) as tmp:
                        tmp_path = tmp.name
                    save_project_to_pfp(_STATE.project, tmp_path)
                    with open(tmp_path, "rb") as f:
                        file_bytes = f.read()
                    os.unlink(tmp_path)
                    self._send_bytes(file_bytes, "application/x-sqlite3", f"{_STATE.project.name}.pfp")
                    return

                exporter = _STATE.manager.registry.exporter(format_id)
                if not exporter:
                    self._send_error(f"Export format {format_id} is not supported.", status=HTTPStatus.BAD_REQUEST)
                    return

                res = exporter(_STATE.project)
                if not res.success or res.data is None:
                    errs = "; ".join(i.message for i in res.errors)
                    self._send_error(f"Export failed: {errs}", status=HTTPStatus.BAD_REQUEST)
                    return

                ext_map = {
                    "microsoft-project-xml": "xml",
                    "ganttproject": "gan",
                    "function-point-json": "json",
                    "planforge-json": "json",
                    "csv": "csv",
                }
                ext = ext_map.get(format_id, "xml")
                mime = "text/xml" if ext in ("xml", "gan") else ("application/json" if ext == "json" else "text/csv")
                filename = f"{_STATE.project.name.replace(' ', '_').lower()}.{ext}"
                self._send_bytes(res.data, mime, filename)
            except Exception as exc:
                self._send_error(str(exc))
            return

        if path == "/api/fp/calculate":
            try:
                data = json.loads(raw_body.decode("utf-8"))
                people = data.get("people", [])
                results = []
                total_hours = 0.0
                total_cost = 0.0

                if fp_logic is not None:
                    for p in people:
                        clean_p = fp_logic.clean_person(p)
                        p_tot = fp_logic.person_totals(clean_p)
                        results.append(p_tot)
                        total_hours += p_tot["hours"]
                        total_cost += p_tot["cost"]
                else:
                    for p in people:
                        rate = float(p.get("hourly_rate", 30.0))
                        c_rate = float(p.get("hours_per_complex_point", 2.5))
                        s_rate = float(p.get("hours_per_simple_point", 1.0))
                        p_hrs = 0.0
                        for t in p.get("tasks", []):
                            per_pt = c_rate if t.get("type") == "complex" else s_rate
                            p_hrs += float(t.get("points", 0)) * per_pt
                        results.append({"name": p.get("name", "Person"), "hours": p_hrs, "cost": p_hrs * rate})
                        total_hours += p_hrs
                        total_cost += p_hrs * rate

                self._send_json({"results": results, "total_hours": total_hours, "total_cost": total_cost})
            except Exception as exc:
                self._send_error(str(exc))
            return

        if path == "/api/fp/transfer":
            # Transfer FP calculations into active project tasks
            try:
                data = json.loads(raw_body.decode("utf-8"))
                people = data.get("people", [])
                if not people:
                    self._send_error("No people or estimation tasks provided.", status=HTTPStatus.BAD_REQUEST)
                    return

                # Convert people dict to FP JSON bytes
                fp_doc = {"application": "Simple Function Point Calculator", "format_version": 3, "saved": datetime.now().isoformat(), "people": people}
                from planforge.interchange.fp_adapter import import_bytes as fp_import
                imp_res = fp_import(json.dumps(fp_doc).encode("utf-8"))
                if not imp_res.success or imp_res.project is None:
                    errs = "; ".join(i.message for i in imp_res.errors)
                    self._send_error(f"Transfer failed: {errs}", status=HTTPStatus.BAD_REQUEST)
                    return

                # Append or update tasks into current project
                proj = _STATE.project
                new_tasks = imp_res.project.tasks
                new_resources = imp_res.project.resources
                new_assignments = imp_res.project.assignments

                # Merge resources by name
                res_name_map = {r.name.casefold(): r for r in proj.resources}
                id_map = {}
                for r in new_resources:
                    if r.name.casefold() in res_name_map:
                        existing = res_name_map[r.name.casefold()]
                        id_map[r.id] = existing.id
                        if r.standard_rate is not None:
                            existing.standard_rate = r.standard_rate
                    else:
                        proj.resources.append(r)
                        id_map[r.id] = r.id

                # Append tasks
                start_order = len(proj.tasks)
                for idx, t in enumerate(new_tasks):
                    t.order = start_order + idx
                    proj.tasks.append(t)

                for a in new_assignments:
                    a.resource_id = id_map.get(a.resource_id, a.resource_id)
                    proj.assignments.append(a)

                _STATE.project = schedule_project(proj)
                self._send_json({"status": "ok", "message": f"Transferred {len(new_tasks)} estimated tasks into project schedule."})
            except Exception as exc:
                self._send_error(str(exc))
            return

        self._send_error("Endpoint not found", status=HTTPStatus.NOT_FOUND)

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, payload: bytes, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, message: str, status: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR) -> None:
        self._send_json({"error": message}, status=status)


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the PlanForge application server."""
    server = ThreadingHTTPServer((host, port), PlanForgeRequestHandler)
    print(f"PlanForge Application Server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port=port)
