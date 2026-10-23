"""Portable, validated per-user PlanForge preferences.

Preferences remain INI-based for compatibility with existing
``PlanForge.conf`` files. Writes are atomic so an interrupted save does not
leave a truncated settings file.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Mapping

from planforge._atomic import atomic_replace, best_effort_unlink

APP_NAME = "PlanForge"
THEMES = ("light", "dark", "midnight", "high_contrast", "classic")
SETTINGS_VERSION = "1"
DATE_FORMATS = {"ISO": "%Y-%m-%d", "UK": "%d/%m/%Y", "US": "%m/%d/%Y", "Long": "%d %b %Y"}
SHORTCUT_DEFAULTS = {"new": "N", "open": "O", "save": "S", "undo": "Z", "redo": "Z" if sys.platform == "darwin" else "Y"}
_RESERVED_SHORTCUT_KEYS = {"I", "E", "C", "Q", "T", "K", "P", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}
_CUSTOM_THEME_ID = re.compile(r"^custom-[a-z0-9][a-z0-9-]{0,78}$")


def _valid_theme_id(theme: str) -> bool:
    return theme == "system" or theme in THEMES or bool(_CUSTOM_THEME_ID.fullmatch(theme))


def get_config_dir(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return the conventional per-user config directory for the current OS."""
    env = os.environ if environ is None else environ
    platform_name = sys.platform if platform_name is None else platform_name
    home = Path.home() if home is None else Path(home)
    if platform_name.startswith("win"):
        root = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    elif platform_name == "darwin":
        root = home / "Library" / "Application Support"
    else:
        root = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    return root / APP_NAME


CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "PlanForge.conf"


