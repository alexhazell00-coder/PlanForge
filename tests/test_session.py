"""Workflow tests for the desktop application's project session.

These cover everything the old web UI did (tasks, dependencies, people,
settings, estimates, import/export, save/open, reports, theme) through the
same session object the Tkinter windows use. No display is required.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

from planforge import config, estimation
from planforge.__main__ import main as cli_main
from planforge.session import ProjectSession, SessionError, TaskEdit

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _task_named(session: ProjectSession, name: str):
    return next(t for t in session.project.tasks if t.name == name)


class DefaultProjectTests(unittest.TestCase):
    def test_default_project_is_scheduled_with_critical_path(self) -> None:
        s = ProjectSession()
        names = [r.task.name for r in s.task_rows()]
        self.assertEqual(names[0], "UI/UX Architecture & Wireframing")
        self.assertEqual(len(names), 4)
        ov = s.overview()
        self.assertTrue(ov.critical_tasks)
        self.assertIsNotNone(ov.finish_date)
        self.assertFalse(s.dirty)

    def test_summary_report_has_expected_sections(self) -> None:
        text = ProjectSession().summary_report_text()
        for heading in ("PLANFORGE PROJECT SUMMARY REPORT", "KEY METRICS", "CRITICAL PATH",
                        "TEAM ALLOCATION & COSTS"):
            self.assertIn(heading, text)
        self.assertIn("Website Redesign & Launch", text)


class TaskHierarchyTests(unittest.TestCase):
    def test_add_indent_outdent_and_delete(self) -> None:
        s = ProjectSession()
        first = _task_named(s, "UI/UX Architecture & Wireframing")
        second = _task_named(s, "Frontend Implementation")
        self.assertTrue(s.dirty is False)

        s.indent_task(second.id)
        self.assertEqual(second.parent_id, first.id)
        self.assertEqual(second.outline_level, 2)
        self.assertTrue(s.dirty)

        s.outdent_task(second.id)
        self.assertIsNone(second.parent_id)

        with self.assertRaises(SessionError):
            s.indent_task(first.id)  # nothing above the first task

        s.indent_task(second.id)
        s.delete_task(first.id)  # children move up to the top level
        self.assertIsNone(second.parent_id)
        self.assertNotIn(first.id, [d.predecessor_id for d in s.project.dependencies])

    def test_add_milestone_and_task(self) -> None:
        s = ProjectSession()
        m = s.add_task("Launch", milestone=True)
        self.assertTrue(m.milestone)
        self.assertEqual(m.duration, 0.0)
        t = s.add_task("Docs")
        self.assertEqual(t.duration, 1.0)
        self.assertGreater(t.order, m.order)

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaises(SessionError):
            ProjectSession().add_task("   ")


class TaskEditTests(unittest.TestCase):
    def test_manual_edit_sets_dependency_and_assignment(self) -> None:
        s = ProjectSession()
        target = _task_named(s, "Beta Release Sign-off")
        pred = _task_named(s, "Frontend Implementation")
        person = s.project.resources[0]
        s.apply_task_edit(target.id, TaskEdit(
            name="Beta Sign-off", description="Final check", duration=3, percent_complete=10, priority=650,
            predecessor_id=pred.id, dependency_type="start_to_start", lag=2, resource_id=person.id))
        self.assertEqual(target.name, "Beta Sign-off")
        self.assertEqual(target.duration, 3)
        dep = s.predecessor_of(target.id)
        self.assertEqual((dep.predecessor_id, dep.relationship_type, dep.lag), (pred.id, "start_to_start", 2))
        assigned = s.assigned_resource_of(target.id)
        self.assertEqual(assigned.id, person.id)
        self.assertEqual(target.finish_date is not None, True)
        self.assertTrue(s.dirty)

    def test_function_point_estimate_sets_hours_cost_and_duration(self) -> None:
        s = ProjectSession()
        target = _task_named(s, "Beta Release Sign-off")
        alice = s.project.resources[0]  # 45 GBP/h, 2.5 hours per complex point, 8 h/day
        s.apply_task_edit(target.id, TaskEdit(name="Estimated", resource_id=alice.id,
                                              fp_complexity="complex", fp_points=20))
        self.assertAlmostEqual(target.estimated_work, 50.0)  # 20 * 2.5
        self.assertAlmostEqual(target.estimated_cost, 50.0 * 45.0)
        self.assertEqual(target.duration, 7.0)  # ceil(50 / 8)
        self.assertEqual(target.function_points.function_points, 20.0)

    def test_fp_requires_person(self) -> None:
        s = ProjectSession()
        target = _task_named(s, "Beta Release Sign-off")
        with self.assertRaises(SessionError):
            s.apply_task_edit(target.id, TaskEdit(name="x", fp_complexity="simple", fp_points=3))

    def test_validation_messages(self) -> None:
        s = ProjectSession()
        target = _task_named(s, "Beta Release Sign-off")
        bad_edits = [
            TaskEdit(name=""),
            TaskEdit(name="ok", percent_complete=120),
            TaskEdit(name="ok", priority=50),
            TaskEdit(name="ok", duration=-1),
            TaskEdit(name="ok", predecessor_id=target.id),
            TaskEdit(name="ok", predecessor_id="missing"),
            TaskEdit(name="ok", dependency_type="sideways"),
        ]
        for edit in bad_edits:
            with self.assertRaises(SessionError, msg=repr(edit)):
                s.apply_task_edit(target.id, edit)


class PeopleTests(unittest.TestCase):
    def test_add_update_delete_person_clears_assignments(self) -> None:
        s = ProjectSession()
        new = s.add_person("Carol", 40, 7.5)
        self.assertEqual(new.custom_fields["hours_per_day"], 7.5)
        s.update_person(new.id, "Carol B", 42, 8)
        self.assertEqual(new.name, "Carol B")
        self.assertEqual(new.standard_rate, 42.0)

        alice = s.project.resources[0]
        before = len(s.project.assignments)
        s.delete_person(alice.id)
        self.assertLess(len(s.project.assignments), before)
        self.assertTrue(all(a.resource_id != alice.id for a in s.project.assignments))

    def test_rejects_bad_rate_and_hours(self) -> None:
        s = ProjectSession()
        with self.assertRaises(SessionError):
            s.add_person("X", -5, 8)
        with self.assertRaises(SessionError):
            s.add_person("X", 10, 0)
        with self.assertRaises(SessionError):
            s.add_person("", 10, 8)

    def test_workload_totals(self) -> None:
        rows = {w.name: w for w in ProjectSession().person_workloads()}
        bob = rows["Bob (Designer & Frontend)"]
        self.assertEqual(bob.task_count, 2)
        self.assertAlmostEqual(bob.hours, 80.0)
        self.assertAlmostEqual(bob.cost, 80.0 * 35.0)


class SettingsTests(unittest.TestCase):
    def test_settings_update_and_reschedule(self) -> None:
        s = ProjectSession()
        first = _task_named(s, "UI/UX Architecture & Wireframing")
        s.update_settings(name="Renamed", description="New desc", start_date=date(2030, 1, 7),
                          currency="USD", working_days=[0, 1, 2, 3, 4])
        self.assertEqual(s.project.name, "Renamed")
        self.assertEqual(s.project.currency, "USD")
        self.assertEqual(first.start_date, date(2030, 1, 7))
        self.assertTrue(s.dirty)

    def test_settings_validation(self) -> None:
        s = ProjectSession()
        with self.assertRaises(SessionError):
            s.update_settings(name="x", description="", start_date=None, currency="JPY", working_days=[0])
        with self.assertRaises(SessionError):
            s.update_settings(name="x", description="", start_date=None, currency="GBP", working_days=[])
        with self.assertRaises(SessionError):
            s.update_settings(name="x", description="", start_date=None, currency="GBP", working_days=[9])


class FileWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_close_and_reopen_pfp(self) -> None:
        s = ProjectSession()
        s.add_task("Extra work")
        saved = s.save(self.dir / "plan")
        self.assertEqual(saved.suffix, ".pfp")
        self.assertFalse(s.dirty)

        reopened = ProjectSession()
        reopened.open_pfp(saved)
        self.assertEqual(reopened.project.name, s.project.name)
        self.assertEqual(len(reopened.project.tasks), len(s.project.tasks))
        self.assertEqual(reopened.file_path, saved)

    def test_save_without_path_raises(self) -> None:
        with self.assertRaises(SessionError):
            ProjectSession().save()

    def test_open_bad_file_is_a_session_error(self) -> None:
        bad = self.dir / "bad.pfp"
        bad.write_bytes(b"not a database")
        with self.assertRaises(SessionError):
            ProjectSession().open_pfp(bad)

    def test_import_preview_then_apply_projectlibre_xml(self) -> None:
        s = ProjectSession()
        result = s.preview_import(FIXTURES / "sample_projectlibre.xml")
        self.assertTrue(result.success, [i.message for i in result.issues])
        self.assertGreater(result.summary.task_count, 0)
        s.apply_import(result)
        self.assertTrue(s.dirty)
        self.assertEqual(len(s.project.tasks), result.summary.task_count)

    def test_import_with_forced_format(self) -> None:
        s = ProjectSession()
        result = s.preview_import(FIXTURES / "house_building_sample.gan", format_id="ganttproject")
        self.assertTrue(result.success, [i.message for i in result.issues])

    def test_apply_failed_import_raises(self) -> None:
        s = ProjectSession()
        bad = s.preview_import(self.dir / "missing.xml")
        with self.assertRaises(SessionError):
            s.apply_import(bad)

    def test_export_round_trips_for_several_formats(self) -> None:
        s = ProjectSession()
        for fmt, filename in [("planforge-json", "p.json"), ("csv", "p.csv"),
                              ("microsoft-project-xml", "p.xml"), ("ganttproject", "p.gan")]:
            target = self.dir / filename
            s.export_to(target, fmt)
            self.assertTrue(target.exists() and target.stat().st_size > 0, fmt)
            again = ProjectSession()
            again.apply_import(again.preview_import(target))
            self.assertEqual(len(again.project.tasks), len(s.project.tasks), fmt)

    def test_export_pfp_format_writes_database(self) -> None:
        s = ProjectSession()
        target = self.dir / "copy.pfp"
        s.export_to(target, "pfp")
        self.assertTrue(target.exists())
        self.assertIsNone(s.file_path)  # exporting a copy does not change the open file

    def test_format_choices_include_pfp_for_export_only(self) -> None:
        s = ProjectSession()
        export_ids = [c[0] for c in s.format_choices("export")]
        import_ids = [c[0] for c in s.format_choices("import")]
        self.assertIn("pfp", export_ids)
        self.assertNotIn("pfp", import_ids)


class EstimatorTests(unittest.TestCase):
    def test_estimators_add_tasks_and_totals(self) -> None:
        s = ProjectSession()
        person = s.add_estimator("Dana")
        self.assertEqual(person["hourly_rate"], 30.0)
        person["tasks"].append(estimation.fp_logic.make_task("Login form", "complex", 8))
        person["tasks"].append(estimation.fp_logic.make_task("Help text", "simple", 10))
        totals = s.estimator_totals()
        self.assertEqual(totals["task_count"], 2)
        self.assertAlmostEqual(totals["total_hours"], 8 * 2.5 + 10 * 1.0)
        self.assertAlmostEqual(totals["total_cost"], (8 * 2.5 + 10) * 30.0)

    def test_transfer_merges_people_and_adds_tasks(self) -> None:
        s = ProjectSession()
        before_tasks = len(s.project.tasks)
        before_people = len(s.project.resources)
        person = s.add_estimator("alice (lead engineer)")  # matches an existing person case-insensitively
        person["hourly_rate"] = 99.0
        person["tasks"].append(estimation.fp_logic.make_task("Dashboard", "complex", 4))
        s.add_estimator("New Estimator")["tasks"].append(estimation.fp_logic.make_task("Spec", "simple", 3))

        added = s.transfer_estimates()
        self.assertEqual(added, 2)
        self.assertEqual(len(s.project.tasks), before_tasks + 2)
        self.assertEqual(len(s.project.resources), before_people + 1)
        alice = next(r for r in s.project.resources if r.name.startswith("Alice"))
        self.assertEqual(alice.standard_rate, 99.0)
        dashboard = _task_named(s, "Dashboard")
        self.assertEqual(s.assigned_resource_of(dashboard.id).id, alice.id)

    def test_transfer_without_estimators_is_an_error(self) -> None:
        with self.assertRaises(SessionError):
            ProjectSession().transfer_estimates()


class ConfigTests(unittest.TestCase):
    def test_theme_round_trip_keeps_other_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "nested" / "PlanForge.conf"
            self.assertEqual(config.get_theme_setting(conf), "light")
            conf.parent.mkdir(parents=True)
            conf.write_text("[other]\nkey = value\n", encoding="utf-8")
            config.set_theme_setting("dark", conf)
            self.assertEqual(config.get_theme_setting(conf), "dark")
            self.assertIn("key = value", conf.read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                config.set_theme_setting("neon", conf)


class CommandLineTests(unittest.TestCase):
    def test_import_and_export_without_a_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            buffer = io.StringIO()
            with redirect_stdout(buffer), self.assertRaises(SystemExit) as raised:
                cli_main(["--import-file", str(FIXTURES / "sample_projectlibre.xml"),
                          "--export-file", str(target), "--export-format", "csv"])
            self.assertEqual(raised.exception.code, 0)
            self.assertIn("Successfully imported", buffer.getvalue())
            self.assertTrue(target.exists())

    def test_bad_import_exits_nonzero(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            cli_main(["--import-file", "/nonexistent/file.xml"])
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
