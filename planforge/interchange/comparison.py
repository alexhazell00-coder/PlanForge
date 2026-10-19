"""Field-level round-trip comparison with explicit loss categories."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from planforge.interchange import csv_adapter, json_adapter
from planforge.interchange.validation import ValidationIssue, validate_project
from planforge.model import Project

NO_DIFFERENCE = "no_meaningful_difference"
EXPECTED_CONVERSION = "expected_format_conversion"
UNSUPPORTED_INFORMATION = "unsupported_information"
UNEXPECTED_DATA_LOSS = "unexpected_data_loss"
SCHEDULING_RECALCULATION = "scheduling_recalculation"


@dataclass(frozen=True, slots=True)
class ProjectDifference:
    path: str
    category: str
    before: Any
    after: Any
    message: str


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    format_id: str
    differences: tuple[ProjectDifference, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def unchanged(self) -> bool:
        return not self.differences and not any(issue.severity == "error" for issue in self.issues)

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(difference.category for difference in self.differences) or frozenset({NO_DIFFERENCE})


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else key
            flattened.update(_flatten(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flattened.update(_flatten(item, f"{prefix}[{index}]"))
        if not value:
            flattened[prefix] = []
    else:
        flattened[prefix] = value
    return flattened


def _numeric_equal(left: Any, right: Any, tolerance: float) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def _duration_equivalent(
    path: str,
    left_value: Any,
    right_value: Any,
    left_flat: dict[str, Any],
    right_flat: dict[str, Any],
    tolerance: float,
) -> bool:
    """Compare exact time units only when no work-calendar assumption is needed."""

    if not path.endswith(".duration") and not path.endswith(".lag"):
        return False
    unit_path = path.rsplit(".", 1)[0] + (".duration_unit" if path.endswith(".duration") else ".lag_unit")
    left_unit, right_unit = left_flat.get(unit_path), right_flat.get(unit_path)
    factors = {
        "minute": 60.0,
        "hour": 3600.0,
        "elapsed_minute": 60.0,
        "elapsed_hour": 3600.0,
        "elapsed_day": 86400.0,
        "elapsed_week": 604800.0,
    }
    if left_unit not in factors or right_unit not in factors:
        return False
    try:
        return math.isclose(
            float(left_value) * factors[left_unit],
            float(right_value) * factors[right_unit],
            rel_tol=tolerance,
            abs_tol=tolerance,
        )
    except (TypeError, ValueError):
        return False


def _category_for(path: str, format_id: str, before: Any, after: Any) -> tuple[str, str]:
    if format_id == csv_adapter.FORMAT_ID and path in {
        "created_at",
        "modified_at",
    }:
        return UNSUPPORTED_INFORMATION, "The CSV template does not include project creation/modification timestamps."
    if any(token in path for token in ("start_date", "finish_date", "deadline", "constraint_date")):
        return SCHEDULING_RECALCULATION, "A scheduling date changed during the round trip; inspect the source and destination schedule."
    if after is None or after == [] or after == {}:
        return UNEXPECTED_DATA_LOSS, "A value present before export is missing after reimport."
    return UNEXPECTED_DATA_LOSS, "A project value changed unexpectedly during the round trip."


def compare_projects(
    before: Project,
    after: Project,
    *,
    format_id: str = "unknown",
    tolerance: float = 1e-9,
) -> ComparisonResult:
    """Compare model content without hiding differences that a format drops."""

    before_report = validate_project(before)
    after_report = validate_project(after)
    validation_issues = before_report.issues + after_report.issues
    if before_report.errors or after_report.errors:
        return ComparisonResult(format_id=format_id, issues=validation_issues)

    left_document = json_adapter.project_to_document(before)["project"]
    right_document = json_adapter.project_to_document(after)["project"]
    left = _flatten(left_document)
    right = _flatten(right_document)
    differences: list[ProjectDifference] = []
    for path in sorted(set(left) | set(right)):
        left_value = left.get(path, _MISSING)
        right_value = right.get(path, _MISSING)
        if left_value is _MISSING or right_value is _MISSING:
            category, message = _category_for(
                path,
                format_id,
                None if left_value is _MISSING else left_value,
                None if right_value is _MISSING else right_value,
            )
            differences.append(ProjectDifference(
                path=path,
                category=category,
                before=None if left_value is _MISSING else left_value,
                after=None if right_value is _MISSING else right_value,
                message=message,
            ))
            continue
        if left_value == right_value:
            continue
        if _numeric_equal(left_value, right_value, tolerance):
            continue
        if _duration_equivalent(path, left_value, right_value, left, right, tolerance):
            differences.append(ProjectDifference(
                path=path,
                category=EXPECTED_CONVERSION,
                before=left_value,
                after=right_value,
                message="Duration values use different units but are exactly equivalent under the supported unit conversion.",
            ))
            continue
        category, message = _category_for(path, format_id, left_value, right_value)
        differences.append(ProjectDifference(path, category, left_value, right_value, message))
    return ComparisonResult(format_id=format_id, differences=tuple(differences), issues=validation_issues)


_MISSING = object()


__all__ = [
    "EXPECTED_CONVERSION",
    "NO_DIFFERENCE",
    "SCHEDULING_RECALCULATION",
    "UNEXPECTED_DATA_LOSS",
    "UNSUPPORTED_INFORMATION",
    "ComparisonResult",
    "ProjectDifference",
    "compare_projects",
]
