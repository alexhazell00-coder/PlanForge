"""Calculations, input checking and file handling for the calculator.

This module deliberately contains NO Tkinter code: all of the "business"
logic (the maths, checking inputs, saving/loading and exporting) lives here
so it can be tested on its own - see test_fp_logic.py.  The window itself
is built in main.py.

Data shapes
-----------
A *person* is a plain dictionary:

    {
        "name": "Alice",
        "hourly_rate": 30.0,              # pounds paid per hour of work
        "hours_per_complex_point": 2.5,   # hours needed for one complex FP
        "hours_per_simple_point": 1.0,    # hours needed for one simple FP
        "tasks": [ ...task dictionaries... ],
    }

A *task* is a plain dictionary.  Every task is either a complex task or a
simple task, chosen when the task is added, with one function point count:

    {
        "name": "Design the login form",
        "type": "complex",     # "complex" or "simple"
        "points": 8,
    }

Older versions of this program stored two separate point counts on each
task (file format version 2) or straight on the person (version 1).  Files
like that are upgraded automatically by load_project().
"""

import csv
import json
import math
from datetime import datetime
from pathlib import Path

APP_NAME = "Simple Function Point Calculator"
FILE_FORMAT_VERSION = 3
TASK_TYPES = ("complex", "simple")   # the two kinds of task
CURRENCY_SYMBOL = "£"


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def make_person(name, hourly_rate, hours_per_complex_point, hours_per_simple_point):
    """Return a brand-new person dictionary with an empty task list."""
    return {
        "name": name,
        "hourly_rate": hourly_rate,
        "hours_per_complex_point": hours_per_complex_point,
        "hours_per_simple_point": hours_per_simple_point,
        "tasks": [],
    }


def make_task(name, task_type, points):
    """Return a brand-new task dictionary (task_type: 'complex' or 'simple')."""
    return {
        "name": name,
        "type": task_type,
        "points": points,
    }


def format_money(amount):
    """Format a number as money, for example 1234.5 becomes £1,234.50."""
    return f"{CURRENCY_SYMBOL}{amount:,.2f}"


# ---------------------------------------------------------------------------
# Checking data read from a file
# ---------------------------------------------------------------------------

def _clean_name(value, label):
    """A name must be text with at least one character."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be empty.")
    return value.strip()


def _clean_positive_number(value, label):
    """Rates and hours-per-point settings must be numbers greater than zero."""
    if (isinstance(value, bool)                      # True/False are ints in
            or not isinstance(value, (int, float))   # Python, so block them
            or not math.isfinite(value)              # separately!
            or value <= 0):
        raise ValueError(f"{label} must be a number greater than zero.")
    return float(value)


def _clean_point_count(value, label):
    """Function point counts must be whole numbers (zero is allowed)."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number of points (0 or more).")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{label} must be a whole number, not {value}.")
        value = int(value)
    if not isinstance(value, int):
        raise ValueError(f"{label} must be a whole number of points (0 or more).")
    if value < 0:
        raise ValueError(f"{label} cannot be a negative number.")
    return value


def clean_task(task, where):
    """Check one task dictionary and return a clean copy of it."""
    if not isinstance(task, dict):
        raise ValueError(f"{where} must be an object with 'name', 'type' and 'points'.")
    try:
        name = _clean_name(task.get("name"), "Task name")
        task_type = task.get("type")
        if not isinstance(task_type, str) or task_type.strip().lower() not in TASK_TYPES:
            raise ValueError("Task type must be either 'complex' or 'simple'.")
        points = _clean_point_count(task.get("points"), "Function points")
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from None
    return make_task(name, task_type.strip().lower(), points)


def clean_person(person, where="Person"):
    """Check one person dictionary (including their tasks), return a clean copy."""
    if not isinstance(person, dict):
        raise ValueError(f"{where} must be an object with a name, settings and tasks.")
    try:
        name = _clean_name(person.get("name"), "Person name")
        hourly_rate = _clean_positive_number(person.get("hourly_rate"), "Hourly rate")
        per_complex = _clean_positive_number(
            person.get("hours_per_complex_point"), "Hours per complex function point")
        per_simple = _clean_positive_number(
            person.get("hours_per_simple_point"), "Hours per simple function point")
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from None

    tasks_in = person.get("tasks", [])
    if not isinstance(tasks_in, list):
        raise ValueError(f"{where} ('{name}'): 'tasks' must be a list.")
    tasks = []
    for index, raw_task in enumerate(tasks_in):
        where_task = f"{where} ('{name}'), task {index + 1}"
        if _is_old_task(raw_task):
            tasks.extend(_upgrade_old_task(raw_task, where_task))
        else:
            tasks.append(clean_task(raw_task, where_task))

    cleaned = make_person(name, hourly_rate, per_complex, per_simple)
    cleaned["tasks"] = tasks
    return cleaned


# ---------------------------------------------------------------------------
# Reading the text typed into entry boxes
# ---------------------------------------------------------------------------

