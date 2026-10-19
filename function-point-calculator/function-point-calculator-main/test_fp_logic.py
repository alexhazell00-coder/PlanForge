"""Tests for the calculations, checking and file handling in fp_logic.py.

Run them from the folder containing the files:

    python -m unittest test_fp_logic -v

or simply:

    python test_fp_logic.py
"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import fp_logic


def make_example_people():
    """Two people with known values, used by several of the tests.

    Expected results (worked out by hand):
      AH: rate 30.00, 2.5 h per complex point, 1.0 h per simple point
        Design user interface   complex  8 -> 20.00 h ->  600.00
        Build login database    complex 14 -> 35.00 h -> 1050.00
        Write user guide        simple  20 -> 20.00 h ->  600.00
        AH totals: 22 complex + 20 simple points, 75.00 h, 2250.00
      TJ: rate 22.50, 3.0 h per complex point, 1.5 h per simple point
        Integration testing     complex  6 -> 18.00 h ->  405.00
        Write test plan         simple  10 -> 15.00 h ->  337.50
        TJ totals: 6 complex + 10 simple points, 33.00 h, 742.50
      Project totals: 2 people, 5 tasks, 28 complex + 30 simple points,
                       108.00 hours, 2992.50
    """
    ah = fp_logic.make_person("AH", 30.0, 2.5, 1.0)
    ah["tasks"] = [
        fp_logic.make_task("Design user interface", "complex", 8),
        fp_logic.make_task("Build login database", "complex", 14),
        fp_logic.make_task("Write user guide", "simple", 20),
    ]
    tj = fp_logic.make_person("TJ", 22.5, 3.0, 1.5)
    tj["tasks"] = [
        fp_logic.make_task("Integration testing", "complex", 6),
        fp_logic.make_task("Write test plan", "simple", 10),
    ]
    return [ah, tj]


class TestCalculations(unittest.TestCase):

    def test_known_values_for_both_task_types(self):
        person = fp_logic.make_person("Alice", 30.0, 2.5, 1.0)
        complex_task = fp_logic.make_task("Design user interface", "complex", 8)
        row = fp_logic.task_row(complex_task, person)
        self.assertEqual(row["hours"], 20.0)     # 8 x 2.5
        self.assertEqual(row["cost"], 600.0)     # 20 x 30
        simple_task = fp_logic.make_task("Write user guide", "simple", 12)
        row = fp_logic.task_row(simple_task, person)
        self.assertEqual(row["hours"], 12.0)     # 12 x 1.0
        self.assertEqual(row["cost"], 360.0)     # 12 x 30

    def test_task_uses_that_persons_own_settings(self):
        alice = fp_logic.make_person("Alice", 30.0, 2.5, 1.0)
        bob = fp_logic.make_person("Bob", 10.0, 1.0, 0.5)
        complex_task = fp_logic.make_task("Same task", "complex", 10)
        simple_task = fp_logic.make_task("Same task", "simple", 10)
        # Alice, complex: 10 x 2.5 = 25 hours, at 30.00 = 750.00
        self.assertAlmostEqual(fp_logic.task_row(complex_task, alice)["cost"], 750.0)
        # Bob, complex:   10 x 1.0 = 10 hours, at 10.00 = 100.00
        self.assertAlmostEqual(fp_logic.task_row(complex_task, bob)["cost"], 100.0)
        # Alice, simple:  10 x 1.0 = 10 hours, at 30.00 = 300.00
        self.assertAlmostEqual(fp_logic.task_row(simple_task, alice)["cost"], 300.0)
        # Bob, simple:    10 x 0.5 =  5 hours, at 10.00 =  50.00
        self.assertAlmostEqual(fp_logic.task_row(simple_task, bob)["cost"], 50.0)

    def test_person_totals_add_up_their_tasks(self):
        ah = make_example_people()[0]
        totals = fp_logic.person_totals(ah)
        self.assertEqual(totals["task_count"], 3)
        self.assertEqual(totals["complex_points"], 22)
        self.assertEqual(totals["simple_points"], 20)
        self.assertAlmostEqual(totals["total_hours"], 75.0)
        self.assertAlmostEqual(totals["total_cost"], 2250.0)

    def test_project_totals_add_up_all_people(self):
        totals = fp_logic.project_totals(make_example_people())
        self.assertEqual(totals["person_count"], 2)
        self.assertEqual(totals["task_count"], 5)
        self.assertEqual(totals["complex_points"], 28)
        self.assertEqual(totals["simple_points"], 30)
        self.assertAlmostEqual(totals["total_hours"], 108.0)
        self.assertAlmostEqual(totals["total_cost"], 2992.50)

    def test_totals_with_no_people_or_no_tasks(self):
        self.assertEqual(fp_logic.project_totals([])["total_cost"], 0.0)
        empty = fp_logic.make_person("Nobody", 10.0, 1.0, 1.0)
        self.assertEqual(fp_logic.person_totals(empty)["total_hours"], 0.0)

    def test_totals_change_after_a_task_is_edited(self):
        ah = make_example_people()[0]
        ah["tasks"][0]["points"] = 18          # was 8 (complex)
        # 10 extra complex points = 25 extra hours = 750 extra pounds
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_hours"], 75.0 + 25.0)
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_cost"], 2250.0 + 750.0)

    def test_totals_change_after_a_task_changes_type(self):
        ah = make_example_people()[0]
        ah["tasks"][0]["type"] = "simple"      # was complex, 8 points
        # 8 complex points (20 h) becomes 8 simple points (8 h)
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_hours"], 75.0 - 20.0 + 8.0)
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_cost"], (75.0 - 12.0) * 30.0)

    def test_totals_change_after_a_task_is_deleted(self):
        ah = make_example_people()[0]
        del ah["tasks"][1]                     # "Build login database" (complex, 14)
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_hours"], 75.0 - 35.0)
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_cost"], 2250.0 - 1050.0)

    def test_totals_change_after_a_persons_settings_change(self):
        ah = make_example_people()[0]
        ah["hourly_rate"] = 60.0               # double AH's rate
        self.assertAlmostEqual(fp_logic.person_totals(ah)["total_cost"], 2250.0 * 2)


class TestInputChecks(unittest.TestCase):

    def test_parse_positive_number_accepts_good_values(self):
        self.assertEqual(fp_logic.parse_positive_number("25", "Hourly rate"), 25.0)
        self.assertEqual(fp_logic.parse_positive_number(" 2.5 ", "Hours"), 2.5)

    def test_parse_positive_number_rejects_bad_values(self):
        for bad in ("", "abc", "-5", "0"):
            with self.assertRaises(ValueError):
                fp_logic.parse_positive_number(bad, "Hourly rate")

    def test_parse_point_count_accepts_good_values(self):
        self.assertEqual(fp_logic.parse_point_count("7", "Complex function points"), 7)
        self.assertEqual(fp_logic.parse_point_count("0", "Simple function points"), 0)

    def test_parse_point_count_rejects_bad_values(self):
        for bad in ("", "abc", "2.5", "-1"):
            with self.assertRaises(ValueError):
                fp_logic.parse_point_count(bad, "Complex function points")

    def test_error_messages_name_the_field(self):
        with self.assertRaises(ValueError) as caught:
            fp_logic.parse_positive_number("nope", "Hourly rate")
        self.assertIn("Hourly rate", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            fp_logic.parse_point_count("lots", "Simple function points")
        self.assertIn("Simple function points", str(caught.exception))

    def test_clean_person_rejects_badly_formed_people(self):
        bad_people = [
            fp_logic.make_person("", 30.0, 2.5, 1.0),          # empty name
            fp_logic.make_person("Al", 0, 2.5, 1.0),           # zero rate
            fp_logic.make_person("Al", "cheap", 2.5, 1.0),     # rate is not a number
            fp_logic.make_person("Al", 30.0, -1, 1.0),         # negative hours per point
        ]
        for person in bad_people:
            with self.assertRaises(ValueError):
                fp_logic.clean_person(person)

    def test_clean_person_rejects_badly_formed_tasks(self):
        person = fp_logic.make_person("Al", 30.0, 2.5, 1.0)
        bad_tasks = [
            fp_logic.make_task("", "complex", 2),        # empty task name
            fp_logic.make_task("T", "hard", 2),          # not a real task type
            fp_logic.make_task("T", "complex", 2.5),     # points are not whole
            fp_logic.make_task("T", "complex", -2),      # negative points
            fp_logic.make_task("T", "complex", "many"),  # points are not a number
        ]
        for task in bad_tasks:
            person["tasks"] = [task]
            with self.assertRaises(ValueError):
                fp_logic.clean_person(person)

    def test_task_type_capitalisation_is_tidied_up(self):
        task = fp_logic.clean_task({"name": "T", "type": "Complex", "points": 5}, "Task 1")
        self.assertEqual(task["type"], "complex")
        task = fp_logic.clean_task({"name": "T", "type": "SIMPLE", "points": 5}, "Task 1")
        self.assertEqual(task["type"], "simple")


class TestJsonFiles(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name) / "project.json")

    def _write(self, data):
        Path(self.path).write_text(json.dumps(data), encoding="utf-8")

    def _write_raw(self, text):
        Path(self.path).write_text(text, encoding="utf-8")

    def test_save_and_load_round_trip(self):
        people = make_example_people()
        fp_logic.save_project(people, self.path)
        self.assertEqual(fp_logic.load_project(self.path), people)

    def test_saved_file_is_json_with_a_people_list(self):
        fp_logic.save_project(make_example_people(), self.path)
        with open(self.path, encoding="utf-8") as file:
            data = json.load(file)
        self.assertEqual(data["application"], fp_logic.APP_NAME)
        self.assertEqual(data["format_version"], fp_logic.FILE_FORMAT_VERSION)
        self.assertEqual(len(data["people"]), 2)
        task = data["people"][0]["tasks"][0]
        self.assertEqual(task["name"], "Design user interface")
        self.assertEqual(task["type"], "complex")
        self.assertEqual(task["points"], 8)

    def test_bare_list_of_people_also_loads(self):
        self._write([{"name": "AB", "hourly_rate": 20, "hours_per_complex_point": 2,
                      "hours_per_simple_point": 1,
                      "tasks": [{"name": "Job", "type": "simple", "points": 4}]}])
        people = fp_logic.load_project(self.path)
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0]["name"], "AB")
        self.assertEqual(people[0]["tasks"][0]["points"], 4)

    def test_example_input_file_loads_with_expected_totals(self):
        people = fp_logic.load_project(Path(__file__).with_name("example_input.json"))
        totals = fp_logic.project_totals(people)
        self.assertEqual(totals["person_count"], 2)
        self.assertEqual(totals["task_count"], 5)
        self.assertEqual(totals["complex_points"], 28)
        self.assertEqual(totals["simple_points"], 30)
        self.assertAlmostEqual(totals["total_hours"], 108.0)
        self.assertAlmostEqual(totals["total_cost"], 2992.50)

    def test_files_from_version_1_are_upgraded(self):
        # Version 1 stored the points directly on the person and had no tasks.
        self._write({"people": [{
            "name": "AB", "complex_points": 10, "simple_points": 5,
            "hourly_rate": 20.0, "hours_per_complex": 2.0, "hours_per_simple": 1.0,
        }]})
        people = fp_logic.load_project(self.path)
        person = people[0]
        self.assertEqual(person["hours_per_complex_point"], 2.0)
        self.assertEqual([t["name"] for t in person["tasks"]],
                         ["Imported work (complex)", "Imported work (simple)"])
        # 10 x 2 + 5 x 1 = 25 hours at 20.00 = 500.00 (nothing lost)
        self.assertAlmostEqual(fp_logic.person_totals(person)["total_hours"], 25.0)
        self.assertAlmostEqual(fp_logic.person_totals(person)["total_cost"], 500.0)

    def test_files_from_version_2_are_upgraded(self):
        # Version 2 stored separate complex/simple point counts on each task.
        self._write({
            "format_version": 2,
            "people": [{
                "name": "AB", "hourly_rate": 20.0,
                "hours_per_complex_point": 2.0, "hours_per_simple_point": 1.0,
                "tasks": [
                    {"name": "Mixed task", "complex_points": 10, "simple_points": 5},
                    {"name": "Pure task", "complex_points": 7, "simple_points": 0},
                ],
            }],
        })
        people = fp_logic.load_project(self.path)
        tasks = people[0]["tasks"]
        # A task that had both kinds of points is split into two; a task
        # with only one kind keeps its name.
        self.assertEqual([t["name"] for t in tasks],
                         ["Mixed task (complex)", "Mixed task (simple)", "Pure task"])
        self.assertEqual([t["type"] for t in tasks], ["complex", "simple", "complex"])
        self.assertEqual([t["points"] for t in tasks], [10, 5, 7])
        # 10x2 + 5x1 + 7x2 = 39 hours at 20.00 = 780.00
        self.assertAlmostEqual(fp_logic.person_totals(people[0])["total_hours"], 39.0)
        self.assertAlmostEqual(fp_logic.person_totals(people[0])["total_cost"], 780.0)

    def test_invalid_files_are_rejected_with_clear_errors(self):
        good_person = {"name": "Bob", "hourly_rate": 20.0,
                       "hours_per_complex_point": 2.0, "hours_per_simple_point": 1.0,
                       "tasks": []}
        cases = {
            "not JSON at all": ("raw", "{ this is not json"),
            "no people list": ("data", {"application": "Calculator"}),
            "people is not a list": ("data", {"people": "everyone"}),
            "person is not an object": ("data", {"people": ["Bob"]}),
            "person is missing their hourly rate":
                ("data", {"people": [{"name": "Bob", "tasks": []}]}),
            "task is missing its points":
                ("data", {"people": [dict(good_person, tasks=[
                    {"name": "T", "type": "complex"}])]}),
            "task type is not complex or simple":
                ("data", {"people": [dict(good_person, tasks=[
                    {"name": "T", "type": "hard", "points": 3}])]}),
            "negative points":
                ("data", {"people": [dict(good_person, tasks=[
                    {"name": "T", "type": "complex", "points": -2}])]}),
            "points are not whole numbers":
                ("data", {"people": [dict(good_person, tasks=[
                    {"name": "T", "type": "simple", "points": 2.5}])]}),
            "newer file format": ("data", {"format_version": 99, "people": []}),
        }
        for label, (kind, payload) in cases.items():
            with self.subTest(label):
                if kind == "raw":
                    self._write_raw(payload)
                else:
                    self._write(payload)
                with self.assertRaises(ValueError):
                    fp_logic.load_project(self.path)

    def test_error_messages_explain_the_problem(self):
        self._write({"people": [{"name": "Bob", "tasks": []}]})
        with self.assertRaises(ValueError) as caught:
            fp_logic.load_project(self.path)
        message = str(caught.exception)
        self.assertIn("Person 1", message)
        self.assertIn("Hourly rate", message)

    def test_missing_file_raises_a_clear_error(self):
        with self.assertRaises(OSError):
            fp_logic.load_project("no_such_file_anywhere.json")


class TestExports(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.csv_path = str(Path(tmp.name) / "estimates.csv")
        self.txt_path = str(Path(tmp.name) / "report.txt")

    def test_csv_has_one_row_per_task_plus_a_totals_row(self):
        fp_logic.export_csv(make_example_people(), self.csv_path)
        with open(self.csv_path, newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
        # header + 5 tasks + blank line + totals = 8 rows
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0], ["Person", "Task", "Task type",
                                   "Function points", "Hours", "Labour cost"])

        first = rows[1]     # AH, Design user interface
        self.assertEqual(first[0], "AH")
        self.assertEqual(first[1], "Design user interface")
        self.assertEqual(first[2], "Complex")
        self.assertEqual(first[3], "8")
        self.assertEqual(first[4], "20.00")
        self.assertEqual(first[5], "600.00")

        totals = rows[7]
        self.assertEqual(totals[0], "PROJECT TOTAL")
        self.assertEqual(totals[3], "58")        # 28 complex + 30 simple
        self.assertEqual(totals[4], "108.00")
        self.assertEqual(totals[5], "2992.50")

    def test_csv_tasks_use_each_persons_own_settings(self):
        fp_logic.export_csv(make_example_people(), self.csv_path)
        with open(self.csv_path, newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
        integration = next(row for row in rows if row[1] == "Integration testing")
        # TJ, complex: 6 x 3.0 = 18.00 hours at 22.50 = 405.00
        self.assertEqual(integration[0], "TJ")
        self.assertEqual(integration[2], "Complex")
        self.assertEqual(integration[4], "18.00")
        self.assertEqual(integration[5], "405.00")
        test_plan = next(row for row in rows if row[1] == "Write test plan")
        # TJ, simple: 10 x 1.5 = 15.00 hours at 22.50 = 337.50
        self.assertEqual(test_plan[2], "Simple")
        self.assertEqual(test_plan[4], "15.00")
        self.assertEqual(test_plan[5], "337.50")

    def test_report_contains_people_tasks_and_totals(self):
        fp_logic.export_report(make_example_people(), self.txt_path)
        text = Path(self.txt_path).read_text(encoding="utf-8")
        for expected in ("AH", "TJ",
                         "Design user interface", "Integration testing",
                         "PROJECT TOTALS", "Complex", "Simple",
                         "£600.00", "£742.50",
                         "£2,250.00", "£2,992.50",
                         "Total estimated hours: 108.00"):
            self.assertIn(expected, text)

    def test_report_for_a_person_with_no_tasks(self):
        lonely = fp_logic.make_person("Sam", 10.0, 1.0, 1.0)
        fp_logic.export_report([lonely], self.txt_path)
        text = Path(self.txt_path).read_text(encoding="utf-8")
        self.assertIn("(no tasks yet)", text)


if __name__ == "__main__":
    unittest.main()
