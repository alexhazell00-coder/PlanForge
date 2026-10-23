"""Tests for Windows & Linux icon generation and native desktop app packaging."""

from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from packaging.install_desktop_app import install_linux
from planforge.icons import (
    ICO_SIZES,
    PNG_EXPORT_SIZES,
    PNG_SIGNATURE,
    assets_dir,
    decode_png_rgba,
    generate_icon_bundle,
    source_icon_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POSIX = os.name == "posix"


class IconGenerationAndPackagingTests(unittest.TestCase):
    def test_source_icon_exists_and_decodes_cleanly(self) -> None:
        src = source_icon_path(REPO_ROOT)
        self.assertTrue(src.is_file(), f"Missing canonical icon: {src}")
        w, h, rgba = decode_png_rgba(src.read_bytes())
        self.assertGreater(w, 256)
        self.assertGreater(h, 256)
        self.assertEqual(len(rgba), w * h * 4)

    def test_generated_ico_and_png_assets_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = generate_icon_bundle(source_icon_path(REPO_ROOT), Path(tmp))

            # 1. Verify all PNG export sizes
            for size in PNG_EXPORT_SIZES:
                png_path = out[f"png_{size}"]
                w, h, _rgba = decode_png_rgba(png_path.read_bytes())
                self.assertEqual((w, h), (size, size))

            # 2. Verify Windows multi-resolution .ico binary header & embedded PNG frames
            ico_bytes = out["ico"].read_bytes()
            reserved, ico_type, count = struct.unpack("<HHH", ico_bytes[:6])
            self.assertEqual((reserved, ico_type, count), (0, 1, len(ICO_SIZES)))
            for idx, expected_size in enumerate(ICO_SIZES):
                entry = ico_bytes[6 + idx * 16 : 6 + (idx + 1) * 16]
                bw, bh, _colors, _res, planes, bpp, byte_len, offset = struct.unpack(
                    "<BBBBHHII", entry
                )
                expected_dim = 0 if expected_size >= 256 else expected_size
                self.assertEqual((bw, bh, planes, bpp), (expected_dim, expected_dim, 1, 32))
                frame = ico_bytes[offset : offset + byte_len]
                self.assertTrue(frame.startswith(PNG_SIGNATURE))
                fw, fh, _ = decode_png_rgba(frame)
                self.assertEqual((fw, fh), (expected_size, expected_size))

    def test_bundled_package_assets_and_readme_macos_note(self) -> None:
        folder = assets_dir()
        for name in ("planforge.ico", "planforge.png", "planforge-256.png", "planforge-32.png"):
            self.assertTrue((folder / name).is_file(), f"Missing bundled asset {name}")
        self.assertFalse((REPO_ROOT / "PlanForge.app").exists())
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("no official native macOS application launcher", readme)

    def test_app_install_and_build_wrappers_have_valid_line_endings_and_syntax(self) -> None:
        for bat_name in ("InstallApp.bat", "BuildApp.bat"):
            raw = (REPO_ROOT / bat_name).read_bytes()
            self.assertIn(b"\r\n", raw)
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), f"{bat_name} must use CRLF")
            raw.decode("ascii")

        if POSIX:
            for script_name in ("InstallApp.sh", "BuildApp.sh"):
                script_path = REPO_ROOT / script_name
                self.assertTrue(os.access(script_path, os.X_OK), f"{script_name} must be executable")
                res = subprocess.run(["/bin/sh", "-n", str(script_path)], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stderr)

    def test_linux_xdg_installer(self) -> None:
        icons = {
            "ico": assets_dir() / "planforge.ico",
            "png": assets_dir() / "planforge.png",
            **{f"png_{s}": assets_dir() / f"planforge-{s}.png" for s in PNG_EXPORT_SIZES},
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            created = install_linux(icons, data_home=tmp_path / "share")
            desktop_file = tmp_path / "share" / "applications" / "planforge.desktop"
            self.assertIn(desktop_file, created)
            text = desktop_file.read_text(encoding="utf-8")
            self.assertIn("Icon=planforge", text)
            self.assertIn("StartupWMClass=PlanForge", text)
            self.assertTrue((tmp_path / "share" / "icons" / "hicolor" / "256x256" / "apps" / "planforge.png").is_file())


if __name__ == "__main__":
    unittest.main()
