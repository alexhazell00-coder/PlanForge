# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for standalone PlanForge native desktop apps."""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
ASSETS = ROOT / "planforge" / "assets"

if sys.platform == "win32":
    ICON_FILE = str(ASSETS / "planforge.ico")
elif sys.platform == "darwin":
    ICON_FILE = str(ASSETS / "planforge.icns")
else:
    ICON_FILE = str(ASSETS / "planforge.png")

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
    # Single-file native Windows executable with embedded multi-size .ico icon
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
elif sys.platform == "darwin":
    # Native macOS .app bundle with Retina .icns icon and .pfp association
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
    app = BUNDLE(
        coll,
        name="PlanForge.app",
        icon=ICON_FILE,
        bundle_identifier="io.planforge.desktop",
        info_plist={
            "CFBundleName": "PlanForge",
            "CFBundleDisplayName": "PlanForge",
            "CFBundleShortVersionString": "1.3.0",
            "CFBundleVersion": "1.3.0",
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "PlanForge Project",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Owner",
                    "CFBundleTypeExtensions": ["pfp"],
                }
            ],
        },
    )
else:
    # Self-contained Linux directory bundle (also packaged into .AppImage & .tar.gz)
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
