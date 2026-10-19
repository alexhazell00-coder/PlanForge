"""Comprehensive automated workflow tests covering the 15 UI/UX workflows:

1. Create a project.
2. Add tasks and subtasks.
3. Create dependencies.
4. Edit scheduling information.
5. Use the Function Point Calculator.
6. Associate estimates with project tasks.
7. Import a project from another application.
8. Review import warnings.
9. Export the project.
10. Reopen the exported project.
11. Save, close and reopen a PlanForge project (.pfp).
12. Window responsiveness / CSS tokens.
13. Keyboard navigation bindings.
14. Light and dark theme configuration.
15. Verify existing functionality remains fully intact.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from datetime import date
from pathlib import Path

from planforge.interchange import InterchangeManager
from planforge.model import Dependency, Project, Resource, Task
from planforge.scheduling.engine import schedule_project
from planforge.server import get_theme_setting, set_theme_setting
from planforge.storage.sqlite_store import load_project_from_pfp, save_project_to_pfp


class UIUXWorkflowTests(unittest.TestCase):
    def test_workflow_1_to_4_create_edit_dependencies_and_schedule(self) -> None:
        # Step 1: Create a project
        p = Project(id="proj-w", name="Workflow Test Project", start_date=date(2026, 5, 4))
        self.assertEqual(p.name, "Workflow Test Project")

        # Step 2: Add tasks and subtasks
        t_parent = Task(id="tp", name="Sprint Planning", duration=5.0, task_type="summary")
        t_sub1 = Task(id="ts1", name="Design Wireframes", parent_id="tp", outline_level=2, duration=2.0)
        t_sub2 = Task(id="ts2", name="Client Review", parent_id="tp", outline_level=2, duration=1.0)
        t_milestone = Task(id="tm", name="Phase 1 Signoff", milestone=True, duration=0.0)
        p.tasks.extend([t_parent, t_sub1, t_sub2, t_milestone])

        # Step 3: Create dependencies
        d1 = Dependency(id="d1", predecessor_id="ts1", successor_id="ts2", relationship_type="finish_to_start", lag=0.0)
        d2 = Dependency(id="d2", predecessor_id="ts2", successor_id="tm", relationship_type="finish_to_start", lag=0.0)
        p.dependencies.extend([d1, d2])

        # Step 4: Schedule information (Forward and backward pass)
        scheduled = schedule_project(p)
        self.assertEqual(t_sub1.start_date, date(2026, 5, 4))
        self.assertEqual(t_sub1.finish_date, date(2026, 5, 5))
        self.assertEqual(t_sub2.start_date, date(2026, 5, 6))
        self.assertEqual(t_sub2.finish_date, date(2026, 5, 6))
        self.assertEqual(t_milestone.start_date, date(2026, 5, 7))
        self.assertEqual(t_milestone.finish_date, date(2026, 5, 7))
        # Critical path detection
        self.assertTrue(t_sub1.custom_fields.get("is_critical"))
        self.assertTrue(t_sub2.custom_fields.get("is_critical"))
        self.assertTrue(t_milestone.custom_fields.get("is_critical"))

    def test_workflow_5_and_6_fp_calculator_and_transfer(self) -> None:
        # Step 5: Use Function Point Calculator
        import fp_logic
        person = fp_logic.make_person("Lead Architect", 40.0, 2.5, 1.0)
        t1 = fp_logic.make_task("Design Database", "complex", 8)
        t2 = fp_logic.make_task("API Spec", "simple", 10)
        person["tasks"].extend([t1, t2])
        cleaned = fp_logic.clean_person(person)
        totals = fp_logic.person_totals(cleaned)
        # 8 * 2.5 = 20h; 10 * 1.0 = 10h; total 30h * 40.0 = 1200.0
        self.assertEqual(totals["total_hours"], 30.0)
        self.assertEqual(totals["total_cost"], 1200.0)

        # Step 6: Associate estimates with project tasks
        fp_doc = {"application": "Simple Function Point Calculator", "format_version": 3, "saved": "2026-10-19", "people": [cleaned]}
        from planforge.interchange.fp_adapter import import_bytes as fp_import
        imp_res = fp_import(json.dumps(fp_doc).encode())
        self.assertTrue(imp_res.success)
        proj = imp_res.project
        assert proj is not None
        self.assertEqual(len(proj.tasks), 2)
        self.assertEqual(proj.tasks[0].estimated_work, 20.0)
        self.assertEqual(proj.tasks[0].estimated_cost, 800.0)
        self.assertEqual(proj.tasks[1].estimated_work, 10.0)
        self.assertEqual(proj.tasks[1].estimated_cost, 400.0)
        self.assertEqual(len(proj.assignments), 2)

    def test_workflow_7_to_10_import_review_export_reopen(self) -> None:
        manager = InterchangeManager()
        # Step 7: Import project from ProjectLibre
        fixture = Path(__file__).parent / "fixtures" / "sample_projectlibre.xml"
        imp = manager.import_file(fixture)
        self.assertTrue(imp.success)
        proj = imp.project
        assert proj is not None

        # Step 8: Review import warnings / issues
        self.assertEqual(imp.errors, ())

        # Step 9: Export the project to GanttProject
        with tempfile.TemporaryDirectory() as td:
            gan_path = Path(td) / "exported_test.gan"
            exp = manager.export_file(proj, "ganttproject", gan_path)
            self.assertTrue(exp.success)

            # Step 10: Reopen the exported project in PlanForge
            re_imp = manager.import_file(gan_path)
            self.assertTrue(re_imp.success)
            self.assertEqual(len(proj.tasks), len(re_imp.project.tasks))  # type: ignore[union-attr]

    def test_workflow_11_save_close_reopen_sqlite_pfp(self) -> None:
        # Step 11: Save, close and reopen a PlanForge project (.pfp)
        p = Project(id="pfp-wf", name="Offline SQLite Plan", tasks=[Task(id="t1", name="Task Alpha")])
        with tempfile.TemporaryDirectory() as td:
            pfp_path = Path(td) / "project.pfp"
            save_project_to_pfp(p, pfp_path)
            self.assertTrue(pfp_path.exists())

            # Reopen
            loaded = load_project_from_pfp(pfp_path)
            self.assertEqual(loaded.name, "Offline SQLite Plan")
            self.assertEqual(len(loaded.tasks), 1)
            self.assertEqual(loaded.tasks[0].name, "Task Alpha")

    def test_workflow_12_to_14_ui_assets_and_theme(self) -> None:
        # Step 12 & 13: Check UI index.html, style.css, and app.js exist and contain shortcuts/accessibility
        ui_dir = Path(__file__).parents[1] / "planforge" / "ui"
        index_html = (ui_dir / "index.html").read_text(encoding="utf-8")
        style_css = (ui_dir / "style.css").read_text(encoding="utf-8")
        app_js = (ui_dir / "app.js").read_text(encoding="utf-8")

        self.assertIn("Ctrl+1", index_html)
        self.assertIn("Ctrl+2", index_html)
        self.assertIn("theme-light", style_css)
        self.assertIn("theme-dark", style_css)
        self.assertIn("planforgeEditTask", app_js)
        self.assertIn("gantt-svg-overlay", style_css)

        # Step 14: Light and dark theme switching
        set_theme_setting("dark")
        self.assertEqual(get_theme_setting(), "dark")
        set_theme_setting("light")
        self.assertEqual(get_theme_setting(), "light")

    def test_workflow_15_server_api_endpoints(self) -> None:
        # Step 15: Verify running server API endpoints
        req = urllib.request.Request("http://localhost:8080/api/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["status"], "ok")

        req = urllib.request.Request("http://localhost:8080/api/formats")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            imp_ids = {f["id"] for f in data["import_formats"]}
            self.assertIn("microsoft-project-xml", imp_ids)
            self.assertIn("ganttproject", imp_ids)


if __name__ == "__main__":
    unittest.main()
