"""Shared import/export results and preview summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from planforge.model import Project
from planforge.interchange.validation import ValidationIssue


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    name: str
    task_count: int
    subtask_count: int
    dependency_count: int
    resource_count: int
    assignment_count: int
    milestone_count: int
    start_date: date | None
    finish_date: date | None


def summarize_project(project: Project) -> ProjectSummary:
    starts = [task.start_date for task in project.tasks if task.start_date is not None]
    finishes = [task.finish_date for task in project.tasks if task.finish_date is not None]
    if project.start_date is not None:
        starts.append(project.start_date)
    if project.finish_date is not None:
        finishes.append(project.finish_date)
    start_date = min(starts) if starts else None
    finish_date = max(finishes) if finishes else None
    return ProjectSummary(
        name=project.name,
        task_count=len(project.tasks),
        subtask_count=sum(task.parent_id is not None for task in project.tasks),
        dependency_count=len(project.dependencies),
        resource_count=len(project.resources),
        assignment_count=len(project.assignments),
        milestone_count=sum(task.milestone or task.task_type == "milestone" for task in project.tasks),
        start_date=start_date,
        finish_date=finish_date,
    )


@dataclass(frozen=True, slots=True)
class ImportResult:
    source_format: str
    project: Project | None
    issues: tuple[ValidationIssue, ...] = ()
    schema_version: int | None = None

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def success(self) -> bool:
        return self.project is not None and not self.errors

    @property
    def summary(self) -> ProjectSummary | None:
        return summarize_project(self.project) if self.project is not None else None


@dataclass(frozen=True, slots=True)
class ExportResult:
    target_format: str
    data: bytes | None
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def success(self) -> bool:
        return self.data is not None and not self.errors


__all__ = ["ExportResult", "ImportResult", "ProjectSummary", "summarize_project"]
