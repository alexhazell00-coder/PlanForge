"""Convert & Interchange tab — one-stop file format conversion."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from planforge.gui.views import BaseView

if TYPE_CHECKING:  # pragma: no cover
    from planforge.gui.app import PlanForgeApp

FILE_FILTERS = [
    ("All project files", "*.xml *.gan *.csv *.json *.pfp"),
    ("Microsoft Project / ProjectLibre XML", "*.xml"),
    ("GanttProject", "*.gan"),
    ("CSV", "*.csv"),
    ("JSON", "*.json"),
    ("PlanForge database", "*.pfp"),
    ("All files", "*.*"),
]


def _safe_name(text: str) -> str:
    base = "".join(c if c.isalnum() or c in " -_" else "_" for c in text).strip() or "project"
    return base.replace(" ", "_").lower()


class ConvertView(BaseView):
    """Wizard that makes conversion obvious: pick source, pick target, click Convert."""

    def _build(self) -> None:
        self._title("Convert & Interchange", "Move projects between PlanForge, Microsoft Project, ProjectLibre, GanttProject, CSV and JSON.")
        subtitle = ttk.Label(self, text="Auto-detects formats • Validates output before saving • Atomic writes (no half-files) • Works offline", style="Muted.TLabel")
        subtitle.pack(anchor="w", pady=(0, 8))

        # Top helper bar
        bar = self._toolbar()
        ttk.Button(bar, text="Open Help Guide", command=self._go_help).pack(side="left")
        ttk.Button(bar, text="Show Supported Formats", command=self._show_formats).pack(side="left", padx=6)
        ttk.Label(bar, text="Tip: You can also use File → Import / Export or the CLI.", style="Muted.TLabel").pack(side="right")

        # Scrollable canvas for main wizard
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill="both", expand=True, pady=(6, 0))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scroll.set)

        self.inner = ttk.Frame(self.canvas, padding=12)
        self.win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.inner.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<Button-4>", self._on_wheel)
        self.inner.bind("<Button-5>", self._on_wheel)

        # State
        self.source_mode_var = tk.StringVar(value="current")  # "current" or "file"
        self.source_path_var = tk.StringVar()
        self.source_format_var = tk.StringVar(value="Detect automatically")
        self.dest_path_var = tk.StringVar()
        self.dest_format_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready — use the current project, or pick a file to convert.")
        self.preview_result = None  # ImportResult

        # Build wizard inside inner
        self._build_source_step()
        self._build_target_step()
        self._build_action_step()
        self._build_formats_panel()

        # Bind auto-inspect for file mode
        self.source_path_var.trace_add("write", lambda *_a: self._auto_suggest_dest())
        # Initial refresh to set up dropdowns
        self.refresh()

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.win_id, width=event.width)

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            delta = -3
        elif getattr(event, "num", None) == 5:
            delta = 3
        else:
            delta = -3 if getattr(event, "delta", 0) > 0 else 3
        self.canvas.yview_scroll(delta, "units")
        return "break"

    # --- steps ---
    def _build_source_step(self) -> None:
        box = ttk.LabelFrame(self.inner, text="Step 1 — Choose Source", padding=10)
        box.pack(fill="x", pady=(0, 10))
        box.columnconfigure(1, weight=1)

        # Mode radios
        self.source_mode_label_var = tk.StringVar(value="Current project: (loading…)")
        mode_row = ttk.Frame(box)
        mode_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        mode_row.columnconfigure(1, weight=1)
        ttk.Radiobutton(mode_row, textvariable=self.source_mode_label_var, value="current", variable=self.source_mode_var, command=self._on_source_mode_change).pack(side="left")
        ttk.Radiobutton(mode_row, text="File on disk:", value="file", variable=self.source_mode_var, command=self._on_source_mode_change).pack(side="left", padx=(16, 0))
        ttk.Button(mode_row, text="Refresh preview", command=self._refresh_source_preview).pack(side="right")

        # File row (only active when mode=file)
        self.file_label = ttk.Label(box, text="Source file")
        self.file_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        row0 = ttk.Frame(box)
        row0.grid(row=1, column=1, sticky="ew", pady=4)
        row0.columnconfigure(0, weight=1)
        self.file_entry = ttk.Entry(row0, textvariable=self.source_path_var)
        self.file_entry.grid(row=0, column=0, sticky="ew")
        self.browse_btn = ttk.Button(row0, text="Browse…", command=self._browse_source)
        self.browse_btn.grid(row=0, column=1, padx=(6, 0))
        self.clear_btn = ttk.Button(row0, text="Clear", command=self._clear_source)
        self.clear_btn.grid(row=0, column=2, padx=(6, 0))

        ttk.Label(box, text="Source format").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.source_format_combo = ttk.Combobox(box, textvariable=self.source_format_var, state="readonly", width=36)
        self.source_format_combo.grid(row=2, column=1, sticky="w", pady=4)
        self.source_format_combo.bind("<<ComboboxSelected>>", lambda _e: self._inspect())

        self.inspect_btn = ttk.Button(box, text="Inspect / Check file", style="Accent.TButton", command=self._inspect)
        self.inspect_btn.grid(row=3, column=1, sticky="w", pady=6)
        self.hint_label = ttk.Label(box, text="For the current project, the preview updates automatically.", style="Muted.TLabel")
        self.hint_label.grid(row=4, column=1, sticky="w")

        # Preview
        self.preview_text = tk.Text(box, width=80, height=10, wrap="word", relief="solid", borderwidth=1, state="disabled", font=("Courier", 9))
        self.preview_text.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        box.rowconfigure(5, weight=1)

        self._on_source_mode_change()

    def _on_source_mode_change(self) -> None:
        is_file = self.source_mode_var.get() == "file"
        state = "normal" if is_file else "disabled"
        # Toggle file controls
        try:
            self.file_entry.configure(state=state)
            self.browse_btn.configure(state=state)
            self.clear_btn.configure(state=state)
            self.source_format_combo.configure(state="readonly" if is_file else "disabled")
            self.inspect_btn.configure(state=state)
        except Exception:
            pass
        if is_file:
            self.hint_label.configure(text="Pick a file, then click Inspect (or it auto-inspects). Format auto-detected from content.")
        else:
            self.hint_label.configure(text="Using the open project — no file needed. Edit it in Tasks/People first, then export below.")
        self._refresh_source_preview()
        self._auto_suggest_dest(force=True)

    def _refresh_source_preview(self) -> None:
        if self.source_mode_var.get() == "current":
            self._show_current_preview()
        else:
            # file mode: if path exists, inspect else show hint
            path = self.source_path_var.get().strip()
            if path and Path(path).is_file():
                self._inspect()
            else:
                self._write_preview([
                    "File mode: Choose a file to preview.",
                    "• Browse… to pick .xml, .gan, .csv, .json, or .pfp",
                    "• .pod / .mpp will show exact steps to export XML first",
                    "",
                    "Or switch to 'Current project' above to export what you see in PlanForge right now.",
                ])
                self.status_var.set("Choose a file, or switch to Current project.")
                self.preview_result = None

    def _show_current_preview(self) -> None:
        try:
            s = self.session.summary()
            p = self.session.project
            lines = [
                f"✓ Source: Current open project",
                f"Project: {s.name}",
                f"Tasks: {s.task_count} ({s.subtask_count} subtasks, {s.milestone_count} milestones)",
                f"Dependencies: {s.dependency_count}",
                f"People: {s.resource_count}",
                f"Assignments: {s.assignment_count}",
                f"Dates: {s.start_date or 'not set'} → {s.finish_date or 'not set'}",
                "",
                f"Currency: {p.currency} • Dirty: {'Yes — save suggested' if self.session.dirty else 'No (saved)'}",
                "Ready to export — choose target format and destination below.",
            ]
            self._write_preview(lines)
            self.status_var.set(f"Current project: {s.task_count} tasks • {s.resource_count} people • {p.name}")
            # Do not set preview_result to file result; _convert will use session.project directly
            self.preview_result = None
            # Update mode label with live name
            self.source_mode_label_var.set(f"Current project: {p.name}  ({s.task_count} tasks)")
        except Exception as exc:
            self._write_preview([f"Could not read current project: {exc}"])
            self.status_var.set("Error reading current project.")

    def _build_target_step(self) -> None:
        box = ttk.LabelFrame(self.inner, text="Step 2 — Choose Target Format & Destination (Export)", padding=10)
        box.pack(fill="x", pady=(0, 10))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Target format").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.dest_format_combo = ttk.Combobox(box, textvariable=self.dest_format_var, state="readonly", width=36)
        self.dest_format_combo.grid(row=0, column=1, sticky="w", pady=4)
        self.dest_format_combo.bind("<<ComboboxSelected>>", lambda _e: self._auto_suggest_dest(force=True))

        ttk.Label(box, text="Save to").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        row1 = ttk.Frame(box)
        row1.grid(row=1, column=1, sticky="ew", pady=4)
        row1.columnconfigure(0, weight=1)
        ttk.Entry(row1, textvariable=self.dest_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row1, text="Browse…", command=self._browse_dest).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(row1, text="Suggest name", command=lambda: self._auto_suggest_dest(force=True)).grid(row=0, column=2, padx=(6, 0))

        ttk.Label(box, text="Suggested names use your project/file name + correct extension — edit as needed.", style="Muted.TLabel").grid(row=2, column=1, sticky="w")

        # Quick-format helpers
        quick = ttk.Frame(box)
        quick.grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Label(quick, text="Quick picks:", style="Muted.TLabel").pack(side="left")
        for label, fid_key in [("MS Project XML", "microsoft-project-xml"), ("GanttProject GAN", "ganttproject"), ("CSV", "csv"), ("JSON", "planforge-json")]:
            ttk.Button(quick, text=label, command=lambda k=fid_key: self._pick_format(k)).pack(side="left", padx=4)

    def _pick_format(self, fid: str) -> None:
        # Find label for fid and set
        for check_fid, label, _ext in self.session.format_choices("export"):
            if check_fid == fid:
                self.dest_format_var.set(label)
                self._auto_suggest_dest(force=True)
                self.status_var.set(f"Target: {label}")
                return

    def _build_action_step(self) -> None:
        box = ttk.LabelFrame(self.inner, text="Step 3 — Convert", padding=10)
        box.pack(fill="x", pady=(0, 10))

        row = ttk.Frame(box)
        row.pack(fill="x")
        self.convert_button = ttk.Button(row, text="Convert / Export  ▶", style="Accent.TButton", command=self._convert)
        self.convert_button.pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Open Containing Folder", command=self._open_folder).pack(side="left", padx=6)
        ttk.Button(row, text="Reset", command=self._reset).pack(side="left")

        status = ttk.Label(box, textvariable=self.status_var, style="Muted.TLabel", wraplength=700, justify="left")
        status.pack(anchor="w", pady=(8, 0))

        # Success panel (hidden until success)
        self.success_var = tk.StringVar()
        self.success_label = ttk.Label(box, textvariable=self.success_var, style="Success.TLabel", wraplength=700, justify="left")
        # will pack when needed
        self._success_packed = False

        ttk.Label(box, text="Works for both modes: current project or file on disk. Validated before saving, atomic write — no half-files.", style="Muted.TLabel", wraplength=700, justify="left").pack(anchor="w", pady=(6, 0))

    def _build_formats_panel(self) -> None:
        box = ttk.LabelFrame(self.inner, text="Supported Formats — Quick Reference", padding=10)
        box.pack(fill="both", expand=True)

        info = (
            "Choose the right format for your workflow:\n"
            "• Have a .xml from ProjectLibre or MS Project? Pick 'Microsoft Project XML (.xml)' — it opens directly in those apps.\n"
            "• Using GanttProject? Pick 'GanttProject (.gan)' — nested tasks and resources preserved.\n"
            "• Just backing up? Pick 'PlanForge JSON (.json)' or save .pfp via File → Save.\n"
            "• Got a spreadsheet? Use 'CSV Task List (.csv)'.\n"
            "• Got .pod or .mpp? PlanForge will explain how to export XML from the original app — it's the safe, lossless path.\n"
        )
        ttk.Label(box, text=info, style="Muted.TLabel", justify="left", wraplength=700).pack(anchor="w", pady=(0, 8))

        # Formats table as text canvas
        self.formats_text = tk.Text(box, wrap="word", height=8, relief="flat", borderwidth=0, font=("Courier", 9), state="disabled")
        self.formats_text.pack(fill="both", expand=True)
        self._fill_formats_table()

        tips = ttk.Frame(box)
        tips.pack(fill="x", pady=(8, 0))
        ttk.Label(tips, text="CLI tip:", style="Heading.TLabel").pack(side="left")
        ttk.Label(tips, text="  ./bin/planforge --import-file in.xml --export-file out.gan --export-format ganttproject", style="Muted.TLabel").pack(side="left", padx=6)
        ttk.Button(tips, text="Copy CLI example", command=self._copy_cli).pack(side="right")

    def _fill_formats_table(self) -> None:
        p = self.app.palette if hasattr(self, "app") else {"panel": "#fff", "text": "#000"}
        self.formats_text.configure(state="normal", background=p["panel"], foreground=p["text"])
        self.formats_text.delete("1.0", "end")
        lines = [
            f"{'Format':<30} {'Ext':<8} {'Import':<8} {'Export':<8} Description",
            "-" * 90,
        ]
        try:
            for fmt in self.session.manager.registry.formats():
                imp = "Yes" if fmt.can_import else "—"
                exp = "Yes" if fmt.can_export else "—"
                lines.append(f"{fmt.name:<30} {','.join(fmt.extensions):<8} {imp:<8} {exp:<8} {fmt.description}")
            lines.append(f"{'PlanForge SQLite database (.pfp)':<30} {'.pfp':<8} {'—':<8} {'Yes':<8} Offline transactional database (File → Save)")
        except Exception:
            lines += [
                "Microsoft Project XML (.xml)   .xml     Yes      Yes      MS Project + ProjectLibre interchange",
                "GanttProject (.gan)            .gan     Yes      Yes      Nested tasks, dependencies, resources",
                "PlanForge JSON (.json)         .json    Yes      Yes      Canonical versioned backup",
                "CSV Task List (.csv)           .csv     Yes      Yes      Header-mapped with JSON-in-cell",
                "Simple FP Calculator (.json)   .json    Yes      Yes      People + function points",
                "PlanForge SQLite database      .pfp     —        Yes      Transactional save (File→Save)",
            ]
        self.formats_text.insert("1.0", "\n".join(lines))
        self.formats_text.configure(state="disabled")

    # --- helpers ---
    def _refresh_combos(self) -> None:
        try:
            import_choices = self.session.format_choices("import")
            export_choices = self.session.format_choices("export")
        except Exception:
            return
        import_labels = ["Detect automatically"] + [label for _fid, label, _ext in import_choices]
        self.source_format_combo.configure(values=import_labels)
        if self.source_format_var.get() not in import_labels:
            self.source_format_var.set("Detect automatically")
        export_labels = [label for _fid, label, _ext in export_choices]
        self.dest_format_combo.configure(values=export_labels)
        if not self.dest_format_var.get() and export_labels:
            self.dest_format_var.set(export_labels[0])

    def _selected_import_id(self) -> str | None:
        label = self.source_format_var.get()
        if label == "Detect automatically":
            return None
        for fid, lbl, _ext in self.session.format_choices("import"):
            if lbl == label:
                return fid
        return None

    def _selected_export_id(self) -> tuple[str | None, str | None]:
        label = self.dest_format_var.get()
        for fid, lbl, ext in self.session.format_choices("export"):
            if lbl == label:
                return fid, ext
        return None, None

    # --- actions ---
    def _browse_source(self) -> None:
        path = filedialog.askopenfilename(parent=self.app, title="Choose a project file to convert", filetypes=FILE_FILTERS)
        if path:
            self.source_mode_var.set("file")
            self._on_source_mode_change()
            self.source_path_var.set(path)
            self._inspect()

    def _clear_source(self) -> None:
        self.source_path_var.set("")
        self.preview_result = None
        self._write_preview(["No file selected. Browse to pick a source file."])
        self.status_var.set("Choose a source file to begin.")

    def _inspect(self) -> None:
        if self.source_mode_var.get() != "file":
            self._show_current_preview()
            return
        path = self.source_path_var.get().strip()
        if not path:
            self._write_preview(["No file selected. Use Browse… to pick a source file, then Inspect."])
            self.status_var.set("Choose a source file to begin.")
            return
        if not Path(path).is_file():
            self._write_preview([f"File not found:\n{path}\n\nCheck the path or use Browse…"])
            self.status_var.set("Source file not found.")
            self.preview_result = None
            return
        fid = self._selected_import_id()
        try:
            result = self.session.preview_import(path, format_id=fid)
        except Exception as exc:
            self._write_preview([f"Error reading file:\n{exc}"])
            self.status_var.set("Error inspecting file.")
            self.preview_result = None
            return
        self.preview_result = result
        lines: list[str] = []
        if result.project is None or not result.success:
            lines.append("This file could not be imported.")
            lines.append("")
            lines.append(f"Attempted format: {result.source_format}")
        else:
            s = result.summary
            lines += [
                f"✓ Format detected: {result.source_format}",
                f"Project: {s.name}",
                f"Tasks: {s.task_count} ({s.subtask_count} subtasks, {s.milestone_count} milestones)",
                f"Dependencies: {s.dependency_count}",
                f"People: {s.resource_count}",
                f"Assignments: {s.assignment_count}",
                f"Dates: {s.start_date or 'not set'} → {s.finish_date or 'not set'}",
                "",
                "Ready to export — choose a target format and destination below.",
            ]
            self.status_var.set(f"Inspected: {s.task_count} tasks • {s.resource_count} people • {result.source_format}")
            if not self.dest_path_var.get().strip():
                self._auto_suggest_dest()
        if result.issues:
            lines.append("")
            lines.append("Messages:")
            lines += [f"  [{i.severity}] {i.message}" for i in result.issues]
        self._write_preview(lines)

    def _auto_suggest_dest(self, force: bool = False) -> None:
        if self.dest_path_var.get().strip() and not force:
            return
        src = self.source_path_var.get().strip() if self.source_mode_var.get() == "file" else ""
        base_name = None
        if self.source_mode_var.get() == "file" and self.preview_result and self.preview_result.project is not None:
            base_name = _safe_name(self.preview_result.project.name)
        elif self.source_mode_var.get() == "file" and src:
            base_name = Path(src).stem
            base_name = _safe_name(base_name) if base_name else "project"
        else:
            try:
                base_name = _safe_name(self.session.project.name)
            except Exception:
                base_name = "project"
        fid, ext = self._selected_export_id()
        if ext is None:
            ext = ".xml"
        suggested = str(Path.home() / f"{base_name}{ext}")
        if src:
            try:
                if Path(src).parent.exists():
                    suggested = str(Path(src).parent / f"{base_name}{ext}")
            except Exception:
                pass
        else:
            # Use current file's folder if available
            try:
                if self.session.file_path and self.session.file_path.parent.exists():
                    suggested = str(self.session.file_path.parent / f"{base_name}{ext}")
            except Exception:
                pass
        self.dest_path_var.set(suggested)

    def _browse_dest(self) -> None:
        fid, ext = self._selected_export_id()
        if ext:
            ftypes = [(f"*{ext}", f"*{ext}"), ("All files", "*.*")]
        else:
            ftypes = FILE_FILTERS
        initial = Path(self.dest_path_var.get()).name if self.dest_path_var.get().strip() else ""
        path = filedialog.asksaveasfilename(parent=self.app, title="Where to save converted file", initialfile=initial, defaultextension=ext or "", filetypes=ftypes)
        if path:
            if ext and not path.lower().endswith(ext.lower()):
                path = path + ext
            self.dest_path_var.set(path)

    def _convert(self) -> None:
        # Determine source project
        use_current = self.source_mode_var.get() == "current"
        dest = self.dest_path_var.get().strip()
        project = None
        source_desc = ""

        if use_current:
            project = self.session.project
            source_desc = f"current project '{project.name}'"
            if not project.tasks and not project.resources:
                if not messagebox.askyesno("Empty project?", "Current project has no tasks/resources. Export anyway?", parent=self.app):
                    return
        else:
            src = self.source_path_var.get().strip()
            if not src:
                messagebox.showwarning("Choose source", "Pick a source file first (Step 1 → Browse…), or switch to 'Current project'.", parent=self.app)
                return
            if self.preview_result is None or not self.preview_result.success or self.preview_result.project is None:
                self._inspect()
                if self.preview_result is None or not self.preview_result.success or self.preview_result.project is None:
                    messagebox.showerror("Cannot convert", "Source file could not be read. Check the preview for details.", parent=self.app)
                    return
            project = self.preview_result.project
            source_desc = Path(src).name

        fid, ext = self._selected_export_id()
        if fid is None:
            messagebox.showwarning("Choose format", "Pick a target format in Step 2.", parent=self.app)
            return
        if not dest:
            messagebox.showwarning("Choose destination", "Pick where to save the converted file (Step 2 → Browse… or Suggest name).", parent=self.app)
            return
        if ext and not dest.lower().endswith(ext.lower()):
            dest = dest + ext
            self.dest_path_var.set(dest)

        if Path(dest).exists():
            if not messagebox.askyesno("Overwrite?", f"The file already exists:\n{dest}\n\nOverwrite?", parent=self.app):
                return

        self.status_var.set(f"Converting… {source_desc} → {Path(dest).name} ({fid}) …")
        self.convert_button.configure(state="disabled")
        # Force UI update
        try:
            self.app.update_idletasks()
        except Exception:
            pass
        try:
            result = self.session.manager.export_file(project, fid, dest, overwrite=True)
            if not result.success:
                details = "; ".join(i.message for i in result.errors) or "Unknown error."
                self.status_var.set(f"Export failed: {details}")
                self._write_preview([f"Export failed for {fid}:"] + [i.message for i in result.errors])
                messagebox.showerror("Export failed", details + "\n\nSee preview for details.", parent=self.app)
                return
            self.status_var.set(f"✓ Converted successfully: {dest}")
            self.success_var.set(f"✓ Saved to: {dest}\nFormat: {fid} • Tasks: {len(project.tasks)} • People: {len(project.resources)}")
            if not self._success_packed:
                self.success_label.pack(anchor="w", pady=(8, 0))
                self._success_packed = True
            messagebox.showinfo("Convert complete", f"Saved converted file to:\n{dest}\n\nSource: {source_desc}\nFormat: {fid}\nTasks: {len(project.tasks)}\nPeople: {len(project.resources)}\n\nYou can now open it in the target application.", parent=self.app)
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            messagebox.showerror("Error", str(exc), parent=self.app)
        finally:
            self.convert_button.configure(state="normal")

    def _open_folder(self) -> None:
        dest = self.dest_path_var.get().strip()
        if not dest:
            messagebox.showinfo("No destination", "Choose a destination file first (Step 2 → Browse… or Suggest name).", parent=self.app)
            return
        p = Path(dest)
        folder = p.parent if p.parent.exists() else Path.home()
        import subprocess, sys, os
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showinfo("Folder", f"Converted file would be in:\n{folder}\n\n({exc})", parent=self.app)

    def _reset(self) -> None:
        self.source_mode_var.set("current")
        self.source_path_var.set("")
        self.source_format_var.set("Detect automatically")
        self.dest_path_var.set("")
        try:
            first = self.session.format_choices("export")[0][1]
            self.dest_format_var.set(first)
        except Exception:
            pass
        self.preview_result = None
        self._on_source_mode_change()
        self.status_var.set("Reset — ready. Current project selected; choose target format and Convert.")
        self.success_var.set("")
        if self._success_packed:
            self.success_label.pack_forget()
            self._success_packed = False

    def _go_help(self) -> None:
        keys = list(self.app.views.keys())
        if "help" in keys:
            self.app.notebook.select(keys.index("help"))

    def _show_formats(self) -> None:
        self.canvas.yview_moveto(1.0)

    def _copy_cli(self) -> None:
        example = "./bin/planforge --import-file in.xml --export-file out.gan --export-format ganttproject"
        try:
            self.clipboard_clear()
            self.clipboard_append(example)
        except Exception:
            pass
        messagebox.showinfo("Copied", "CLI example copied to clipboard:\n" + example, parent=self.app)

    def _write_preview(self, lines: list[str]) -> None:
        p = self.app.palette
        self.preview_text.configure(state="normal", background=p["panel"], foreground=p["text"])
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "\n".join(lines))
        self.preview_text.configure(state="disabled")

    def refresh(self) -> None:
        p = self.app.palette
        self.canvas.configure(background=p["bg"])
        self.inner.configure(style="TFrame")
        try:
            self.preview_text.configure(background=p["panel"], foreground=p["text"])
            self.formats_text.configure(background=p["panel"], foreground=p["text"])
        except Exception:
            pass
        self._refresh_combos()
        self._fill_formats_table()
        # Update current project label and preview if in current mode
        try:
            if self.source_mode_var.get() == "current":
                self.source_mode_label_var.set(f"Current project: {self.session.project.name}  ({len(self.session.project.tasks)} tasks)")
                self._show_current_preview()
        except Exception:
            pass

    def on_show(self) -> None:
        self.refresh()
        self._fill_formats_table()

__all__ = ["ConvertView"]
