# Simple Function Point Calculator

A small desktop application (Python + Tkinter) for estimating project effort
and labour cost from function points, built for U3 PIDs and project planning
in ProjectLibre.

Each **person** in the project has their own hourly rate and their own
hours-per-function-point settings, and each person can have any number of
**tasks**. Every task is either a **complex** task or a **simple** task —
chosen from a drop-down when the task is added — and its estimate is
calculated with that person's settings.

## What it can do

- Add, edit and remove **people** (name or initials, hourly rate, hours per
  complex point, hours per simple point).
- Add, edit and remove **tasks** for the selected person: pick **Complex**
  or **Simple** from a drop-down, and the points box asks for that kind of
  function points only. As many tasks as you like, different for each person.
- A live table of every task's type, points, hours and cost,
  **selected-person totals** and **whole-project totals** that update
  automatically after every change.
- Open and save projects as **JSON**. Files saved by earlier versions of
  this calculator (which stored two separate point counts per task, or the
  points straight on the person) are upgraded automatically when opened —
  a task that had both kinds of points is split into a complex task and a
  simple task so no points are lost.
- Export **one row per task to CSV** for spreadsheets and ProjectLibre
  planning, and a readable **text report**.
- Input validation with clear error messages, and an unsaved-changes warning.

## Files in this package

| File | What it is |
| --- | --- |
| `main.py` | The Tkinter window: layout, buttons and menus. |
| `fp_logic.py` | The maths, input checking and file import/export (no Tkinter). |
| `test_fp_logic.py` | Automated tests for the maths and file handling. |
| `test_gui.py` | Automated tests that open the real window and click the buttons. |
| `example_input.json` | An example project you can open from the File menu. |

## Running the program

You need Python 3.8 or newer. Tkinter is included with standard Python on
Windows and macOS. On Debian/Ubuntu Linux, install it first with:

    sudo apt install python3-tk

Then, from this folder:

    python main.py

## How to use it

1. **Add a person** - fill in the *Person details* form on the left and click
   **Add person**. A person must exist before tasks can be added.
2. **Add tasks** - with the person selected, fill in the *Task details* form
   on the right: type the task name, choose **Complex** or **Simple** from
   the drop-down (the points box relabels itself to match), enter that
   kind of function points, and click **Add task**. Repeat for as many
   tasks as needed.
3. **Edit** - click a person in the list (or a task in the table) to load
   their details into the form, change the values, then click **Update** /
   **Update task**. Changing a task's type recalculates its hours using the
   matching hours-per-point setting.
4. **Totals** - the bottom right shows the selected person's totals and the
   whole project's totals. They recalculate automatically, including when a
   person's rate or hours-per-point settings change.
5. **Save / open** - use the *File* menu to save the project as JSON and
   open it again later (Ctrl+S / Ctrl+O).
6. **Export** - *File > Export task estimates as CSV* writes one row per
   task; *File > Export text report* writes a printable summary.

## How the estimates are calculated

Every task is either complex or simple, and each task uses **that person's**
settings:

    complex task hours = complex function points x hours per complex point
    simple task hours  = simple function points  x hours per simple point
    labour cost        = task hours x hourly rate

Person totals add up that person's tasks; project totals add up every person.

### Worked example (from `example_input.json`)

AH has a rate of £30.00/hour, 2.5 hours per complex point and 1.0 hour per
simple point. The task "Design user interface" is a complex task with 8
points:

- complex task hours = 8 x 2.5 = 20.00
- labour cost = 20.00 x £30.00 = **£600.00**

TJ's task "Write test plan" is a simple task with 10 points, and uses TJ's
own settings (1.5 h per simple point, £22.50/hour):
10 x 1.5 = 15.00 hours = **£337.50**.
The whole example project comes to 108.00 hours and **£2,992.50**.

## Project file format

`example_input.json` shows the format; you can also write your own input
files by hand:

```json
{
  "application": "Simple Function Point Calculator",
  "format_version": 3,
  "people": [
    {
      "name": "AH",
      "hourly_rate": 30.0,
      "hours_per_complex_point": 2.5,
      "hours_per_simple_point": 1.0,
      "tasks": [
        { "name": "Design user interface", "type": "complex", "points": 8 },
        { "name": "Write user guide", "type": "simple", "points": 20 }
      ]
    }
  ]
}
```

A file holding just a bare list of people (without the outer object) also
opens fine. Files that are invalid - not JSON, missing fields, negative or
non-whole point counts, a task type other than complex/simple, and so on -
are rejected with a message that says which person/task and which field is
wrong.

## Exports and ProjectLibre

The CSV has one row per task with the columns: Person, Task, Task type
(Complex or Simple), Function points, Hours, Labour cost - followed by a
PROJECT TOTAL row. It is written as UTF-8 with a BOM so the pound sign
displays correctly when the file is opened in Excel.

This program does not create or edit ProjectLibre (.pod) files. A typical
workflow: open the CSV in a spreadsheet, then in ProjectLibre create your
resources from the people (with their hourly rates) and enter the tasks,
using the estimated hours as the work for each assignment.

## Running the tests

From this folder:

    python -m unittest test_fp_logic test_gui -v

- `test_fp_logic.py` (30 tests) checks the maths with known values for both
  task types, that tasks always use their own person's settings, the person
  and project totals (including a task changing type), JSON save/load
  including broken files and the automatic upgrade of version 1 and 2 files,
  and the CSV/report exports.
- `test_gui.py` (22 tests) opens the real window and tests the type
  drop-down relabelling the points box, adding, editing, re-typing and
  deleting people and tasks, the validation messages, totals updating after
  changes, saving/opening projects (including an old-format file), starting
  a new project, and exporting. It needs a screen to draw on; if the machine
  has no display it skips automatically so the rest still passes.

To only check that the code compiles:

    python -m py_compile main.py fp_logic.py

## Changes from the first prototype

The original prototype had six flat input fields and only printed them out.
This version reorganises the data into **people who each own tasks**, so
different people can use different rates and hours-per-point settings. Each
task is now complex or simple, chosen from a drop-down, with a single
function point count. The interface is split into a people panel (left) and
a tasks panel (right) as set out in the project flowchart, and the program
can save, open, and export the results.
