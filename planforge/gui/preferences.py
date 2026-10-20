"""Application-wide preferences, separate from project settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from planforge.config import (
    DATE_FORMATS,
    SHORTCUT_DEFAULTS,
    get_preference,
    get_shortcut_keys,
    set_settings,
    validate_shortcut_keys,
)


class PreferencesDialog(tk.Toplevel):
    """Edit workspace preferences in one place without touching project data."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        super().__init__(parent)
        self.app = app
        self.title("PlanForge Preferences")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Workspace", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.suggestions_var = tk.BooleanVar(
            value=get_preference("workspace", "show_suggestions", "true").casefold() not in ("false", "0", "no")
        )
        ttk.Checkbutton(body, text="Show suggested next steps on Overview", variable=self.suggestions_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 4)
        )
        ttk.Label(body, text="Default Gantt zoom").grid(row=2, column=0, sticky="w", pady=4)
        saved_zoom = get_preference("workspace", "timeline_zoom", "Days")
        self.zoom_var = tk.StringVar(value=saved_zoom if saved_zoom in ("Days", "Weeks", "Months") else "Days")
        ttk.Combobox(body, textvariable=self.zoom_var, state="readonly", values=("Days", "Weeks", "Months"),
                     width=12).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(body, text="Date display format").grid(row=3, column=0, sticky="w", pady=4)
        saved_format = get_preference("workspace", "date_format", "ISO")
        self.date_format_var = tk.StringVar(value=saved_format if saved_format in DATE_FORMATS else "ISO")
        ttk.Combobox(body, textvariable=self.date_format_var, state="readonly",
                     values=tuple(DATE_FORMATS), width=12).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(body, text="Recovery", style="Heading.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 2))
        self.recovery_enabled_var = tk.BooleanVar(
            value=get_preference("recovery", "autosave_enabled", "true").casefold() not in ("false", "0", "no")
        )
        ttk.Checkbutton(body, text="Enable crash-recovery snapshots", variable=self.recovery_enabled_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=3
        )
        ttk.Label(body, text="Snapshot interval").grid(row=6, column=0, sticky="w", pady=4)
        saved_interval = get_preference("recovery", "interval_seconds", "60")
        try:
            saved_interval = int(saved_interval)
        except ValueError:
            saved_interval = 60
        interval_label = "1 minute" if saved_interval <= 60 else ("2 minutes" if saved_interval <= 120 else "5 minutes")
        self.interval_var = tk.StringVar(value=interval_label)
        ttk.Combobox(body, textvariable=self.interval_var, state="readonly",
                     values=("1 minute", "2 minutes", "5 minutes"), width=12).grid(row=6, column=1, sticky="w", pady=4)
        ttk.Label(body, text="Keyboard shortcuts (modifier is Ctrl / Command)", style="Heading.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(12, 3)
        )
        shortcuts = get_shortcut_keys()
        self.shortcut_vars = {name: tk.StringVar(value=shortcuts[name]) for name in ("new", "open", "save", "undo", "redo")}
        shortcut_frame = ttk.Frame(body)
        shortcut_frame.grid(row=8, column=0, columnspan=2, sticky="ew")
        for row, (left, right) in enumerate((("new", "open"), ("save", "undo"), ("redo", None))):
            for column, action in ((0, left), (2, right)):
                if action is None:
                    continue
                ttk.Label(shortcut_frame, text=action.title()).grid(row=row, column=column, sticky="w", padx=(0, 4), pady=2)
                ttk.Entry(shortcut_frame, textvariable=self.shortcut_vars[action], width=4, justify="center").grid(
                    row=row, column=column + 1, sticky="w", padx=(0, 12), pady=2
                )
        ttk.Label(body, text="Themes are managed from View → Manage Themes. Recovery files stay separate from project files.",
                  style="Muted.TLabel", wraplength=420).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.status_var = tk.StringVar(value="Preferences are stored separately from project data.")
        ttk.Label(body, textvariable=self.status_var, style="Muted.TLabel", wraplength=400).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(4, 8)
        )
        buttons = ttk.Frame(body)
        buttons.grid(row=11, column=0, columnspan=2, sticky="ew")
        ttk.Button(buttons, text="Reset Workspace", command=self._reset).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=self._apply).pack(side="right", padx=6)
        self.grab_set()

    def _reset(self) -> None:
        self.suggestions_var.set(True)
        self.zoom_var.set("Days")
        self.date_format_var.set("ISO")
        self.recovery_enabled_var.set(True)
        self.interval_var.set("1 minute")
        for action, default in SHORTCUT_DEFAULTS.items():
            if action in self.shortcut_vars:
                self.shortcut_vars[action].set(default)
        self.status_var.set("Workspace, recovery and shortcut defaults selected. Choose Apply to save them.")

    def _apply(self) -> None:
        seconds = {"1 minute": "60", "2 minutes": "120", "5 minutes": "300"}.get(self.interval_var.get(), "60")
        try:
            shortcut_keys = validate_shortcut_keys({key: value.get() for key, value in self.shortcut_vars.items()})
            settings = {
                ("workspace", "show_suggestions"): str(self.suggestions_var.get()).lower(),
                ("workspace", "timeline_zoom"): self.zoom_var.get(),
                ("workspace", "date_format"): self.date_format_var.get(),
                ("workspace", "dismissed_suggestions"): "",
                ("recovery", "autosave_enabled"): str(self.recovery_enabled_var.get()).lower(),
                ("recovery", "interval_seconds"): seconds,
            }
            settings.update({("shortcuts", key): value for key, value in shortcut_keys.items()})
            set_settings(settings)
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Could not save preferences: {exc}")
            return
        timeline = self.app.views.get("timeline")
        if timeline:
            timeline.zoom_var.set(self.zoom_var.get())
        overview = self.app.views.get("overview")
        if overview:
            overview._suggestions_enabled = self.suggestions_var.get()
            overview._dismissed_suggestions.clear()
            overview.refresh()
        self.app._schedule_recovery()
        self.app._bind_shortcuts()
        self.app._build_menu()
        self.app.refresh_all()
        self.status_var.set("Preferences and shortcuts applied and saved.")
        self.after(500, self.destroy)


__all__ = ["PreferencesDialog"]
