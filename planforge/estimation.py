"""Bridge to the Simple Function Point Calculator maths.

The calculator's ``fp_logic`` module lives in ``function-point-calculator/`` and
contains no GUI code, so PlanForge imports it directly. Both tools therefore
produce identical hours and costs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FP_DIR = Path(__file__).resolve().parents[1] / "function-point-calculator" / "function-point-calculator-main"
if str(_FP_DIR) not in sys.path:
    sys.path.insert(0, str(_FP_DIR))

import fp_logic  # noqa: E402  (path set up above)

TASK_TYPES = fp_logic.TASK_TYPES
FP_APP_NAME = fp_logic.APP_NAME
FP_FILE_FORMAT_VERSION = fp_logic.FILE_FORMAT_VERSION

__all__ = [
    "FP_APP_NAME",
    "FP_FILE_FORMAT_VERSION",
    "TASK_TYPES",
    "fp_logic",
]
