"""User preferences stored in ``~/.config/PlanForge/PlanForge.conf``.

The file uses the same INI layout as earlier versions so existing settings
(such as the theme) are preserved.
"""

from __future__ import annotations

import configparser
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "PlanForge"
CONFIG_FILE = CONFIG_DIR / "PlanForge.conf"

THEMES = ("light", "dark")


def get_theme_setting(config_file: Path | None = None) -> str:
    """Return the saved theme name, or ``"light"`` when none is saved."""
    path = config_file or CONFIG_FILE
    if path.exists():
        parser = configparser.ConfigParser()
        try:
            parser.read(str(path), encoding="utf-8")
            theme = parser.get("view", "theme", fallback="light")
        except (configparser.Error, OSError):
            return "light"
        return theme if theme in THEMES else "light"
    return "light"


def set_theme_setting(theme: str, config_file: Path | None = None) -> None:
    """Save the theme name, keeping any other settings already in the file."""
    if theme not in THEMES:
        raise ValueError(f"Unknown theme {theme!r}; expected one of {', '.join(THEMES)}.")
    path = config_file or CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    if path.exists():
        try:
            parser.read(str(path), encoding="utf-8")
        except configparser.Error:
            parser = configparser.ConfigParser()
    if not parser.has_section("view"):
        parser.add_section("view")
    parser.set("view", "theme", theme)
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)


__all__ = ["CONFIG_DIR", "CONFIG_FILE", "THEMES", "get_theme_setting", "set_theme_setting"]
