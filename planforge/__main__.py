"""PlanForge command line entry point.

With no arguments this opens the desktop application. The import and export
flags convert files without opening a window.
"""

from __future__ import annotations

import argparse
import sys

from planforge.interchange import InterchangeManager


def _convert(import_file: str, export_file: str | None, export_format: str) -> int:
    mgr = InterchangeManager()
    res = mgr.import_file(import_file)
    if not res.success or res.project is None:
        print(f"Error importing {import_file}:", file=sys.stderr)
        for err in res.errors:
            print(f" - {err.message}", file=sys.stderr)
        return 1

    print(f"Successfully imported '{res.project.name}' ({res.source_format}):")
    print(f" - Tasks: {len(res.project.tasks)}")
    print(f" - Dependencies: {len(res.project.dependencies)}")
    print(f" - Resources: {len(res.project.resources)}")
    print(f" - Assignments: {len(res.project.assignments)}")

    if export_file:
        exp_res = mgr.export_file(res.project, export_format, export_file, overwrite=True)
        if not exp_res.success:
            print(f"Error exporting to {export_file}:", file=sys.stderr)
            for err in exp_res.errors:
                print(f" - {err.message}", file=sys.stderr)
            return 1
        print(f"Successfully exported to {export_file} ({export_format})")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PlanForge — Project Planner and Interoperability Engine")
    parser.add_argument("project", nargs="?", help="PlanForge project (.pfp) to open when the window starts")
    parser.add_argument("--import-file", type=str, help="Import a project file and print a summary (no window)")
    parser.add_argument("--export-file", type=str, help="Export path used with --import-file")
    parser.add_argument("--export-format", type=str, default="microsoft-project-xml",
                        help="Format to export (e.g. microsoft-project-xml, ganttproject, csv, planforge-json)")
    args = parser.parse_args(argv)

    if args.import_file:
        sys.exit(_convert(args.import_file, args.export_file, args.export_format))

    try:
        from planforge.gui.app import run
    except ImportError as exc:
        print(
            "PlanForge's window needs Tkinter, which is not available in this Python:\n"
            f"  {exc}\n"
            "Install Tk support: 'sudo apt install python3-tk' on Debian/Ubuntu, "
            "or use the python.org installer on Windows and macOS.",
            file=sys.stderr,
        )
        sys.exit(1)
    run(args.project)


if __name__ == "__main__":
    main()
