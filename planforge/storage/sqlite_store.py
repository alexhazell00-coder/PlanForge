"""SQLite project storage (.pfp) with schema versioning and atomic saves.

Saves and loads PlanForge projects to/from SQLite database files (.pfp)
with transactional atomic saving and schema migration backups.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from planforge._atomic import atomic_replace, best_effort_unlink
from planforge.interchange.json_adapter import export_project as project_to_json, import_bytes as project_from_json
from planforge.interchange.validation import validate_project
from planforge.model import Project

CURRENT_STORAGE_VERSION = 1


class StorageError(Exception):
    """Raised when loading or saving a .pfp file fails."""


def init_db(connection: sqlite3.Connection) -> None:
    """Initialize database tables for a new .pfp project file."""
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_payload (
                id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                saved_at TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?);", (str(CURRENT_STORAGE_VERSION),))


def save_project_to_pfp(project: Project, path: str | Path) -> None:
    """Save a project atomically to a .pfp SQLite database file."""
    validation = validate_project(project)
    if not validation.valid:
        errors = "; ".join(issue.message for issue in validation.errors)
        raise StorageError(f"Cannot save project with validation errors: {errors}")

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Convert project to versioned JSON representation
    export_res = project_to_json(project)
    if not export_res.success or export_res.data is None:
        raise StorageError("Failed to serialize project payload.")

    json_str = export_res.data.decode("utf-8")

    # Atomic write to a temporary file
    temp_dir = dest.parent
    temp_file: str | None = None
    try:
        fd, temp_file = tempfile.mkstemp(
            prefix=f".{dest.name}.",
            suffix=".tmp",
            dir=temp_dir,
        )
        os.close(fd)

        # Explicitly close the SQLite connection before replacing the target:
        # sqlite3.Connection.__exit__ commits/rolls back transactions without
        # closing the OS file handle, which causes [WinError 32] on Windows.
        with closing(sqlite3.connect(temp_file)) as conn:
            init_db(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO project_payload (id, schema_version, payload_json, saved_at)
                VALUES (?, ?, ?, ?);
                """,
                (project.id, CURRENT_STORAGE_VERSION, json_str, datetime.now().isoformat()),
            )
            conn.commit()

        # Atomic replacement (with transient lock retry for Windows/OneDrive)
        atomic_replace(temp_file, dest)
        temp_file = None
    finally:
        best_effort_unlink(temp_file)


def load_project_from_pfp(path: str | Path) -> Project:
    """Load a project from a .pfp SQLite database file with backup on upgrade."""
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise StorageError(f"File not found: {source}")

    with closing(sqlite3.connect(source)) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT value FROM meta WHERE key = 'schema_version';")
            row = cursor.fetchone()
            version = int(row[0]) if row else 1
        except sqlite3.OperationalError:
            version = 0

        # Backup if older schema version
        if version < CURRENT_STORAGE_VERSION:
            backup_path = source.with_suffix(f".v{version}.bak")
            shutil.copy2(source, backup_path)

        cursor.execute("SELECT payload_json FROM project_payload ORDER BY saved_at DESC LIMIT 1;")
        row = cursor.fetchone()
        if not row:
            raise StorageError("No project payload found in .pfp file.")

        json_bytes = row[0].encode("utf-8")
        import_res = project_from_json(json_bytes)
        if not import_res.success or import_res.project is None:
            errs = "; ".join(issue.message for issue in import_res.errors)
            raise StorageError(f"Corrupted project data in .pfp: {errs}")

        return import_res.project


__all__ = [
    "CURRENT_STORAGE_VERSION",
    "StorageError",
    "load_project_from_pfp",
    "save_project_to_pfp",
]
