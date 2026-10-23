# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for standalone Windows and Linux PlanForge apps."""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
ASSETS = ROOT / "planforge" / "assets"

ICON_FILE = str(ASSETS / "planforge.ico") if sys.platform == "win32" else str(ASSETS / "planforge.png")

datas = [
    (str(ASSETS), "planforge/assets"),
    (str(ROOT / "docs" / "icon_transparent_background.png"), "docs"),
    (str(ROOT / "schemas"), "schemas"),
    (
        str(ROOT / "function-point-calculator" / "function-point-calculator-main"),
        "function-point-calculator/function-point-calculator-main",
    ),
]

hiddenimports = [
    "fp_logic",
    "sqlite3",
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.colorchooser",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "app_entry.py")],
    pathex=[
        str(ROOT),
        str(ROOT / "function-point-calculator" / "function-point-calculator-main"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["unittest", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "win32":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="PlanForge",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        icon=ICON_FILE,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PlanForge",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON_FILE,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="PlanForge",
    )
