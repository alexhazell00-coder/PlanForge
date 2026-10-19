"""Tests that open the real Tkinter window and click the buttons.

Run them from the folder containing the files:

    python -m unittest test_gui -v

These tests need a screen to draw on, which any normal desktop has.  On a
machine with no display (for example a server) they skip automatically so
the rest of the suite still passes.
"""

import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import fp_logic
import main


def _display_available():
    """True if Tk can open a window on this machine."""
    try:
        window = tk.Tk()
    except tk.TclError:
        return False
    window.destroy()
    return True


DISPLAY_AVAILABLE = _display_available()


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display available for Tkinter")
class AppTestCase(unittest.TestCase):
    """Shared setup: one fresh window and application for each test."""

    def setUp(self):
        self.root = tk.Tk()
        self.app = main.FunctionPointApp(self.root)
        self.addCleanup(self.root.destroy)

    # -- little helpers to keep the tests readable ----------------------

    def type_person(self, name, rate, per_complex, per_simple):
        self.app.person_name_var.set(str(name))
        self.app.hourly_rate_var.set(str(rate))
        self.app.hours_complex_var.set(str(per_complex))
        self.app.hours_simple_var.set(str(per_simple))

    def type_task(self, name, task_type, points):
        """Fill the task form.  task_type is 'Complex' or 'Simple'."""
        self.app.task_name_var.set(str(name))
        self.app.task_type_var.set(str(task_type).capitalize())
        self.app.task_points_var.set(str(points))
        self.app._on_task_type_chosen()

    def click(self, button):
        button.invoke()
        self.root.update()   # let Tk process any events the click produced

    def select_person(self, index):
        """Select a person in the list exactly like a mouse click would."""
        self.app.people_list.selection_clear(0, tk.END)
        self.app.people_list.selection_set(index)
        self.app.people_list.event_generate("<<ListboxSelect>>")
        self.root.update()

    def select_task(self, index):
        """Select a task in the table exactly like a mouse click would."""
        self.app.task_tree.selection_set(str(index))
        self.app.task_tree.event_generate("<<TreeviewSelect>>")
        self.root.update()


