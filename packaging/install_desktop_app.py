"""Install native OS shortcuts / application menu entries with PlanForge's icon.

Works immediately on a fresh clone OR with built binaries in ``dist/``:
- Windows : Start Menu + Desktop ``PlanForge.lnk`` shortcuts using ``planforge.ico``
            (launches built ``PlanForge.exe`` if present, otherwise windowless ``pythonw.exe``)
- macOS   : ``~/Applications/PlanForge.app`` bundle with ``planforge.icns``
- Linux   : ``~/.local/share/applications/planforge.desktop`` + XDG hicolor PNG icons
"""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planforge.icons import PNG_EXPORT_SIZES, generate_icon_bundle  # noqa: E402


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _find_pythonw() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.is_file():
        return candidate
    return exe


def install_windows(icon_files: dict[str, Path], *, target_dir: Path | None = None) -> list[Path]:
    ico_path = icon_files["ico"]
    built_exe = REPO_ROOT / "dist" / "PlanForge.exe"
    if built_exe.is_file():
        target_exe = str(built_exe)
        arguments = ""
    else:
        target_exe = str(_find_pythonw())
        arguments = f'"{REPO_ROOT / "PlanForgeLauncher.py"}"'

    shortcut_locations: list[Path] = []
    if target_dir is not None:
        target_dir.mkdir(parents=True, exist_ok=True)
        shortcut_locations.append(target_dir / "PlanForge.lnk")
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            start_menu.mkdir(parents=True, exist_ok=True)
            shortcut_locations.append(start_menu / "PlanForge.lnk")
        desktop = Path.home() / "Desktop"
        if desktop.is_dir():
            shortcut_locations.append(desktop / "PlanForge.lnk")

    created: list[Path] = []
    for lnk_path in shortcut_locations:
        ps_script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{str(lnk_path).replace(chr(39), chr(39)*2)}'); "
            f"$s.TargetPath = '{target_exe.replace(chr(39), chr(39)*2)}'; "
            f"$s.Arguments = '{arguments.replace(chr(39), chr(39)*2)}'; "
            f"$s.WorkingDirectory = '{str(REPO_ROOT).replace(chr(39), chr(39)*2)}'; "
            f"$s.IconLocation = '{str(ico_path).replace(chr(39), chr(39)*2)},0'; "
            "$s.Description = 'PlanForge - Project Planner and Interoperability Suite'; "
            "$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            check=True,
        )
        created.append(lnk_path)
    return created


def create_macos_launcher_bundle(
    dest_app: Path,
    icns_path: Path,
    *,
    fallback_repo: Path | None = None,
) -> Path:
    """Create or refresh a standalone clickable macOS ``PlanForge.app`` bundle."""
    contents = dest_app / "Contents"
    macos_dir = contents / "MacOS"
    res_dir = contents / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(icns_path, res_dir / "planforge.icns")

    info_data = {
        "CFBundleName": "PlanForge",
        "CFBundleDisplayName": "PlanForge",
        "CFBundleIdentifier": "io.planforge.desktop",
        "CFBundleVersion": "1.3.0",
        "CFBundleShortVersionString": "1.3.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "PlanForge",
        "CFBundleIconFile": "planforge.icns",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info_data))

    if fallback_repo is not None:
        repo_str = str(fallback_repo).replace('"', '\\"')
        else_branch = f'else\n    REPO_DIR="{repo_str}"\n'
    else:
        else_branch = (
            'else\n'
            '    osascript -e \'display alert "PlanForge" message "Keep PlanForge.app inside the PlanForge folder or run InstallApp.command once."\' >/dev/null 2>&1 || true\n'
            '    exit 1\n'
        )
    launcher_script = (
        '#!/bin/sh\n'
        'BUNDLE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"\n'
        'if [ -f "$BUNDLE_ROOT/PlanForgeLauncher.sh" ]; then\n'
        '    REPO_DIR="$BUNDLE_ROOT"\n'
        f'{else_branch}'
        'fi\n'
        'export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"\n'
        'for arg in "$@"; do\n'
        '    case "$arg" in\n'
        '        -psn_*) ;;\n'
        '        *) set -- "$@" "$arg" ;;\n'
        '    esac\n'
        '    shift\n'
        'done\n'
        'exec /bin/sh "$REPO_DIR/PlanForgeLauncher.sh" "$@"\n'
    )
    exe_file = macos_dir / "PlanForge"
    exe_file.write_text(launcher_script, encoding="utf-8")
    _make_executable(exe_file)
    return dest_app


def install_macos(icon_files: dict[str, Path], *, target_dir: Path | None = None) -> list[Path]:
    icns_path = icon_files["icns"]
    repo_app = create_macos_launcher_bundle(REPO_ROOT / "PlanForge.app", icns_path)
    apps_dir = target_dir or (Path.home() / "Applications")
    apps_dir.mkdir(parents=True, exist_ok=True)
    dest = apps_dir / "PlanForge.app"
    built_app = REPO_ROOT / "dist" / "PlanForge.app"
    if dest.exists():
        shutil.rmtree(dest)
    if built_app.is_dir():
        shutil.copytree(built_app, dest, symlinks=True)
    else:
        create_macos_launcher_bundle(dest, icns_path, fallback_repo=REPO_ROOT)
    return [repo_app, dest]


def install_linux(icon_files: dict[str, Path], *, data_home: Path | None = None) -> list[Path]:
    xdg_data = data_home or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    created: list[Path] = []
    for size in PNG_EXPORT_SIZES:
        if size <= 512:
            icon_dir = xdg_data / "icons" / "hicolor" / f"{size}x{size}" / "apps"
            icon_dir.mkdir(parents=True, exist_ok=True)
            dest_icon = icon_dir / "planforge.png"
            shutil.copy2(icon_files[f"png_{size}"], dest_icon)
            created.append(dest_icon)

    built_bin = REPO_ROOT / "dist" / "PlanForge" / "PlanForge"
    exec_cmd = f'"{built_bin}" %f' if built_bin.is_file() else f'"{REPO_ROOT / "PlanForgeLauncher.sh"}" %f'

    desktop_content = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=PlanForge\n"
        "GenericName=Project Planner\n"
        "Comment=Offline-first project planning, scheduling, and interoperability suite\n"
        f"Exec={exec_cmd}\n"
        "Icon=planforge\n"
        "Terminal=false\n"
        "Categories=Office;ProjectManagement;Development;\n"
        "StartupWMClass=PlanForge\n"
        "MimeType=application/x-planforge-project;\n"
    )
    apps_dir = xdg_data / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = apps_dir / "planforge.desktop"
    desktop_path.write_text(desktop_content, encoding="utf-8")
    _make_executable(desktop_path)
    created.append(desktop_path)

    update_cache = shutil.which("gtk-update-icon-cache")
    if update_cache:
        subprocess.run([update_cache, "-f", "-t", str(xdg_data / "icons" / "hicolor")], check=False)
    update_desktop = shutil.which("update-desktop-database")
    if update_desktop:
        subprocess.run([update_desktop, str(apps_dir)], check=False)

    return created


def main() -> int:
    icon_files = generate_icon_bundle()
    create_macos_launcher_bundle(REPO_ROOT / "PlanForge.app", icon_files["icns"])

    if sys.platform == "win32":
        installed = install_windows(icon_files)
    elif sys.platform == "darwin":
        installed = install_macos(icon_files)
    else:
        installed = install_linux(icon_files)

    print("Installed PlanForge application launchers with icon:")
    for path in installed:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