def parse_positive_number(text, label):
    """Turn text from an entry box into a number greater than zero.

    Raises ValueError with a friendly message if the text is not usable.
    """
    try:
        value = float(str(text).strip())
    except ValueError:
        raise ValueError(f"{label} must be a number, for example 25.50.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a number greater than zero.")
    return value


def parse_point_count(text, label):
    """Turn text from an entry box into a whole number of points (0 or more).

    Raises ValueError with a friendly message if the text is not usable.
    """
    raw = str(text).strip()
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{label} must be a whole number, for example 8.") from None
    if not math.isfinite(value) or value != int(value):
        raise ValueError(f"{label} must be a whole number, not {raw}.")
    if value < 0:
        raise ValueError(f"{label} cannot be a negative number.")
    return int(value)


# ---------------------------------------------------------------------------
# The maths
# ---------------------------------------------------------------------------

def task_row(task, person):
    """Return every calculated value for one task, using the person's settings.

    A complex task uses the person's hours per complex point; a simple task
    uses their hours per simple point.
    """
    if task["type"] == "complex":
        per_point = person["hours_per_complex_point"]
    else:
        per_point = person["hours_per_simple_point"]
    hours = task["points"] * per_point
    return {
        "name": task["name"],
        "type": task["type"],
        "points": task["points"],
        "hours": hours,
        "cost": hours * person["hourly_rate"],
    }


def person_totals(person):
    """Add up all of one person's tasks."""
    totals = {
        "name": person["name"],
        "task_count": 0,
        "complex_points": 0,
        "simple_points": 0,
        "total_hours": 0.0,
        "total_cost": 0.0,
    }
    for task in person["tasks"]:
        row = task_row(task, person)
        totals["task_count"] += 1
        if task["type"] == "complex":
            totals["complex_points"] += row["points"]
        else:
            totals["simple_points"] += row["points"]
        totals["total_hours"] += row["hours"]
        totals["total_cost"] += row["cost"]
    return totals


def project_totals(people):
    """Add up every person to give the totals for the whole project."""
    totals = {
        "person_count": len(people),
        "task_count": 0,
        "complex_points": 0,
        "simple_points": 0,
        "total_hours": 0.0,
        "total_cost": 0.0,
    }
    for person in people:
        summary = person_totals(person)
        for key in ("task_count", "complex_points", "simple_points",
                    "total_hours", "total_cost"):
            totals[key] += summary[key]
    return totals


# ---------------------------------------------------------------------------
# Saving and loading project files (JSON)
# ---------------------------------------------------------------------------

def save_project(people, path):
    """Save the whole project (people and their tasks) as a JSON file."""
    data = {
        "application": APP_NAME,
        "format_version": FILE_FORMAT_VERSION,
        "saved": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "people": people,
    }
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def load_project(path):
    """Load a project JSON file and return a clean list of people.

    Raises OSError if the file cannot be read, or ValueError with a helpful
    message if the file is not a valid project file.
    """
    with open(path, "r", encoding="utf-8") as file:   # OSError goes to the caller
        text = file.read()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"This file is not valid JSON: {error.msg} (line {error.lineno}).") from None

    # The file either holds a bare list of people, or an object like the one
    # save_project() writes with a "people" list inside it.
    if isinstance(data, list):
        people_data = data
    elif isinstance(data, dict) and isinstance(data.get("people"), list):
        people_data = data["people"]
    else:
        raise ValueError("This file does not look like a project file. "
                         "It must contain a list of people (or a 'people' list).")

    if isinstance(data, dict):
        version = data.get("format_version", 1)
        if not isinstance(version, int) or version > FILE_FORMAT_VERSION:
            raise ValueError(
                f"This file was written by a newer version of the program "
                f"(format version {version}); this program understands up to "
                f"version {FILE_FORMAT_VERSION}.")

    people = []
    for index, person in enumerate(people_data):
        where = f"Person {index + 1}"
        if _is_old_format_person(person):
            people.append(_upgrade_old_person(person, where))
        else:
            people.append(clean_person(person, where))
    return people


def _is_old_format_person(person):
    """Spot people saved by version 1 of this calculator.

    The old flat version stored function points directly on the person and
    had no tasks at all.
    """
    return (isinstance(person, dict)
            and "tasks" not in person
            and ("complex_points" in person or "simple_points" in person))


def _is_old_task(task):
    """Spot tasks saved by versions 1 and 2 (two separate point counts)."""
    return (isinstance(task, dict) and "type" not in task
            and ("complex_points" in task or "simple_points" in task))


