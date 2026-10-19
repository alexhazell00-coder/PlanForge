"""Scheduling calculation engine for PlanForge.

Implements forward and backward pass critical-path calculations, working-day
calendar progression, dependency lag handling, daily capacity calculations,
summary task aggregation, and float/critical-path analysis.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import date, timedelta
from typing import Sequence

from planforge.model import Calendar, Dependency, Project, Resource, Task


def is_working_day(target_date: date, calendar: Calendar | None = None) -> bool:
    """Check if a date is a working day according to the calendar."""
    iso_weekday = target_date.weekday()  # 0=Monday, 6=Sunday
    working_days = calendar.working_days if calendar is not None else [0, 1, 2, 3, 4]
    holidays = set(calendar.holidays) if calendar is not None else set()
    return (iso_weekday in working_days) and (target_date not in holidays)


def add_working_days(start: date, days: int, calendar: Calendar | None = None) -> date:
    """Advance (or reverse if days < 0) by a count of whole working days."""
    if days == 0:
        curr = start
        while not is_working_day(curr, calendar):
            curr += timedelta(days=1)
        return curr

    step = 1 if days > 0 else -1
    remaining = abs(days)
    curr = start
    while remaining > 0:
        curr += timedelta(days=step)
        if is_working_day(curr, calendar):
            remaining -= 1
    return curr


def working_days_between(start: date, finish: date, calendar: Calendar | None = None) -> int:
    """Calculate the number of working days between start and finish inclusive."""
    if start > finish:
        return 0
    count = 0
    curr = start
    while curr <= finish:
        if is_working_day(curr, calendar):
            count += 1
        curr += timedelta(days=1)
    return count


def calculate_daily_capacity(task: Task, project: Project) -> float:
    """Calculate the hours of daily work capacity allocated to a task.

    If nobody is assigned, defaults to 8.0 hours.
    Otherwise, sum over assigned people of (allocation % * that person's daily hours).
    """
    assignments = [a for a in project.assignments if a.task_id == task.id]
    if not assignments:
        return 8.0

    res_map = {r.id: r for r in project.resources}
    total_capacity = 0.0
    for a in assignments:
        res = res_map.get(a.resource_id)
        # Standard working day is 8 hours unless specified
        person_hours_per_day = 8.0
        if res and "hours_per_day" in res.custom_fields:
            try:
                person_hours_per_day = float(res.custom_fields["hours_per_day"])  # type: ignore[arg-type]
            except (ValueError, TypeError):
                pass
        total_capacity += a.units * person_hours_per_day

    return max(1.0, total_capacity)


def schedule_project(project: Project) -> Project:
    """Perform forward and backward passes to compute schedule dates and float.

    Updates task start_date, finish_date, float, and identifies critical tasks.
    """
    cal = project.calendars[0] if project.calendars else None
    proj_start = project.start_date or (
        min((t.start_date for t in project.tasks if t.start_date), default=date.today())
    )

    # Map children and parents
    tasks_by_id = {t.id: t for t in project.tasks}
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    for t in project.tasks:
        if t.parent_id:
            children_by_parent[t.parent_id].append(t.id)

    # Dependencies
    preds_map: dict[str, list[Dependency]] = defaultdict(list)
    succs_map: dict[str, list[Dependency]] = defaultdict(list)
    for dep in project.dependencies:
        if dep.predecessor_id in tasks_by_id and dep.successor_id in tasks_by_id:
            preds_map[dep.successor_id].append(dep)
            succs_map[dep.predecessor_id].append(dep)

    # Topological sort for leaf tasks
    in_degree: dict[str, int] = {t.id: 0 for t in project.tasks}
    for dep in project.dependencies:
        if dep.successor_id in in_degree and dep.predecessor_id in tasks_by_id:
            in_degree[dep.successor_id] += 1

    queue = deque([t_id for t_id, deg in in_degree.items() if deg == 0])
    topo_order: list[str] = []
    while queue:
        curr = queue.popleft()
        topo_order.append(curr)
        for dep in succs_map.get(curr, []):
            in_degree[dep.successor_id] -= 1
            if in_degree[dep.successor_id] == 0:
                queue.append(dep.successor_id)

    # In case of cycles, append any remaining tasks
    for t in project.tasks:
        if t.id not in topo_order:
            topo_order.append(t.id)

    # 1. Forward pass
    earliest_start: dict[str, date] = {}
    earliest_finish: dict[str, date] = {}

    for t_id in topo_order:
        task = tasks_by_id[t_id]
        if task.id in children_by_parent:
            # Summary task dates are determined by children later
            continue

        # Calculate duration in working days
        is_m = task.milestone or task.task_type == "milestone"
        if is_m:
            dur_days = 0
        elif task.duration is not None and task.duration_unit == "day":
            dur_days = max(1, int(round(task.duration)))
        elif task.estimated_work is not None:
            capacity = calculate_daily_capacity(task, project)
            dur_days = max(1, math.ceil(task.estimated_work / capacity))
        else:
            dur_days = 1

        # Determine earliest valid start date
        candidate_starts = [proj_start]
        if task.start_date:
            candidate_starts.append(task.start_date)

        for dep in preds_map.get(t_id, []):
            pred_id = dep.predecessor_id
            pred_finish = earliest_finish.get(pred_id, proj_start)
            pred_start = earliest_start.get(pred_id, proj_start)
            lag_days = int(round(dep.lag))

            if dep.relationship_type == "finish_to_start":
                req_start = add_working_days(pred_finish, lag_days + 1, cal)
                candidate_starts.append(req_start)
            elif dep.relationship_type == "start_to_start":
                req_start = add_working_days(pred_start, lag_days, cal)
                candidate_starts.append(req_start)
            elif dep.relationship_type == "finish_to_finish":
                # finish >= pred_finish + lag => start >= pred_finish + lag - dur
                req_fin = add_working_days(pred_finish, lag_days, cal)
                req_start = add_working_days(req_fin, -max(0, dur_days - 1), cal)
                candidate_starts.append(req_start)
            elif dep.relationship_type == "start_to_finish":
                req_fin = add_working_days(pred_start, lag_days, cal)
                req_start = add_working_days(req_fin, -max(0, dur_days - 1), cal)
                candidate_starts.append(req_start)

        t_start = max(candidate_starts)
        if not is_working_day(t_start, cal):
            t_start = add_working_days(t_start, 0, cal)

        if is_m or dur_days == 0:
            t_finish = t_start
        else:
            t_finish = add_working_days(t_start, dur_days - 1, cal)

        earliest_start[t_id] = t_start
        earliest_finish[t_id] = t_finish

    # Aggregate summary tasks bottom-up
    def aggregate_summary(parent_id: str) -> tuple[date, date]:
        child_starts: list[date] = []
        child_finishes: list[date] = []
        for c_id in children_by_parent.get(parent_id, []):
            if c_id in children_by_parent:
                cs, cf = aggregate_summary(c_id)
            else:
                cs = earliest_start.get(c_id, proj_start)
                cf = earliest_finish.get(c_id, proj_start)
            child_starts.append(cs)
            child_finishes.append(cf)
        s = min(child_starts) if child_starts else proj_start
        f = max(child_finishes) if child_finishes else proj_start
        earliest_start[parent_id] = s
        earliest_finish[parent_id] = f
        return s, f

    for t in project.tasks:
        if t.id in children_by_parent and t.id not in earliest_start:
            aggregate_summary(t.id)

    # 2. Backward pass
    max_finish = max(earliest_finish.values()) if earliest_finish else proj_start
    latest_finish: dict[str, date] = {}
    latest_start: dict[str, date] = {}

    for t_id in reversed(topo_order):
        task = tasks_by_id[t_id]
        if task.id in children_by_parent:
            continue

        is_m = task.milestone or task.task_type == "milestone"
        if is_m:
            dur_days = 0
        elif task.duration is not None and task.duration_unit == "day":
            dur_days = max(1, int(round(task.duration)))
        elif task.estimated_work is not None:
            capacity = calculate_daily_capacity(task, project)
            dur_days = max(1, math.ceil(task.estimated_work / capacity))
        else:
            dur_days = 1

        candidate_finishes = [max_finish]
        if task.deadline:
            candidate_finishes.append(task.deadline)

        for dep in succs_map.get(t_id, []):
            succ_id = dep.successor_id
            succ_start = latest_start.get(succ_id, max_finish)
            succ_finish = latest_finish.get(succ_id, max_finish)
            lag_days = int(round(dep.lag))

            if dep.relationship_type == "finish_to_start":
                req_finish = add_working_days(succ_start, -(lag_days + 1), cal)
                candidate_finishes.append(req_finish)
            elif dep.relationship_type == "finish_to_finish":
                req_finish = add_working_days(succ_finish, -lag_days, cal)
                candidate_finishes.append(req_finish)
            elif dep.relationship_type == "start_to_start":
                # Start must be <= succ_start - lag => finish <= start + dur - 1
                req_start = add_working_days(succ_start, -lag_days, cal)
                req_finish = add_working_days(req_start, max(0, dur_days - 1), cal)
                candidate_finishes.append(req_finish)
            elif dep.relationship_type == "start_to_finish":
                req_start = add_working_days(succ_finish, -lag_days, cal)
                req_finish = add_working_days(req_start, max(0, dur_days - 1), cal)
                candidate_finishes.append(req_finish)

        t_fin = min(candidate_finishes)
        if not is_working_day(t_fin, cal):
            t_fin = add_working_days(t_fin, 0, cal)

        if is_m or dur_days == 0:
            t_st = t_fin
        else:
            t_st = add_working_days(t_fin, -max(0, dur_days - 1), cal)

        latest_finish[t_id] = t_fin
        latest_start[t_id] = t_st

    # Update task fields with scheduled dates and float
    for t in project.tasks:
        if t.id in earliest_start:
            t.start_date = earliest_start[t.id]
        if t.id in earliest_finish:
            t.finish_date = earliest_finish[t.id]

        if t.id in latest_start and t.id in earliest_start:
            float_days = working_days_between(earliest_start[t.id], latest_start[t.id], cal) - 1
            float_days = max(0, float_days)
            t.custom_fields["total_float"] = float_days
            t.custom_fields["is_critical"] = (float_days == 0)
        else:
            t.custom_fields["total_float"] = 0
            t.custom_fields["is_critical"] = False

    project.start_date = min((t.start_date for t in project.tasks if t.start_date), default=proj_start)
    project.finish_date = max((t.finish_date for t in project.tasks if t.finish_date), default=max_finish)

    return project


__all__ = [
    "add_working_days",
    "calculate_daily_capacity",
    "is_working_day",
    "schedule_project",
    "working_days_between",
]
