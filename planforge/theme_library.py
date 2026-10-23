"""Data-only, local theme library. Theme packages never contain executable code."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from planforge._atomic import atomic_replace, best_effort_unlink
from planforge.config import CONFIG_DIR

THEME_SCHEMA_VERSION = 1
MAX_PACKAGE_BYTES = 512 * 1024
THEME_ID_PATTERN = re.compile(r"^custom-[a-z0-9][a-z0-9-]{0,78}$")
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
PALETTE_KEYS = (
    "bg", "panel", "text", "muted", "border", "accent", "accent_text", "danger", "success",
    "bar", "bar_done", "bar_critical", "bar_critical_done", "summary", "milestone", "weekend",
    "grid", "row_alt", "link", "today", "select",
)


def default_theme_dir() -> Path:
    return CONFIG_DIR / "themes"


def _clean_string(value: Any, label: str, *, limit: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Theme {label} must be text.")
    result = value.strip()
    if required and not result:
        raise ValueError(f"Theme {label} cannot be empty.")
    if len(result) > limit:
        raise ValueError(f"Theme {label} must be {limit} characters or fewer.")
    return result


def validate_theme_package(data: Any) -> dict[str, Any]:
    """Validate untrusted package JSON and return a normalized, data-only value."""
    if not isinstance(data, dict):
        raise ValueError("Theme package must contain a JSON object.")
    version = data.get("schema_version")
    if type(version) is not int or version != THEME_SCHEMA_VERSION:
        raise ValueError(f"Unsupported theme package schema version: {version!r}.")
    name = _clean_string(data.get("name"), "name", limit=64, required=True)
    description = _clean_string(data.get("description", ""), "description", limit=500)
    author = _clean_string(data.get("author", ""), "author", limit=80)
    theme_version = _clean_string(data.get("version", "1.0"), "version", limit=32, required=True)
    raw_palette = data.get("palette")
    if not isinstance(raw_palette, dict):
        raise ValueError("Theme palette must be a JSON object.")
    unknown = set(raw_palette) - set(PALETTE_KEYS)
    missing = set(PALETTE_KEYS) - set(raw_palette)
    if unknown:
        raise ValueError(f"Unsupported theme colour key(s): {', '.join(sorted(unknown))}.")
    if missing:
        raise ValueError(f"Theme palette is missing: {', '.join(sorted(missing))}.")
    package_id = data.get("id", "")
    if not isinstance(package_id, str) or package_id and not THEME_ID_PATTERN.fullmatch(package_id):
        raise ValueError("Theme ID is malformed.")
    created_at = data.get("created_at", "")
    if not isinstance(created_at, str) or len(created_at) > 48:
        raise ValueError("Theme creation timestamp is malformed.")
    palette: dict[str, str] = {}
    for key in PALETTE_KEYS:
        color = raw_palette[key]
        if not isinstance(color, str) or not COLOR_PATTERN.fullmatch(color):
            raise ValueError(f"Theme colour {key!r} must be a six-digit hexadecimal colour such as #336699.")
        palette[key] = color.lower()
    return {
        "schema_version": THEME_SCHEMA_VERSION,
        "name": name,
        "description": description,
        "author": author,
        "version": theme_version,
        "palette": palette,
        "id": package_id,
        "created_at": created_at,
    }


def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(temp_name, path)
    except BaseException:
        best_effort_unlink(temp_name)
        raise


def _theme_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "theme"
    slug = slug[:42].rstrip("-")
    return f"custom-{slug}-{uuid4().hex}"


def create_theme_package(
    name: str,
    palette: dict[str, str],
    *,
    description: str = "",
    author: str = "",
    version: str = "1.0",
) -> dict[str, Any]:
    return validate_theme_package({
        "schema_version": THEME_SCHEMA_VERSION,
        "name": name,
        "description": description,
        "author": author,
        "version": version,
        "palette": palette,
    })


def install_theme_package(data: Any, theme_dir: Path | None = None) -> dict[str, Any]:
    """Install as a new local theme; imported IDs cannot overwrite existing files."""
    package = validate_theme_package(data)
    directory = Path(theme_dir) if theme_dir is not None else default_theme_dir()
    directory.mkdir(parents=True, exist_ok=True)
    package["id"] = _theme_id(package["name"])
    package["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    target = directory / f"{package['id']}.json"
    _atomic_json_write(target, package)
    return package


def load_theme_package(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Theme package must be a regular local file.")
        if path.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError("Theme package exceeds the 512 KiB size limit.")
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not access theme package: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read theme package: {exc}") from exc
    package = validate_theme_package(raw)
    package["id"] = raw.get("id", "") if isinstance(raw.get("id", ""), str) else ""
    package["created_at"] = raw.get("created_at", "") if isinstance(raw.get("created_at", ""), str) else ""
    return package


def list_installed_themes(theme_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Load valid local themes, reporting corrupt files without aborting startup."""
    directory = Path(theme_dir) if theme_dir is not None else default_theme_dir()
    themes: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        paths = sorted(directory.glob("custom-*.json")) if directory.exists() else []
    except OSError as exc:
        return [], [f"Could not list local themes: {exc}"]
    for path in paths:
        if path.is_symlink() or not THEME_ID_PATTERN.fullmatch(path.stem):
            continue
        try:
            package = load_theme_package(path)
            package["id"] = path.stem
            themes.append(package)
        except ValueError as exc:
            warnings.append(f"{path.name}: {exc}")
    return themes, warnings


def export_theme_package(package: dict[str, Any], target: Path) -> Path:
    """Export validated package JSON to the user-selected path."""
    normalized = validate_theme_package(package)
    _atomic_json_write(Path(target), normalized)
    return Path(target)


def remove_installed_theme(theme_id: str, theme_dir: Path | None = None) -> None:
    """Remove only a validated custom-theme file, never a built-in or arbitrary path."""
    if not THEME_ID_PATTERN.fullmatch(theme_id):
        raise ValueError("Built-in or invalid themes cannot be removed.")
    directory = Path(theme_dir) if theme_dir is not None else default_theme_dir()
    target = directory / f"{theme_id}.json"
    if target.is_symlink():
        raise ValueError("Refusing to remove a symbolic-link theme file.")
    try:
        target.unlink()
    except FileNotFoundError:
        raise ValueError("That installed theme no longer exists.") from None


__all__ = [
    "MAX_PACKAGE_BYTES", "PALETTE_KEYS", "THEME_SCHEMA_VERSION", "create_theme_package",
    "default_theme_dir", "export_theme_package", "install_theme_package", "list_installed_themes",
    "load_theme_package", "remove_installed_theme", "validate_theme_package",
]
