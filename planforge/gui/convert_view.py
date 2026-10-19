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
        self.source_path_var = tk.StringVar()
        self.source_format_var = tk.StringVar(value="Detect automatically")
        self.dest_path_var = tk.StringVar()
        self.dest_format_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a source file to begin.")
        self.preview_result = None  # ImportResult

        # Build wizard inside inner
        self._build_source_step()
        self._build_target_step()
        self._build_action_step()
        self._build_formats_panel()

        # Bind auto-inspect
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
        box = ttk.LabelFrame(self.inner, text="Step 1 — Choose Source File (Import)", padding=10)
        box.pack(fill="x", pady=(0, 10))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Source file").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        row0 = ttk.Frame(box)
        row0.grid(row=0, column=1, sticky="ew", pady=4)
        row0.columnconfigure(0, weight=1)
        ttk.Entry(row0, textvariable=self.source_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row0, text="Browse…", command=self._browse_source).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(row0, text="Clear", command=self._clear_source).grid(row=0, column=2, padx=(6, 0))

        ttk.Label(box, text="Source format").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.source_format_combo = ttk.Combobox(box, textvariable=self.source_format_var, state="readonly", width=36)
        self.source_format_combo.grid(row=1, column=1, sticky="w", pady=4)
        self.source_format_combo.bind("<<ComboboxSelected>>", lambda _e: self._inspect())

        ttk.Button(box, text="Inspect / Check file", style="Accent.TButton", command=self._inspect).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(box, text="After picking a file, click Inspect (or it will auto-inspect) to see what PlanForge found.", style="Muted.TLabel").grid(row=3, column=1, sticky="w")

        # Preview
        self.preview_text = tk.Text(box, width=80, height=10, wrap="word", relief="solid", borderwidth=1, state="disabled", font=("Courier", 9))
        self.preview_text.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        box.rowconfigure(4, weight=1)
        # Scroll for preview
        # (make it fixed height, no extra scrollbar; but we could add one if needed)

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

        ttk.Label(box, text="Suggested names are based on your project/source name and correct extension — edit as needed.", style="Muted.TLabel").grid(row=2, column=1, sticky="w")

    def _build_action_step(self) -> None:
        box = ttk.LabelFrame(self.inner, text="Step 3 — Convert", padding=10)
        box.pack(fill="x", pady=(0, 10))

        row = ttk.Frame(box)
        row.pack(fill="x")
        self.convert_button = ttk.Button(row, text="Convert (Import → Export)  ▶", style="Accent.TButton", command=self._convert)
        self.convert_button.pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Open Containing Folder", command=self._open_folder).pack(side="left", padx=6)
        ttk.Button(row, text="Reset", command=self._reset).pack(side="left")

        status = ttk.Label(box, textvariable=self.status_var, style="Muted.TLabel", wraplength=700, justify="left")
        status.pack(anchor="w", pady=(8, 0))

        # Success panel (hidden until success)
        self.success_var = tk.StringVar()
        self.success_label = ttk.Label(box, textvariable=self.success_var, style="Success.TLabel", wraplength=700, justify="left")
        # will pack when needed

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
        # Pull from session if available, else fallback
        try:
            import_choices = self.session.format_choices("import")
            export_choices = self.session.format_choices("export")
            # Build mapping
            import_ids = {fid for fid, _label, _ext in import_choices}
            export_ids = {fid for fid, _label, _ext in export_choices}
            all_defs = {}
            # Use registry to get descriptions
            for fmt in self.session.manager.registry.formats():
                all_defs[fmt.id] = fmt
            for fid, label, ext in import_choices + export_choices:
                if fid in all_defs:
                    fmt = all_defs[fid]
                    # Only add once
                    continue
            # Simpler: just iterate registry formats
            for fmt in self.session.manager.registry.formats():
                imp = "Yes" if fmt.can_import else "—"
                exp = "Yes" if fmt.can_export else "—"
                lines.append(f"{fmt.name:<30} {','.join(fmt.extensions):<8} {imp:<8} {exp:<8} {fmt.description}")
            # Add pfp
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
            self.source_path_var.set(path)
            self._inspect()

    def _clear_source(self) -> None:
        self.source_path_var.set("")
        self.preview_result = None
        self._write_preview(["No file selected. Browse to pick a source file."])
        self.status_var.set("Choose a source file to begin.")

    def _inspect(self) -> None:
        path = self.source_path_var.get().strip()
        if not path:
            self._write_preview(["No file selected. Use Browse… to pick a source file, then Inspect."])
            return
        if not Path(path).is_file():
            self._write_preview([f"File not found:\n{path}\n\nCheck the path or use Browse…"])
            self.status_var.set("Source file not found.")
            return
        fid = self._selected_import_id()
        try:
            result = self.session.preview_import(path, format_id=fid)
        except Exception as exc:
            self._write_preview([f"Error reading file:\n{exc}"])
            self.status_var.set("Error inspecting file.")
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
            # Auto-suggest dest if empty
            if not self.dest_path_var.get().strip():
                self._auto_suggest_dest()
        if result.issues:
            lines.append("")
            lines.append("Messages:")
            lines += [f"  [{i.severity}] {i.message}" for i in result.issues]
        self._write_preview(lines)

    def _auto_suggest_dest(self, force: bool = False) -> None:
        # Suggest destination filename based on preview project name or source basename
        if self.dest_path_var.get().strip() and not force:
            return
        src = self.source_path_var.get().strip()
        base_name = None
        if self.preview_result and self.preview_result.project is not None:
            base_name = _safe_name(self.preview_result.project.name)
        elif src:
            base_name = Path(src).stem
            base_name = _safe_name(base_name) if base_name else "project"
        else:
            # Use current project name
            try:
                base_name = _safe_name(self.session.project.name)
            except Exception:
                base_name = "project"
        fid, ext = self._selected_export_id()
        if ext is None:
            ext = ".xml"  # default
        suggested = str(Path.home() / f"{base_name}{ext}")
        # Prefer same folder as source if source exists
        if src:
            try:
                if Path(src).parent.exists():
                    suggested = str(Path(src).parent / f"{base_name}{ext}")
            except Exception:
                pass
        self.dest_path_var.set(suggested)

    def _browse_dest(self) -> None:
        fid, ext = self._selected_export_id()
        # Build filetypes for current format
        if ext:
            ftypes = [(f"*{ext}", f"*{ext}"), ("All files", "*.*")]
        else:
            ftypes = FILE_FILTERS
        initial = Path(self.dest_path_var.get()).name if self.dest_path_var.get().strip() else ""
        path = filedialog.asksaveasfilename(parent=self.app, title="Where to save converted file", initialfile=initial, defaultextension=ext or "", filetypes=ftypes)
        if path:
            # Ensure extension
            if ext and not path.lower().endswith(ext.lower()):
                path = path + ext
            self.dest_path_var.set(path)

    def _convert(self) -> None:
        src = self.source_path_var.get().strip()
        dest = self.dest_path_var.get().strip()
        if not src:
            messagebox.showwarning("Choose source", "Pick a source file first (Step 1 → Browse…)", parent=self.app)
            return
        if self.preview_result is None or not self.preview_result.success or self.preview_result.project is None:
            # Try to inspect again
            self._inspect()
            if self.preview_result is None or not self.preview_result.success or self.preview_result.project is None:
                messagebox.showerror("Cannot convert", "Source file could not be read. Check the preview for details.", parent=self.app)
                return
        fid, ext = self._selected_export_id()
        if fid is None:
            messagebox.showwarning("Choose format", "Pick a target format in Step 2.", parent=self.app)
            return
        if not dest:
            messagebox.showwarning("Choose destination", "Pick where to save the converted file (Step 2 → Browse… or Suggest name).", parent=self.app)
            return
        # Ensure extension matches chosen format
        if ext and not dest.lower().endswith(ext.lower()):
            dest = dest + ext
            self.dest_path_var.set(dest)

        # Confirm overwrite if exists
        if Path(dest).exists():
            if not messagebox.askyesno("Overwrite?", f"The file already exists:\n{dest}\n\nOverwrite?", parent=self.app):
                return

        self.status_var.set(f"Converting… {Path(src).name} → {Path(dest).name} ({fid})")
        self.convert_button.configure(state="disabled")
        self.app.update_idletasks()
        try:
            # Use the already-inspected project to export
            project = self.preview_result.project
            # Validate via manager export (which re-validates)
            result = self.session.manager.export_file(project, fid, dest, overwrite=True)
            if not result.success:
                details = "; ".join(i.message for i in result.errors) or "Unknown error."
                self.status_var.set(f"Export failed: {details}")
                self._write_preview([f"Export failed for {fid}:"] + [i.message for i in result.errors])
                messagebox.showerror("Export failed", details, parent=self.app)
                return
            self.status_var.set(f"✓ Converted successfully: {dest}")
            self.success_var.set(f"✓ Saved to: {dest}\nFormat: {fid} • Tasks: {len(project.tasks)} • People: {len(project.resources)}")
            if not hasattr(self, "_success_packed") or not self._success_packed:
                self.success_label.pack(anchor="w", pady=(8, 0))
                self._success_packed = True
            messagebox.showinfo("Convert complete", f"Saved converted file to:\n{dest}\n\nFormat: {fid}\nTasks: {len(project.tasks)}\nYou can now open it in the target application.", parent=self.app)
        finally:
            self.convert_button.configure(state="normal")

    def _open_folder(self) -> None:
        dest = self.dest_path_var.get().strip()
        if not dest:
            messagebox.showinfo("No destination", "Choose a destination file first.", parent=self.app)
            return
        p = Path(dest)
        folder = p.parent if p.parent.exists() else Path.home()
        # Try to open folder with best available method
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
        self.source_path_var.set("")
        self.source_format_var.set("Detect automatically")
        self.dest_path_var.set("")
        # reset dest format to first
        try:
            first = self.session.format_choices("export")[0][1]
            self.dest_format_var.set(first)
        except Exception:
            pass
        self.preview_result = None
        self._write_preview(["Reset. Pick a new source file to start another conversion."])
        self.status_var.set("Choose a source file to begin.")
        self.success_var.set("")
        if hasattr(self, "_success_packed") and self._success_packed:
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
        self.clipboard_clear()
        self.clipboard_append(example)
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
        self.preview_text.configure(background=p["panel"], foreground=p["text"])
        self.formats_text.configure(background=p["panel"], foreground=p["text"])
        self._refresh_combos()
        self._fill_formats_table()
        # If source already selected but preview not yet shown, inspect
        # (defer to avoid spamming on every refresh)
        if self.source_path_var.get().strip() and self.preview_result is None:
            # don't auto - user explicit
            pass

    def on_show(self) -> None:
        self.refresh()
        self._fill_formats_table()

__all__ = ["ConvertView"]

