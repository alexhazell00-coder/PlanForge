# PlanForge Interoperability (checkout status: 2026-10-19)

## Repository audit and scope

The checked-out repository contains a README, a settings file, and an uninitialized `function-point-calculator` gitlink. It does **not** contain the PlanForge desktop application, its SQLite `.pfp` storage, the documented scheduling/estimation/UI modules, launchers, dependency file, or the original test suite. The referenced submodule commit is not available in the checkout. Consequently, this implementation is an isolated, standard-library interoperability foundation; it is not wired to a Qt menu, existing project database, or the Function Point Calculator application.

This boundary is intentional: the data classes below are an explicit exchange contract, not a claim that the missing desktop model or project files have been migrated. Restore the application source before attempting UI integration or changing `.pfp` storage.

## Current compatibility matrix

"Implemented" means the adapter parses or writes the format and has automated tests within this repository. It does not mean the file was tested in ProjectLibre, Microsoft Project, GanttProject, or the absent PlanForge desktop application.

| Format | PlanForge adapter import | PlanForge adapter export | Canonical field coverage | Adapter round-trip tests | External-application round-trip test |
| --- | --- | --- | --- | --- | --- |
| PlanForge JSON (`.json`) | Yes | Yes | Full v1 model; unknown JSON retained in extensions | Yes, model-level | Not performed |
| PlanForge CSV template (`.csv`) | Yes | Yes | Full v1 model via explicit columns and JSON-in-cell fields | Yes, model-level | Not performed |
| Unfamiliar CSV with mapped columns | Yes | N/A | Mapped subset; unmapped cells retained as text metadata | Mapping/import tests | Not performed |
| Microsoft Project XML / MSPDI (`.xml`) | No | No | None | No | No |
| ProjectLibre POD (`.pod`) | No | No | None | No | No |
| Microsoft Project MPP (`.mpp`) | No | No | None | No | No |
| GanttProject GAN (`.gan`) | No | No | None | No | No |
| Calculator-specific JSON | No | No | None | No | No |
| PlanForge SQLite project (`.pfp`) | No | No | None | No | No |

The registry lists only JSON and CSV. Unsupported formats are not shown as available, and requests to use them return a clear error. XML, POD, MPP, and GAN support must not be advertised until adapters exist and real target-application round trips have been completed.

## Modules

- `planforge/model.py`: explicit project/task/resource/dependency/assignment/calendar exchange model. Task dates are date-only values; no timezone conversion or schedule recalculation occurs.
- `planforge/interchange/json_adapter.py`: versioned PlanForge JSON parser, v0-to-v1 migration, unknown-field preservation, and exporter.
- `planforge/interchange/csv_adapter.py`: UTF-8 CSV reader/writer, header suggestions, user mappings, standard template, and JSON-in-cell fields for richer relationships.
- `planforge/interchange/validation.py`: IDs, references, calendars, dates, ranges, self-links, and circular task/dependency checks.
- `planforge/interchange/registry.py`: adapter registry, content-first detection, file-size limits, and atomic export.
- `planforge/interchange/comparison.py`: field-level round-trip comparison and explicit loss classifications.
- `schemas/planforge-project-v1.schema.json`: Draft 2020-12 JSON Schema for the version 1 format.

Python 3.10 or newer is expected. Runtime dependencies are Python's standard library only.

## PlanForge JSON v1

A file has this top-level shape (abbreviated; exports include all fields in the schema):

```json
{
  "format": "planforge-project",
  "schema_version": 1,
  "project": {
    "id": "project-id",
    "name": "Example",
    "tasks": [],
    "dependencies": [],
    "resources": [],
    "assignments": [],
    "calendars": []
  }
}
```

Export includes all model fields (including null/empty values) for a stable schema. The JSON representation covers project metadata and external IDs, task hierarchy and schedule properties, date-only start/finish/deadline/constraint dates, duration and work units, progress, costs, custom fields, Function Point Calculator counts/complexities/derived values, dependency types and lag, resources, assignments (with separate work units), calendar weeks/exceptions/holidays, external IDs, and namespaced extensions.

Dates use `YYYY-MM-DD`; they are not parsed as midnight UTC. Timestamps are ISO strings and keep their supplied offset. Unknown JSON properties are retained under `extensions` in the `org.planforge.interchange:unknown-fields` or `org.planforge.interchange:unknown-root-fields` namespace. Unknown data is inert JSON: it is never evaluated or instantiated as Python objects. Duplicate object keys, non-standard `NaN`/infinite values, future schema versions, invalid date strings, and invalid structures are rejected with diagnostics.

Unversioned version-0 draft documents are migrated to v1 by adding the format/version and missing collection defaults. This migration is not a compatibility promise for historical desktop-app exports because those implementations and fixtures are absent.

## CSV template and mappings

