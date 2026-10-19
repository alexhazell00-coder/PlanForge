from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path

from planforge.interchange import (
    CsvImportOptions,
    FormatRegistry,
    InterchangeManager,
    compare_projects,
    validate_project,
)
from planforge.interchange.comparison import (
    EXPECTED_CONVERSION,
    SCHEDULING_RECALCULATION,
    UNEXPECTED_DATA_LOSS,
    UNSUPPORTED_INFORMATION,
)
from planforge.interchange.csv_adapter import (
    CSV_COLUMNS,
    export_project as export_csv,
    import_bytes as import_csv,
    suggest_column_mapping,
)
from planforge.interchange.json_adapter import (
    CURRENT_SCHEMA_VERSION,
    export_project as export_json,
    import_bytes as import_json,
    migrate_document,
)
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


def sample_project() -> Project:
    calendar = Calendar(
        id="calendar-standard",
        name="Standard weekdays",
        external_ids={"mspdi": "1"},
        working_days=[0, 1, 2, 3, 4],
        working_periods={
            0: [
                WorkingPeriod(time(9), time(12), extensions={"vendor.period": {"keep": True}}),
                WorkingPeriod(time(13), time(17)),
            ],
            1: [WorkingPeriod(time(9), time(12)), WorkingPeriod(time(13), time(17))],
            2: [WorkingPeriod(time(9), time(12)), WorkingPeriod(time(13), time(17))],
            3: [WorkingPeriod(time(9), time(12)), WorkingPeriod(time(13), time(17))],
            4: [WorkingPeriod(time(9), time(12)), WorkingPeriod(time(13), time(16))],
        },
        holidays=[date(2026, 12, 25)],
        exceptions=[CalendarException(
            start_date=date(2026, 12, 24),
            finish_date=date(2026, 12, 24),
            working=True,
            working_periods=[WorkingPeriod(time(9), time(12))],
            name="Christmas Eve short day",
        )],
        timezone="Europe/London",
        extensions={"vendor.calendar": {"calendar_kind": "standard"}},
    )
    project = Project(
        id="project-1",
        name="Interop acceptance",
        description="A realistic small project, with notes, costs and dependencies.",
        author="PlanForge tests",
        external_ids={"mspdi": "project-xml-1", "projectlibre": "project-pod-1"},
        created_at=datetime(2026, 1, 3, 9, 30, tzinfo=timezone.utc),
        modified_at=datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc),
        start_date=date(2026, 1, 5),
        finish_date=date(2026, 1, 12),
        schedule_mode="auto",
        default_calendar_id=calendar.id,
        currency="GBP",
        status="in_progress",
        custom_fields={"programme": "North", "reviewed": True},
        extensions={"com.example.source": {"release": 4}},
        calendars=[calendar],
    )
    project.tasks = [
        Task(
            id="task-summary",
            name="Delivery",
            task_type="summary",
            order=0,
            start_date=date(2026, 1, 5),
            finish_date=date(2026, 1, 12),
            calendar_id=calendar.id,
            external_ids={"mspdi": "10"},
        ),
        Task(
            id="task-analysis",
            name="Analyse requirements",
            description="Keep the comma, quote \"and\" line break.\nSecond line.",
            parent_id="task-summary",
            outline_level=1,
            order=1,
            start_date=date(2026, 1, 5),
            finish_date=date(2026, 1, 7),
            duration=3,
            duration_unit="day",
            percent_complete=50,
            priority=700,
            task_type="task",
            schedule_mode="manual",
            calendar_id=calendar.id,
            deadline=date(2026, 1, 8),
            constraint_type="start_no_earlier_than",
            constraint_date=date(2026, 1, 5),
            estimated_work=24,
            actual_work=12,
            remaining_work=12,
            work_unit="hour",
            estimated_cost=1200.5,
            actual_cost=600.25,
            custom_fields={"risk": "medium", "client_ref": "A-12"},
            function_points=FunctionPointEstimate(
                counts={"external_inputs": 3, "external_outputs": 2},
                complexities={"external_inputs": "low", "external_outputs": "average"},
                function_points=12.5,
                estimated_hours=24,
                hourly_rate=50.02,
                estimated_cost=1200.5,
                currency="GBP",
                extensions={"calculator-version": "test"},
            ),
            external_ids={"mspdi": "11", "projectlibre": "T-11"},
            extensions={"vendor.task": {"original_custom": "keep me"}},
        ),
        Task(
            id="task-milestone",
            name="Design approved",
            parent_id="task-summary",
            outline_level=1,
            order=2,
            start_date=date(2026, 1, 8),
            finish_date=date(2026, 1, 8),
            duration=0,
            duration_unit="day",
            percent_complete=100,
            milestone=True,
            task_type="milestone",
            calendar_id=calendar.id,
        ),
    ]
    project.dependencies = [
        Dependency(
            id="dependency-1",
            predecessor_id="task-analysis",
            successor_id="task-milestone",
            relationship_type="finish_to_start",
            lag=-0.5,
            lag_unit="day",
            external_ids={"mspdi": "32"},
            extensions={"vendor.link": {"original_lag": "-4h"}},
        ),
    ]
    person = Resource(
        id="resource-1",
        name="A. Person",
        external_ids={"mspdi": "r1"},
        resource_type="work",
        max_units=1.5,
        standard_rate=50.02,
        standard_rate_unit="hour",
        overtime_rate=75,
        cost_per_use=10,
        calendar_id=calendar.id,
        availability=[AvailabilityPeriod(date(2026, 1, 1), date(2026, 12, 31), units=0.8)],
        notes="Part-time resource",
        custom_fields={"team": "engineering"},
        extensions={"vendor.resource": {"badge": 27}},
    )
    project.resources.append(person)
    project.assignments.append(Assignment(
        id="assignment-1",
        task_id="task-analysis",
        resource_id=person.id,
        units=0.75,
        work=24,
        actual_work=12,
        remaining_work=12,
        cost=1200.5,
        actual_cost=600.25,
        start_date=date(2026, 1, 5),
        finish_date=date(2026, 1, 7),
        external_ids={"mspdi": "a1"},
        custom_fields={"assignment_note": "kept"},
        extensions={"vendor.assignment": {"cost_rate": "50.02"}},
    ))
    return project


