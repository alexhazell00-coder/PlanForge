"""Timeline tab: a Gantt chart drawn on a Canvas.

Task names sit in a fixed column on the left. Bars, milestones, summary
brackets, dependency arrows and the "today" marker are drawn on a scrollable
chart. The two canvases scroll vertically together.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from typing import Any

from planforge.config import format_date, get_preference, set_preference
from planforge.gui.views import BaseView
from planforge.scheduling.engine import is_working_day
from planforge.session import DEPENDENCY_TYPES

ZOOM_PIXELS_PER_DAY = {"Days": 22, "Weeks": 8, "Months": 3}
ROW_HEIGHT = 28
HEADER_HEIGHT = 48
LABEL_WIDTH = 280
PAD_DAYS_BEFORE = 3
PAD_DAYS_AFTER = 10


class TimelineView(BaseView):
    def _build(self) -> None:
        self._title("Timeline & Gantt Chart", "Red bars are on the critical path. Arrows show dependencies.")
        bar = self._toolbar()
        saved_zoom = get_preference("workspace", "timeline_zoom", "Days")
        self.zoom_var = tk.StringVar(value=saved_zoom if saved_zoom in ZOOM_PIXELS_PER_DAY else "Days")
        self.zoom_var.trace_add("write", self._save_zoom_preference)
        for name in ZOOM_PIXELS_PER_DAY:
            ttk.Radiobutton(bar, text=name, value=name, variable=self.zoom_var,
                            command=self.refresh, style="TRadiobutton").pack(side="left", padx=(0, 8))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self.names = tk.Canvas(body, width=LABEL_WIDTH, highlightthickness=0, borderwidth=0)
        self.chart = tk.Canvas(body, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(body, orient="vertical", command=self._yview)
        self.hbar = ttk.Scrollbar(body, orient="horizontal", command=self.chart.xview)
        self.chart.configure(xscrollcommand=self.hbar.set, yscrollcommand=self._on_yscroll)
        self.names.grid(row=0, column=0, sticky="ns")
        self.chart.grid(row=0, column=1, sticky="nsew")
        self.vbar.grid(row=0, column=2, sticky="ns")
        self.hbar.grid(row=1, column=1, sticky="ew")

        for widget in (self.chart, self.names):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", self._on_wheel)
            widget.bind("<Button-5>", self._on_wheel)
        self.chart.bind("<Shift-MouseWheel>", self._on_hwheel)
        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Edit Task…", command=self._edit_context_task)
        self.context_menu.add_command(label="Show in Task List", command=self._show_context_task)
        self.chart.bind("<Button-3>", self._show_context_menu)
        self.chart.bind("<Control-Button-1>", self._show_context_menu)
        self._context_task_id: str | None = None

    # --- persistent workspace preference

    def _save_zoom_preference(self, *_args: Any) -> None:
        zoom = self.zoom_var.get()
        if zoom in ZOOM_PIXELS_PER_DAY:
            try:
                set_preference("workspace", "timeline_zoom", zoom)
            except OSError:
                pass

    # --- scrolling

    def _yview(self, *args: str) -> None:
        self.chart.yview(*args)
        self.names.yview(*args)

    def _on_yscroll(self, first: str, last: str) -> None:
        self.vbar.set(first, last)
        self.names.yview_moveto(first)

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            steps = -3
        elif getattr(event, "num", None) == 5:
            steps = 3
        else:
            steps = -3 if event.delta > 0 else 3
        self._yview("scroll", steps, "units")
        return "break"

    def _on_hwheel(self, event: tk.Event) -> str:
        self.chart.xview("scroll", -3 if event.delta > 0 else 3, "units")
        return "break"

    def _show_context_menu(self, event: tk.Event) -> str:
        y = self.chart.canvasy(event.y)
        index = int((y - HEADER_HEIGHT) // ROW_HEIGHT)
        rows = self.session.task_rows()
        if index < 0 or index >= len(rows):
            return "break"
        self._context_task_id = rows[index].task.id
        self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()
        return "break"

    def _edit_context_task(self) -> None:
        if self._context_task_id:
            self.app.views["tasks"].edit_task_by_id(self._context_task_id)

    def _show_context_task(self) -> None:
        if self._context_task_id:
            self.app.views["tasks"].select_task_by_id(self._context_task_id)
            self.app.select_tab_by_key("tasks")

    # --- drawing

    def refresh(self) -> None:
        self._draw()

    def _draw(self) -> None:
        p = self.app.palette
        session = self.session
        project = session.project
        rows = session.task_rows()
        zoom = self.zoom_var.get()
        ppd = ZOOM_PIXELS_PER_DAY.get(zoom, 22)

        self.chart.configure(background=p["panel"])
        self.names.configure(background=p["panel"])
        self.chart.delete("all")
        self.names.delete("all")

        dated = [r.task for r in rows if r.task.start_date and r.task.finish_date]
        if not rows or not dated:
            self.chart.configure(scrollregion=(0, 0, 400, 100))
            self.names.configure(scrollregion=(0, 0, LABEL_WIDTH, 100))
            self.chart.create_text(16, 24, anchor="w", fill=p["muted"],
                                   text="Add tasks with durations to see the timeline.")
            return

        start = min(t.start_date for t in dated) - timedelta(days=PAD_DAYS_BEFORE)
        finish = max(t.finish_date for t in dated) + timedelta(days=PAD_DAYS_AFTER)
        days = (finish - start).days + 1
        width = days * ppd
        height = HEADER_HEIGHT + len(rows) * ROW_HEIGHT
        self.chart.configure(scrollregion=(0, 0, width, height))
        self.names.configure(scrollregion=(0, 0, LABEL_WIDTH, height))

        calendar = project.calendars[0] if project.calendars else None

        def x_of(day: date) -> float:
            return (day - start).days * ppd

        def row_center(index: int) -> float:
            return HEADER_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT / 2

        c = self.chart
        # Row bands and non-working days.
        for index in range(len(rows)):
            top = HEADER_HEIGHT + index * ROW_HEIGHT
            if index % 2:
                c.create_rectangle(0, top, width, top + ROW_HEIGHT, fill=p["row_alt"], outline="")
        if ppd >= 8:
            for offset in range(days):
                day = start + timedelta(days=offset)
                if not is_working_day(day, calendar):
                    x = offset * ppd
                    c.create_rectangle(x, HEADER_HEIGHT, x + ppd, height, fill=p["weekend"], outline="")

        self._draw_header(start, finish, ppd, width)

        # Horizontal grid lines.
        for index in range(len(rows) + 1):
            y = HEADER_HEIGHT + index * ROW_HEIGHT
            c.create_line(0, y, width, y, fill=p["grid"])

        # Today marker.
        today = date.today()
        if start <= today <= finish:
            x = x_of(today) + ppd / 2
            c.create_line(x, HEADER_HEIGHT, x, height, fill=p["today"], dash=(4, 3))

        # Geometry for each task: (left, right, centre_y).
        index_of = {r.task.id: i for i, r in enumerate(rows)}
        geometry: dict[str, tuple[float, float, float]] = {}
        for index, r in enumerate(rows):
            task = r.task
            if not (task.start_date and task.finish_date):
                continue
            is_milestone = task.milestone or task.task_type == "milestone"
            left = x_of(task.start_date)
            if is_milestone:
                centre = left + ppd / 2
                geometry[task.id] = (centre, centre, row_center(index))
            else:
                geometry[task.id] = (left, x_of(task.finish_date) + ppd, row_center(index))

        # Dependency arrows, drawn before the bars so the bars sit on top.
        for dep in project.dependencies:
            pred = geometry.get(dep.predecessor_id)
            succ = geometry.get(dep.successor_id)
            if pred is None or succ is None:
                continue
            if dep.predecessor_id not in index_of or dep.successor_id not in index_of:
                continue
            kind = dep.relationship_type if dep.relationship_type in DEPENDENCY_TYPES else "finish_to_start"
            pred_x = pred[0] if kind in ("start_to_start", "start_to_finish") else pred[1]
            succ_x = succ[1] if kind in ("finish_to_finish", "start_to_finish") else succ[0]
            elbow = min(pred_x, succ_x) - 4 if succ_x < pred_x else pred_x + 8
            c.create_line(pred_x, pred[2], elbow, pred[2], elbow, succ[2], succ_x, succ[2],
                          fill=p["link"], width=1, arrow="last", arrowshape=(8, 10, 4))

        # Bars, milestones and summary brackets.
        for index, r in enumerate(rows):
            task = r.task
            if task.id not in geometry:
                continue
            left, right, yc = geometry[task.id]
            critical = bool(task.custom_fields.get("is_critical"))
            if task.milestone or task.task_type == "milestone":
                c.create_polygon(left, yc - 9, left + 9, yc, left, yc + 9, left - 9, yc,
                                 fill=p["milestone"], outline="")
                continue
            if r.is_summary:
                c.create_rectangle(left, yc - 4, right, yc + 2, fill=p["summary"], outline="")
                c.create_rectangle(left, yc - 4, left + 4, yc + 9, fill=p["summary"], outline="")
                c.create_rectangle(right - 4, yc - 4, right, yc + 9, fill=p["summary"], outline="")
                continue
            base = p["bar_critical"] if critical else p["bar"]
            done = p["bar_critical_done"] if critical else p["bar_done"]
            c.create_rectangle(left, yc - 8, right, yc + 8, fill=base, outline="")
            progress = max(0.0, min(100.0, task.percent_complete or 0.0))
            if progress > 0:
                c.create_rectangle(left, yc - 8, left + (right - left) * progress / 100, yc + 8,
                                   fill=done, outline="")

        # Left-hand task names, aligned with the chart rows.
        n = self.names
        n.create_rectangle(0, 0, LABEL_WIDTH, HEADER_HEIGHT, fill=p["bg"], outline="")
        n.create_text(12, HEADER_HEIGHT / 2, anchor="w", fill=p["muted"], font=("Helvetica", 9, "bold"),
                      text="TASK")
        n.create_line(LABEL_WIDTH - 1, 0, LABEL_WIDTH - 1, height, fill=p["border"])
        for index, r in enumerate(rows):
            task = r.task
            yc = row_center(index)
            indent = 10 + r.depth * 16
            if r.is_summary:
                font = ("Helvetica", 10, "bold")
                color = p["summary"]
                label = "▾ " + task.name
            elif task.milestone or task.task_type == "milestone":
                font = ("Helvetica", 10)
                color = p["milestone"]
                label = "◆ " + task.name
            else:
                font = ("Helvetica", 10)
                color = p["danger"] if task.custom_fields.get("is_critical") else p["text"]
                label = task.name
            n.create_text(indent, yc, anchor="w", fill=color, font=font, text=label)

    def _draw_header(self, start: date, finish: date, ppd: int, width: int) -> None:
        p = self.app.palette
        c = self.chart
        c.create_rectangle(0, 0, width, HEADER_HEIGHT, fill=p["bg"], outline="")
        c.create_line(0, HEADER_HEIGHT, width, HEADER_HEIGHT, fill=p["border"])
        zoom = self.zoom_var.get()
        days = (finish - start).days + 1

        if zoom == "Days":
            last_month = None
            for offset in range(days):
                day = start + timedelta(days=offset)
                x = offset * ppd
                if day.month != last_month:
                    last_month = day.month
                    c.create_text(x + 4, 12, anchor="w", fill=p["text"], font=("Helvetica", 9, "bold"),
                                  text=day.strftime("%B %Y"))
                if ppd >= 16 or day.day % 2 == 1:
                    c.create_text(x + ppd / 2, 32, anchor="center", fill=p["muted"], font=("Helvetica", 8),
                                  text=str(day.day))
                if day.weekday() == 0:
                    c.create_line(x, HEADER_HEIGHT - 6, x, HEADER_HEIGHT, fill=p["muted"])
        elif zoom == "Weeks":
            day = start
            while day <= finish:
                x = (day - start).days * ppd
                c.create_line(x, HEADER_HEIGHT - 16, x, HEADER_HEIGHT, fill=p["muted"])
                c.create_text(x + 4, 16, anchor="w", fill=p["text"], font=("Helvetica", 9, "bold"),
                              text=format_date(day))
                c.create_text(x + 4, 34, anchor="w", fill=p["muted"], font=("Helvetica", 8),
                              text="week")
                day += timedelta(days=7)
        else:  # Months
            day = date(start.year, start.month, 1)
            while day <= finish:
                x = max((day - start).days, 0) * ppd
                c.create_line(x, 0, x, HEADER_HEIGHT, fill=p["grid"])
                c.create_text(x + 6, HEADER_HEIGHT / 2, anchor="w", fill=p["text"], font=("Helvetica", 9, "bold"),
                              text=day.strftime("%b %Y"))
                day = date(day.year + (day.month // 12), day.month % 12 + 1, 1)


__all__ = ["TimelineView", "ZOOM_PIXELS_PER_DAY"]
