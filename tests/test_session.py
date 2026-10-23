"""Workflow tests for the desktop application's project session.

These cover everything the old web UI did (tasks, dependencies, people,
settings, estimates, import/export, save/open, reports, theme) through the
same session object the Tkinter windows use. No display is required.
"""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from planforge import config, estimation
from planforge.__main__ import main as cli_main
from planforge.recovery import list_recovery_snapshots, load_recovery_project, save_recovery_snapshot
from planforge.session import ProjectSession, SessionError, TaskEdit

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _task_named(session: ProjectSession, name: str):
    return next(t for t in session.project.tasks if t.name == name)


class DefaultProjectTests(unittest.TestCase):
    def test_new_project_starts_blank_without_replacing_first_launch_sample(self) -> None:
        s = ProjectSession()
        self.assertEqual(len(s.project.tasks), 4)
        s.new_project()
        self.assertEqual(s.project.name, "Untitled project")
        self.assertEqual(s.project.tasks, [])
        self.assertIsNone(s.file_path)
        self.assertFalse(s.dirty)

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

    def test_undo_redo_add_task_restores_complete_project_snapshots(self) -> None:
        s = ProjectSession()
        original_count = len(s.project.tasks)
        task = s.add_task("Undoable task")
        self.assertTrue(s.can_undo)
        self.assertFalse(s.can_redo)
        s.undo()
        self.assertEqual(len(s.project.tasks), original_count)
        self.assertFalse(s.dirty)
        self.assertFalse(s.can_undo)
        self.assertTrue(s.can_redo)
        s.redo()
        self.assertEqual(len(s.project.tasks), original_count + 1)
        self.assertEqual(s.project.tasks[-1].id, task.id)
        self.assertTrue(s.dirty)

    def test_new_project_can_be_undone_and_redone(self) -> None:
        s = ProjectSession()
        sample_name = s.project.name
        s.new_project()
        s.undo()
        self.assertEqual(s.project.name, sample_name)
        self.assertEqual(len(s.project.tasks), 4)
        s.redo()
        self.assertEqual(s.project.name, "Untitled project")
        self.assertEqual(s.project.tasks, [])

    def test_undo_after_save_marks_older_snapshot_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = ProjectSession()
            task = session.add_task("Saved version")
            destination = Path(tmp) / "project.pfp"
            session.save(destination)
            self.assertFalse(session.dirty)
            session.undo()
            self.assertNotIn(task.id, {item.id for item in session.project.tasks})
            self.assertTrue(session.dirty)
            session.redo()
            self.assertFalse(session.dirty)

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
    def test_settings_update_and_reschedule_forward_and_backward(self) -> None:
        s = ProjectSession()
        first = _task_named(s, "UI/UX Architecture & Wireframing")
        second = _task_named(s, "Frontend Implementation")

        # Move earlier than today (2026-10-23) — previously reset back to today!
        s.update_settings(
            name="Earlier Start",
            description="Retroactive start",
            start_date=date(2026, 9, 1),
            currency="GBP",
            working_days=[0, 1, 2, 3, 4],
        )
        self.assertEqual(s.project.start_date, date(2026, 9, 1))
        self.assertEqual(first.start_date, date(2026, 9, 1))
        self.assertEqual(second.start_date, date(2026, 9, 7))

        # Move far forward into 2030
        s.update_settings(
            name="Renamed",
            description="New desc",
            start_date=date(2030, 1, 7),
            currency="USD",
            working_days=[0, 1, 2, 3, 4],
        )
        self.assertEqual(s.project.name, "Renamed")
        self.assertEqual(s.project.currency, "USD")
        self.assertEqual(s.project.start_date, date(2030, 1, 7))
        self.assertEqual(first.start_date, date(2030, 1, 7))
        self.assertTrue(s.dirty)

        # Move back earlier again after moving forward — must never ratchet!
        s.update_settings(
            name="Back to October",
            description="Moved back again",
            start_date=date(2026, 10, 19),
            currency="USD",
            working_days=[0, 1, 2, 3, 4],
        )
        self.assertEqual(s.project.start_date, date(2026, 10, 19))
        self.assertEqual(first.start_date, date(2026, 10, 19))

    def test_imported_constrained_and_manual_tasks_shift_with_project_start_and_persist_in_pfp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfp_file = Path(tmp) / "projectlibre_import.pfp"
            s = ProjectSession()
            s.apply_import(s.preview_import(FIXTURES / "sample_projectlibre.xml"))
            # Simulate tasks stamped with today's date (2026-10-23) in ProjectLibre
            s.project.start_date = date(2026, 10, 23)
            for idx, task in enumerate(s.project.tasks):
                task.start_date = date(2026, 10, 23)
                if idx == 1:
                    task.constraint_type = "start_no_earlier_than"
                    task.constraint_date = date(2026, 10, 23)
            s.recalculate()
            s.save(pfp_file)

            reopened = ProjectSession()
            reopened.open_pfp(pfp_file)
            reopened.update_settings(
                name=reopened.project.name,
                description=reopened.project.description,
                start_date=date(2026, 9, 14),
                currency=reopened.project.currency,
                working_days=[0, 1, 2, 3, 4],
            )
            self.assertEqual(reopened.project.start_date, date(2026, 9, 14))
            self.assertEqual(min(t.start_date for t in reopened.project.tasks if t.start_date), date(2026, 9, 14))
            reopened.save()

            verified = ProjectSession()
            verified.open_pfp(pfp_file)
            self.assertEqual(verified.project.start_date, date(2026, 9, 14))

    def test_empty_project_allows_clearing_and_setting_any_start_date(self) -> None:
        s = ProjectSession()
        s.new_project()
        s.update_settings(name="Blank", description="", start_date=None, currency="GBP", working_days=[0, 1, 2, 3, 4])
        self.assertIsNone(s.project.start_date)
        self.assertIsNone(s.project.finish_date)

        s.update_settings(
            name="Blank",
            description="",
            start_date=date(2026, 8, 3),
            currency="GBP",
            working_days=[0, 1, 2, 3, 4],
        )
        self.assertEqual(s.project.start_date, date(2026, 8, 3))

    def test_parse_date_input_supports_iso_uk_us_and_long_formats(self) -> None:
        from planforge.config import parse_date_input, set_preference

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "PlanForge.conf"
            self.assertIsNone(parse_date_input("   ", cfg))
            self.assertEqual(parse_date_input("2026-9-1", cfg), date(2026, 9, 1))
            self.assertEqual(parse_date_input("2026/09/01", cfg), date(2026, 9, 1))
            self.assertEqual(parse_date_input("01/09/2026", cfg), date(2026, 9, 1))
            self.assertEqual(parse_date_input("1 Sep 2026", cfg), date(2026, 9, 1))

            set_preference("workspace", "date_format", "US", cfg)
            self.assertEqual(parse_date_input("09/01/2026", cfg), date(2026, 9, 1))
            self.assertEqual(parse_date_input("25/10/2026", cfg), date(2026, 10, 25))

            with self.assertRaises(ValueError):
                parse_date_input("2026-02-30", cfg)
            with self.assertRaises(ValueError):
                parse_date_input("not-a-date", cfg)

    def test_task_edit_can_pin_and_reset_individual_task_start_date(self) -> None:
        s = ProjectSession()
        first = _task_named(s, "UI/UX Architecture & Wireframing")
        second = _task_named(s, "Frontend Implementation")

        # Pin first task to an earlier date than today
        s.apply_task_edit(first.id, TaskEdit(name=first.name, duration=4, start_date=date(2026, 9, 7)))
        self.assertEqual(first.start_date, date(2026, 9, 7))
        self.assertEqual(second.start_date, date(2026, 9, 11))
        self.assertEqual(s.project.start_date, date(2026, 9, 7))

        # Reset task back to automatic scheduling and update project start date
        s.apply_task_edit(first.id, TaskEdit(name=first.name, duration=4, start_date=None))
        s.update_settings(
            name=s.project.name,
            description=s.project.description,
            start_date=date(2026, 10, 5),
            currency="GBP",
            working_days=[0, 1, 2, 3, 4],
        )
        self.assertEqual(first.start_date, date(2026, 10, 5))

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

    def test_preview_import_supports_pfp_database_files(self) -> None:
        s = ProjectSession()
        s.add_task("Stored in database")
        pfp_path = s.save(self.dir / "from_pfp.pfp")
        preview = s.preview_import(pfp_path)
        self.assertTrue(preview.success, [i.message for i in preview.issues])
        self.assertEqual(preview.source_format, "pfp")
        assert preview.project is not None
        self.assertEqual(len(preview.project.tasks), len(s.project.tasks))

        broken = self.dir / "broken.pfp"
        broken.write_bytes(b"not sqlite")
        bad_preview = s.preview_import(broken)
        self.assertFalse(bad_preview.success)
        self.assertEqual(bad_preview.source_format, "pfp")


