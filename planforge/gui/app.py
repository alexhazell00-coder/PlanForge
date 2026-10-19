"""The PlanForge desktop window.

The window owns the shared ``ProjectSession``, the active theme palette, the
menus and toolbar, and the tabs. Every project change goes through
``perform()``, which shows any ``SessionError`` in a message box and then
refreshes all views.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from planforge.config import THEMES, get_theme_setting, set_theme_setting
from planforge.gui.dialogs import ExportDialog, ImportDialog
from planforge.gui.theme import apply_theme
from planforge.gui.timeline import TimelineView
from planforge.gui.views import (
    CostsView,
    EstimatorView,
    OverviewView,
    PeopleView,
    ReportView,
    SettingsView,
    TasksView,
)
from planforge.session import PFP_EXTENSION, ProjectSession, SessionError

VIEWS: list[tuple[str, str, type]] = [
    ("overview", "Overview", OverviewView),
    ("tasks", "Tasks", TasksView),
    ("timeline", "Timeline", TimelineView),
    ("people", "People", PeopleView),
    ("costs", "Costs & Workload", CostsView),
    ("estimates", "Function Points", EstimatorView),
    ("summary", "Summary Report", ReportView),
    ("settings", "Settings", SettingsView),
]


class PlanForgeApp(tk.Tk):
    def __init__(self, open_path: str | Path | None = None) -> None:
        super().__init__()
        self.title("PlanForge")
        self.geometry("1280x820")
        self.minsize(980, 640)

        self.theme_name = get_theme_setting()
        self.palette = apply_theme(self, self.theme_name)
        self.session = ProjectSession()

        self._build_menu()
        self._build_toolbar()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.views: dict[str, Any] = {}
        for key, label, view_class in VIEWS:
            view = view_class(self.notebook, self)
            self.notebook.add(view, text=label)
            self.views[key] = view
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.status_var = tk.StringVar()
        status = ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel", padding=(10, 4))
        status.pack(fill="x", side="bottom")

        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        if open_path is not None:
            self.open_project_file(open_path, ask_discard=False)
        self.refresh_all()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Project", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_project)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import…", accelerator="Ctrl+I", command=self.import_project)
        file_menu.add_command(label="Export…", accelerator="Ctrl+E", command=self.export_project)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Recalculate Schedule", accelerator="F5", command=self.recalculate)
        view_menu.add_command(label="Toggle Light/Dark Theme", accelerator="Ctrl+T", command=self.toggle_theme)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About PlanForge", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="PlanForge", style="Title.TLabel").pack(side="left", padx=(0, 16))
        buttons = [
            ("New", self.new_project),
            ("Open", self.open_project),
            ("Save", self.save_project),
            ("Import", self.import_project),
            ("Export", self.export_project),
            ("Recalculate", self.recalculate),
        ]
        for text, command in buttons:
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(0, 6))
        self.theme_button = ttk.Button(bar, text="", command=self.toggle_theme)
        self.theme_button.pack(side="right")
        self._update_theme_button()

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-n>", lambda _e: self.new_project())
        self.bind("<Control-o>", lambda _e: self.open_project())
        self.bind("<Control-s>", lambda _e: self.save_project())
        self.bind("<Control-S>", lambda _e: self.save_project_as())
        self.bind("<Control-i>", lambda _e: self.import_project())
        self.bind("<Control-e>", lambda _e: self.export_project())
        self.bind("<Control-q>", lambda _e: self.quit_app())
        self.bind("<Control-t>", lambda _e: self.toggle_theme())
        self.bind("<F5>", lambda _e: self.recalculate())
        for index in range(len(VIEWS)):
            self.bind(f"<Control-Key-{index + 1}>", lambda _e, i=index: self._select_tab(i))

    # ------------------------------------------------------------------
    # Running actions
    # ------------------------------------------------------------------

    def perform(self, action: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        """Run a session change. On success refresh every view; on error show a message."""
        try:
            action(*args, **kwargs)
        except SessionError as exc:
            messagebox.showerror("PlanForge", str(exc), parent=self)
            return False
        self.refresh_all()
        return True

    def refresh_all(self) -> None:
        for view in self.views.values():
            view.refresh()
        self._update_title()
        self._update_status()

    def _select_tab(self, index: int) -> None:
        if 0 <= index < len(VIEWS):
            self.notebook.select(index)

    def _on_tab_changed(self, _event: Any = None) -> None:
        current = self.notebook.select()
        for key, _label, _cls in VIEWS:
            if str(self.views[key]) == current:
                self.views[key].on_show()
                break

    # ------------------------------------------------------------------
    # Title and status
    # ------------------------------------------------------------------

    def _update_title(self) -> None:
        name = self.session.project.name
        marker = " *" if self.session.dirty else ""
        self.title(f"{name}{marker} – PlanForge")

    def _update_status(self) -> None:
        p = self.session.project
        location = str(self.session.file_path) if self.session.file_path else "Not saved to a file yet"
        unsaved = "Unsaved changes" if self.session.dirty else "All changes saved"
        finish = p.finish_date.isoformat() if p.finish_date else "not scheduled"
        self.status_var.set(
            f"{location}   ·   {len(p.tasks)} tasks   ·   finish {finish}   ·   {unsaved}"
        )

    def _update_theme_button(self) -> None:
        other = "Dark" if self.theme_name == "light" else "Light"
        self.theme_button.configure(text=f"{other} theme")

    # ------------------------------------------------------------------
    # File and project actions
    # ------------------------------------------------------------------

    def confirm_discard(self) -> bool:
        """Return True if it is safe to replace the open project."""
        if not self.session.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            f"Save changes to '{self.session.project.name}' before continuing?",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if self.confirm_discard():
            self.perform(self.session.new_project)

    def open_project(self) -> None:
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, title="Open PlanForge project", filetypes=[
            ("PlanForge projects", f"*{PFP_EXTENSION}"),
            ("All files", "*.*"),
        ])
        if path:
            self.open_project_file(path, ask_discard=False)

    def open_project_file(self, path: str | Path, *, ask_discard: bool = True) -> None:
        if ask_discard and not self.confirm_discard():
            return
        self.perform(self.session.open_pfp, path)

    def save_project(self) -> bool:
        if self.session.file_path is None:
            return self.save_project_as()
        return self._save_to(self.session.file_path)

    def save_project_as(self) -> bool:
        default = self.session.project.name.replace(" ", "_").replace("/", "_") + PFP_EXTENSION
        path = filedialog.asksaveasfilename(parent=self, title="Save PlanForge project", defaultextension=PFP_EXTENSION,
                                            initialfile=default,
                                            filetypes=[("PlanForge projects", f"*{PFP_EXTENSION}")])
        if not path:
            return False
        return self._save_to(path)

    def _save_to(self, path: str | Path) -> bool:
        try:
            self.session.save(path)
        except SessionError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self.refresh_all()
        return True

    def import_project(self) -> None:
        if not self.confirm_discard():
            return
        dialog = ImportDialog(self, self.session)
        if dialog.show():
            self.refresh_all()

    def export_project(self) -> None:
        dialog = ExportDialog(self, self.session)
        dialog.show()

    def recalculate(self) -> None:
        self.perform(self.session.recalculate)

    def toggle_theme(self) -> None:
        new_theme = THEMES[1] if self.theme_name == THEMES[0] else THEMES[0]
        try:
            set_theme_setting(new_theme)
        except OSError:
            pass  # the theme still applies for this session even if it cannot be saved
        self.theme_name = new_theme
        self.palette = apply_theme(self, new_theme)
        self._update_theme_button()
        self.refresh_all()

    def show_about(self) -> None:
        messagebox.showinfo(
            "About PlanForge",
            "PlanForge – Project Planner and Interoperability Engine.\n\n"
            "Runs as a desktop application with no web server or browser.",
            parent=self,
        )

    def quit_app(self) -> None:
        if self.confirm_discard():
            self.destroy()


def run(open_path: str | Path | None = None) -> None:
    """Start the desktop application and block until the window is closed."""
    app = PlanForgeApp(open_path)
    app.mainloop()


__all__ = ["PlanForgeApp", "VIEWS", "run"]
