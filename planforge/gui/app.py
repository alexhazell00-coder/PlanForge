"""The PlanForge desktop window.

The window owns the shared ``ProjectSession``, the active theme palette, the
menus and toolbar, and the tabs. Every project change goes through
``perform()``, which shows any ``SessionError`` in a message box and then
refreshes all views.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from planforge.config import (
    THEMES,
    clear_recent_projects,
    delete_workspace_layout,
    format_date,
    get_preference,
    get_recent_projects,
    get_shortcut_keys,
    get_theme_setting,
    get_workspace_layouts,
    remember_recent_project,
    set_theme_setting,
    set_workspace_layout,
)
from planforge.gui.appearance import AppearanceManagerDialog
from planforge.gui.convert_view import ConvertView
from planforge.gui.dialogs import ExportDialog, ImportDialog
from planforge.gui.help_view import HelpView
from planforge.gui.preferences import PreferencesDialog
from planforge.gui.recovery_dialog import RecoveryDialog
from planforge.gui.theme import apply_palette, palette_for, system_theme_name
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
from planforge.icons import apply_window_icon, configure_platform_app_identity
from planforge.session import PFP_EXTENSION, ProjectSession, SessionError
from planforge.recovery import clear_recovery_snapshot, list_recovery_snapshots, save_recovery_snapshot
from planforge.theme_library import list_installed_themes

TK_MODIFIER = "Command" if sys.platform == "darwin" else "Control"
SHORTCUT_MODIFIER = "⌘" if sys.platform == "darwin" else "Ctrl+"


def _shortcut(key: str, *, shift: bool = False) -> str:
    return f"{SHORTCUT_MODIFIER}{'Shift+' if shift else ''}{key}"


VIEWS: list[tuple[str, str, type]] = [
    ("overview", "Overview", OverviewView),
    ("tasks", "Tasks", TasksView),
    ("timeline", "Timeline", TimelineView),
    ("people", "People & Materials", PeopleView),
    ("costs", "Costs & Workload", CostsView),
    ("estimates", "Function Points", EstimatorView),
    ("convert", "Convert", ConvertView),
    ("summary", "Summary Report", ReportView),
    ("settings", "Settings", SettingsView),
    ("help", "Help", HelpView),
]


class PlanForgeApp(tk.Tk):
    def __init__(self, open_path: str | Path | None = None) -> None:
        configure_platform_app_identity()
        super().__init__(className="PlanForge")
        self.title("PlanForge")
        self.geometry("1320x860")
        self.minsize(1020, 680)
        apply_window_icon(self)

        self.theme_name = get_theme_setting()
        initial_palette = self._theme_palette(self.theme_name)
        if initial_palette is None:
            self.theme_name = "light"
            initial_palette = palette_for("light")
        self.theme_var = tk.StringVar(value=self.theme_name)
        self.palette = apply_palette(self, initial_palette)
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
        self._schedule_recovery()
        self.after_idle(self._check_recovery)

    @staticmethod
    def _theme_palette(theme_id: str) -> dict[str, str] | None:
        if theme_id == "system":
            return palette_for(system_theme_name())
        if theme_id in THEMES:
            return palette_for(theme_id)
        if not theme_id.startswith("custom-"):
            return None
        themes, _warnings = list_installed_themes()
        item = next((theme for theme in themes if theme["id"] == theme_id), None)
        return dict(item["palette"]) if item else None

    def _theme_title(self, theme_id: str) -> str:
        if theme_id == "system":
            return f"System ({system_theme_name().title()})"
        if theme_id in THEMES:
            return theme_id.replace("_", " ").title()
        themes, _warnings = list_installed_themes()
        item = next((theme for theme in themes if theme["id"] == theme_id), None)
        return item["name"] if item else "Light"

    def _shortcut_key(self, action: str) -> str:
        return get_shortcut_keys().get(action, {"new": "N", "open": "O", "save": "S", "undo": "Z", "redo": "Y"}.get(action, ""))

    def _shortcut_accelerator(self, action: str, *, shift: bool = False) -> str:
        return f"{SHORTCUT_MODIFIER}{'Shift+' if shift else ''}{self._shortcut_key(action)}"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        previous_menu = getattr(self, "_menubar", None)
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Project", accelerator=self._shortcut_accelerator("new"), command=self.new_project)
        file_menu.add_command(label="Open…", accelerator=self._shortcut_accelerator("open"), command=self.open_project)
        self.recent_menu = tk.Menu(file_menu, tearoff=False, postcommand=self._populate_recent_menu)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator=self._shortcut_accelerator("save"), command=self.save_project)
        file_menu.add_command(label="Save As…", accelerator=self._shortcut_accelerator("save", shift=True), command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import…", accelerator=_shortcut("I"), command=self.import_project)
        file_menu.add_command(label="Export…", accelerator=_shortcut("E"), command=self.export_project)
        file_menu.add_command(label="Quick Convert…", accelerator=_shortcut("C", shift=True), command=self.quick_convert)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator=_shortcut("Q"), command=self.quit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        self.edit_menu = tk.Menu(menubar, tearoff=False)
        self.edit_menu.add_command(label="Undo", accelerator=self._shortcut_accelerator("undo"), command=self.undo)
        redo_accelerator = self._shortcut_accelerator("redo", shift=sys.platform == "darwin")
        self.edit_menu.add_command(label="Redo", accelerator=redo_accelerator, command=self.redo)
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Add Task", command=lambda: self._run_view_action("tasks", "_add"))
        self.edit_menu.add_command(label="Add Person…", command=lambda: self._run_view_action("people", "_add"))
        self.edit_menu.add_command(label="Add Material…", command=lambda: self._run_view_action("people", "_add_material"))
        menubar.add_cascade(label="Edit", menu=self.edit_menu)
        self._update_history_menu()

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Recalculate Schedule", accelerator="F5", command=self.recalculate)
        theme_menu = tk.Menu(view_menu, tearoff=False)
        for theme in THEMES:
            theme_menu.add_radiobutton(
                label=theme.replace("_", " ").title(),
                variable=self.theme_var,
                value=theme,
                command=lambda name=theme: self.set_theme(name),
            )
        theme_menu.add_separator()
        theme_menu.add_radiobutton(label="System Default", variable=self.theme_var, value="system",
                                   command=lambda: self.set_theme("system"))
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        view_menu.add_command(label="Manage Themes…", command=self.open_theme_manager)
        view_menu.add_command(label="Cycle Theme", accelerator=_shortcut("T"), command=self.toggle_theme)
        self.layout_menu = tk.Menu(view_menu, tearoff=False, postcommand=self._populate_layout_menu)
        view_menu.add_cascade(label="Workspace Layouts", menu=self.layout_menu)
        view_menu.add_separator()
        for idx, (key, label, _cls) in enumerate(VIEWS):
            acc = _shortcut(str(idx + 1)) if idx < 9 else (_shortcut("0") if idx == 9 else "")
            view_menu.add_command(label=f"Show {label}", accelerator=acc, command=lambda i=idx: self._select_tab(i))
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Command Palette…", accelerator=_shortcut("P", shift=True), command=self.show_command_palette)
        tools_menu.add_command(label="Preferences…", command=self.open_preferences)
        tools_menu.add_command(label="Function Point Calculator", command=lambda: self.select_tab_by_key("estimates"))
        tools_menu.add_command(label="Import / Export Tools", command=lambda: self.select_tab_by_key("convert"))
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="User Guide (Help tab)", accelerator="F1", command=self.open_help)
        help_menu.add_command(label="Keyboard Shortcuts", accelerator=_shortcut("K"), command=self.show_shortcuts)
        help_menu.add_command(label="File Conversion Help", command=self.open_convert_help)
        help_menu.add_separator()
        help_menu.add_command(label="About PlanForge", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menubar)
        self._menubar = menubar
        if previous_menu is not None:
            try:
                previous_menu.destroy()
            except tk.TclError:
                pass

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
            button = ttk.Button(bar, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            if text == "New":
                self.new_button = button
        # Prominent convert button
        self.convert_button = ttk.Button(bar, text="Quick Convert ▶", style="Accent.TButton", command=self.quick_convert)
        self.convert_button.pack(side="left", padx=(12, 6))
        # Help button
        ttk.Button(bar, text="Help", command=self.open_help).pack(side="left", padx=(0, 6))
        self.theme_button = ttk.Button(bar, text="", command=self.toggle_theme)
        self.theme_button.pack(side="right")
        self._update_theme_button()

    def _bind_shortcuts(self) -> None:
        # A binding on the Tk root widget itself only fires when that widget has
        # focus. Most input focus is in a child widget, so bind shortcuts at the
        # application level instead. Returning "break" prevents the focused
        # control from also handling the key (for example, Ctrl+N in a text box).
        for sequence in getattr(self, "_shortcut_sequences", []):
            self.unbind_all(sequence)
        self._shortcut_sequences: list[str] = []

        def bind(sequence: str, action: Callable[[], Any]) -> None:
            self._shortcut_sequences.append(sequence)
            self.bind_all(sequence, lambda _event: (action(), "break")[1])

        def bind_edit(sequence: str, action: Callable[[], Any]) -> None:
            self._shortcut_sequences.append(sequence)
            def dispatch(_event: Any) -> str | None:
                focused = self.focus_get()
                if focused is not None and focused.winfo_class() in {"Entry", "Text", "TEntry", "TCombobox", "TSpinbox"}:
                    return None  # leave standard text editing undo/redo to Tk
                action()
                return "break"
            self.bind_all(sequence, dispatch)

        bind_edit(f"<{TK_MODIFIER}-{self._shortcut_key('undo').lower()}>", self.undo)
        if sys.platform == "darwin":
            bind_edit(f"<Command-Shift-{self._shortcut_key('redo').lower()}>", self.redo)
        else:
            bind_edit(f"<Control-{self._shortcut_key('redo').lower()}>", self.redo)
        bind(f"<{TK_MODIFIER}-{self._shortcut_key('new').lower()}>", self.new_project)
        bind(f"<{TK_MODIFIER}-{self._shortcut_key('open').lower()}>", self.open_project)
        bind(f"<{TK_MODIFIER}-{self._shortcut_key('save').lower()}>", self.save_project)
        bind(f"<{TK_MODIFIER}-Shift-{self._shortcut_key('save').lower()}>", self.save_project_as)
        bind(f"<{TK_MODIFIER}-i>", self.import_project)
        bind(f"<{TK_MODIFIER}-e>", self.export_project)
        bind(f"<{TK_MODIFIER}-Shift-c>", self.quick_convert)
        bind(f"<{TK_MODIFIER}-q>", self.quit_app)
        bind(f"<{TK_MODIFIER}-t>", self.toggle_theme)
        bind(f"<{TK_MODIFIER}-k>", self.show_shortcuts)
        bind(f"<{TK_MODIFIER}-Shift-p>", self.show_command_palette)
        bind("<F1>", self.open_help)
        bind("<F5>", self.recalculate)
        # Bind modifier+1..9 and modifier+0 for 10 tabs (0 = 10th)
        for index in range(min(len(VIEWS), 9)):
            bind(f"<{TK_MODIFIER}-Key-{index + 1}>", lambda i=index: self._select_tab(i))
        if len(VIEWS) >= 10:
            bind(f"<{TK_MODIFIER}-Key-0>", lambda: self._select_tab(9))
        # Also handle Ctrl+Shift+C for quick convert (Control-C with Shift).

    # ------------------------------------------------------------------
    # Running actions
    # ------------------------------------------------------------------

    def perform(self, action: Callable[..., Any], *args: Any, show_errors: bool = True, **kwargs: Any) -> bool:
        """Run a session change. On success refresh every view; on error show a message."""
        previous_project_id = self.session.project.id
        try:
            action(*args, **kwargs)
        except SessionError as exc:
            if show_errors:
                messagebox.showerror("PlanForge", str(exc), parent=self)
            return False
        if self.session.project.id != previous_project_id:
            clear_recovery_snapshot(previous_project_id)
        elif getattr(action, "__name__", "") in {"undo", "redo"} and not self.session.dirty:
            clear_recovery_snapshot(self.session.project.id)
        self.refresh_all()
        return True

    def _commit_pending_settings(self, *, show_errors: bool = False) -> bool:
        settings_view = self.views.get("settings")
        if settings_view is not None and hasattr(settings_view, "commit_pending"):
            return bool(settings_view.commit_pending(show_errors=show_errors))
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
        self._update_history_menu()

    def _update_history_menu(self) -> None:
        menu = getattr(self, "edit_menu", None)
        if menu is None or not hasattr(self, "session"):
            return
        menu.entryconfigure(0, state="normal" if self.session.can_undo else "disabled")
        menu.entryconfigure(1, state="normal" if self.session.can_redo else "disabled")

    def _recovery_interval_ms(self) -> int:
        enabled = get_preference("recovery", "autosave_enabled", "true").casefold() not in ("false", "0", "no")
        if not enabled:
            return 0
        try:
            seconds = int(get_preference("recovery", "interval_seconds", "60"))
        except ValueError:
            seconds = 60
        return max(30, min(seconds, 3600)) * 1000

    def _schedule_recovery(self) -> None:
        pending = getattr(self, "_recovery_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass
        self._recovery_after_id = None
        interval = self._recovery_interval_ms()
        if interval:
            self._recovery_after_id = self.after(interval, self._autosave_recovery)

    def _autosave_recovery(self) -> None:
        self._recovery_after_id = None
        if not self.winfo_exists():
            return
        if self._recovery_interval_ms() and self.session.dirty:
            try:
                save_recovery_snapshot(self.session.project, self.session.file_path)
                self.status_var.set("Crash-recovery snapshot updated. Save Project still writes your project file.")
            except Exception as exc:
                self.status_var.set(f"Crash-recovery snapshot failed: {exc}")
        self._schedule_recovery()

    def _check_recovery(self) -> None:
        records, warnings = list_recovery_snapshots()
        if not records:
            if warnings:
                self.status_var.set(warnings[0])
            return
        dialog = RecoveryDialog(self, self, records, warnings)
        self.wait_window(dialog)

    def _populate_layout_menu(self) -> None:
        self.layout_menu.delete(0, "end")
        self.layout_menu.add_command(label="Save Current Layout…", command=self.save_workspace_layout)
        layouts = get_workspace_layouts()
        if layouts:
            self.layout_menu.add_separator()
            for name in sorted(layouts, key=str.casefold):
                self.layout_menu.add_command(label=name, command=lambda key=name: self.apply_workspace_layout(key))
            self.layout_menu.add_separator()
            self.layout_menu.add_command(label="Remove Saved Layout…", command=self.remove_workspace_layout)

    def save_workspace_layout(self) -> None:
        name = simpledialog.askstring("Save Workspace Layout", "Name this layout:", parent=self)
        if name is None:
            return
        timeline = self.views.get("timeline")
        tasks = self.views.get("tasks")
        zoom = timeline.zoom_var.get() if timeline else "Days"
        hidden = [key for key, variable in getattr(tasks, "_column_vars", {}).items() if not variable.get()]
        try:
            set_workspace_layout(name, self.notebook.index(self.notebook.select()), zoom, hidden)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Workspace Layout", str(exc), parent=self)
            return
        self.status_var.set(f"Workspace layout '{name.strip()}' saved.")

    def apply_workspace_layout(self, name: str) -> None:
        layout = get_workspace_layouts().get(name)
        if layout is None:
            return
        timeline = self.views.get("timeline")
        if timeline:
            timeline.zoom_var.set(layout["zoom"])
        tasks = self.views.get("tasks")
        if tasks:
            hidden = set(layout["hidden"])
            for key, variable in tasks._column_vars.items():
                variable.set(key not in hidden)
            tasks._apply_task_columns(save=False)
        self._select_tab(int(layout["tab"]))
        self.status_var.set(f"Workspace layout '{name}' applied.")

    def remove_workspace_layout(self) -> None:
        layouts = get_workspace_layouts()
        if not layouts:
            return
        name = simpledialog.askstring("Remove Workspace Layout", "Enter the saved layout name to remove:\n" +
                                      ", ".join(sorted(layouts)), parent=self)
        if name is None:
            return
        if name not in layouts:
            messagebox.showinfo("Workspace Layout", "No saved layout has that exact name.", parent=self)
            return
        delete_workspace_layout(name)
        self.status_var.set(f"Workspace layout '{name}' removed.")

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
        settings_view = self.views.get("settings")
        if settings_view is not None and str(settings_view) != current:
            self._commit_pending_settings(show_errors=False)
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
        finish = format_date(p.finish_date) if p.finish_date else "not scheduled"
        self.status_var.set(
            f"{location}   ·   {len(p.tasks)} tasks   ·   finish {finish}   ·   {unsaved}"
        )

    def _update_theme_button(self) -> None:
        self.theme_button.configure(text=f"Theme: {self._theme_title(self.theme_name)}")

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

    def _populate_recent_menu(self) -> None:
        self.recent_menu.delete(0, "end")
        paths = get_recent_projects()
        if not paths:
            self.recent_menu.add_command(label="No recent projects", state="disabled")
        else:
            for path in paths:
                label = f"{path.name} — {path.parent}" if path.exists() else f"{path} (missing)"
                self.recent_menu.add_command(
                    label=label,
                    state="normal" if path.is_file() else "disabled",
                    command=lambda item=path: self.open_recent_project(item),
                )
        self.recent_menu.add_separator()
        self.recent_menu.add_command(label="Clear Recent Projects", command=self._clear_recent_projects,
                                     state="normal" if paths else "disabled")

    def open_recent_project(self, path: Path) -> None:
        if not path.is_file():
            messagebox.showerror("Open Recent", f"The project file no longer exists:\n{path}", parent=self)
            return
        self.open_project_file(path)

    def _clear_recent_projects(self) -> None:
        clear_recent_projects()
        self._populate_recent_menu()
        self.status_var.set("Recent project history cleared.")

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
        if self.perform(self.session.open_pfp, path):
            remember_recent_project(path)

    def save_project(self) -> bool:
        if not self._commit_pending_settings(show_errors=True):
            return False
        if self.session.file_path is None:
            return self.save_project_as()
        return self._save_to(self.session.file_path)

    def save_project_as(self) -> bool:
        if not self._commit_pending_settings(show_errors=True):
            return False
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
        clear_recovery_snapshot(self.session.project.id)
        remember_recent_project(path)
        self.refresh_all()
        return True

    def import_project(self) -> None:
        if not self.confirm_discard():
            return
        previous_project_id = self.session.project.id
        dialog = ImportDialog(self, self.session)
        if dialog.show():
            if self.session.project.id != previous_project_id:
                clear_recovery_snapshot(previous_project_id)
            self.refresh_all()

    def export_project(self) -> None:
        if not self._commit_pending_settings(show_errors=True):
            return
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

    def undo(self) -> None:
        self.perform(self.session.undo)

    def redo(self) -> None:
        self.perform(self.session.redo)

    def recalculate(self) -> None:
        self.perform(self.session.recalculate)

    def toggle_theme(self) -> None:
        """Cycle through built-in themes (Ctrl+T and the toolbar button)."""
        try:
            next_index = (THEMES.index(self.theme_name) + 1) % len(THEMES)
        except ValueError:  # cycling from a custom theme returns to the first built-in
            next_index = 0
        self.set_theme(THEMES[next_index])

    def set_theme(self, theme: str) -> bool:
        """Apply and persist an installed theme without changing project data."""
        palette = self._theme_palette(theme)
        if palette is None:
            return False
        self.theme_preference_saved = True
        try:
            set_theme_setting(theme)
        except OSError:
            # Keep the visual change available for this session if preferences
            # are read-only; the next launch will use the last saved choice.
            self.theme_preference_saved = False
        self.theme_name = theme
        self.theme_var.set(theme if theme in THEMES else "")
        self.palette = apply_palette(self, palette)
        self._update_theme_button()
        self.refresh_all()
        if not self.theme_preference_saved:
            self.status_var.set("Theme changed for this session, but the preference could not be saved.")
        return True

    def open_theme_manager(self) -> None:
        dialog = AppearanceManagerDialog(self, self)
        self.wait_window(dialog)

    def open_preferences(self) -> None:
        dialog = PreferencesDialog(self, self)
        self.wait_window(dialog)

    def show_command_palette(self) -> None:
        """Open a searchable, keyboard-operable list of implemented commands."""
        commands: list[tuple[str, str, Callable[[], Any]]] = [
            ("New Project", _shortcut("N"), self.new_project),
            ("Open Project…", _shortcut("O"), self.open_project),
            ("Save Project", _shortcut("S"), self.save_project),
            ("Save Project As…", _shortcut("S", shift=True), self.save_project_as),
            ("Import Project…", _shortcut("I"), self.import_project),
            ("Export Project…", _shortcut("E"), self.export_project),
            ("Add Task", "", lambda: self._run_view_action("tasks", "_add")),
            ("Add Milestone", "", lambda: self._run_view_action("tasks", "_add", milestone=True)),
            ("Find Task", "", self._focus_task_search),
            ("Open Theme Library", "", self.open_theme_manager),
            ("Preferences", "", self.open_preferences),
            ("Cycle Theme", _shortcut("T"), self.toggle_theme),
            ("Function Point Calculator", "", lambda: self.select_tab_by_key("estimates")),
            ("Import / Export Tools", "", lambda: self.select_tab_by_key("convert")),
            ("Recalculate Schedule", "F5", self.recalculate),
            ("Keyboard Shortcuts", "Ctrl+K", self.show_shortcuts),
            ("Help Guide", "F1", self.open_help),
        ]
        if self.session.can_undo:
            commands.insert(0, ("Undo", _shortcut("Z"), self.undo))
        if self.session.can_redo:
            commands.insert(0, ("Redo", _shortcut("Z", shift=True) if sys.platform == "darwin" else _shortcut("Y"), self.redo))
        win = tk.Toplevel(self)
        win.title("Command Palette")
        win.transient(self)
        win.geometry("560x390")
        win.minsize(440, 280)
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Search commands", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        query = tk.StringVar()
        entry = ttk.Entry(body, textvariable=query)
        entry.pack(fill="x", pady=(0, 8))
        listing = tk.Listbox(body, exportselection=False, activestyle="dotbox", height=12)
        listing.pack(fill="both", expand=True)
        matches: list[tuple[str, str, Callable[[], Any]]] = []

        def update(_args: Any = None) -> None:
            nonlocal matches
            needle = query.get().strip().casefold()
            matches = [item for item in commands if needle in item[0].casefold()]
            listing.delete(0, "end")
            for title, shortcut, _callback in matches:
                listing.insert("end", f"{title}{f'    {shortcut}' if shortcut else ''}")
            if matches:
                listing.selection_set(0)
                listing.activate(0)

        def run_selected(_event: Any = None) -> str:
            selected = listing.curselection()
            if selected and selected[0] < len(matches):
                callback = matches[selected[0]][2]
                win.destroy()
                self.after_idle(callback)
            return "break"

        def move_selection(delta: int) -> str:
            if not matches:
                return "break"
            current = listing.curselection()
            index = max(0, min(len(matches) - 1, (current[0] if current else 0) + delta))
            listing.selection_clear(0, "end")
            listing.selection_set(index)
            listing.activate(index)
            listing.see(index)
            return "break"

        query.trace_add("write", update)
        entry.bind("<Return>", run_selected)
        entry.bind("<Down>", lambda _event: move_selection(1))
        entry.bind("<Up>", lambda _event: move_selection(-1))
        listing.bind("<Return>", run_selected)
        listing.bind("<Double-1>", run_selected)
        listing.bind("<Escape>", lambda _event: win.destroy())
        entry.bind("<Escape>", lambda _event: win.destroy())
        update()
        win.grab_set()
        entry.focus_set()

    def _run_view_action(self, key: str, method: str, **kwargs: Any) -> None:
        self.select_tab_by_key(key)
        action = getattr(self.views.get(key), method, None)
        if action:
            action(**kwargs)

    def _focus_task_search(self) -> None:
        self.select_tab_by_key("tasks")
        entry = getattr(self.views.get("tasks"), "search_entry", None)
        if entry:
            entry.focus_set()
            entry.select_range(0, "end")

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
            f"  {_shortcut('N')}  New Project\n"
            f"  {_shortcut('O')}  Open…\n"
            f"  {_shortcut('S')}  Save\n"
            f"  {_shortcut('S', shift=True)}  Save As…\n"
            f"  {_shortcut('I')}  Import…\n"
            f"  {_shortcut('E')}  Export…\n"
            f"  {_shortcut('C', shift=True)}  Quick Convert\n"
            f"  {_shortcut('Q')}  Quit\n\n"
            f"  {_shortcut('Z')}  Undo project edit\n"
            f"  {_shortcut('Z', shift=True) if sys.platform == 'darwin' else _shortcut('Y')}  Redo project edit\n\n"
            "View:\n"
            "  F5      Recalculate Schedule\n"
            f"  {_shortcut('T')}  Cycle Themes\n"
            f"  {_shortcut('1')}..{_shortcut('0')}  Jump to tabs 1-10\n"
            "  F1      User Guide\n"
            f"  {_shortcut('K')}  This shortcuts help\n"
            f"  {_shortcut('P', shift=True)}  Command Palette\n\n"
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
                "Theme: Ctrl+T cycles built-in themes; selection is saved in your per-user preferences.\n\n"
                "Tip: Press F1 for the full User Guide, or Ctrl+K for shortcuts."
            ),
            parent=self,
        )

    def quit_app(self) -> None:
        project_id = self.session.project.id
        was_dirty = self.session.dirty
        if self.confirm_discard():
            if was_dirty and self.session.dirty:  # user explicitly chose Discard
                clear_recovery_snapshot(project_id)
            self.destroy()

    def destroy(self) -> None:
        pending = getattr(self, "_recovery_after_id", None)
        self._recovery_after_id = None
        if pending:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass
        super().destroy()


def run(open_path: str | Path | None = None) -> None:
    """Start the desktop application and block until the window is closed."""
    app = PlanForgeApp(open_path)
    app.mainloop()


__all__ = ["PlanForgeApp", "VIEWS", "run"]