def _upgrade_old_task(old, where):
    """Turn an old-style task into new-style task(s) and return a list.

    A task that had both complex and simple points becomes two tasks - one
    of each type - so that no function points are lost.  A task with only
    one kind of points keeps its name.
    """
    try:
        name = _clean_name(old.get("name"), "Task name")
        complex_points = _clean_point_count(
            old.get("complex_points", 0), "Complex function points")
        simple_points = _clean_point_count(
            old.get("simple_points", 0), "Simple function points")
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from None

    upgraded = []
    if complex_points and simple_points:
        # The task had both kinds of points, so it is split into two tasks.
        # The suffixes show where each half came from.
        upgraded.append(make_task(f"{name} (complex)", "complex", complex_points))
        upgraded.append(make_task(f"{name} (simple)", "simple", simple_points))
    elif complex_points:
        upgraded.append(make_task(name, "complex", complex_points))
    elif simple_points:
        upgraded.append(make_task(name, "simple", simple_points))
    else:
        upgraded.append(make_task(name, "complex", 0))
    return upgraded


def _upgrade_old_person(old, where):
    """Convert a version 1 person into the new format by splitting their
    points into one complex and one simple task."""
    upgraded = {
        "name": old.get("name"),
        "hourly_rate": old.get("hourly_rate"),
        "hours_per_complex_point": old.get("hours_per_complex_point",
                                           old.get("hours_per_complex")),
        "hours_per_simple_point": old.get("hours_per_simple_point",
                                          old.get("hours_per_simple")),
        "tasks": [],
    }
    complex_points = old.get("complex_points", 0)
    simple_points = old.get("simple_points", 0)
    if complex_points:
        upgraded["tasks"].append(
            make_task("Imported work (complex)", "complex", complex_points))
    if simple_points:
        upgraded["tasks"].append(
            make_task("Imported work (simple)", "simple", simple_points))
    if not upgraded["tasks"]:
        upgraded["tasks"].append(make_task("Imported work", "complex", 0))
    return clean_person(upgraded, where)


# ---------------------------------------------------------------------------
# Exporting results (CSV and text report)
# ---------------------------------------------------------------------------

CSV_HEADERS = [
    "Person", "Task", "Task type",
    "Function points", "Hours", "Labour cost",
]


def build_csv_rows(people):
    """Build the spreadsheet rows: one row per task, then a totals row."""
    rows = [list(CSV_HEADERS)]
    for person in people:
        for task in person["tasks"]:
            row = task_row(task, person)
            rows.append([
                person["name"],
                row["name"],
                row["type"].capitalize(),
                row["points"],
                f"{row['hours']:.2f}",
                f"{row['cost']:.2f}",
            ])

    totals = project_totals(people)
    rows.append([])   # a blank line before the totals
    rows.append([
        "PROJECT TOTAL", "",
        "", totals["complex_points"] + totals["simple_points"],
        f"{totals['total_hours']:.2f}", f"{totals['total_cost']:.2f}",
    ])
    return rows


def export_csv(people, path):
    """Write one row per task to a CSV file that opens nicely in spreadsheets.

    The file is written as UTF-8 with a BOM so Excel shows the pound sign
    correctly when the CSV is double-clicked.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        csv.writer(file).writerows(build_csv_rows(people))


def build_report_text(people):
    """Build a plain-text report showing every person, task and the totals."""
    lines = [
        f"{APP_NAME} - PROJECT REPORT",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 68,
        "",
    ]
    for person in people:
        lines.append(
            f"Person: {person['name']}  "
            f"(rate {format_money(person['hourly_rate'])} per hour, "
            f"{person['hours_per_complex_point']:.2f} hours per complex point, "
            f"{person['hours_per_simple_point']:.2f} hours per simple point)")
        if person["tasks"]:
            lines.append(
                f"    {'Task':<30}{'Type':>8}{'Points':>8}{'Hours':>9}{'Cost':>13}")
            for task in person["tasks"]:
                row = task_row(task, person)
                cost_text = format_money(row["cost"])
                lines.append(
                    f"    {row['name'][:30]:<30}"
                    f"{row['type'].capitalize():>8}{row['points']:>8}"
                    f"{row['hours']:>9.2f}{cost_text:>13}")
        else:
            lines.append("    (no tasks yet)")
        summary = person_totals(person)
        task_word = "task" if summary["task_count"] == 1 else "tasks"
        lines.append(
            f"    Subtotal: {summary['total_hours']:.2f} hours, "
            f"{format_money(summary['total_cost'])} "
            f"({summary['task_count']} {task_word}, {summary['complex_points']} complex + "
            f"{summary['simple_points']} simple points)")
        lines.append("")

    totals = project_totals(people)
    lines.extend([
        "=" * 68,
        "PROJECT TOTALS",
        f"People: {totals['person_count']}    Tasks: {totals['task_count']}",
        f"Complex function points: {totals['complex_points']}",
        f"Simple function points: {totals['simple_points']}",
        f"Total estimated hours: {totals['total_hours']:.2f}",
        f"Total labour cost: {format_money(totals['total_cost'])}",
    ])
    return "\n".join(lines) + "\n"


def export_report(people, path):
    """Write the readable text report to a file."""
    Path(path).write_text(build_report_text(people), encoding="utf-8")
