"""Local-first built-in and custom theme manager/editor dialogs."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any

from planforge.config import THEMES
from planforge.gui.theme import palette_for
from planforge.theme_library import (
    PALETTE_KEYS,
    create_theme_package,
    export_theme_package,
    install_theme_package,
    list_installed_themes,
    remove_installed_theme,
)


class AppearanceManagerDialog(tk.Toplevel):
    """Browse/apply built-in and local themes; all operations work offline."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        super().__init__(parent)
        self.app = app
        self.title("Theme Library")
        self.transient(parent.winfo_toplevel())
        self.geometry("760x500")
        self.minsize(650, 420)
        self._themes: list[dict[str, Any]] = []
        self._visible_themes: list[dict[str, Any]] = []

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Available themes", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.search_var).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        filter_row = ttk.Frame(left)
        filter_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(filter_row, text="Show").pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar(value="All themes")
        self.filter_combo = ttk.Combobox(filter_row, textvariable=self.filter_var, state="readonly",
                                         values=("All themes", "Built-in", "Local", "Light", "Dark", "High contrast"), width=14)
        self.filter_combo.pack(side="left")
        self.sort_var = tk.StringVar(value="Name")
        ttk.Label(filter_row, text="Sort").pack(side="left", padx=(10, 5))
        self.sort_combo = ttk.Combobox(filter_row, textvariable=self.sort_var, state="readonly",
                                       values=("Name", "Recently added"), width=14)
        self.sort_combo.pack(side="left")
        self.listbox = tk.Listbox(left, exportselection=False, height=12)
        self.listbox.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.bind("<<ListboxSelect>>", self._show_selected)
        self.search_var.trace_add("write", self._render_list)
        self.filter_combo.bind("<<ComboboxSelected>>", self._render_list)
        self.sort_combo.bind("<<ComboboxSelected>>", self._render_list)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        self.name_var = tk.StringVar(value="Select a theme")
        ttk.Label(right, textvariable=self.name_var, style="Heading.TLabel").pack(anchor="w")
        self.details_var = tk.StringVar()
        ttk.Label(right, textvariable=self.details_var, style="Muted.TLabel", wraplength=400,
                  justify="left").pack(anchor="w", pady=(4, 12))
        self.preview = tk.Canvas(right, height=190, highlightthickness=1, relief="solid")
        self.preview.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Built-in and local themes are available offline.")
        ttk.Label(right, textvariable=self.status_var, style="Muted.TLabel", wraplength=420).pack(anchor="w", pady=(8, 0))

        actions = ttk.Frame(self, padding=(14, 0, 14, 14))
        actions.pack(fill="x")
        ttk.Button(actions, text="Import…", command=self._import).pack(side="left")
        ttk.Button(actions, text="Export…", command=self._export).pack(side="left", padx=6)
        ttk.Button(actions, text="Remove", command=self._remove).pack(side="left")
        ttk.Button(actions, text="Duplicate / Customize…", command=self._customize).pack(side="left", padx=6)
        ttk.Button(actions, text="Apply", style="Accent.TButton", command=self._apply).pack(side="right")
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right", padx=6)
        self._reload()
        self.grab_set()

    def _reload(self, select_id: str | None = None) -> None:
        custom, warnings = list_installed_themes()
        self._themes = [
            {"id": theme_id, "name": theme_id.replace("_", " ").title(),
             "description": "PlanForge built-in theme", "version": "Built-in", "palette": palette_for(theme_id),
             "builtin": True, "author": "PlanForge"}
            for theme_id in THEMES
        ] + [dict(item, builtin=False) for item in custom]
        self._render_list()
        self.status_var.set(warnings[0] if warnings else "Built-in and local themes are available offline.")
        target = select_id or self.app.theme_name
        index = next((i for i, item in enumerate(self._visible_themes) if item["id"] == target), 0)
        if self._visible_themes:
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
            self._show_selected()

    @staticmethod
    def _theme_category(item: dict[str, Any]) -> str:
        if item["builtin"]:
            return {"light": "Light", "classic": "Light", "dark": "Dark", "midnight": "Dark",
                    "high_contrast": "High contrast"}.get(item["id"], "Other")
        background, foreground = item["palette"]["bg"], item["palette"]["text"]

        def luminance(value: str) -> float:
            channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
            return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

        a, b = luminance(background), luminance(foreground)
        contrast = (max(a, b) + .05) / (min(a, b) + .05)
        if contrast >= 7:
            return "High contrast"
        return "Dark" if a < .45 else "Light"

    def _render_list(self, *_args: Any) -> None:
        needle = self.search_var.get().strip().casefold()
        category = self.filter_var.get()
        self._visible_themes = [
            item for item in self._themes
            if needle in item["name"].casefold()
            and (category == "All themes" or category in ("Built-in", "Local") and (category == "Built-in") == item["builtin"]
                 or category in ("Light", "Dark", "High contrast") and category == self._theme_category(item))
        ]
        if self.sort_var.get() == "Recently added":
            self._visible_themes.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        else:
            self._visible_themes.sort(key=lambda item: (not item["builtin"], item["name"].casefold()))
        self.listbox.delete(0, "end")
        for item in self._visible_themes:
            kind = "Built-in" if item["builtin"] else f"Local · v{item.get('version', '1.0')}"
            self.listbox.insert("end", f"{item['name']}  —  {kind}")
        if self._visible_themes:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._show_selected()
        else:
            self.name_var.set("No themes match")
            self.details_var.set("")
            self.preview.delete("all")

    def _selected(self) -> dict[str, Any] | None:
        selection = self.listbox.curselection()
        return self._visible_themes[selection[0]] if selection and selection[0] < len(self._visible_themes) else None

    def _show_selected(self, _event: Any = None) -> None:
        item = self._selected()
        if item is None:
            return
        self.name_var.set(item["name"])
        details = item.get("description") or "No description provided."
        author = item.get("author") or "Unknown author"
        self.details_var.set(f"{details}\n\n{author} · {item.get('version', '1.0')} · {'Built-in' if item['builtin'] else 'Installed locally'}")
        self._draw_preview(item["palette"])

    def _draw_preview(self, p: dict[str, str]) -> None:
        c = self.preview
        c.delete("all")
        c.configure(background=p["bg"])
        width = max(c.winfo_width(), 380)
        c.create_rectangle(14, 14, width - 14, 176, fill=p["panel"], outline=p["border"], width=2)
        c.create_text(28, 32, anchor="w", fill=p["text"], text="PlanForge · Workspace preview",
                      font=("TkDefaultFont", 11, "bold"))
        c.create_rectangle(28, 52, width - 28, 82, fill=p["select"], outline=p["border"])
        c.create_text(38, 67, anchor="w", fill=p["text"], text="Selected task  ·  4 days  ·  60% complete")
        c.create_rectangle(38, 102, width - 110, 122, fill=p["bar"], outline="")
        c.create_rectangle(38, 102, 38 + (width - 148) * .6, 122, fill=p["bar_done"], outline="")
        c.create_line(28, 142, width - 28, 142, fill=p["grid"])
        c.create_rectangle(28, 151, 126, 169, fill=p["accent"], outline=p["accent"])
        c.create_text(77, 160, fill=p["accent_text"], text="Action button", font=("TkDefaultFont", 9, "bold"))

    def _apply(self) -> None:
        item = self._selected()
        if not item:
            return
        if self.app.set_theme(item["id"]):
            saved = getattr(self.app, "theme_preference_saved", True)
            self.status_var.set(f"Applied {item['name']}." if saved else
                                f"Applied {item['name']} for this session; preferences could not be saved.")

    def _customize(self) -> None:
        item = self._selected()
        if item:
            dialog = ThemeEditorDialog(self, self.app, item)
            self.wait_window(dialog)
            self._reload(getattr(dialog, "saved_theme_id", None) or item["id"])

    def _import(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Import theme package",
                                          filetypes=[("PlanForge theme packages", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            from planforge.theme_library import load_theme_package
            package = load_theme_package(Path(path))
            installed = install_theme_package(package)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Theme import failed", str(exc), parent=self)
            return
        self.status_var.set(f"Installed {installed['name']}. Select it and choose Apply to use it.")
        self._reload(installed["id"])

    def _export(self) -> None:
        item = self._selected()
        if not item:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export theme package", defaultextension=".json",
                                            initialfile=f"{item['name'].lower().replace(' ', '-')}.json",
                                            filetypes=[("PlanForge theme packages", "*.json")], confirmoverwrite=True)
        if not path:
            return
        try:
            package = create_theme_package(item["name"], item["palette"],
                                           description=item.get("description", ""),
                                           author=item.get("author", ""),
                                           version=item.get("version", "1.0"))
            export_theme_package(package, Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Theme export failed", str(exc), parent=self)
            return
        self.status_var.set(f"Exported {item['name']} to {path}.")

    def _remove(self) -> None:
        item = self._selected()
        if not item:
            return
        if item["builtin"]:
            self.status_var.set("Built-in themes are protected and cannot be removed.")
            return
        if not messagebox.askyesno("Remove theme", f"Remove the local theme '{item['name']}'?", parent=self):
            return
        if self.app.theme_name == item["id"]:
            self.app.set_theme("light")
        try:
            remove_installed_theme(item["id"])
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        self.status_var.set(f"Removed {item['name']}. Project data was not changed.")
        self._reload("light")


class ThemeEditorDialog(tk.Toplevel):
    """Create a named local theme from a copy; cancellation never changes settings."""

    def __init__(self, parent: tk.Misc, app: Any, source: dict[str, Any]) -> None:
        super().__init__(parent)
        self.app = app
        self.source = source
        self.saved_theme_id: str | None = None
        self.title("Customize Theme")
        self.transient(parent.winfo_toplevel())
        self.geometry("760x680")
        self.minsize(700, 600)
        self.palette = dict(source["palette"])
        self.color_vars: dict[str, tk.StringVar] = {}

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        ttk.Label(outer, text="Create a custom copy", style="Heading.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, text=f"Based on {source['name']}; built-in themes are never overwritten.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 10))
        ttk.Label(outer, text="Theme name").grid(row=2, column=0, sticky="w", pady=3)
        self.name_var = tk.StringVar(value=f"{source['name']} Custom")
        ttk.Entry(outer, textvariable=self.name_var, width=36).grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(outer, text="Description").grid(row=3, column=0, sticky="w", pady=3)
        self.description_var = tk.StringVar(value="A personalized PlanForge theme")
        ttk.Entry(outer, textvariable=self.description_var).grid(row=3, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Label(outer, text="Author (optional)").grid(row=4, column=0, sticky="w", pady=3)
        self.author_var = tk.StringVar()
        ttk.Entry(outer, textvariable=self.author_var, width=36).grid(row=4, column=1, sticky="ew", pady=3)

        colors = ttk.LabelFrame(outer, text="Colors · hex or choose", padding=8)
        colors.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(8, 8))
        outer.rowconfigure(5, weight=1)
        for i, key in enumerate(PALETTE_KEYS):
            col = 0 if i < (len(PALETTE_KEYS) + 1) // 2 else 3
            row = i if col == 0 else i - (len(PALETTE_KEYS) + 1) // 2
            label = key.replace("_", " ").title()
            ttk.Label(colors, text=label).grid(row=row, column=col, sticky="w", padx=(0, 6), pady=2)
            var = tk.StringVar(value=self.palette[key])
            self.color_vars[key] = var
            var.trace_add("write", lambda *_a, k=key: self._changed(k))
            entry = ttk.Entry(colors, textvariable=var, width=10)
            entry.grid(row=row, column=col + 1, sticky="w", pady=2)
            ttk.Button(colors, text="Pick…", command=lambda k=key: self._pick_color(k)).grid(row=row, column=col + 2, padx=(4, 12), pady=2)

        self.preview = tk.Canvas(outer, height=125, highlightthickness=1, relief="solid")
        self.preview.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(2, 8))
        self.error_var = tk.StringVar(value="Preview updates as valid colors are entered.")
        ttk.Label(outer, textvariable=self.error_var, style="Muted.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
        buttons = ttk.Frame(outer)
        buttons.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Reset", command=self._reset).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save & Apply", style="Accent.TButton", command=self._save).pack(side="right", padx=6)
        self._draw_preview()
        self.grab_set()

    def _changed(self, key: str) -> None:
        self.palette[key] = self.color_vars[key].get().strip()
        if all(isinstance(value, str) and len(value) == 7 and value.startswith("#") and
               all(char in "0123456789abcdefABCDEF" for char in value[1:]) for value in self.palette.values()):
            self.error_var.set("Preview updates as valid colors are entered.")
            self._draw_preview()
        else:
            self.error_var.set(f"{key.replace('_', ' ').title()} needs a six-digit hex color (for example #336699).")

    def _pick_color(self, key: str) -> None:
        current = self.color_vars[key].get().strip()
        if len(current) != 7 or not current.startswith("#"):
            current = self.source["palette"][key]
        try:
            selected = colorchooser.askcolor(current, parent=self)
        except tk.TclError:
            selected = colorchooser.askcolor(self.source["palette"][key], parent=self)
        if selected and selected[1]:
            self.color_vars[key].set(selected[1])

    def _draw_preview(self) -> None:
        p = self.palette
        c = self.preview
        c.configure(background=p["bg"])
        c.delete("all")
        width = max(c.winfo_width(), 580)
        c.create_rectangle(12, 12, width - 12, 112, fill=p["panel"], outline=p["border"], width=2)
        c.create_text(24, 30, anchor="w", fill=p["text"], text="Selected task · example project row",
                      font=("TkDefaultFont", 10, "bold"))
        c.create_rectangle(24, 43, width - 24, 64, fill=p["select"], outline=p["border"])
        c.create_text(34, 53, anchor="w", fill=p["text"], text="UI implementation  ·  60% complete")
        c.create_rectangle(34, 76, width - 120, 92, fill=p["bar"], outline="")
        c.create_rectangle(34, 76, 34 + (width - 154) * .6, 92, fill=p["bar_done"], outline="")
        c.create_rectangle(width - 102, 78, width - 32, 98, fill=p["accent"], outline="")
        c.create_text(width - 67, 88, fill=p["accent_text"], text="Apply", font=("TkDefaultFont", 9, "bold"))

    def _reset(self) -> None:
        for key in PALETTE_KEYS:
            self.color_vars[key].set(self.source["palette"][key])
        self.name_var.set(f"{self.source['name']} Custom")
        self.error_var.set("Reset to the source theme defaults; Save & Apply to keep this copy.")

    def _save(self) -> None:
        try:
            package = create_theme_package(self.name_var.get(), self.palette,
                                           description=self.description_var.get(), author=self.author_var.get())
            installed = install_theme_package(package)
            if not self.app.set_theme(installed["id"]):
                raise ValueError("The theme was saved, but could not be activated.")
        except (OSError, ValueError) as exc:
            self.error_var.set(str(exc))
            return
        self.saved_theme_id = installed["id"]
        self.destroy()


__all__ = ["AppearanceManagerDialog", "ThemeEditorDialog"]
