"""PlanForge import/export foundation.

Only PlanForge JSON and the documented CSV template are implemented in this
checkout. Format metadata is exposed through :class:`FormatRegistry`; no UI or
external-application compatibility is implied.
"""

from planforge.interchange.comparison import ComparisonResult, compare_projects
from planforge.interchange.csv_adapter import CsvImportOptions
from planforge.interchange.registry import FormatRegistry, InterchangeManager
from planforge.interchange.results import ExportResult, ImportResult, ProjectSummary
from planforge.interchange.validation import ValidationIssue, ValidationReport, validate_project

__all__ = [
    "ComparisonResult",
    "CsvImportOptions",
    "ExportResult",
    "FormatRegistry",
    "ImportResult",
    "InterchangeManager",
    "ProjectSummary",
    "ValidationIssue",
    "ValidationReport",
    "compare_projects",
    "validate_project",
]
