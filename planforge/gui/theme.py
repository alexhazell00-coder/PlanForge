"""Light and dark colour palettes plus the ttk style configuration."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f3f5f8",
        "panel": "#ffffff",
        "text": "#1f2933",
        "muted": "#64707d",
        "border": "#d5dce5",
        "accent": "#2563eb",
        "accent_text": "#ffffff",
        "danger": "#dc2626",
        "success": "#15803d",
        "bar": "#93c5fd",
        "bar_done": "#2563eb",
        "bar_critical": "#f87171",
        "bar_critical_done": "#dc2626",
        "summary": "#1e3a8a",
        "milestone": "#f59e0b",
        "weekend": "#eef2f7",
        "grid": "#e3e8ef",
        "row_alt": "#f8fafc",
        "link": "#475569",
        "today": "#dc2626",
        "select": "#dbeafe",
    },
    "dark": {
        "bg": "#0f172a",
        "panel": "#1e293b",
        "text": "#e2e8f0",
        "muted": "#94a3b8",
        "border": "#334155",
        "accent": "#3b82f6",
        "accent_text": "#ffffff",
        "danger": "#f87171",
        "success": "#4ade80",
        "bar": "#1e4f8a",
        "bar_done": "#3b82f6",
        "bar_critical": "#7f1d1d",
        "bar_critical_done": "#f87171",
        "summary": "#93c5fd",
        "milestone": "#fbbf24",
        "weekend": "#172135",
        "grid": "#2b3a50",
        "row_alt": "#18243a",
        "link": "#94a3b8",
        "today": "#f87171",
        "select": "#1e3a5f",
    },
}

# Keep the original Light and Dark palettes stable for existing users while
# providing a few carefully bounded alternatives. Canvas-based views consume
# the same keys as ttk widgets, so each palette supplies the complete set.
PALETTES["midnight"] = {
    **PALETTES["dark"],
    "bg": "#090d18",
    "panel": "#111827",
    "text": "#e5e7eb",
    "muted": "#9ca3af",
    "border": "#273449",
    "accent": "#8b5cf6",
    "bar": "#4c3a80",
    "bar_done": "#8b5cf6",
    "weekend": "#101625",
    "grid": "#263247",
    "row_alt": "#0d1422",
    "select": "#30234f",
}
PALETTES["high_contrast"] = {
    **PALETTES["dark"],
    "bg": "#000000",
    "panel": "#000000",
    "text": "#ffffff",
    "muted": "#e5e5e5",
    "border": "#ffffff",
    "accent": "#ffff00",
    "accent_text": "#000000",
    "danger": "#ff6b6b",
    "success": "#00ff7f",
    "bar": "#00bfff",
    "bar_done": "#00ff7f",
    "bar_critical": "#ff3030",
    "bar_critical_done": "#ff6b6b",
    "summary": "#ffff00",
    "milestone": "#ff8c00",
    "weekend": "#171717",
    "grid": "#666666",
    "row_alt": "#111111",
    "link": "#ffffff",
    "today": "#ff3030",
    "select": "#343400",
}
PALETTES["classic"] = {
    **PALETTES["light"],
    "bg": "#e9e7df",
    "panel": "#f7f6f0",
    "text": "#282820",
    "muted": "#626157",
    "border": "#b7b4a8",
    "accent": "#315f52",
    "accent_text": "#ffffff",
    "bar": "#a7c3b4",
    "bar_done": "#315f52",
    "bar_critical": "#d58b7b",
    "bar_critical_done": "#a33d32",
    "summary": "#315f52",
    "milestone": "#b27a24",
    "weekend": "#e4e2d9",
    "grid": "#d0cec4",
    "row_alt": "#efeee8",
    "link": "#626157",
    "today": "#a33d32",
    "select": "#d7e4dc",
}


def system_theme_name() -> str:
    """Best-effort offline light/dark detection with safe fallbacks per OS."""
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if int(value) else "dark"
        except (ImportError, OSError, ValueError):
            return "light"
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                    capture_output=True, text=True, timeout=1, check=False)
            return "dark" if result.returncode == 0 and result.stdout.strip().casefold() == "dark" else "light"
        except (OSError, subprocess.TimeoutExpired):
            return "light"
    gtk_theme = os.environ.get("GTK_THEME", "").casefold()
    if "dark" in gtk_theme:
        return "dark"
    color_scheme = os.environ.get("COLORFGBG", "")
    if color_scheme.endswith(";0"):
        return "dark"
    gsettings = shutil.which("gsettings")
    if gsettings:
        try:
            result = subprocess.run([gsettings, "get", "org.gnome.desktop.interface", "color-scheme"],
                                    capture_output=True, text=True, timeout=1, check=False)
            if result.returncode == 0 and "dark" in result.stdout.casefold():
                return "dark"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "light"


def palette_for(theme: str) -> dict[str, str]:
    """Return a copy so a view cannot mutate the shared built-in palette."""
    return dict(PALETTES.get(theme, PALETTES["light"]))


def apply_palette(root: tk.Misc, palette: dict[str, str]) -> dict[str, str]:
    """Configure every ttk style for a validated palette and return a copy."""
    p = dict(palette)
    root.configure(background=p["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["panel"],
                    bordercolor=p["border"], lightcolor=p["panel"], darkcolor=p["border"],
                    troughcolor=p["row_alt"], selectbackground=p["select"], selectforeground=p["text"],
                    font=("Helvetica", 10))
    style.configure("TFrame", background=p["bg"])
    style.configure("Panel.TFrame", background=p["panel"])
    style.configure("Card.TFrame", background=p["panel"], relief="solid", borderwidth=1)
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Panel.TLabel", background=p["panel"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("PanelMuted.TLabel", background=p["panel"], foreground=p["muted"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"], font=("Helvetica", 16, "bold"))
    style.configure("Heading.TLabel", background=p["panel"], foreground=p["text"], font=("Helvetica", 11, "bold"))
    style.configure("Metric.TLabel", background=p["panel"], foreground=p["text"], font=("Helvetica", 20, "bold"))
    style.configure("Danger.TLabel", background=p["bg"], foreground=p["danger"])
    style.configure("Success.TLabel", background=p["bg"], foreground=p["success"])
    style.configure("TLabelframe", background=p["panel"], bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["panel"], foreground=p["text"], font=("Helvetica", 10, "bold"))

    style.configure("TButton", background=p["panel"], foreground=p["text"], bordercolor=p["border"], padding=(10, 5))
    style.map("TButton", background=[("active", p["select"]), ("disabled", p["bg"])],
              foreground=[("disabled", p["muted"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_text"], bordercolor=p["accent"])
    style.map("Accent.TButton", background=[("active", p["accent"]), ("disabled", p["muted"])],
              foreground=[("disabled", p["bg"])])
    style.configure("Danger.TButton", background=p["panel"], foreground=p["danger"])

    style.configure("TEntry", fieldbackground=p["panel"], foreground=p["text"], insertcolor=p["text"])
    style.configure("TCombobox", fieldbackground=p["panel"], foreground=p["text"], arrowcolor=p["text"])
    style.map("TCombobox", fieldbackground=[("readonly", p["panel"])], foreground=[("readonly", p["text"])])
    style.configure("TSpinbox", fieldbackground=p["panel"], foreground=p["text"], arrowcolor=p["text"])
    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
    style.map("TCheckbutton", background=[("active", p["bg"])])
    style.configure("Panel.TCheckbutton", background=p["panel"], foreground=p["text"])
    style.map("Panel.TCheckbutton", background=[("active", p["panel"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
    style.map("TRadiobutton", background=[("active", p["bg"])])
    style.configure("Panel.TRadiobutton", background=p["panel"], foreground=p["text"])
    style.map("Panel.TRadiobutton", background=[("active", p["panel"])])

    style.configure("Treeview", background=p["panel"], fieldbackground=p["panel"], foreground=p["text"],
                    rowheight=26, bordercolor=p["border"])
    style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["text"])])
    style.configure("Treeview.Heading", background=p["bg"], foreground=p["text"], font=("Helvetica", 10, "bold"),
                    relief="flat")
    style.map("Treeview.Heading", background=[("active", p["select"])])

    style.configure("TNotebook", background=p["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], padding=(14, 7))
    style.map("TNotebook.Tab", background=[("selected", p["panel"])], foreground=[("selected", p["text"])])

    style.configure("TProgressbar", background=p["accent"], troughcolor=p["row_alt"])
    style.configure("Vertical.TScrollbar", background=p["panel"], troughcolor=p["bg"])
    style.configure("Horizontal.TScrollbar", background=p["panel"], troughcolor=p["bg"])
    return p


def apply_theme(root: tk.Misc, theme: str) -> dict[str, str]:
    """Configure ttk styles for a named built-in theme."""
    return apply_palette(root, palette_for(theme))


__all__ = ["PALETTES", "apply_palette", "apply_theme", "palette_for"]
