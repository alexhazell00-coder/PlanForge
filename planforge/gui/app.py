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
from planforge.gui.convert_view import ConvertView
from planforge.gui.dialogs import ExportDialog, ImportDialog
from planforge.gui.help_view import HelpView
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
    ("convert", "Convert", ConvertView),
    ("summary", "Summary Report", ReportView),
    ("settings", "Settings", SettingsView),
    ("help", "Help", HelpView),
]


class PlanForgeApp(tk.Tk):
    def __init__(self, open_path: str | Path | None = None) -> None:
        super().__init__()
        self.title("PlanForge")
        self.geometry("1320x860")
        self.minsize(1020, 680)

        self.theme_name = get_theme_setting()
        self.palette = apply_theme(self, self.theme_name)
        self.session = ProjectSession()

        # Expose VIEWS on instance for views to navigate (HelpView etc.)
        self.VIEWS = VIEWS

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
        file_menu.add_command(label="Quick Convert…", accelerator="Ctrl+Shift+C", command=self.quick_convert)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Recalculate Schedule", accelerator="F5", command=self.recalculate)
        view_menu.add_command(label="Toggle Light/Dark Theme", accelerator="Ctrl+T", command=self.toggle_theme)
        view_menu.add_separator()
        for idx, (key, label, _cls) in enumerate(VIEWS):
            acc = f"Ctrl+{idx+1}" if idx < 9 else ("Ctrl+0" if idx == 9 else "")
            view_menu.add_command(label=f"Show {label}", accelerator=acc, command=lambda i=idx: self._select_tab(i))
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="User Guide (Help tab)", accelerator="F1", command=self.open_help)
        help_menu.add_command(label="Keyboard Shortcuts", accelerator="Ctrl+K", command=self.show_shortcuts)
        help_menu.add_command(label="File Conversion Help", command=self.open_convert_help)
        help_menu.add_separator()
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
        # Prominent convert button
        self.convert_button = ttk.Button(bar, text="Quick Convert ▶", style="Accent.TButton", command=self.quick_convert)
        self.convert_button.pack(side="left", padx=(12, 6))
        # Help button
        ttk.Button(bar, text="Help", command=self.open_help).pack(side="left", padx=(0, 6))
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
        self.bind("<Control-C>", lambda _e: self.quick_convert())
        self.bind("<Control-q>", lambda _e: self.quit_app())
        self.bind("<Control-t>", lambda _e: self.toggle_theme())
        self.bind("<Control-k>", lambda _e: self.show_shortcuts())
        self.bind("<F1>", lambda _e: self.open_help())
        self.bind("<F5>", lambda _e: self.recalculate())
        # Bind Ctrl+1..9 and Ctrl+0 for 10 tabs (0 = 10th)
        for index in range(min(len(VIEWS), 9)):
            self.bind(f"<Control-Key-{index + 1}>", lambda _e, i=index: self._select_tab(i))
        if len(VIEWS) >= 10:
            self.bind("<Control-Key-0>", lambda _e: self._select_tab(9))
        # Also handle Ctrl+Shift+C for quick convert (already bound via Control-C upper)

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
            try:
                view.refresh()
            except Exception:
                # Don't let one broken view prevent others - show in status
                pass
        self._update_title()
        self._update_status()

    def _select_tab(self, index: int) -> None:
        if 0 <= index < len(VIEWS):
            self.notebook.select(index)

    def select_tab_by_key(self, key: str) -> bool:
        """Select a tab by its key (e.g. 'convert', 'help'). Returns True if found."""
        for idx, (k, _label, _cls) in enumerate(VIEWS):
            if k == key:
                self.notebook.select(idx)
                return True
        return False

    def _on_tab_changed(self, _event: Any = None) -> None:
        current = self.notebook.select()
        for key, _label, _cls in VIEWS:
            if str(self.views[key]) == current:
                try:
                    self.views[key].on_show()
                except Exception:
                    pass
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

    def quick_convert(self) -> None:
        """Jump to the Convert tab — the easiest way to convert formats."""
        if self.select_tab_by_key("convert"):
            # Give immediate feedback that the button worked (status bar updates, preview refreshes via tab change)
            try:
                cv = self.views.get("convert")
                if cv and hasattr(cv, "status_var"):
                    cv.status_var.set("Convert tab ready — Current project is pre-selected. Choose target format and click Convert.")
            except Exception:
                pass

    def open_help(self) -> None:
        if self.select_tab_by_key("help"):
            try:
                hv = self.views.get("help")
                if hv and hasattr(hv, "status_var"):
                    pass  # help tab has its own status
            except Exception:
                pass

    def open_convert_help(self) -> None:
        # Go to help then filter to convert section if possible
        if self.select_tab_by_key("help"):
            # Try to select convert section in help view
            try:
                hv = self.views.get("help")
                if hv and hasattr(hv, "_show_section"):
                    hv._show_section("convert")
                    # Also select in nav list
                    if hasattr(hv, "_filtered"):
                        for idx, (sid, _title) in enumerate(hv._filtered):
                            if sid == "convert":
                                hv.nav_list.selection_clear(0, "end")
                                hv.nav_list.selection_set(idx)
                                hv.nav_list.see(idx)
                                break
            except Exception:
                pass
        else:
            self.show_about()

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

    def show_shortcuts(self) -> None:
        # Show as dialog, or jump to help shortcuts section
        # Prefer help tab if available
        if "help" in self.views:
            self.open_help()
            try:
                hv = self.views["help"]
                hv._show_section("menus_toolbar")
                if hasattr(hv, "_filtered"):
                    for idx, (sid, _title) in enumerate(hv._filtered):
                        if sid == "menus_toolbar":
                            hv.nav_list.selection_clear(0, "end")
                            hv.nav_list.selection_set(idx)
                            hv.nav_list.see(idx)
                            break
                return
            except Exception:
                pass
        # Fallback dialog
        win = tk.Toplevel(self)
        win.title("Keyboard Shortcuts")
        win.transient(self)
        win.geometry("560x420")
        txt = tk.Text(win, wrap="word", padx=12, pady=12, font=("Helvetica", 10))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        content = (
            "PlanForge Keyboard Shortcuts\n============================\n\n"
            "File:\n"
            "  Ctrl+N  New Project\n"
            "  Ctrl+O  Open…\n"
            "  Ctrl+S  Save\n"
            "  Ctrl+Shift+S  Save As…\n"
            "  Ctrl+I  Import…\n"
            "  Ctrl+E  Export…\n"
            "  Ctrl+Shift+C  Quick Convert\n"
            "  Ctrl+Q  Quit\n\n"
            "View:\n"
            "  F5      Recalculate Schedule\n"
            "  Ctrl+T  Toggle Light/Dark Theme\n"
            "  Ctrl+1..Ctrl+0  Jump to tabs 1-10\n"
            "  F1      User Guide\n"
            "  Ctrl+K  This shortcuts help\n\n"
            "Tasks tab:\n"
            "  Double-click or Enter  Edit task\n"
            "  Delete                 Delete task\n"
            "  Type in search box     Filter tasks live\n"
        )
        txt.insert("1.0", content)
        txt.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)
        win.grab_set()

    def show_about(self) -> None:
        messagebox.showinfo(
            "About PlanForge",
            (
                "PlanForge — Project Planner & Schedule Manager\n\n"
                "Offline, no server, no browser. Everything runs in one Python process.\n\n"
                "• Create tasks, dependencies & critical path\n"
                "• Assign people with rates → costs & workload\n"
                "• Estimate with function points\n"
                "• Import/Export: Microsoft Project XML (.xml), GanttProject (.gan),\n"
                "  CSV (.csv), PlanForge JSON (.json), SQLite (.pfp), FP Calculator\n"
                "• Convert tab gives you one-click conversion with validation\n"
                "• Help tab explains every tab and button\n\n"
                "Launcher: PlanForgeLauncher.py detects OS, creates .venv and starts the app.\n"
                "Docs: README.md, docs/launcher.md, docs/interoperability.md\n"
                "Theme: Ctrl+T toggles Light/Dark (saved in ~/.config/PlanForge/PlanForge.conf)\n\n"
                "Tip: Press F1 for the full User Guide, or Ctrl+K for shortcuts."
            ),
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
