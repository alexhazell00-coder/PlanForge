"""PlanForge command line and server entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from planforge.interchange import InterchangeManager
from planforge.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="PlanForge — Project Planner and Interoperability Engine")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind application server (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind application server (default: 0.0.0.0)")
    parser.add_argument("--import-file", type=str, help="Import a project file and print summary")
    parser.add_argument("--export-file", type=str, help="Export path")
    parser.add_argument("--export-format", type=str, default="microsoft-project-xml", help="Format to export (e.g. microsoft-project-xml, ganttproject, csv, planforge-json)")

    args = parser.parse_args()

    if args.import_file:
        mgr = InterchangeManager()
        res = mgr.import_file(args.import_file)
        if not res.success or res.project is None:
            print(f"Error importing {args.import_file}:", file=sys.stderr)
            for err in res.errors:
                print(f" - {err.message}", file=sys.stderr)
            sys.exit(1)

        print(f"Successfully imported '{res.project.name}' ({res.source_format}):")
        print(f" - Tasks: {len(res.project.tasks)}")
        print(f" - Dependencies: {len(res.project.dependencies)}")
        print(f" - Resources: {len(res.project.resources)}")
        print(f" - Assignments: {len(res.project.assignments)}")

        if args.export_file:
            exp_res = mgr.export_file(res.project, args.export_format, args.export_file, overwrite=True)
            if not exp_res.success:
                print(f"Error exporting to {args.export_file}:", file=sys.stderr)
                for err in exp_res.errors:
                    print(f" - {err.message}", file=sys.stderr)
                sys.exit(1)
            print(f"Successfully exported to {args.export_file} ({args.export_format})")
        return

    # Start the server
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