class ProjectValidationTests(unittest.TestCase):
    def test_valid_project_and_missing_dependency_target(self) -> None:
        project = sample_project()
        self.assertTrue(validate_project(project).valid)
        project.dependencies[0].predecessor_id = "missing"
        report = validate_project(project)
        self.assertFalse(report.valid)
        self.assertIn("dependency.predecessor.missing", {issue.code for issue in report.errors})

    def test_duplicate_identifiers_are_reported(self) -> None:
        project = Project(id="p", name="Duplicate IDs")
        project.tasks = [Task(id="same", name="A"), Task(id="same", name="B")]
        self.assertIn("id.duplicate", {issue.code for issue in validate_project(project).errors})

    def test_self_and_circular_dependencies_are_reported(self) -> None:
        project = Project(id="p", name="Cycle")
        project.tasks = [Task(id="a", name="A"), Task(id="b", name="B"), Task(id="c", name="C")]
        project.dependencies = [
            Dependency(id="ab", predecessor_id="a", successor_id="b"),
            Dependency(id="bc", predecessor_id="b", successor_id="c"),
            Dependency(id="ca", predecessor_id="c", successor_id="a"),
            Dependency(id="aa", predecessor_id="a", successor_id="a"),
        ]
        codes = {issue.code for issue in validate_project(project).errors}
        self.assertIn("dependency.self", codes)
        self.assertIn("dependency.cycle", codes)

    def test_parent_cycle_is_reported(self) -> None:
        project = Project(id="p", name="Hierarchy")
        project.tasks = [Task(id="a", name="A", parent_id="b"), Task(id="b", name="B", parent_id="a")]
        report = validate_project(project)
        self.assertIn("task.hierarchy.cycle", {issue.code for issue in report.errors})

    def test_large_linear_schedule_validation_is_iterative(self) -> None:
        project = Project(id="large", name="Large schedule")
        project.tasks = [Task(id=f"t{index}", name=f"Task {index}", parent_id=f"t{index - 1}" if index else None) for index in range(1500)]
        project.dependencies = [
            Dependency(id=f"d{index}", predecessor_id=f"t{index}", successor_id=f"t{index + 1}")
            for index in range(1499)
        ]
        self.assertTrue(validate_project(project).valid)

    def test_date_only_values_reject_timezone_datetimes(self) -> None:
        project = Project(id="p", name="bad", start_date=datetime.now(timezone.utc))  # type: ignore[arg-type]
        self.assertIn("date.invalid", {issue.code for issue in validate_project(project).errors})


