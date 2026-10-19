"""Light and dark colour palettes plus the ttk style configuration."""

from __future__ import annotations

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


def palette_for(theme: str) -> dict[str, str]:
    return PALETTES.get(theme, PALETTES["light"])


def apply_theme(root: tk.Misc, theme: str) -> dict[str, str]:
    """Configure every ttk style for the chosen theme and return its palette."""
    p = palette_for(theme)
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


__all__ = ["PALETTES", "apply_theme", "palette_for"]
