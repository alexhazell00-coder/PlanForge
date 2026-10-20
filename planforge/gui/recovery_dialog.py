"""Crash-recovery chooser; snapshots remain separate from normal project files."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from planforge.recovery import RecoveryRecord, clear_recovery_snapshot


class RecoveryDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, app: Any, records: list[RecoveryRecord], warnings: list[str] | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.records = list(records)
        self.title("Recover Previous Work?")
        self.transient(parent.winfo_toplevel())
        self.geometry("620x360")
        self.minsize(500, 280)
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="PlanForge found crash-recovery snapshots.", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(body, text="Choose a snapshot to restore. Recovery does not overwrite the original project file.",
                  style="Muted.TLabel", wraplength=560).pack(anchor="w", pady=(4, 10))
        self.listbox = tk.Listbox(body, exportselection=False, height=8)
        self.listbox.pack(fill="both", expand=True)
        for item in self.records:
            source = f"  ·  {item.source_path.name}" if item.source_path else "  ·  unsaved project"
            self.listbox.insert("end", f"{item.project_name}  ·  {item.saved_at}{source}")
        self.status_var = tk.StringVar(value=(warnings[0] if warnings else "Select a snapshot to restore or discard."))
        ttk.Label(body, textvariable=self.status_var, style="Muted.TLabel", wraplength=560).pack(anchor="w", pady=(8, 4))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Discard Selected…", command=self._discard).pack(side="left")
        ttk.Button(buttons, text="Later", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Restore Selected", style="Accent.TButton", command=self._restore).pack(side="right", padx=6)
        if self.records:
            self.listbox.selection_set(0)
        self.listbox.bind("<Double-1>", lambda _event: self._restore())
        self.listbox.bind("<Return>", lambda _event: self._restore())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()

    def _selected(self) -> RecoveryRecord | None:
        selected = self.listbox.curselection()
        return self.records[selected[0]] if selected and selected[0] < len(self.records) else None

    def _restore(self) -> None:
        item = self._selected()
        if not item:
            self.status_var.set("Select a recovery snapshot first.")
            return
        source = item.source_path
        if source is not None and not source.exists():
            source = None
        if not self.app.perform(self.app.session.restore_recovery, item.snapshot_path, source):
            return
        self.app.status_var.set(f"Recovered '{item.project_name}'. Save it to preserve the recovered changes.")
        self.destroy()

    def _discard(self) -> None:
        item = self._selected()
        if not item:
            self.status_var.set("Select a recovery snapshot first.")
            return
        if not messagebox.askyesno("Discard recovery", f"Permanently discard the recovery copy of '{item.project_name}'?",
                                  parent=self):
            return
        clear_recovery_snapshot(item.project_id)
        index = self.listbox.curselection()[0]
        self.listbox.delete(index)
        self.records.pop(index)
        if not self.records:
            self.status_var.set("No recovery snapshots remain.")
        else:
            self.listbox.selection_set(min(index, len(self.records) - 1))


__all__ = ["RecoveryDialog"]