def _read_parser(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def _parser_for_update(path: Path) -> configparser.ConfigParser:
    try:
        return _read_parser(path)
    except (configparser.Error, OSError, UnicodeError):
        # Keep a corrupt input file before replacing it with safe settings.
        if path.exists():
            backup = Path(f"{path}.corrupt")
            if backup.exists():
                backup = Path(f"{path}.corrupt-{time.time_ns()}")
            shutil.copy2(path, backup)
        return configparser.ConfigParser()


def get_theme_setting(config_file: Path | None = None) -> str:
    """Return a validated saved theme, using Light for absent/invalid values."""
    path = config_file or CONFIG_FILE
    try:
        parser = _read_parser(path)
        theme = parser.get("view", "theme", fallback="light").strip().lower()
    except (configparser.Error, OSError, UnicodeError):
        return "light"
    return theme if _valid_theme_id(theme) else "light"


def get_preference(section: str, key: str, fallback: str = "", config_file: Path | None = None) -> str:
    """Read an arbitrary app preference, returning its fallback if unavailable."""
    try:
        return _read_parser(Path(config_file) if config_file is not None else CONFIG_FILE).get(
            section, key, fallback=fallback
        )
    except (configparser.Error, OSError, UnicodeError):
        return fallback


def format_date(value: date | None, config_file: Path | None = None) -> str:
    """Format a displayed date using a validated user preference."""
    if value is None:
        return ""
    selected = get_preference("workspace", "date_format", "ISO", config_file)
    return value.strftime(DATE_FORMATS.get(selected, DATE_FORMATS["ISO"]))


def parse_date_input(value: str, config_file: Path | None = None) -> date | None:
    """Parse user-entered dates in ISO, UK, US, or written month formats."""
    from datetime import datetime as _dt

    text = (value or "").strip()
    if not text:
        return None

    iso_match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if iso_match:
        year, month, day = (int(part) for part in iso_match.groups())
        return date(year, month, day)

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    selected = get_preference("workspace", "date_format", "ISO", config_file)
    dmy_formats = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")
    mdy_formats = ("%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y")
    ordered_formats = (
        (*mdy_formats, *dmy_formats) if selected == "US" else (*dmy_formats, *mdy_formats)
    ) + ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y")

    for fmt in ordered_formats:
        try:
            return _dt.strptime(text, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Invalid date {text!r}. Use YYYY-MM-DD (for example, 2026-10-19).")


def _save_parser(parser: configparser.ConfigParser, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not parser.has_section("app"):
        parser.add_section("app")
    previous_version = parser.get("app", "settings_version", fallback="0")
    try:
        should_upgrade = int(previous_version) < int(SETTINGS_VERSION)
    except ValueError:
        should_upgrade = True
    if should_upgrade:
        parser.set("app", "settings_version", SETTINGS_VERSION)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(temp_name, path)
    except BaseException:
        best_effort_unlink(temp_name)
        raise


def set_settings(values: Mapping[tuple[str, str], str], config_file: Path | None = None) -> None:
    """Atomically update keys across preference sections in one INI replacement."""
    if not values or any(not section.strip() or not key.strip() for section, key in values):
        raise ValueError("Preference sections and keys must be non-empty.")
    path = Path(config_file) if config_file is not None else CONFIG_FILE
    parser = _parser_for_update(path)
    for (section, key), value in values.items():
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, str(value))
    _save_parser(parser, path)


def set_preferences(section: str, values: Mapping[str, str], config_file: Path | None = None) -> None:
    """Atomically update several values in one preference category."""
    if not section.strip():
        raise ValueError("Preference section must be non-empty.")
    set_settings({(section, key): value for key, value in values.items()}, config_file)


def set_preference(section: str, key: str, value: str, config_file: Path | None = None) -> None:
    """Atomically store a single preference while retaining other settings."""
    set_preferences(section, {key: value}, config_file)


def get_recent_projects(config_file: Path | None = None, limit: int = 10) -> list[Path]:
    """Read the bounded, user-local project history without trusting arbitrary sections."""
    try:
        parser = _read_parser(Path(config_file) if config_file is not None else CONFIG_FILE)
    except (configparser.Error, OSError, UnicodeError):
        return []
    if not parser.has_section("recent_projects"):
        return []
    paths: list[Path] = []
    for index in range(max(0, min(limit, 50))):
        value = parser.get("recent_projects", f"path_{index}", fallback="", raw=True).strip()
        if value:
            candidate = Path(value).expanduser()
            if candidate not in paths:
                paths.append(candidate)
    return paths


def remember_recent_project(path: str | Path, config_file: Path | None = None, limit: int = 10) -> None:
    """Move one local path to the front of the bounded recent-project list."""
    candidate = Path(path).expanduser().resolve()
    recent = [item for item in get_recent_projects(config_file, limit=50) if item != candidate]
    recent.insert(0, candidate)
    bounded = recent[: max(1, min(limit, 50))]
    values = {f"path_{index}": str(bounded[index]) if index < len(bounded) else "" for index in range(50)}
    set_preferences("recent_projects", values, config_file)


def clear_recent_projects(config_file: Path | None = None) -> None:
    set_preferences("recent_projects", {f"path_{index}": "" for index in range(50)}, config_file)


def get_workspace_layouts(config_file: Path | None = None) -> dict[str, dict[str, object]]:
    """Load only validated data-only layout records from local preferences."""
    try:
        parser = _read_parser(Path(config_file) if config_file is not None else CONFIG_FILE)
        raw = parser.get("workspace_layouts", "items", fallback="{}", raw=True)
        parsed = json.loads(raw)
    except (configparser.Error, OSError, UnicodeError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    allowed_columns = {"duration", "start", "finish", "progress", "predecessor", "people", "cost"}
    valid: dict[str, dict[str, object]] = {}
    for name, value in list(parsed.items())[:30]:
        if (not isinstance(name, str) or not name.strip() or len(name) > 40
                or any(ord(char) < 32 for char in name) or not isinstance(value, dict)):
            continue
        tab, zoom, hidden = value.get("tab"), value.get("zoom"), value.get("hidden", [])
        if (not isinstance(tab, int) or isinstance(tab, bool) or not 0 <= tab <= 9
                or zoom not in ("Days", "Weeks", "Months") or not isinstance(hidden, list)
                or any(not isinstance(item, str) or item not in allowed_columns for item in hidden)):
            continue
        valid[name] = {"tab": tab, "zoom": zoom, "hidden": list(dict.fromkeys(hidden))}
    return valid


def set_workspace_layout(name: str, tab: int, zoom: str, hidden_columns: list[str],
                         config_file: Path | None = None) -> None:
    name = name.strip()
    if not name or len(name) > 40 or any(ord(char) < 32 for char in name):
        raise ValueError("Layout names must contain 1 to 40 printable characters.")
    if not isinstance(tab, int) or isinstance(tab, bool) or not 0 <= tab <= 9:
        raise ValueError("Workspace tab is out of range.")
    if zoom not in ("Days", "Weeks", "Months"):
        raise ValueError("Unknown timeline zoom.")
    allowed = {"duration", "start", "finish", "progress", "predecessor", "people", "cost"}
    if any(item not in allowed for item in hidden_columns):
        raise ValueError("Unknown task column.")
    layouts = get_workspace_layouts(config_file)
    if name not in layouts and len(layouts) >= 30:
        raise ValueError("You can save up to 30 workspace layouts.")
    layouts[name] = {"tab": tab, "zoom": zoom, "hidden": list(dict.fromkeys(hidden_columns))}
    set_preferences("workspace_layouts", {"items": json.dumps(layouts, ensure_ascii=False, separators=(",", ":"))},
                    config_file)


def delete_workspace_layout(name: str, config_file: Path | None = None) -> None:
    layouts = get_workspace_layouts(config_file)
    layouts.pop(name, None)
    set_preferences("workspace_layouts", {"items": json.dumps(layouts, ensure_ascii=False, separators=(",", ":"))},
                    config_file)


def get_shortcut_keys(config_file: Path | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for action, default in SHORTCUT_DEFAULTS.items():
        value = get_preference("shortcuts", action, default, config_file).strip().upper()
        result[action] = value if re.fullmatch(r"[A-Z0-9]", value) else default
    chords = [(key, sys.platform == "darwin" and action == "redo") for action, key in result.items()]
    reserved = {key for key, shifted in chords if not shifted}
    if len(set(chords)) != len(chords) or reserved & _RESERVED_SHORTCUT_KEYS:
        return dict(SHORTCUT_DEFAULTS)
    return result


def validate_shortcut_keys(values: Mapping[str, str], config_file: Path | None = None) -> dict[str, str]:
    if not values or any(action not in SHORTCUT_DEFAULTS for action in values):
        raise ValueError("Unknown keyboard shortcut action.")
    normalized = get_shortcut_keys(config_file)
    for action, value in values.items():
        key = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]", key):
            raise ValueError("Shortcut keys must be a single letter or number.")
        normalized[action] = key
    chords = [(key, sys.platform == "darwin" and action == "redo") for action, key in normalized.items()]
    reserved = {key for key, shifted in chords if not shifted}
    if len(set(chords)) != len(chords) or reserved & _RESERVED_SHORTCUT_KEYS:
        raise ValueError("Shortcut keys must be unique and cannot conflict with built-in shortcuts.")
    return normalized


def set_shortcut_keys(values: Mapping[str, str], config_file: Path | None = None) -> None:
    set_preferences("shortcuts", validate_shortcut_keys(values, config_file), config_file)


def set_theme_setting(theme: str, config_file: Path | None = None) -> None:
    """Persist a valid theme while retaining other readable INI preferences."""
    if not _valid_theme_id(theme):
        raise ValueError(f"Unknown theme identifier {theme!r}.")
    path = Path(config_file) if config_file is not None else CONFIG_FILE
    parser = _parser_for_update(path)
    if not parser.has_section("view"):
        parser.add_section("view")
    parser.set("view", "theme", theme)
    _save_parser(parser, path)


__all__ = [
    "APP_NAME",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DATE_FORMATS",
    "SHORTCUT_DEFAULTS",
    "SETTINGS_VERSION",
    "format_date",
    "parse_date_input",
    "THEMES",
    "get_config_dir",
    "get_preference",
    "get_recent_projects",
    "clear_recent_projects",
    "remember_recent_project",
    "get_workspace_layouts",
    "get_shortcut_keys",
    "set_shortcut_keys",
    "validate_shortcut_keys",
    "set_workspace_layout",
    "delete_workspace_layout",
    "get_theme_setting",
    "set_preference",
    "set_preferences",
    "set_settings",
    "set_theme_setting",
]