class PlanForgeJsonTests(unittest.TestCase):
    def test_full_project_round_trip_is_equal(self) -> None:
        original = sample_project()
        exported = export_json(original)
        self.assertTrue(exported.success, exported.issues)
        imported = import_json(exported.data or b"")
        self.assertTrue(imported.success, imported.issues)
        self.assertEqual(imported.schema_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(compare_projects(original, imported.project, format_id="planforge-json").differences, ())  # type: ignore[arg-type]

    def test_unknown_fields_are_retained_in_namespaced_extensions(self) -> None:
        document = json.loads(export_json(sample_project()).data or b"{}")
        document["future_root"] = {"value": 7}
        document["project"]["future_project_field"] = "project-value"
        document["project"]["tasks"][1]["future_task_field"] = [1, 2]
        imported = import_json(json.dumps(document).encode())
        self.assertTrue(imported.success, imported.issues)
        project = imported.project
        assert project is not None
        self.assertEqual(project.extensions["org.planforge.interchange:unknown-root-fields"], {"future_root": {"value": 7}})
        self.assertEqual(project.extensions["org.planforge.interchange:unknown-fields"]["future_project_field"], "project-value")
        self.assertEqual(project.tasks[1].extensions["org.planforge.interchange:unknown-fields"]["future_task_field"], [1, 2])

    def test_unversioned_document_is_migrated(self) -> None:
        document = {"id": "legacy", "name": "Legacy project", "tasks": []}
        migrated, version, issues = migrate_document(document)
        self.assertEqual(version, 1)
        self.assertEqual(migrated["format"], "planforge-project")
        self.assertEqual(migrated["schema_version"], 1)
        self.assertEqual(migrated["project"]["tasks"], [])
        self.assertTrue(any(issue.code == "json.schema.migrated" for issue in issues))
        imported = import_json(json.dumps(document).encode())
        self.assertTrue(imported.success, imported.issues)

    def test_invalid_duplicate_keys_dates_and_cycles_fail_safely(self) -> None:
        duplicate = b'{"format":"planforge-project","format":"x"}'
        result = import_json(duplicate)
        self.assertFalse(result.success)
        self.assertIn("json.document.invalid", {issue.code for issue in result.errors})

        document = json.loads(export_json(sample_project()).data or b"{}")
        document["project"]["tasks"][1]["start_date"] = "2026-02-30"
        result = import_json(json.dumps(document).encode())
        self.assertFalse(result.success)
        self.assertIn("json.document.invalid", {issue.code for issue in result.errors})

        cyclic = sample_project()
        cyclic.dependencies.append(Dependency(id="cycle", predecessor_id="task-milestone", successor_id="task-analysis"))
        self.assertFalse(export_json(cyclic).success)

    def test_unrepresentably_large_schedule_numbers_are_rejected_without_crashing(self) -> None:
        document = json.loads(export_json(sample_project()).data or b"{}")
        document["project"]["tasks"][1]["duration"] = 10**1000
        result = import_json(json.dumps(document).encode())
        self.assertFalse(result.success)
        self.assertIn("json.document.invalid", {issue.code for issue in result.errors})

    def test_json_constants_and_future_versions_are_rejected(self) -> None:
        result = import_json(b'{"format":"planforge-project","schema_version":1,"project":{"x":NaN}}')
        self.assertFalse(result.success)
        future = json.loads(export_json(sample_project()).data or b"{}")
        future["schema_version"] = 99
        result = import_json(json.dumps(future).encode())
        self.assertFalse(result.success)
        self.assertIn("json.document.invalid", {issue.code for issue in result.errors})

    def test_utf8_bom_is_accepted_and_invalid_encoding_rejected(self) -> None:
        encoded = export_json(sample_project()).data or b""
        self.assertTrue(import_json(b"\xef\xbb\xbf" + encoded).success)
        self.assertFalse(import_json(b"\xff\xfe\x00").success)


class CsvTests(unittest.TestCase):
    def test_full_template_round_trip(self) -> None:
        original = sample_project()
        exported = export_csv(original)
        self.assertTrue(exported.success, exported.issues)
        text = (exported.data or b"").decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
        self.assertEqual(len(rows), 3)
        self.assertEqual(tuple(rows[0].keys()), CSV_COLUMNS)
        imported = import_csv(exported.data or b"")
        self.assertTrue(imported.success, imported.issues)
        self.assertEqual(compare_projects(original, imported.project, format_id="csv").differences, ())  # type: ignore[arg-type]

    def test_all_dependency_types_and_lag_units_round_trip_in_json_and_csv(self) -> None:
        project = Project(id="links", name="Relationships")
        project.tasks = [Task(id=f"t{index}", name=f"Task {index}", order=index) for index in range(4)]
        project.dependencies = [
            Dependency(id="d-fs", predecessor_id="t0", successor_id="t1", relationship_type="finish_to_start", lag=2, lag_unit="day"),
            Dependency(id="d-ss", predecessor_id="t1", successor_id="t2", relationship_type="start_to_start", lag=-1, lag_unit="hour"),
            Dependency(id="d-ff", predecessor_id="t2", successor_id="t3", relationship_type="finish_to_finish", lag=0.5, lag_unit="week"),
            Dependency(id="d-sf", predecessor_id="t0", successor_id="t3", relationship_type="start_to_finish", lag=30, lag_unit="minute"),
        ]
        for exporter, importer, format_id in (
            (export_json, import_json, "planforge-json"),
            (export_csv, import_csv, "csv"),
        ):
            with self.subTest(format_id=format_id):
                exported = exporter(project)
                imported = importer(exported.data or b"")
                self.assertTrue(imported.success, imported.issues)
                self.assertEqual(
                    compare_projects(project, imported.project, format_id=format_id).differences,  # type: ignore[arg-type]
                    (),
                )

    def test_unfamiliar_headers_can_be_mapped_and_unmapped_columns_preserved(self) -> None:
        suggestions = suggest_column_mapping(["Title", "From", "To", "Done", "Depends", "Owner", "Custom"])
        self.assertEqual(suggestions["task_name"], "Title")
        data = 'Task Ref;Title;From;To;Done;Depends;Owner;Custom\nimport-1;Build, release;2026-03-01;2026-03-02;50%;;Lee;keep this\nimport-2;QA;2026-03-03;2026-03-03;0%;import-1;Lee;other\n'.encode()
        options = CsvImportOptions(
            delimiter=";",
            column_mapping={
                "task_id": "Task Ref",
                "task_name": "Title",
                "start_date": "From",
                "finish_date": "To",
                "percent_complete": "Done",
                "predecessors": "Depends",
                "resource_names": "Owner",
            },
        )
        imported = import_csv(data, options=options)
        self.assertTrue(imported.success, imported.issues)
        project = imported.project
        assert project is not None
        self.assertEqual(project.tasks[0].name, "Build, release")
        self.assertEqual(project.tasks[1].percent_complete, 0)
        self.assertEqual(project.dependencies[0].relationship_type, "finish_to_start")
        self.assertEqual(project.resources[0].name, "Lee")
        self.assertEqual(project.tasks[0].extensions["org.planforge.interchange:unknown-fields"]["org.planforge.csv:unmapped_columns"]["Custom"], "keep this")
        self.assertIn("csv.dependencies.assumed_finish_to_start", {issue.code for issue in imported.warnings})

    def test_delimiters_quotes_newlines_and_bom(self) -> None:
        data = b'\xef\xbb\xbfTask,Description\r\nA,"line one\nline two, with comma"\r\n'
        imported = import_csv(data)
        self.assertTrue(imported.success, imported.issues)
        assert imported.project is not None
        self.assertEqual(imported.project.tasks[0].description, "line one\nline two, with comma")

    def test_invalid_csv_inputs_return_useful_errors(self) -> None:
        for payload in (b"", b"\xff", b"Name,Name\nA,B\n", b"Title,Start\nBuild,not-a-date\n"):
            with self.subTest(payload=payload):
                imported = import_csv(payload)
                self.assertFalse(imported.success)
                self.assertTrue(imported.errors)

    def test_csv_export_preserves_original_and_uses_formula_safety_only_on_request(self) -> None:
        project = Project(id="p", name="CSV", tasks=[Task(id="t", name="=SUM(A1:A2)")])
        exported = export_csv(project)
        safe = export_csv(project, spreadsheet_safe=True)
        self.assertIn(b"=SUM", exported.data or b"")
        self.assertIn(b"'=SUM", safe.data or b"")
        self.assertEqual(project.tasks[0].name, "=SUM(A1:A2)")

    def test_empty_project_round_trip(self) -> None:
        project = Project(id="empty", name="No tasks")
        exported = export_csv(project)
        imported = import_csv(exported.data or b"")
        self.assertTrue(imported.success, imported.issues)
        self.assertEqual(imported.project.tasks, [])  # type: ignore[union-attr]


class RegistryAndFileSafetyTests(unittest.TestCase):
    def test_registry_lists_only_formats_with_working_adapters(self) -> None:
        registry = FormatRegistry()
        expected = {"planforge-json", "csv", "microsoft-project-xml", "ganttproject", "function-point-json"}
        self.assertEqual({item.id for item in registry.import_formats()}, expected)
        self.assertEqual({item.id for item in registry.export_formats()}, expected)

    def test_content_detection_beats_extension(self) -> None:
        registry = FormatRegistry()
        json_data = export_json(sample_project()).data or b""
        detection = registry.detect(json_data, "misnamed.csv")
        self.assertEqual(detection.format_id, "planforge-json")
        self.assertIn("format.extension.mismatch", {issue.code for issue in detection.issues})
        csv_data = export_csv(sample_project()).data or b""
        self.assertEqual(registry.detect(csv_data, "file.json").format_id, "csv")

    def test_mapping_api_is_extensible(self) -> None:
        registry = FormatRegistry()
        from planforge.interchange.registry import FormatDefinition
        from planforge.interchange.results import ExportResult, ImportResult

        definition = FormatDefinition("test", "Test", (".tst",), True, True, "test adapter")
        registry.register(
            definition,
            importer=lambda data, **kwargs: ImportResult("test", Project(id="p", name="Test")),
            exporter=lambda project, **kwargs: ExportResult("test", b"ok"),
            sniffer=lambda data, extension: data == b"test",
        )
        self.assertEqual(registry.detect(b"test", "x").format_id, "test")
        self.assertEqual(registry.importer("test")(b"x").project.name, "Test")  # type: ignore[union-attr]

    def test_export_is_validated_atomic_and_does_not_overwrite_implicitly(self) -> None:
        manager = InterchangeManager()
        project = sample_project()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "plan.json"
            first = manager.export_file(project, "planforge-json", target)
            self.assertTrue(first.success, first.issues)
            old_data = target.read_bytes()
            refused = manager.export_file(project, "planforge-json", target)
            self.assertFalse(refused.success)
            self.assertIn("file.exists", {issue.code for issue in refused.errors})
            self.assertEqual(target.read_bytes(), old_data)
            replacement = Project(id="new", name="Replacement")
            second = manager.export_file(replacement, "planforge-json", target, overwrite=True)
            self.assertTrue(second.success, second.issues)
            imported = manager.import_file(target)
            self.assertTrue(imported.success, imported.issues)
            self.assertEqual(imported.project.name, "Replacement")  # type: ignore[union-attr]
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_pod_and_mpp_unsupported_guidance(self) -> None:
        registry = FormatRegistry()
        pod_detection = registry.detect(b"\xac\xed\x00\x05sample", "project.pod")
        self.assertIsNone(pod_detection.format_id)
        self.assertIn("format.pod_unsupported", {issue.code for issue in pod_detection.issues})
        self.assertIn("ProjectLibre XML", pod_detection.issues[0].message)

        mpp_detection = registry.detect(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1sample", "project.mpp")
        self.assertIsNone(mpp_detection.format_id)
        self.assertIn("format.mpp_unsupported", {issue.code for issue in mpp_detection.issues})
        self.assertIn("Microsoft Project XML", mpp_detection.issues[0].message)


class MSPDIAndProjectLibreTests(unittest.TestCase):
    def test_import_sample_projectlibre_xml(self) -> None:
        manager = InterchangeManager()
        fixture = Path(__file__).parent / "fixtures" / "sample_projectlibre.xml"
        result = manager.import_file(fixture)
        self.assertTrue(result.success, result.issues)
        project = result.project
        assert project is not None
        self.assertEqual(project.name, "Software Development Plan")
        self.assertEqual(len(project.tasks), 8)
        self.assertEqual(sum(t.parent_id is not None for t in project.tasks), 4)
        self.assertEqual(sum(t.milestone for t in project.tasks), 2)
        self.assertEqual(len(project.dependencies), 5)
        self.assertEqual(len(project.resources), 3)
        self.assertEqual(len(project.assignments), 4)

    def test_mspdi_round_trip(self) -> None:
        manager = InterchangeManager()
        project = sample_project()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "mspdi_roundtrip.xml"
            exported = manager.export_file(project, "microsoft-project-xml", target)
            self.assertTrue(exported.success, exported.issues)
            imported = manager.import_file(target)
            self.assertTrue(imported.success, imported.issues)
            re_project = imported.project
            assert re_project is not None
            self.assertEqual(len(project.tasks), len(re_project.tasks))
            self.assertEqual(len(project.dependencies), len(re_project.dependencies))
            self.assertEqual(len(project.resources), len(re_project.resources))
            self.assertEqual(len(project.assignments), len(re_project.assignments))

    def test_malformed_xml_handling(self) -> None:
        from planforge.interchange.mspdi_adapter import import_bytes
        res = import_bytes(b"<Project><Unclosed>")
        self.assertFalse(res.success)
        self.assertEqual(res.errors[0].code, "xml.parse_error")


class GanttProjectTests(unittest.TestCase):
    def test_import_sample_gan(self) -> None:
        manager = InterchangeManager()
        fixture = Path(__file__).parent / "fixtures" / "house_building_sample.gan"
        result = manager.import_file(fixture)
        self.assertTrue(result.success, result.issues)
        project = result.project
        assert project is not None
        self.assertEqual(len(project.tasks), 20)
        self.assertEqual(len(project.dependencies), 17)
        self.assertEqual(len(project.resources), 7)
        self.assertEqual(len(project.assignments), 30)

    def test_ganttproject_round_trip(self) -> None:
        manager = InterchangeManager()
        fixture = Path(__file__).parent / "fixtures" / "house_building_sample.gan"
        imp1 = manager.import_file(fixture)
        assert imp1.project is not None
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "exported.gan"
            exported = manager.export_file(imp1.project, "ganttproject", target)
            self.assertTrue(exported.success, exported.issues)
            imp2 = manager.import_file(target)
            self.assertTrue(imp2.success, imp2.issues)
            assert imp2.project is not None
            self.assertEqual(len(imp1.project.tasks), len(imp2.project.tasks))
            self.assertEqual(len(imp1.project.dependencies), len(imp2.project.dependencies))
            self.assertEqual(len(imp1.project.resources), len(imp2.project.resources))
            self.assertEqual(len(imp1.project.assignments), len(imp2.project.assignments))

    def test_malformed_gan_handling(self) -> None:
        from planforge.interchange.ganttproject_adapter import import_bytes
        res = import_bytes(b"<not_project></not_project>")
        self.assertFalse(res.success)
        self.assertEqual(res.errors[0].code, "gan.root_invalid")


class FunctionPointCalculatorAdapterTests(unittest.TestCase):
    def test_import_example_input_json(self) -> None:
        manager = InterchangeManager()
        fixture = Path(__file__).parents[1] / "function-point-calculator" / "function-point-calculator-main" / "example_input.json"
        result = manager.import_file(fixture)
        self.assertTrue(result.success, result.issues)
        p = result.project
        assert p is not None
        self.assertEqual(len(p.resources), 2)
        self.assertEqual(len(p.tasks), 5)
        self.assertEqual(len(p.assignments), 5)
        # Check task hours calculated correctly
        task_names = {t.name: t for t in p.tasks}
        self.assertEqual(task_names["Design user interface"].estimated_work, 20.0)
        self.assertEqual(task_names["Design user interface"].estimated_cost, 600.0)
        self.assertEqual(task_names["Integration testing"].estimated_work, 18.0)
        self.assertEqual(task_names["Integration testing"].estimated_cost, 405.0)

    def test_fp_round_trip(self) -> None:
        manager = InterchangeManager()
        fixture = Path(__file__).parents[1] / "function-point-calculator" / "function-point-calculator-main" / "example_input.json"
        imp = manager.import_file(fixture)
        assert imp.project is not None
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "fp_out.json"
            exported = manager.export_file(imp.project, "function-point-json", target)
            self.assertTrue(exported.success, exported.issues)
            re_imp = manager.import_file(target)
            self.assertTrue(re_imp.success, re_imp.issues)
            assert re_imp.project is not None
            self.assertEqual(len(imp.project.tasks), len(re_imp.project.tasks))
            self.assertEqual(len(imp.project.resources), len(re_imp.project.resources))


class CrossSoftwareInterchangeTests(unittest.TestCase):
    def test_cross_interchange_projectlibre_to_ganttproject_and_back(self) -> None:
        manager = InterchangeManager()
        fixture = Path(__file__).parent / "fixtures" / "sample_projectlibre.xml"
        imp_xml = manager.import_file(fixture)
        assert imp_xml.project is not None
        with tempfile.TemporaryDirectory() as td:
            gan_path = Path(td) / "cross.gan"
            exp_gan = manager.export_file(imp_xml.project, "ganttproject", gan_path)
            self.assertTrue(exp_gan.success, exp_gan.issues)

            imp_gan = manager.import_file(gan_path)
            self.assertTrue(imp_gan.success, imp_gan.issues)
            assert imp_gan.project is not None

            xml_path = Path(td) / "cross.xml"
            exp_xml = manager.export_file(imp_gan.project, "microsoft-project-xml", xml_path)
            self.assertTrue(exp_xml.success, exp_xml.issues)

            imp_xml2 = manager.import_file(xml_path)
            self.assertTrue(imp_xml2.success, imp_xml2.issues)
            assert imp_xml2.project is not None

            self.assertEqual(len(imp_xml.project.tasks), len(imp_xml2.project.tasks))
            self.assertEqual(len(imp_xml.project.dependencies), len(imp_xml2.project.dependencies))
            self.assertEqual(len(imp_xml.project.resources), len(imp_xml2.project.resources))


class ComparisonTests(unittest.TestCase):
    def test_field_differences_are_not_hidden(self) -> None:
        left = sample_project()
        right = sample_project()
        right.tasks[1].start_date = date(2026, 1, 6)
        result = compare_projects(left, right, format_id="test")
        self.assertIn(SCHEDULING_RECALCULATION, result.categories)
        right.tasks[1].name = "Different"
        result = compare_projects(left, right, format_id="test")
        self.assertIn(UNEXPECTED_DATA_LOSS, result.categories)

    def test_duration_equivalence_is_explicit(self) -> None:
        left = Project(id="p", name="units", tasks=[Task(id="t", name="Task", duration=60, duration_unit="minute")])
        right = Project(id="p", name="units", tasks=[Task(id="t", name="Task", duration=1, duration_unit="hour")])
        result = compare_projects(left, right, format_id="test")
        self.assertIn(EXPECTED_CONVERSION, result.categories)

    def test_unsupported_fields_are_classified_instead_of_hidden(self) -> None:
        before = Project(id="p", name="Timestamp", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        after = Project(id="p", name="Timestamp")
        result = compare_projects(before, after, format_id="csv")
        self.assertIn(UNSUPPORTED_INFORMATION, result.categories)

    def test_no_difference_category(self) -> None:
        result = compare_projects(sample_project(), sample_project(), format_id="planforge-json")
        self.assertTrue(result.unchanged)
        self.assertEqual(result.categories, frozenset({"no_meaningful_difference"}))


class SchemaTests(unittest.TestCase):
    def test_schema_is_valid_json_and_all_local_refs_exist(self) -> None:
        schema_path = Path(__file__).parents[1] / "schemas" / "planforge-project-v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        def visit(value: object) -> None:
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    self.assertIn(ref.rsplit("/", 1)[-1], schema["$defs"])
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(schema)
        document = json.loads(export_json(sample_project()).data or b"{}")
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)


if __name__ == "__main__":
    unittest.main()