@contextmanager
def _enforce_windows_file_locks():
    """Simulate Windows NT file locking where open SQLite handles block replace/unlink."""
    open_handles: dict[Path, int] = {}
    real_connect = sqlite3.connect
    real_replace = os.replace
    real_unlink = os.unlink

    class _TrackedConnection:
        def __init__(self, raw: sqlite3.Connection, target: Path) -> None:
            self._raw = raw
            self._target = target
            self._closed = False
            open_handles[target] = open_handles.get(target, 0) + 1

        def close(self) -> None:
            if not self._closed:
                self._closed = True
                remaining = open_handles.get(self._target, 1) - 1
                if remaining <= 0:
                    open_handles.pop(self._target, None)
                else:
                    open_handles[self._target] = remaining
            self._raw.close()

        def __enter__(self):
            self._raw.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            # Matches stdlib sqlite3.Connection.__exit__: commits/rolls back, never closes!
            return self._raw.__exit__(exc_type, exc, tb)

        def __getattr__(self, item: str):
            return getattr(self._raw, item)

    def tracked_connect(database, *args, **kwargs):
        resolved = Path(database).resolve()
        raw = real_connect(database, *args, **kwargs)
        return _TrackedConnection(raw, resolved)

    def windows_replace(src, dst):
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()
        if src_path in open_handles or dst_path in open_handles:
            err = PermissionError(
                13,
                "The process cannot access the file because it is being used by another process",
                str(src),
            )
            err.winerror = 32  # type: ignore[attr-defined]
            err.filename2 = str(dst)
            raise err
        return real_replace(src, dst)

    def windows_unlink(path, *args, **kwargs):
        resolved = Path(path).resolve()
        if resolved in open_handles:
            err = PermissionError(
                13,
                "The process cannot access the file because it is being used by another process",
                str(path),
            )
            err.winerror = 32  # type: ignore[attr-defined]
            raise err
        return real_unlink(path, *args, **kwargs)

    with (
        patch("planforge.storage.sqlite_store.sqlite3.connect", side_effect=tracked_connect),
        patch("planforge._atomic.os.replace", side_effect=windows_replace),
        patch("planforge._atomic.os.unlink", side_effect=windows_unlink),
        patch("planforge._atomic.time.sleep", return_value=None),
    ):
        yield open_handles


class WindowsFileLockingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_reopen_overwrite_and_recovery_close_sqlite_handles_before_replace(self) -> None:
        with _enforce_windows_file_locks() as open_handles:
            session = ProjectSession()
            imported = session.preview_import(FIXTURES / "sample_projectlibre.xml")
            session.apply_import(imported)

            target = self.dir / "neomybank_self-service_point_installation.pfp"
            saved = session.save(target)
            self.assertEqual(saved, target)
            self.assertEqual(open_handles, {})
            self.assertEqual(list(self.dir.glob(".*.tmp")), [])

            reopened = ProjectSession()
            reopened.open_pfp(target)
            self.assertEqual(open_handles, {})

            reopened.add_task("Follow-up installation check")
            reopened.save()
            self.assertEqual(open_handles, {})
            self.assertEqual(list(self.dir.glob(".*.tmp")), [])

            recovery_root = self.dir / "config"
            snapshot = save_recovery_snapshot(reopened.project, target, root=recovery_root)
            self.assertEqual(open_handles, {})
            records, warnings = list_recovery_snapshots(root=recovery_root)
            self.assertEqual(warnings, [])
            self.assertEqual(len(records), 1)
            restored = load_recovery_project(snapshot.snapshot_path)
            self.assertEqual(restored.id, reopened.project.id)
            self.assertEqual(open_handles, {})

    def test_transient_onedrive_sharing_violation_retries_and_succeeds(self) -> None:
        real_replace = os.replace
        attempts = 0

        def flaky_replace(src, dst):
            nonlocal attempts
            attempts += 1
            if attempts <= 3:
                err = PermissionError(
                    13,
                    "The process cannot access the file because it is being used by another process",
                    str(src),
                )
                err.winerror = 32  # type: ignore[attr-defined]
                err.filename2 = str(dst)
                raise err
            return real_replace(src, dst)

        with (
            patch("planforge._atomic.os.replace", side_effect=flaky_replace),
            patch("planforge._atomic.time.sleep", return_value=None),
        ):
            session = ProjectSession()
            target = self.dir / "onedrive_synced_project.pfp"
            session.save(target)

        self.assertEqual(attempts, 4)
        self.assertTrue(target.is_file())
        self.assertEqual(list(self.dir.glob(".*.tmp")), [])

    def test_persistent_lock_error_cleans_up_temp_file_and_raises_session_error(self) -> None:
        def always_locked(src, dst):
            err = PermissionError(
                13,
                "The process cannot access the file because it is being used by another process",
                str(src),
            )
            err.winerror = 32  # type: ignore[attr-defined]
            err.filename2 = str(dst)
            raise err

        with (
            patch("planforge._atomic.os.replace", side_effect=always_locked),
            patch("planforge._atomic.time.sleep", return_value=None),
        ):
            session = ProjectSession()
            target = self.dir / "locked_project.pfp"
            with self.assertRaises(SessionError):
                session.save(target)

        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.glob(".*.tmp")), [])


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
            config.set_theme_setting("custom-harbor-12345678", conf)
            self.assertEqual(config.get_theme_setting(conf), "custom-harbor-12345678")
            saved = conf.read_text(encoding="utf-8")
            self.assertIn("key = value", saved)
            self.assertIn("settings_version = 1", saved)
            with self.assertRaises(ValueError):
                config.set_theme_setting("neon", conf)

    def test_platform_config_directories(self) -> None:
        home = Path("/home/tester")
        self.assertEqual(
            config.get_config_dir(platform_name="linux", environ={"XDG_CONFIG_HOME": "/tmp/cfg"}, home=home),
            Path("/tmp/cfg/PlanForge"),
        )
        self.assertEqual(
            config.get_config_dir(platform_name="darwin", environ={}, home=home),
            home / "Library" / "Application Support" / "PlanForge",
        )
        self.assertEqual(
            config.get_config_dir(platform_name="win32", environ={"APPDATA": "C:/Users/test/AppData/Roaming"}, home=home),
            Path("C:/Users/test/AppData/Roaming/PlanForge"),
        )

    def test_corrupt_settings_fall_back_and_recover_on_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "PlanForge.conf"
            conf.write_text("[broken\nnot valid", encoding="utf-8")
            self.assertEqual(config.get_theme_setting(conf), "light")
            config.set_theme_setting("classic", conf)
            self.assertEqual(config.get_theme_setting(conf), "classic")
            self.assertTrue(Path(f"{conf}.corrupt").exists())

    def test_future_settings_version_is_not_downgraded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "PlanForge.conf"
            conf.write_text("[app]\nsettings_version = 42\n[view]\ntheme = dark\n", encoding="utf-8")
            config.set_theme_setting("light", conf)
            config.set_theme_setting("system", conf)
            self.assertEqual(config.get_theme_setting(conf), "system")
            self.assertIn("settings_version = 42", conf.read_text(encoding="utf-8"))

    def test_workspace_preferences_round_trip_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "PlanForge.conf"
            config.set_preference("workspace", "timeline_zoom", "Weeks", conf)
            config.set_preference("workspace", "show_suggestions", "false", conf)
            self.assertEqual(config.get_preference("workspace", "timeline_zoom", "Days", conf), "Weeks")
            self.assertEqual(config.get_preference("workspace", "show_suggestions", "true", conf), "false")
            self.assertEqual(config.get_theme_setting(conf), "light")

    def test_recent_projects_are_bounded_deduplicated_and_clearable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / "PlanForge.conf"
            paths = [root / f"project-{index}.pfp" for index in range(12)]
            for path in paths:
                config.remember_recent_project(path, conf)
            config.remember_recent_project(paths[0], conf)
            recent = config.get_recent_projects(conf)
            self.assertEqual(len(recent), 10)
            self.assertEqual(recent[0], paths[0].resolve())
            self.assertEqual(len(set(recent)), 10)
            config.clear_recent_projects(conf)
            self.assertEqual(config.get_recent_projects(conf), [])

    def test_workspace_layouts_and_date_formats_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "PlanForge.conf"
            config.set_workspace_layout("Planning", 2, "Weeks", ["cost", "cost"], conf)
            self.assertEqual(config.get_workspace_layouts(conf)["Planning"],
                             {"tab": 2, "zoom": "Weeks", "hidden": ["cost"]})
            config.set_preference("workspace", "date_format", "UK", conf)
            self.assertEqual(config.format_date(date(2026, 10, 20), conf), "20/10/2026")
            with self.assertRaises(ValueError):
                config.set_workspace_layout("Bad", 99, "Weeks", [], conf)

    def test_custom_shortcut_keys_are_validated_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "PlanForge.conf"
            keys = config.validate_shortcut_keys({"new": "G", "redo": "R"}, conf)
            config.set_preferences("shortcuts", keys, conf)
            self.assertEqual(config.get_shortcut_keys(conf)["new"], "G")
            with self.assertRaises(ValueError):
                config.validate_shortcut_keys({"new": "O"}, conf)
            with self.assertRaises(ValueError):
                config.validate_shortcut_keys({"save": "T"}, conf)


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


