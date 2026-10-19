# PlanForge Interoperability Guide

## Overview

PlanForge supports robust, bidirectional project data interchange with established project-management applications, including **ProjectLibre**, **Microsoft Project**, **GanttProject**, and the **Simple Function Point Calculator**, as well as structured **CSV** and **PlanForge JSON**.

The primary supported workflow is:
**Existing Software → PlanForge → Existing Software**

PlanForge avoids vendor lock-in by using open, standard interchange formats and preserving project hierarchies, dates, durations, dependencies, milestones, resources, rates, allocations, costs, calendars, and Function Point Calculator data across round trips.

## Compatibility Matrix

| Format / Application | Import | Export | Supported Data | Round-Trip Verified |
| --- | --- | --- | --- | --- |
| **PlanForge JSON (`.json`)** | Yes | Yes | Complete canonical model, custom fields, unknown fields in extensions | Yes |
| **Microsoft Project XML / MSPDI (`.xml`)** | Yes | Yes | Tasks, subtask hierarchy, FS/SS/FF/SF dependencies, lag, durations, dates, milestones, resources, rates, assignments, costs, calendars | Yes |
| **ProjectLibre Desktop (`.xml`)** | Yes | Yes | Full project interchange via ProjectLibre-compatible MSPDI XML | Yes |
| **ProjectLibre Native (`.pod`)** | Guided | Guided | Binary Java serialization stream. Sniffed with actionable guidance to use XML export. | Workflow via XML |
| **Microsoft Project Native (`.mpp`)** | Guided | Guided | Proprietary OLE binary format. Sniffed with actionable guidance to use XML export. | Workflow via XML |
| **GanttProject (`.gan`)** | Yes | Yes | Nested task hierarchy, dependencies with lag, milestones, resources, rates, allocations, calendars & holidays | Yes |
| **Simple Function Point Calculator (`.json`)** | Yes | Yes | People, hourly rates, complexity points, hours, costs, task estimations | Yes |
| **CSV Task List (`.csv`)** | Yes | Yes | Tasks, dates, durations, completion, priorities, dependencies, resources; JSON-in-cell columns for full fidelity | Yes |

## Application-Specific Workflows

### 1. ProjectLibre Desktop

- **Interchange Format:** Microsoft Project XML (`.xml`).
- **Exporting from ProjectLibre:** Open your project in ProjectLibre Desktop, choose **File → Save As**, and choose **Microsoft Project XML (*.xml)**.
- **Importing into PlanForge:** Open or drag-and-drop the `.xml` file into PlanForge. Tasks, nested subtasks, start/finish dates, durations, dependencies (Finish-to-Start, Start-to-Start, Finish-to-Finish, Start-to-Finish with lag), milestones, resources, hourly rates, and assignments will be loaded into PlanForge's project model.
- **Exporting back to ProjectLibre:** In PlanForge, choose **File → Export…** and select **Microsoft Project XML (.xml)**. Open the resulting `.xml` file directly in ProjectLibre.
- **Why not `.pod` directly?** ProjectLibre `.pod` files use native Java object serialization (`java.io.ObjectOutputStream`, magic header `0xACED0005`). Direct manipulation without running the full ProjectLibre Java runtime is unsafe and prone to serialization discrepancies. The XML interchange workflow is the official, lossless interchange method recommended by ProjectLibre.

### 2. Microsoft Project

- **Interchange Format:** Microsoft Project XML / MSPDI (`.xml`).
- **Exporting from MS Project:** Open your project in MS Project, select **File → Save As**, and select **XML Format (*.xml)**.
- **Importing into PlanForge:** Open the `.xml` file in PlanForge.
- **Exporting back to MS Project:** In PlanForge, choose **File → Export…** and select **Microsoft Project XML (.xml)**. Microsoft Project 2003 through 2021/365 opens this standard XML format natively.
- **Why not `.mpp` directly?** `.mpp` is a proprietary binary compound document format without an open write specification. Microsoft Project itself provides the XML format specifically for third-party tool interoperability.

### 3. GanttProject

- **Interchange Format:** GanttProject XML (`.gan`).
- **Workflow:** GanttProject project files (`.gan`) can be opened directly in PlanForge and exported back to `.gan`.
- **Preserved Information:**
  - Nested `<task>` parent-child hierarchy
  - Task start dates, working day durations, completion percentages, notes, and costs
  - Milestones (`meeting="true"`)
  - Dependencies with types and lag difference
  - Resources with rates, roles, and contacts
  - Task allocations with load percentage
  - Working week configuration and project holidays.

### 4. Simple Function Point Calculator

- **Interchange Format:** JSON (`.json`, format versions 1, 2, and 3).
- **Importing into PlanForge:** When importing a Function Point Calculator file, PlanForge:
  - Creates a resource for each Person with their hourly rate and complexity settings.
  - Creates tasks for each person's estimated tasks, attaching the `FunctionPointEstimate` metadata.
  - Automatically calculates hours and costs using the exact calculator rules (`fp_logic.py`).
  - Creates assignments linking each person to their estimated tasks.
- **Exporting to Function Point Calculator:** PlanForge groups tasks by assigned resource and writes a version 3 JSON file compatible with the calculator application.

### 5. CSV Import & Export

- **Standard Template:** Contains task and project columns, with optional JSON-in-cell columns (`dependencies_json`, `assignments_json`, `resources_json`, `calendars_json`) for full fidelity.
- **Unfamiliar CSVs:** Automatic column header alias suggestions and user-defined `CsvImportOptions.column_mapping` allow importing CSV files from any third-party spreadsheet or task tracker.

## Architecture

The interchange layer is modular and located under `planforge/interchange/`:

- `planforge/model.py`: Canonical exchange data model.
- `planforge/interchange/registry.py`: Central registry with content-based format sniffing, safe file handling, and atomic exports.
- `planforge/interchange/mspdi_adapter.py`: Microsoft Project & ProjectLibre XML adapter.
- `planforge/interchange/ganttproject_adapter.py`: GanttProject `.gan` adapter.
- `planforge/interchange/fp_adapter.py`: Simple Function Point Calculator adapter.
- `planforge/interchange/csv_adapter.py`: CSV reader/writer with column mapping.
- `planforge/interchange/json_adapter.py`: PlanForge JSON reader/writer.
- `planforge/interchange/validation.py`: Data integrity checks (circular dependencies, broken references, date consistency).
- `planforge/interchange/comparison.py`: Field-level round-trip comparisons and diff reporting.
