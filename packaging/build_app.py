"""Native application builder for PlanForge (Windows & Linux).

Builds ready-to-distribute native desktop applications with
``docs/icon_transparent_background.png`` compiled into platform icons:

- Windows : ``dist/PlanForge.exe`` + ``dist/PlanForge-Windows-x64.zip``
- Linux   : ``dist/PlanForge/PlanForge`` + ``dist/PlanForge-Linux-x86_64.AppImage``
            (when ``appimagetool`` is on PATH) + ``dist/PlanForge-Linux-x86_64.tar.gz``

Note: macOS has no official standalone native app launcher; macOS users can run
PlanForge directly via ``PlanForgeLauncher.command`` or ``./PlanForgeLauncher.sh``.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import sysconfig
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planforge.icons import PNG_EXPORT_SIZES, generate_icon_bundle  # noqa: E402


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _ensure_pyinstaller(auto_install: bool) -> None:
    probe = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        print(f"Using PyInstaller {probe.stdout.strip()}")
        return
    if not auto_install:
        raise RuntimeError(
            "PyInstaller is not installed in this Python environment.\n"
            f"Install it with:\n  {sys.executable} -m pip install -r packaging/requirements-build.txt\n"
            "or re-run with: python packaging/build_app.py --install-pyinstaller"
        )
    print("Installing PyInstaller into build environment...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--requirement",
            str(REPO_ROOT / "packaging" / "requirements-build.txt"),
        ],
        check=True,
    )


def _package_windows(dist_dir: Path) -> list[Path]:
    exe_path = dist_dir / "PlanForge.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"Expected built executable not found: {exe_path}")
    arch = "arm64" if "arm" in platform.machine().lower() else "x64"
    zip_path = dist_dir / f"PlanForge-Windows-{arch}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, arcname="PlanForge.exe")
        zf.write(REPO_ROOT / "README.md", arcname="README.md")
    return [exe_path, zip_path]


def _package_linux(dist_dir: Path, icon_files: dict[str, Path]) -> list[Path]:
    app_folder = dist_dir / "PlanForge"
    binary_path = app_folder / "PlanForge"
    if not binary_path.is_file():
        raise FileNotFoundError(f"Expected Linux executable not found: {binary_path}")
    _make_executable(binary_path)

    machine = platform.machine() or "x86_64"
    outputs: list[Path] = []

    appdir = dist_dir / "PlanForge.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    usr_bin = appdir / "usr" / "bin"
    usr_bin.mkdir(parents=True)
    shutil.copytree(app_folder, appdir / "usr" / "lib" / "planforge", symlinks=True)

    apprun = appdir / "AppRun"
    apprun.write_text(
        '#!/bin/sh\n'
        'SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$SELF_DIR/usr/lib/planforge/PlanForge" "$@"\n',
        encoding="utf-8",
    )
    _make_executable(apprun)

    launcher_symlink = usr_bin / "PlanForge"
    launcher_symlink.symlink_to("../lib/planforge/PlanForge")

    desktop_entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PlanForge\n"
        "GenericName=Project Planner\n"
        "Comment=Offline-first project planning, scheduling, and interoperability suite\n"
        "Exec=PlanForge %f\n"
        "Icon=planforge\n"
        "Terminal=false\n"
        "Categories=Office;ProjectManagement;Development;\n"
        "StartupWMClass=PlanForge\n"
        "MimeType=application/x-planforge-project;\n"
    )
    desktop_file = appdir / "planforge.desktop"
    desktop_file.write_text(desktop_entry, encoding="utf-8")
    _make_executable(desktop_file)

    main_png = icon_files["png"]
    shutil.copy2(main_png, appdir / "planforge.png")
    shutil.copy2(main_png, appdir / ".DirIcon")
    for size in PNG_EXPORT_SIZES:
        icon_dest = appdir / "usr" / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        icon_dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_files[f"png_{size}"], icon_dest / "planforge.png")

    shutil.copy2(main_png, app_folder / "planforge.png")
    portable_install = app_folder / "install-desktop.sh"
    portable_install.write_text(
        '#!/bin/sh\n'
        'set -eu\n'
        'APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"\n'
        'MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"\n'
        'mkdir -p "$ICON_DIR" "$MENU_DIR"\n'
        'cp "$APP_DIR/planforge.png" "$ICON_DIR/planforge.png"\n'
        'cat > "$MENU_DIR/planforge.desktop" <<EOF\n'
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Name=PlanForge\n'
        'Comment=Offline-first project planning and scheduling\n'
        'Exec="$APP_DIR/PlanForge" %f\n'
        'Icon=planforge\n'
        'Terminal=false\n'
        'Categories=Office;ProjectManagement;Development;\n'
        'StartupWMClass=PlanForge\n'
        'EOF\n'
        'chmod +x "$MENU_DIR/planforge.desktop"\n'
        'echo "Installed PlanForge desktop entry -> $MENU_DIR/planforge.desktop"\n',
        encoding="utf-8",
    )
    _make_executable(portable_install)

    tar_path = dist_dir / f"PlanForge-Linux-{machine}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(app_folder, arcname="PlanForge")
    outputs.append(tar_path)

    appimagetool = shutil.which("appimagetool")
    if appimagetool:
        appimage_path = dist_dir / f"PlanForge-Linux-{machine}.AppImage"
        if appimage_path.exists():
            appimage_path.unlink()
        env = dict(os.environ)
        env.setdefault("ARCH", machine)
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
        subprocess.run(
            [appimagetool, str(appdir), str(appimage_path)],
            env=env,
            check=True,
        )
        _make_executable(appimage_path)
        outputs.append(appimage_path)

    return outputs


def build_native_app(*, install_pyinstaller: bool = False) -> list[Path]:
    if sys.platform == "darwin":
        raise RuntimeError(
            "macOS currently has no official native app launcher package. "
            "Launch PlanForge via PlanForgeLauncher.command or ./PlanForgeLauncher.sh."
        )

    print("Step 1/3: Generating native icons (.ico, .png) from docs/icon_transparent_background.png...")
    icon_files = generate_icon_bundle()

    print("Step 2/3: Running PyInstaller native bundle build...")
    _ensure_pyinstaller(install_pyinstaller)
    dist_dir = REPO_ROOT / "dist"
    build_dir = REPO_ROOT / "build"
    pyi_env = dict(os.environ)
    libdir = sysconfig.get_config_var("LIBDIR")
    if libdir and Path(libdir).is_dir():
        existing_ld = pyi_env.get("LD_LIBRARY_PATH", "")
        pyi_env["LD_LIBRARY_PATH"] = f"{libdir}:{existing_ld}" if existing_ld else libdir

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(build_dir),
            str(REPO_ROOT / "PlanForge.spec"),
        ],
        cwd=str(REPO_ROOT),
        env=pyi_env,
    )
    if proc.returncode != 0:
        if sys.platform.startswith("linux"):
            ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            raise RuntimeError(
                f"PyInstaller exited with status {proc.returncode}. On Debian/Ubuntu ensure "
                f"'sudo apt install libpython{ver} python3-tk' is installed."
            )
        raise RuntimeError(f"PyInstaller exited with status {proc.returncode}.")

    print("Step 3/3: Packaging platform distributable archives...")
    if sys.platform == "win32":
        artifacts = _package_windows(dist_dir)
    else:
        artifacts = _package_linux(dist_dir, icon_files)

    print("\nBuild complete! Distributable artifacts:")
    for item in artifacts:
        size_desc = f"{item.stat().st_size:,} bytes" if item.is_file() else "bundle directory"
        print(f"  - {item} ({size_desc})")
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build standalone native PlanForge desktop app (Windows/Linux).")
    parser.add_argument(
        "--install-pyinstaller",
        action="store_true",
        help="Install PyInstaller from packaging/requirements-build.txt if not already present.",
    )
    args = parser.parse_args(argv)
    try:
        build_native_app(install_pyinstaller=args.install_pyinstaller)
    except Exception as exc:
        print(f"Build error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