class MaterialAndResourceHierarchyTests(unittest.TestCase):
    def test_work_and_material_hierarchy_assignments_costs_reports_and_pfp_persistence(self) -> None:
        from planforge.session import TaskEdit

        s = ProjectSession()
        s.new_project()
        s.project.name = "IT Infrastructure Upgrade"
        s.project.currency = "GBP"

        md = s.add_person("MR.NewBrook", 35.0, 8.0, group="Managing director", initials="M")
        pm = s.add_person("Alex Hazell", 30.0, 8.0, group="project manager", initials="A", parent_id=md.id)
        net = s.add_person("network infrastructure team", 20.0, 8.0, group="junior network engineer", initials="n", parent_id=pm.id)
        mats_hdr = s.add_material("Materials", 0.0, initials="M")
        server = s.add_material("Dell PowerEdge server", 5000.0, material_label="unit", initials="D", parent_id=mats_hdr.id)
        switch = s.add_material("Cisco 24-port network switch", 1200.0, material_label="unit", initials="C", parent_id=mats_hdr.id)
        cable = s.add_material("cat6 network cabling", 6.49, material_label="metre", initials="c")
        # Exact ProjectLibre OutlineLevel indent/outdent transitions:
        # depth 0 -> 1st indent puts cable at depth 1 under Materials;
        # depth 1 -> 2nd indent puts cable at depth 2 under switch;
        # outdent steps back to depth 1 under Materials!
        s.indent_resource(cable.id)
        self.assertEqual(cable.custom_fields.get("parent_id"), mats_hdr.id)
        s.indent_resource(cable.id)
        self.assertEqual(cable.custom_fields.get("parent_id"), switch.id)
        s.outdent_resource(cable.id)
        self.assertEqual(cable.custom_fields.get("parent_id"), mats_hdr.id)

        task = s.add_task("Install Rack & Cabling")
        s.apply_task_edit(
            task.id,
            TaskEdit(
                name="Install Rack & Cabling",
                description="Rack server, switches and structured cabling",
                milestone=False,
                duration=5.0,
                percent_complete=25.0,
                priority=600,
                predecessor_id=None,
                dependency_type="finish_to_start",
                lag=0.0,
                resource_id=net.id,
                fp_complexity=None,
                fp_points=None,
                material_assignments=[(server.id, 1.0), (switch.id, 2.0), (cable.id, 100.0)],
            ),
        )

        # Labour = 5d * 8h * £20 = £800; Materials = £5000 + 2*£1200 + 100*£6.49 = £8049; Total = £8849
        self.assertAlmostEqual(task.estimated_work or 0.0, 40.0)
        self.assertAlmostEqual(task.estimated_cost or 0.0, 8849.0)
        ov = s.overview()
        self.assertEqual(ov.resource_count, 3)
        self.assertEqual(ov.material_count, 4)
        self.assertAlmostEqual(ov.labour_cost, 800.0)
        self.assertAlmostEqual(ov.material_cost, 8049.0)
        self.assertAlmostEqual(ov.total_cost, 8849.0)

        report = s.summary_report_text()
        self.assertIn("MATERIALS & EQUIPMENT COSTS", report)
        self.assertIn("Dell PowerEdge server", report)
        self.assertIn("cat6 network cabling", report)

        # Updating a material unit rate automatically recalculates task & assignment costs!
        s.update_person(
            switch.id,
            "Cisco 24-port network switch",
            1000.0,
            resource_type="material",
            material_label="unit",
            initials="C",
            parent_id=mats_hdr.id,
        )
        self.assertAlmostEqual(task.estimated_cost or 0.0, 8449.0)

        # Save to .pfp and reopen cleanly
        with tempfile.TemporaryDirectory() as tmp:
            pfp = Path(tmp) / "infra.pfp"
            s.save(pfp)
            reopened = ProjectSession()
            reopened.open_pfp(pfp)
            self.assertEqual(reopened.overview().material_count, 4)
            self.assertAlmostEqual(reopened.overview().material_cost, 7649.0)
            self.assertAlmostEqual(reopened.overview().total_cost, 8449.0)


if __name__ == "__main__":
    unittest.main()