The standard template is one row per task. It has task columns for ID, name, notes, parent, order, dates, duration/unit, completion, priority, milestone/type, schedule mode, deadline/constraint, work, costs, external IDs, and custom fields. Project metadata uses `project_*` headers. The following columns hold JSON values inside correctly quoted CSV cells:

- `dependencies_json`: an array of predecessor links; each link has stable predecessor/successor IDs, one of the four dependency types, lag and lag unit.
- `assignments_json`: assignments for that task, including assigned resource ID, units, work and its unit, actual/remaining work and costs.
- `resources_json`: resource catalog, including rates, availability, calendars, notes and extensions.
- `calendars_json`: project calendars, working days/hours, holidays and exceptions.
- `custom_fields_json`, `function_points_json`, and `*_extensions_json`: structured data not represented in ordinary columns.

Project-level columns (scalar and JSON) are populated on the first data row (or the sole metadata row for an empty project). Keep that row when editing the file. CSV without the JSON columns is a useful task-list interchange, but does not itself imply a complete schedule. Resource names in a plain `resources`/`resource_names` column are grouped by case-insensitive name within the newly imported CSV and produce a warning; no existing project resources are merged.

For an unfamiliar CSV, `suggest_column_mapping(headers)` proposes aliases. Pass explicit mappings from canonical field to source header through `CsvImportOptions`:

```python
from planforge.interchange import CsvImportOptions, InterchangeManager

result = InterchangeManager().import_file(
    "tasks-export.csv",
    csv_options=CsvImportOptions(
        delimiter=";",
        column_mapping={
            "task_id": "Reference",
            "task_name": "Activity",
            "start_date": "Begin",
            "finish_date": "End",
            "percent_complete": "Done",
            "predecessors": "Predecessor IDs",
            "resource_names": "People",
        },
    ),
)
if not result.success:
    for issue in result.errors:
        print(issue.path, issue.message)
```

`predecessors` as a semicolon- or pipe-separated list maps to finish-to-start links with zero lag and emits a warning. To preserve dependency types and lags, map a JSON-array column to `dependencies_json`. Dates must be ISO date-only values. UTF-8 (with or without BOM), quoted commas/quotes/newlines, CRLF/LF files, and comma/semicolon/tab/pipe delimiters are handled. Non-UTF-8 input is rejected with an encoding diagnostic.

`spreadsheet_safe=True` prefixes formula-like text cells with an apostrophe. This is intended for files opened in spreadsheet software, where formulas may otherwise be evaluated; it can make those specific text values differ on reimport. The default export does not rewrite project data.

## Validation, previews, and file safety

`ImportResult` contains a candidate `Project`, a summary (task/subtask/dependency/resource/assignment/milestone counts and date range), and issues. Callers must not commit a project with errors. Warnings include unknown fields, resource-name identity assumptions, and conversions such as predecessor-only columns. The library never imports into or overwrites a current project; it returns a new project value.

`InterchangeManager` limits input to 50 MiB (CSV also has a 250,000-row limit), detects content before relying on the suffix, does not extract archives, and does not execute imported content. Export validates the model, validates generated bytes with the registered parser, writes a same-directory temporary file, and only then installs it. Existing destinations are refused unless `overwrite=True` is explicitly supplied. This module has no UI, so an application must obtain confirmation before setting that flag.

`compare_projects(before, after, format_id=...)` reports field-level differences as `expected_format_conversion`, `unsupported_information`, `unexpected_data_loss`, or `scheduling_recalculation`; it does not hide changed fields merely because the project still parses. Minute/hour equivalence is recognized; working-day/week equivalence is deliberately not guessed without calendar semantics.

## Tests

Run:

```sh
python3 -m unittest discover -v
```

The suite covers JSON and CSV model round trips, hierarchy/dependency validation, broken references/cycles, unknown field preservation, schema migration/version rejection, CSV mapping and quoting, file detection, no-overwrite behavior, atomic export, and round-trip diagnostics. Fixtures are generated from the exchange model; no externally produced PlanForge/ProjectLibre/Microsoft Project/GanttProject sample files are present, and no external desktop application round trip has been performed.

## Next integration stages

1. Restore the actual PlanForge application source and its submodule metadata, model, `.pfp` schema, launchers, dependencies, and regression tests.
2. Map the exchange model to the actual application model (or replace it with explicit converters) and verify Function Point Calculator semantics before connecting it to the UI.
3. Add UI-driven file selection, column mapping, preview/cancel, new-project import, warnings, and explicit overwrite confirmation.
4. Implement Microsoft Project XML/MSPDI using documented structures and independent sample files; validate in both Microsoft Project and ProjectLibre before calling it supported.
5. Investigate `.pod`, `.mpp`, and `.gan` only after XML and core round trips are reliable. Do not implement those formats by renaming other output files.
