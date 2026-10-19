"""Format registry, content-based detection, and safe file operations."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from planforge.interchange import csv_adapter, json_adapter
from planforge.interchange.csv_adapter import CsvImportOptions
from planforge.interchange.results import ExportResult, ImportResult
from planforge.interchange.validation import ValidationIssue
from planforge.model import Project

MAX_FILE_BYTES = min(csv_adapter.MAX_IMPORT_BYTES, json_adapter.MAX_IMPORT_BYTES)


@dataclass(frozen=True, slots=True)
class FormatDefinition:
    id: str
    name: str
    extensions: tuple[str, ...]
    can_import: bool
    can_export: bool
    description: str
    tested_at_adapter_level: bool = False
    external_application_round_trip_tested: bool = False


@dataclass(frozen=True, slots=True)
class FormatDetection:
    format_id: str | None
    issues: tuple[ValidationIssue, ...] = ()


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)


class FormatRegistry:
    """Registry for adapters; new formats can be registered independently."""

    def __init__(self) -> None:
        self._formats: dict[str, FormatDefinition] = {}
        self._importers: dict[str, Callable[..., ImportResult]] = {}
        self._exporters: dict[str, Callable[..., ExportResult]] = {}
        self._sniffers: dict[str, Callable[[bytes, str], bool]] = {}
        self.register(
            FormatDefinition(
                id=json_adapter.FORMAT_ID,
                name=json_adapter.FORMAT_NAME,
                extensions=(".json",),
                can_import=True,
                can_export=True,
                description="Versioned PlanForge project JSON. Preserves the canonical interchange model.",
                tested_at_adapter_level=True,
            ),
            importer=lambda data, **kwargs: json_adapter.import_bytes(data, source_name=kwargs.get("source_name")),
            exporter=lambda project, **kwargs: json_adapter.export_project(project),
        )
        self.register(
            FormatDefinition(
                id=csv_adapter.FORMAT_ID,
                name=csv_adapter.FORMAT_NAME,
                extensions=(".csv",),
                can_import=True,
                can_export=True,
                description="One row per task. Optional JSON-in-cell columns carry dependencies, resources, assignments, calendars, and custom data.",
                tested_at_adapter_level=True,
            ),
            importer=lambda data, **kwargs: csv_adapter.import_bytes(
                data,
                options=kwargs.get("csv_options"),
                source_name=kwargs.get("source_name"),
            ),
            exporter=lambda project, **kwargs: csv_adapter.export_project(
                project, spreadsheet_safe=bool(kwargs.get("spreadsheet_safe", False))
            ),
        )

    def register(
        self,
        definition: FormatDefinition,
        *,
        importer: Callable[..., ImportResult] | None = None,
        exporter: Callable[..., ExportResult] | None = None,
        sniffer: Callable[[bytes, str], bool] | None = None,
    ) -> None:
        """Register one adapter and its pure byte/model conversion functions.

        Importers receive bytes plus optional keyword arguments and return an
        ImportResult. Exporters receive a Project and optional keywords and
        return an ExportResult. The registry does not perform UI or persistence
        work on behalf of an adapter.
        """

        if not definition.id or definition.id in self._formats:
            raise ValueError(f"Format ID is empty or already registered: {definition.id!r}")
        if definition.can_import and importer is None:
            raise ValueError(f"Format {definition.id!r} declares import support but has no importer.")
        if definition.can_export and exporter is None:
            raise ValueError(f"Format {definition.id!r} declares export support but has no exporter.")
        self._formats[definition.id] = definition
        if importer is not None:
            self._importers[definition.id] = importer
        if exporter is not None:
            self._exporters[definition.id] = exporter
        if sniffer is not None:
            self._sniffers[definition.id] = sniffer

    def get(self, format_id: str) -> FormatDefinition | None:
        return self._formats.get(format_id)

    def importer(self, format_id: str) -> Callable[..., ImportResult] | None:
        return self._importers.get(format_id)

    def exporter(self, format_id: str) -> Callable[..., ExportResult] | None:
        return self._exporters.get(format_id)

    def formats(self) -> tuple[FormatDefinition, ...]:
        return tuple(self._formats.values())

    def import_formats(self) -> tuple[FormatDefinition, ...]:
        return tuple(item for item in self._formats.values() if item.can_import)

    def export_formats(self) -> tuple[FormatDefinition, ...]:
        return tuple(item for item in self._formats.values() if item.can_export)

    def detect(self, data: bytes, filename: str | Path | None = None) -> FormatDetection:
        """Detect JSON/CSV by structure first, then use a supported extension."""

        suffix = Path(filename).suffix.casefold() if filename is not None else ""
        issues: list[ValidationIssue] = []
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = None

        detected: str | None = None
        if text is not None:
            stripped = text.lstrip()
            if stripped.startswith(("{", "[")):
                try:
                    document: Any = json.loads(text)
                except (json.JSONDecodeError, RecursionError):
                    # Send malformed JSON to the JSON parser if the extension
                    # indicates JSON, so it can provide a precise parse error.
                    if suffix == ".json":
                        detected = json_adapter.FORMAT_ID
                else:
                    if isinstance(document, dict) and (
                        document.get("format") == "planforge-project"
                        or ("schema_version" in document and "project" in document)
                    ):
                        detected = json_adapter.FORMAT_ID
                    elif suffix == ".json":
                        detected = json_adapter.FORMAT_ID

            if detected is None:
                try:
                    dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
                    first_row = next(csv.reader(io.StringIO(text), dialect=dialect), [])
                except (csv.Error, StopIteration):
                    first_row = []
                if len(first_row) >= 2:
                    header_names = {
                        "".join(char for char in cell.casefold() if char.isalnum())
                        for cell in first_row
                    }
                    if header_names & {"task", "taskname", "name", "title", "subject", "taskid", "startdate"}:
                        detected = csv_adapter.FORMAT_ID
            if detected is None and suffix == ".csv":
                detected = csv_adapter.FORMAT_ID
            elif detected is None and suffix == ".json":
                detected = json_adapter.FORMAT_ID

        if detected is None:
            for candidate_id, sniffer in self._sniffers.items():
                try:
                    if sniffer(data, suffix):
                        detected = candidate_id
                        break
                except Exception:
                    # A detector is advisory; malformed content must be
                    # reported by the selected parser, not crash file picking.
                    continue
        if detected is None and suffix:
            extension_matches = [
                item.id for item in self._formats.values() if suffix in item.extensions
            ]
            if len(extension_matches) == 1:
                detected = extension_matches[0]
        if detected is None:
            return FormatDetection(None, (_issue(
                "error", "format.unsupported", "$",
                "Could not identify this file as PlanForge JSON or CSV. Supported formats in this build: .json and .csv.",
            ),))
        detected_format = self.get(detected)
        if detected_format is None:
            return FormatDetection(None, (_issue("error", "format.unregistered", "$", f"Detected format {detected!r} is not registered."),))
        if suffix and suffix not in detected_format.extensions:
            issues.append(_issue(
                "warning", "format.extension.mismatch", "$",
                f"File content looks like {detected_format.name}, although its extension is {suffix!r}.",
            ))
        return FormatDetection(detected, tuple(issues))


class InterchangeManager:
    """Content-detecting import and atomic export facade.

    Imports always produce a new Project value. They never merge into or write
    over an existing project. Export uses a temporary file and validates the
    generated content before touching the destination.
    """

    def __init__(self, registry: FormatRegistry | None = None) -> None:
        self.registry = registry or FormatRegistry()

    def import_file(
        self,
        path: str | Path,
        *,
        format_id: str | None = None,
        csv_options: CsvImportOptions | None = None,
    ) -> ImportResult:
        source = Path(path)
        try:
            with source.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            return ImportResult(format_id or "unknown", None, (_issue("error", "file.read.failed", str(source), str(exc)),))
        if len(data) > MAX_FILE_BYTES:
            return ImportResult(format_id or "unknown", None, (_issue("error", "file.too_large", str(source), f"File exceeds the {MAX_FILE_BYTES}-byte import limit."),))

        detection = self.registry.detect(data, source)
        selected = format_id or detection.format_id
        if selected is None:
            return ImportResult("unknown", None, detection.issues)
        definition = self.registry.get(selected)
        importer = self.registry.importer(selected)
        if definition is None or not definition.can_import or importer is None:
            return ImportResult(selected, None, (_issue("error", "format.import.unsupported", str(source), f"Format {selected!r} is not available for import in this build."),))

        result = importer(data, source_name=source.name, csv_options=csv_options)
        extra = list(detection.issues) if format_id is None or detection.format_id is not None else []
        if format_id is not None and detection.format_id is not None and detection.format_id != format_id:
            extra.append(_issue(
                "warning", "format.forced", str(source),
                f"The file was parsed as {definition.name} because that format was explicitly selected; content detection suggested {detection.format_id}.",
            ))
        return ImportResult(result.source_format, result.project, tuple(extra) + result.issues, result.schema_version)

    def export_file(
        self,
        project: Project,
        format_id: str,
        path: str | Path,
        *,
        overwrite: bool = False,
        spreadsheet_safe: bool = False,
    ) -> ExportResult:
        destination = Path(path)
        definition = self.registry.get(format_id)
        exporter = self.registry.exporter(format_id)
        if definition is None or not definition.can_export or exporter is None:
            return ExportResult(format_id, None, (_issue("error", "format.export.unsupported", str(destination), f"Format {format_id!r} is not available for export in this build."),))
        result = exporter(project, spreadsheet_safe=spreadsheet_safe)
        if not result.success or result.data is None:
            return result

        # Validate output through its own registered importer. This proves the
        # adapter can read the generated bytes; it does not prove compatibility
        # with an external desktop application.
        importer = self.registry.importer(format_id)
        if importer is None:
            return ExportResult(format_id, None, result.issues + (_issue(
                "error", "export.validation.unavailable", str(destination),
                "No importer is registered to validate this generated output.",
            ),))
        check = importer(result.data, source_name=destination.name)
        if not check.success:
            details = "; ".join(issue.message for issue in check.errors)
            return ExportResult(format_id, None, result.issues + (_issue(
                "error", "export.validation.failed", str(destination),
                f"Generated output did not pass its importer validation: {details}",
            ),))

        if destination.exists() and not overwrite:
            return ExportResult(format_id, None, result.issues + (_issue(
                "error", "file.exists", str(destination), "Destination already exists; pass overwrite=True only after explicit confirmation."),))
        if not destination.parent.exists() or not destination.parent.is_dir():
            return ExportResult(format_id, None, result.issues + (_issue(
                "error", "file.destination.invalid", str(destination.parent), "Destination folder does not exist."),))

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(result.data)
                temporary.flush()
                os.fsync(temporary.fileno())
            if overwrite:
                os.replace(temporary_name, destination)
            else:
                # Linking a same-directory temporary file is atomic and fails
                # if another process created the destination meanwhile.
                os.link(temporary_name, destination)
                os.unlink(temporary_name)
            temporary_name = None
        except OSError as exc:
            return ExportResult(format_id, None, result.issues + (_issue(
                "error", "file.write.failed", str(destination), f"Export was not saved: {exc}"),))
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
        return result


__all__ = ["FormatDefinition", "FormatDetection", "FormatRegistry", "InterchangeManager", "MAX_FILE_BYTES"]
