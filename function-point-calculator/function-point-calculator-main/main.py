"""Simple Function Point Calculator - the Tkinter window.

Run the program with:

    python main.py

All of the calculations, input checking and file handling live in
fp_logic.py; this file only builds the window and connects the buttons to
that logic.  People are shown on the left, the selected person's tasks on
the right, exactly as set out in the project flowchart.

Each task is either a COMPLEX task or a SIMPLE task, chosen from a
drop-down when the task is added; the points box then asks for that kind
of function points only.
"""

import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:            # Tkinter is missing on a few Linux setups.
    tk = None                  # main() shows a friendly message if so.

import fp_logic


class FunctionPointApp:
    """Builds and controls the main window of the calculator."""

    def __init__(self, root):
        self.root = root
        self.root.minsize(980, 640)

        # The project data: a list of person dictionaries (see fp_logic.py).
        self.people = []
        # The file the project was loaded from / last saved to (if any).
        self.current_file = None
        # True when there are changes that have not been saved yet.
        self.dirty = False
        # The task currently selected in the task table (or None).
        self.editing_task_index = None

        # Text typed into the person form.
        self.person_name_var = tk.StringVar()
        self.hourly_rate_var = tk.StringVar()
        self.hours_complex_var = tk.StringVar()
        self.hours_simple_var = tk.StringVar()
        # Text typed into the task form.  The type is picked from a
        # drop-down, and one box asks for that type's function points.
        self.task_name_var = tk.StringVar()
        self.task_type_var = tk.StringVar(value="Complex")
        self.task_points_var = tk.StringVar()

        self._build_menu()
        self._build_layout()

        self._refresh_all()
        self._say("Welcome! Add a person on the left, or open a project from the File menu.")

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New project", accelerator="Ctrl+N",
                              command=self.new_project)
        file_menu.add_separator()
        file_menu.add_command(label="Open project...", accelerator="Ctrl+O",
                              command=self.open_project)
        file_menu.add_command(label="Save project", accelerator="Ctrl+S",
                              command=self.save_project)
        file_menu.add_command(label="Save project as...", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Export task estimates as CSV...", command=self.export_csv)
        file_menu.add_command(label="Export text report...", command=self.export_report)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="How the estimates are calculated",
                              command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda event: self.new_project())
        self.root.bind("<Control-o>", lambda event: self.open_project())
        self.root.bind("<Control-s>", lambda event: self.save_project())

    def _build_layout(self):
        self.root.columnconfigure(0, weight=0)   # people panel keeps its size
        self.root.columnconfigure(1, weight=1)   # tasks panel grows
        self.root.rowconfigure(0, weight=1)

        self._build_people_panel()
        self._build_tasks_panel()

        # Status bar along the bottom.
        self.status = ttk.Label(self.root, relief="sunken", anchor="w", padding=(6, 3))
        self.status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _build_people_panel(self):
        """Left side: the list of people, the person form and its buttons."""
        left = ttk.LabelFrame(self.root, text=" People ")
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)

        # The list of people in the project.
        self.people_list = tk.Listbox(left, height=8, width=28, exportselection=False)
        people_scroll = ttk.Scrollbar(left, orient="vertical",
                                      command=self.people_list.yview)
        self.people_list.configure(yscrollcommand=people_scroll.set)
        self.people_list.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=(4, 4))
        people_scroll.grid(row=0, column=1, sticky="ns", pady=(4, 4))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.people_list.bind("<<ListboxSelect>>", self._on_person_selected)

        # The form for one person's details.  These settings belong to the
        # person and are used by every one of their tasks.
        form = ttk.LabelFrame(left, text=" Person details ")
        form.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 4))
        fields = (
            ("Name or initials", self.person_name_var),
            ("Hourly rate (£)", self.hourly_rate_var),
            ("Hours per complex point", self.hours_complex_var),
            ("Hours per simple point", self.hours_simple_var),
        )
        for row, (label, variable) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w",
                                             padx=(8, 2), pady=3)
            entry = ttk.Entry(form, textvariable=variable, width=16)
            entry.grid(row=row, column=1, sticky="ew", padx=(2, 8), pady=3)
        form.columnconfigure(1, weight=1)

        # Buttons for working with people.
        buttons = ttk.Frame(left)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        self.add_person_button = ttk.Button(buttons, text="Add person",
                                            command=self.add_person)
        self.update_person_button = ttk.Button(buttons, text="Update",
                                               command=self.update_person)
        self.remove_person_button = ttk.Button(buttons, text="Remove",
                                               command=self.remove_person)
        self.add_person_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.update_person_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.remove_person_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        for column in range(3):
            buttons.columnconfigure(column, weight=1)

    def _build_tasks_panel(self):
        """Right side: the selected person's tasks, totals and the task form."""
        right = ttk.LabelFrame(self.root, text=" Tasks ")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self.tasks_heading = ttk.Label(right, anchor="w",
                                       text="Select or add a person to see their tasks.")
        self.tasks_heading.grid(row=0, column=0, columnspan=2, sticky="ew",
                                padx=8, pady=(4, 2))

        # The table of the selected person's tasks.  Selecting a row loads
        # it into the task form so it can be edited.
        columns = ("task", "type", "points", "hours", "cost")
        self.task_tree = ttk.Treeview(right, columns=columns, show="headings", height=9)
        headings = (
            ("task", "Task", 240, "w"),
            ("type", "Type", 90, "center"),
            ("points", "Function points", 120, "e"),
            ("hours", "Hours", 90, "e"),
            ("cost", "Cost (£)", 100, "e"),
        )
        for column_id, text, width, anchor in headings:
            self.task_tree.heading(column_id, text=text)
            self.task_tree.column(column_id, width=width, anchor=anchor)
        task_scroll = ttk.Scrollbar(right, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=task_scroll.set)
        self.task_tree.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=4)
        task_scroll.grid(row=1, column=1, sticky="ns", pady=4)
        self.task_tree.bind("<<TreeviewSelect>>", self._on_task_selected)

        # The form for adding or editing one task.  The drop-down chooses
        # whether the task is complex or simple, and the points box below
        # asks for whichever kind of function points was chosen.
        task_form = ttk.LabelFrame(right, text=" Task details ")
        task_form.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=4)

        ttk.Label(task_form, text="Task name").grid(row=0, column=0, sticky="w",
                                                    padx=(8, 2), pady=3)
        self.task_name_entry = ttk.Entry(task_form, textvariable=self.task_name_var,
                                         width=22)
        self.task_name_entry.grid(row=0, column=1, sticky="ew", padx=(2, 8), pady=3)

        ttk.Label(task_form, text="Task type").grid(row=1, column=0, sticky="w",
                                                    padx=(8, 2), pady=3)
        self.task_type_combo = ttk.Combobox(task_form, textvariable=self.task_type_var,
                                            state="readonly", width=20,
                                            values=("Complex", "Simple"))
        self.task_type_combo.grid(row=1, column=1, sticky="ew", padx=(2, 8), pady=3)
        self.task_type_combo.bind("<<ComboboxSelected>>", self._on_task_type_chosen)

        # This label changes its text when the drop-down above changes.
        self.task_points_label = ttk.Label(task_form, text="Complex function points")
        self.task_points_label.grid(row=2, column=0, sticky="w", padx=(8, 2), pady=3)
        self.task_points_entry = ttk.Entry(task_form, textvariable=self.task_points_var,
                                           width=22)
        self.task_points_entry.grid(row=2, column=1, sticky="ew", padx=(2, 8), pady=3)
        task_form.columnconfigure(1, weight=1)

        task_buttons = ttk.Frame(task_form)
        task_buttons.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
        self.add_task_button = ttk.Button(task_buttons, text="Add task",
                                          command=self.add_task)
        self.update_task_button = ttk.Button(task_buttons, text="Update task",
                                             command=self.update_task)
        self.remove_task_button = ttk.Button(task_buttons, text="Remove task",
                                             command=self.remove_task)
        self.clear_task_button = ttk.Button(task_buttons, text="Clear form",
                                            command=self.clear_task_form)
        self.add_task_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.update_task_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.remove_task_button.grid(row=0, column=2, sticky="ew", padx=4)
        self.clear_task_button.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        for column in range(4):
            task_buttons.columnconfigure(column, weight=1)

        # The two totals boxes along the bottom.
        totals_frame = ttk.Frame(right)
        totals_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        person_box = ttk.LabelFrame(totals_frame, text=" Selected person ")
        person_box.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        project_box = ttk.LabelFrame(totals_frame, text=" Whole project ")
        project_box.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        totals_frame.columnconfigure(0, weight=1)
        totals_frame.columnconfigure(1, weight=1)
        self.person_totals_label = ttk.Label(person_box, justify="left",
                                             padding=6, text="No person selected.")
        self.person_totals_label.pack(anchor="w")
        self.project_totals_label = ttk.Label(project_box, justify="left",
                                              padding=6, text="No people yet.")
        self.project_totals_label.pack(anchor="w")

    # ------------------------------------------------------------------
    # People buttons
    # ------------------------------------------------------------------

    def add_person(self):
        """Read the person form, check it, and add the person to the project."""
        try:
            person = self._read_person_form()
        except ValueError as error:
            messagebox.showerror("Check the person details", str(error), parent=self.root)
            return
        clash = self._name_already_used(person["name"])
        if clash:
            messagebox.showerror(
                "Name already used",
                f"A person called '{clash}' is already in the project.\n"
                f"Please choose a different name or initials.",
                parent=self.root)
            return
        self.people.append(person)
        self.dirty = True
        self._refresh_all(select_person=len(self.people) - 1)
        self._say(f"Added '{person['name']}'. Now add their tasks on the right.")

    def update_person(self):
        """Save the changes typed in the person form back to the selected person."""
        index = self._selected_person_index()
        if index is None:
            messagebox.showinfo("No person selected",
                                "Select a person in the list on the left first.",
                                parent=self.root)
            return
        try:
            person = self._read_person_form()
        except ValueError as error:
            messagebox.showerror("Check the person details", str(error), parent=self.root)
            return
        clash = self._name_already_used(person["name"], ignore_index=index)
        if clash:
            messagebox.showerror(
                "Name already used",
                f"A person called '{clash}' is already in the project.\n"
                f"Please choose a different name or initials.",
                parent=self.root)
            return
        person["tasks"] = self.people[index]["tasks"]   # keep their tasks
        self.people[index] = person
        self.dirty = True
        self._refresh_all(select_person=index)
        self._say(f"Updated '{person['name']}' - hours and costs recalculated.")

    def remove_person(self):
        """Remove the selected person (and their tasks), after confirming."""
        index = self._selected_person_index()
        if index is None:
            messagebox.showinfo("No person selected",
                                "Select a person in the list on the left first.",
                                parent=self.root)
            return
        person = self.people[index]
        question = (f"Remove '{person['name']}' and their "
                    f"{len(person['tasks'])} task(s)?\n\nThis cannot be undone.")
        if not messagebox.askyesno("Remove person", question, parent=self.root):
            return
        self.people.pop(index)
        self.editing_task_index = None
        self.dirty = True
        if not self.people:
            self._clear_person_form()
        self._refresh_all()
        self._say(f"Removed '{person['name']}'.")

    # ------------------------------------------------------------------
    # Task buttons
    # ------------------------------------------------------------------

    def add_task(self):
        """Read the task form, check it, and add the task to the selected person."""
        person = self._selected_person()
        if person is None:
            messagebox.showinfo("No person selected",
                                "Add or select a person first - every task belongs "
                                "to a person.", parent=self.root)
            return
        try:
            task = self._read_task_form()
        except ValueError as error:
            messagebox.showerror("Check the task details", str(error), parent=self.root)
            return
        person["tasks"].append(task)
        self.editing_task_index = None
        self.dirty = True
        self._refresh_all(select_person=self._selected_person_index())
        self._say(f"Added {task['type']} task '{task['name']}' to '{person['name']}'.")

    def update_task(self):
        """Save the changes typed in the task form back to the selected task."""
        person = self._selected_person()
        if person is None:
            messagebox.showinfo("No person selected",
                                "Select a person on the left first.",
                                parent=self.root)
            return
        if self.editing_task_index is None:
            messagebox.showinfo("No task selected",
                                "Click a task in the table first, then change the "
                                "values here.", parent=self.root)
            return
        try:
            task = self._read_task_form()
        except ValueError as error:
            messagebox.showerror("Check the task details", str(error), parent=self.root)
            return
        index = self.editing_task_index
        person["tasks"][index] = task
        self.dirty = True
        self._refresh_all(select_person=self._selected_person_index(),
                          select_task=index)
        self._say(f"Updated task '{task['name']}'.")

    def remove_task(self):
        """Remove the task selected in the table."""
        person = self._selected_person()
        if person is None:
            messagebox.showinfo("No person selected",
                                "Select a person on the left first.",
                                parent=self.root)
            return
        if self.editing_task_index is None:
            messagebox.showinfo("No task selected",
                                "Click the task you want to remove in the table "
                                "first.", parent=self.root)
            return
        index = self.editing_task_index
        removed = person["tasks"].pop(index)
        self.editing_task_index = None
        self.dirty = True
        self._refresh_all(select_person=self._selected_person_index())
        self._say(f"Removed task '{removed['name']}' from '{person['name']}'.")

    def clear_task_form(self):
        """Empty the task form ready for typing a brand-new task."""
        self.editing_task_index = None
        self.task_tree.selection_remove(*self.task_tree.selection())
        self._clear_task_form_vars()

    # ------------------------------------------------------------------
    # File menu
    # ------------------------------------------------------------------

    def new_project(self):
        """Clear everything and start again from an empty project."""
        if not self._confirm_discard("start a new project"):
            return
        self.people = []
        self.current_file = None
        self.dirty = False
        self.editing_task_index = None
        self._clear_person_form()
        self._clear_task_form_vars()
        self._refresh_all()
        self._say("Started a new, empty project.")

    def open_project(self):
        """Load people and tasks from a JSON project file."""
        if not self._confirm_discard("open a different project"):
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Open a project file",
            filetypes=[("Project files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            people = fp_logic.load_project(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not open the project", str(error),
                                 parent=self.root)
            return
        self.people = people
        self.current_file = path
        self.dirty = False
        self.editing_task_index = None
        self._refresh_all(select_person=0 if self.people else None)
        self._say(f"Loaded {len(self.people)} person(s) from '{Path(path).name}'.")

    def save_project(self):
        """Save to the current file (asking for a name if there isn't one yet)."""
        if self.current_file is None:
            return self.save_project_as()
        try:
            fp_logic.save_project(self.people, self.current_file)
        except OSError as error:
            messagebox.showerror("Could not save the project", str(error),
                                 parent=self.root)
            return False
        self.dirty = False
        self._refresh_title()
        self._say(f"Project saved to '{Path(self.current_file).name}'.")
        return True

    def save_project_as(self):
        """Ask for a file name, then save the project there."""
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save the project as",
            defaultextension=".json", initialfile="function_point_project.json",
            filetypes=[("Project files", "*.json"), ("All files", "*.*")])
        if not path:
            return False
        self.current_file = path
        return self.save_project()

    def export_csv(self):
        """Export one row per task as a CSV file for spreadsheets/ProjectLibre."""
        if not self._require_people():
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export task estimates as CSV",
            defaultextension=".csv", initialfile="function_point_estimates.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            fp_logic.export_csv(self.people, path)
        except OSError as error:
            messagebox.showerror("Could not export the CSV file", str(error),
                                 parent=self.root)
            return
        self._say(f"CSV exported to '{Path(path).name}' - one row per task.")

    def export_report(self):
        """Export a readable text report of the whole project."""
        if not self._require_people():
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export a text report",
            defaultextension=".txt", initialfile="function_point_report.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            fp_logic.export_report(self.people, path)
        except OSError as error:
            messagebox.showerror("Could not export the report", str(error),
                                 parent=self.root)
            return
        self._say(f"Text report exported to '{Path(path).name}'.")

    # ------------------------------------------------------------------
    # Help and closing
    # ------------------------------------------------------------------

    def show_about(self):
        messagebox.showinfo(
            "How the estimates are calculated",
            "Simple Function Point Calculator\n\n"
            "Each task belongs to a person, is either complex or simple, and\n"
            "uses that person's settings:\n\n"
            "  complex task hours = complex function points\n"
            "                      x hours per complex point\n"
            "  simple task hours  = simple function points\n"
            "                      x hours per simple point\n"
            "  labour cost        = task hours x hourly rate\n\n"
            "Person totals add up that person's tasks, and the project totals\n"
            "add up every person.",
            parent=self.root)

    def _on_close(self):
        if not self._confirm_discard("close the program"):
            return
        self.root.destroy()

    # ------------------------------------------------------------------
    # Reading and checking the forms
    # ------------------------------------------------------------------

    def _read_person_form(self):
        """Check the person form and return a new person dictionary.

        Raises ValueError with a friendly message if anything is wrong.
        """
        name = self.person_name_var.get().strip()
        if not name:
            raise ValueError("Please type a name or initials for the person.")
        hourly_rate = fp_logic.parse_positive_number(
            self.hourly_rate_var.get(), "Hourly rate")
        hours_per_complex = fp_logic.parse_positive_number(
            self.hours_complex_var.get(), "Hours per complex function point")
        hours_per_simple = fp_logic.parse_positive_number(
            self.hours_simple_var.get(), "Hours per simple function point")
        return fp_logic.make_person(name, hourly_rate,
                                     hours_per_complex, hours_per_simple)

    def _read_task_form(self):
        """Check the task form and return a new task dictionary.

        Raises ValueError with a friendly message if anything is wrong.
        """
        name = self.task_name_var.get().strip()
        if not name:
            raise ValueError("Please type a name for the task.")
        task_type = self.task_type_var.get().strip().lower()
        if task_type not in fp_logic.TASK_TYPES:
            raise ValueError("Please choose Complex or Simple as the task type.")
        points = fp_logic.parse_point_count(
            self.task_points_var.get(), f"{task_type.capitalize()} function points")
        return fp_logic.make_task(name, task_type, points)

    def _name_already_used(self, name, ignore_index=None):
        """Return the existing person's name if 'name' is already taken."""
        for index, person in enumerate(self.people):
            if index != ignore_index and person["name"].lower() == name.lower():
                return person["name"]
        return None

    def _require_people(self):
        """Guards the exports: there must be at least one person."""
        if not self.people:
            messagebox.showinfo("Nothing to export",
                                "Add or load at least one person before exporting.",
                                parent=self.root)
            return False
        return True

    def _confirm_discard(self, action):
        """Check whether unsaved changes can be thrown away.

        Offers to save first: 'Yes' saves and carries on, 'No' carries on
        without saving, 'Cancel' stops whatever started this question.
        """
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            f"You have unsaved changes.\n\nSave them before you {action}?",
            parent=self.root)
        if answer is None:            # Cancel
            return False
        if answer:                    # Yes - save first, then carry on
            return self.save_project()
        return True                   # No - throw the changes away

    # ------------------------------------------------------------------
    # Keeping the window in step with the data
    # ------------------------------------------------------------------

    def _selected_person_index(self):
        """The position of the selected person in the list, or None."""
        selection = self.people_list.curselection()
        return selection[0] if selection else None

    def _selected_person(self):
        """The person dictionary currently selected, or None."""
        index = self._selected_person_index()
        return self.people[index] if index is not None else None

    def _on_person_selected(self, event=None):
        """Runs when the user clicks a person in the list."""
        self.editing_task_index = None
        self._refresh_all()

    def _on_task_selected(self, event=None):
        """Runs when the user clicks a task in the table: fills in the form."""
        selection = self.task_tree.selection()
        person = self._selected_person()
        if not selection or person is None:
            return
        self.editing_task_index = int(selection[0])
        task = person["tasks"][self.editing_task_index]
        self.task_name_var.set(task["name"])
        self.task_type_var.set(task["type"].capitalize())
        self.task_points_var.set(str(task["points"]))
        self._on_task_type_chosen()   # keep the points label in step

    def _on_task_type_chosen(self, event=None):
        """Runs when the type drop-down changes: relabel the points box.

        Choosing 'Simple' makes the box ask for simple function points,
        and choosing 'Complex' makes it ask for complex function points.
        """
        chosen = self.task_type_var.get()
        self.task_points_label.configure(text=f"{chosen} function points")

    def _refresh_all(self, select_person=None, select_task=None):
        """Rebuild every part of the window from self.people."""
        if select_person is None:
            select_person = self._selected_person_index()
        self._refresh_people_list(select_person)
        self._refresh_person_form()
        self._refresh_tasks(select_task)
        self._refresh_totals()
        self._refresh_task_form_state()
        self._refresh_title()

    def _refresh_people_list(self, select_index):
        self.people_list.delete(0, tk.END)
        for person in self.people:
            count = len(person["tasks"])
            task_word = "task" if count == 1 else "tasks"
            self.people_list.insert(
                tk.END, f"{person['name']}  ({count} {task_word})")
        if select_index is not None and 0 <= select_index < len(self.people):
            self.people_list.selection_set(select_index)
            self.people_list.see(select_index)

    def _refresh_person_form(self):
        person = self._selected_person()
        if person is None:
            return          # leave whatever the user is typing
        self.person_name_var.set(person["name"])
        self.hourly_rate_var.set(f"{person['hourly_rate']:g}")
        self.hours_complex_var.set(f"{person['hours_per_complex_point']:g}")
        self.hours_simple_var.set(f"{person['hours_per_simple_point']:g}")

    def _refresh_tasks(self, select_task=None):
        """Fill the task table with the selected person's tasks."""
        person = self._selected_person()
        self.task_tree.delete(*self.task_tree.get_children())
        if person is None:
            self.tasks_heading.configure(
                text="Select or add a person to see their tasks.")
            self.editing_task_index = None
            self._clear_task_form_vars()
            return

        count = len(person["tasks"])
        task_word = "task" if count == 1 else "tasks"
        self.tasks_heading.configure(
            text=f"Tasks for {person['name']} - {count} {task_word}")
        for index, task in enumerate(person["tasks"]):
            row = fp_logic.task_row(task, person)
            self.task_tree.insert("", tk.END, iid=str(index), values=(
                row["name"],
                row["type"].capitalize(),
                row["points"],
                f"{row['hours']:.2f}",
                f"{row['cost']:.2f}",
            ))

        if select_task is None:
            select_task = self.editing_task_index   # keep the same task selected
        if select_task is not None and 0 <= select_task < len(person["tasks"]):
            self.task_tree.selection_set(str(select_task))
            self.task_tree.see(str(select_task))
            # Selecting the row fires <<TreeviewSelect>>, which fills the form.
        else:
            self.editing_task_index = None
            self._clear_task_form_vars()

    def _refresh_totals(self):
        """Update the two totals boxes at the bottom right."""
        person = self._selected_person()
        if person is None:
            self.person_totals_label.configure(text="No person selected.")
        else:
            summary = fp_logic.person_totals(person)
            self.person_totals_label.configure(text=(
                f"Person: {summary['name']}\n"
                f"Tasks: {summary['task_count']}  "
                f"({summary['complex_points']} complex + "
                f"{summary['simple_points']} simple points)\n"
                f"Estimated hours: {summary['total_hours']:.2f}\n"
                f"Labour cost: {fp_logic.format_money(summary['total_cost'])}"))

        totals = fp_logic.project_totals(self.people)
        if not self.people:
            self.project_totals_label.configure(text="No people yet.")
        else:
            self.project_totals_label.configure(text=(
                f"People: {totals['person_count']}  Tasks: {totals['task_count']}\n"
                f"Function points: {totals['complex_points']} complex + "
                f"{totals['simple_points']} simple\n"
                f"Estimated hours: {totals['total_hours']:.2f}\n"
                f"Labour cost: {fp_logic.format_money(totals['total_cost'])}"))

    def _refresh_task_form_state(self):
        """The task form only makes sense once a person has been selected."""
        enabled = self._selected_person() is not None
        for entry in (self.task_name_entry, self.task_points_entry):
            entry.configure(state="normal" if enabled else "disabled")
        # A combobox is "readonly" when it can be used (only list values can
        # be picked) and "disabled" when it is greyed out.
        self.task_type_combo.configure(
            state="readonly" if enabled else "disabled")

    def _refresh_title(self):
        file_name = (Path(self.current_file).name if self.current_file
                     else "Untitled project")
        star = " *" if self.dirty else ""
        self.root.title(f"{file_name}{star} - Simple Function Point Calculator")

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _say(self, message):
        """Show a message in the status bar along the bottom."""
        self.status.configure(text=message)

    def _clear_person_form(self):
        for variable in (self.person_name_var, self.hourly_rate_var,
                         self.hours_complex_var, self.hours_simple_var):
            variable.set("")

    def _clear_task_form_vars(self):
        self.task_name_var.set("")
        self.task_points_var.set("")
        # Keep the chosen type so several similar tasks can be added in a
        # row, but make sure the points label matches it.
        self._on_task_type_chosen()


def main():
    if tk is None:
        sys.exit("Tkinter is missing, so the window cannot open.\n"
                 "On Linux, install it with:  sudo apt install python3-tk")
    root = tk.Tk()
    FunctionPointApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