class TestPeopleAndTasks(AppTestCase):

    def test_task_form_is_locked_until_a_person_exists(self):
        self.assertEqual(str(self.app.task_name_entry.cget("state")), "disabled")
        self.assertEqual(str(self.app.task_points_entry.cget("state")), "disabled")
        self.assertEqual(str(self.app.task_type_combo.cget("state")), "disabled")
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.assertEqual(str(self.app.task_name_entry.cget("state")), "normal")
        self.assertEqual(str(self.app.task_points_entry.cget("state")), "normal")
        self.assertEqual(str(self.app.task_type_combo.cget("state")), "readonly")

    def test_choosing_a_task_type_relabels_the_points_box(self):
        self.assertEqual(self.app.task_points_label.cget("text"),
                         "Complex function points")
        self.app.task_type_var.set("Simple")
        self.app.task_type_combo.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(self.app.task_points_label.cget("text"),
                         "Simple function points")
        self.app.task_type_var.set("Complex")
        self.app.task_type_combo.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(self.app.task_points_label.cget("text"),
                         "Complex function points")

    def test_add_two_people_with_several_tasks(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        self.type_task("Write guide", "simple", 20)
        self.click(self.app.add_task_button)

        self.type_person("Tom", 22.5, 3, 1.5)
        self.click(self.app.add_person_button)
        self.type_task("Testing", "complex", 6)
        self.click(self.app.add_task_button)
        self.type_task("Test plan", "simple", 10)
        self.click(self.app.add_task_button)

        self.assertEqual(len(self.app.people), 2)
        self.assertEqual(len(self.app.people[0]["tasks"]), 2)
        self.assertEqual(len(self.app.people[1]["tasks"]), 2)
        # The list shows both people and Tom (just added) is selected.
        self.assertEqual(self.app.people_list.size(), 2)
        self.assertEqual(self.app._selected_person()["name"], "Tom")
        # Tom's table shows his two tasks, not Alice's.
        self.assertEqual(len(self.app.task_tree.get_children()), 2)

    def test_tasks_use_their_own_persons_rate_and_hours(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        # Complex task: 8 x 2.5 = 20.00 hours, at 30.00 = 600.00
        values = self.app.task_tree.item("0", "values")
        self.assertEqual(values[1], "Complex")
        self.assertEqual(values[3], "20.00")
        self.assertEqual(values[4], "600.00")

    def test_selecting_a_person_shows_their_tasks(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        self.type_task("Write guide", "simple", 20)
        self.click(self.app.add_task_button)
        self.type_person("Tom", 22.5, 3, 1.5)
        self.click(self.app.add_person_button)
        self.type_task("Testing", "complex", 6)
        self.click(self.app.add_task_button)

        self.select_person(0)   # back to Alice
        self.assertEqual(self.app._selected_person()["name"], "Alice")
        self.assertEqual(len(self.app.task_tree.get_children()), 2)
        self.assertIn("Alice", self.app.tasks_heading.cget("text"))
        self.assertEqual(self.app.person_name_var.get(), "Alice")

    def test_selecting_a_task_fills_the_form_for_editing(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        self.type_task("Write guide", "simple", 20)
        self.click(self.app.add_task_button)

        self.select_task(0)     # the complex task
        self.assertEqual(self.app.task_name_var.get(), "Design UI")
        self.assertEqual(self.app.task_type_var.get(), "Complex")
        self.assertEqual(self.app.task_points_var.get(), "8")
        self.assertEqual(self.app.task_points_label.cget("text"),
                         "Complex function points")

        self.select_task(1)     # the simple task
        self.assertEqual(self.app.task_name_var.get(), "Write guide")
        self.assertEqual(self.app.task_type_var.get(), "Simple")
        self.assertEqual(self.app.task_points_var.get(), "20")
        self.assertEqual(self.app.task_points_label.cget("text"),
                         "Simple function points")

    def test_editing_a_task_updates_the_table_and_totals(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)

        self.select_task(0)
        self.app.task_points_var.set("18")
        self.click(self.app.update_task_button)
        # 18 x 2.5 = 45.00 hours, at 30.00 = 1350.00
        values = self.app.task_tree.item("0", "values")
        self.assertEqual(values[2], "18")
        self.assertEqual(values[3], "45.00")
        self.assertIn("£1,350.00", self.app.person_totals_label.cget("text"))

    def test_changing_a_tasks_type_recalculates_it(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        # Complex: 8 x 2.5 = 20.00 hours.
        self.assertEqual(self.app.task_tree.item("0", "values")[3], "20.00")

        self.select_task(0)
        self.app.task_type_var.set("Simple")
        self.click(self.app.update_task_button)
        # Simple: 8 x 1.0 = 8.00 hours, at 30.00 = 240.00
        values = self.app.task_tree.item("0", "values")
        self.assertEqual(values[1], "Simple")
        self.assertEqual(values[3], "8.00")
        self.assertEqual(values[4], "240.00")

    def test_deleting_a_task(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        self.type_task("Write guide", "simple", 20)
        self.click(self.app.add_task_button)

        self.select_task(1)      # "Write guide"
        self.click(self.app.remove_task_button)
        self.assertEqual(len(self.app.people[0]["tasks"]), 1)
        self.assertEqual(len(self.app.task_tree.get_children()), 1)
        self.assertEqual(self.app.people[0]["tasks"][0]["name"], "Design UI")

    def test_removing_a_person_asks_first(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        self.type_person("Tom", 22.5, 3, 1.5)
        self.click(self.app.add_person_button)
        self.select_person(0)    # Alice

        # Answering "No" must leave everything as it is.
        with mock.patch("main.messagebox.askyesno", return_value=False) as asked:
            self.click(self.app.remove_person_button)
        asked.assert_called_once()
        self.assertEqual(len(self.app.people), 2)

        # Answering "Yes" removes Alice and all of her tasks.
        with mock.patch("main.messagebox.askyesno", return_value=True):
            self.click(self.app.remove_person_button)
        self.assertEqual(len(self.app.people), 1)
        self.assertEqual(self.app.people[0]["name"], "Tom")

    def test_empty_person_form_shows_a_clear_error(self):
        with mock.patch("main.messagebox.showerror") as show_error:
            self.click(self.app.add_person_button)      # everything is blank
        show_error.assert_called_once()
        message = show_error.call_args.args[1]
        self.assertIn("name", message.lower())
        self.assertEqual(self.app.people, [])

    def test_bad_numbers_are_rejected_with_a_clear_error(self):
        self.type_person("Alice", "cheap", 2.5, 1)
        with mock.patch("main.messagebox.showerror") as show_error:
            self.click(self.app.add_person_button)
        show_error.assert_called_once()
        self.assertIn("Hourly rate", show_error.call_args.args[1])
        self.assertEqual(self.app.people, [])

    def test_bad_points_are_rejected_with_a_clear_error(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", "lots")
        with mock.patch("main.messagebox.showerror") as show_error:
            self.click(self.app.add_task_button)
        show_error.assert_called_once()
        # The message names the points box for the chosen type.
        self.assertIn("Complex function points", show_error.call_args.args[1])
        self.assertEqual(self.app.people[0]["tasks"], [])

    def test_adding_a_task_without_a_person_shows_a_clear_error(self):
        with mock.patch("main.messagebox.showinfo") as show_info:
            self.click(self.app.add_task_button)
        show_info.assert_called_once()
        self.assertEqual(self.app.people, [])

    def test_duplicate_person_names_are_rejected(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_person("alice", 25, 2, 1)
        with mock.patch("main.messagebox.showerror") as show_error:
            self.click(self.app.add_person_button)
        show_error.assert_called_once()
        self.assertEqual(len(self.app.people), 1)

    def test_totals_update_when_a_persons_settings_change(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)
        self.assertIn("£600.00", self.app.person_totals_label.cget("text"))

        # Give Alice a pay rise to 60 per hour and save the change.
        self.app.hourly_rate_var.set("60")
        self.click(self.app.update_person_button)
        self.assertIn("£1,200.00", self.app.person_totals_label.cget("text"))
        self.assertIn("£1,200.00", self.app.project_totals_label.cget("text"))


class TestFileMenu(AppTestCase):

    def _add_example_person_and_task(self):
        self.type_person("Alice", 30, 2.5, 1)
        self.click(self.app.add_person_button)
        self.type_task("Design UI", "complex", 8)
        self.click(self.app.add_task_button)

    def test_save_and_open_a_project(self):
        self._add_example_person_and_task()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "project.json")
            self.app.current_file = path
            self.assertTrue(self.app.save_project())
            self.assertFalse(self.app.dirty)
            self.assertIn("project.json", self.root.title())

            # Start from empty data, then load the file back in.
            self.app.people = []
            self.app._refresh_all()
            with mock.patch("main.filedialog.askopenfilename", return_value=path):
                self.app.open_project()
                self.root.update()
            self.assertEqual(len(self.app.people), 1)
            self.assertEqual(self.app.people[0]["name"], "Alice")
            task = self.app.people[0]["tasks"][0]
            self.assertEqual(task["name"], "Design UI")
            self.assertEqual(task["type"], "complex")
            self.assertEqual(task["points"], 8)
            self.assertEqual(self.app.current_file, path)
            self.assertEqual(len(self.app.task_tree.get_children()), 1)

    def test_opening_an_invalid_file_shows_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "broken.json"
            bad_path.write_text("{ this is not json", encoding="utf-8")
            with mock.patch("main.filedialog.askopenfilename", return_value=str(bad_path)):
                with mock.patch("main.messagebox.showerror") as show_error:
                    self.app.open_project()
        show_error.assert_called_once()
        self.assertIn("not valid JSON", show_error.call_args.args[1])
        self.assertEqual(self.app.people, [])

    def test_old_task_files_are_upgraded_when_opened(self):
        # A version 2 file: the task has two separate point counts.
        old_file = {
            "format_version": 2,
            "people": [{
                "name": "AB", "hourly_rate": 20.0,
                "hours_per_complex_point": 2.0, "hours_per_simple_point": 1.0,
                "tasks": [{"name": "Mixed task",
                           "complex_points": 10, "simple_points": 5}],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps(old_file), encoding="utf-8")
            with mock.patch("main.filedialog.askopenfilename", return_value=str(path)):
                self.app.open_project()
                self.root.update()
        tasks = self.app.people[0]["tasks"]
        self.assertEqual([t["name"] for t in tasks],
                         ["Mixed task (complex)", "Mixed task (simple)"])
        self.assertEqual([t["type"] for t in tasks], ["complex", "simple"])
        # 10 x 2 + 5 x 1 = 25.00 hours in total.
        self.assertIn("25.00", self.app.person_totals_label.cget("text"))

    def test_new_project_clears_everything(self):
        self._add_example_person_and_task()
        self.assertTrue(self.app.dirty)
        with mock.patch("main.messagebox.askyesnocancel", return_value=False):  # "don't save"
            self.app.new_project()
        self.assertEqual(self.app.people, [])
        self.assertIsNone(self.app.current_file)
        self.assertFalse(self.app.dirty)
        self.assertEqual(self.app.people_list.size(), 0)

    def test_export_csv_and_report_from_the_gui(self):
        self._add_example_person_and_task()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = str(Path(tmp) / "estimates.csv")
            txt_path = str(Path(tmp) / "report.txt")
            with mock.patch("main.filedialog.asksaveasfilename",
                            side_effect=[csv_path, txt_path]):
                self.app.export_csv()
                self.app.export_report()
            csv_text = Path(csv_path).read_text(encoding="utf-8-sig")
            self.assertIn("Design UI", csv_text)
            self.assertIn("Complex", csv_text)
            self.assertIn("600.00", csv_text)
            report_text = Path(txt_path).read_text(encoding="utf-8")
            self.assertIn("Alice", report_text)
            self.assertIn("PROJECT TOTALS", report_text)

    def test_export_with_no_people_shows_a_message(self):
        with mock.patch("main.messagebox.showinfo") as show_info:
            self.app.export_csv()
        show_info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
