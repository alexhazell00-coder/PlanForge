"""Atomic local crash-recovery snapshots kept separate from project files."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planforge._atomic import atomic_replace, best_effort_unlink
from planforge.config import CONFIG_DIR
from planforge.model import Project
from planforge.storage.sqlite_store import load_project_from_pfp, save_project_to_pfp


@dataclass(frozen=True)
class RecoveryRecord:
    snapshot_path: Path
    project_id: str
    project_name: str
    source_path: Path | None
    saved_at: str


def recovery_directory(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else CONFIG_DIR) / "recovery"


def _key(project_id: str) -> str:
    return hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:32]


def save_recovery_snapshot(
    project: Project,
    source_path: Path | None = None,
    *,
    root: Path | None = None,
) -> RecoveryRecord:
    """Write an independent .pfp snapshot and metadata via atomic replacements."""
    directory = recovery_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    key = _key(project.id)
    snapshot = directory / f"recovery-{key}.pfp"
    meta = directory / f"recovery-{key}.json"
    save_project_to_pfp(project, snapshot)
    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "schema_version": 1,
        "project_id": project.id,
        "project_name": project.name,
        "source_path": str(source_path) if source_path else "",
        "saved_at": saved_at,
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{meta.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(temporary, meta)
    except BaseException:
        best_effort_unlink(temporary)
        raise
    return RecoveryRecord(snapshot, project.id, project.name, source_path, saved_at)


def list_recovery_snapshots(*, root: Path | None = None) -> tuple[list[RecoveryRecord], list[str]]:
    """Return valid recoveries and warnings; one damaged file cannot block launch."""
    directory = recovery_directory(root)
    records: list[RecoveryRecord] = []
    warnings: list[str] = []
    if not directory.exists():
        return records, warnings
    try:
        paths = sorted(directory.glob("recovery-*.pfp"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError as exc:
        return records, [f"Could not inspect recovery files: {exc}"]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        meta = path.with_suffix(".json")
        try:
            project = load_project_from_pfp(path)
            metadata: dict[str, Any] = {}
            if meta.is_file() and not meta.is_symlink():
                parsed = json.loads(meta.read_text(encoding="utf-8"))
                if isinstance(parsed, dict) and parsed.get("schema_version") == 1:
                    metadata = parsed
            source = metadata.get("source_path", "")
            source_path = Path(source) if isinstance(source, str) and source else None
            saved_at = metadata.get("saved_at", "")
            if not isinstance(saved_at, str) or not saved_at:
                saved_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            records.append(RecoveryRecord(path, project.id, project.name, source_path, saved_at))
        except Exception as exc:
            warnings.append(f"{path.name}: recovery snapshot could not be loaded ({exc}).")
    return records, warnings


def clear_recovery_snapshot(project_id: str, *, root: Path | None = None) -> None:
    """Delete only the two files addressed by a project-ID hash."""
    directory = recovery_directory(root)
    key = _key(project_id)
    for path in (directory / f"recovery-{key}.pfp", directory / f"recovery-{key}.json"):
        if path.is_symlink():
            continue
        try:
            path.unlink()
        except OSError:
            # Recovery cleanup is best-effort; it must never block project actions.
            pass


def load_recovery_project(snapshot_path: Path) -> Project:
    return load_project_from_pfp(snapshot_path)


__all__ = [
    "RecoveryRecord", "clear_recovery_snapshot", "list_recovery_snapshots", "load_recovery_project",
    "recovery_directory", "save_recovery_snapshot",
]
