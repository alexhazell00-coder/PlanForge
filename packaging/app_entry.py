"""Standalone native application entry point for frozen builds (PyInstaller)."""

from __future__ import annotations

import os
import sys

# On Windows windowed executables (console=False), sys.stdout/sys.stderr are None
# when launched via Explorer double-click. Provide safe streams so print/logging never fail.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

# Ensure statically visible imports for PyInstaller's module graph analyzer
import sqlite3  # noqa: F401, E402
import xml.etree.ElementTree  # noqa: F401, E402
import planforge.estimation  # noqa: F401, E402
import planforge.icons  # noqa: F401, E402
import planforge.interchange  # noqa: F401, E402
from planforge.__main__ import main  # noqa: E402


def run_frozen() -> None:
    # Filter legacy macOS Finder process serial number argument (-psn_...)
    cleaned_argv = [arg for arg in sys.argv[1:] if not arg.startswith("-psn_")]
    main(cleaned_argv)


if __name__ == "__main__":
    run_frozen()
