"""Security and persistence tests for the data-only local theme library."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from planforge.theme_library import (
    MAX_PACKAGE_BYTES,
    PALETTE_KEYS,
    create_theme_package,
    export_theme_package,
    install_theme_package,
    list_installed_themes,
    load_theme_package,
    remove_installed_theme,
    validate_theme_package,
)


class ThemePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.palette = {key: "#336699" for key in PALETTE_KEYS}
        self.package = create_theme_package("Test Theme", self.palette, description="Unit test theme")

    def test_validate_normalizes_colors_and_rejects_bad_values(self) -> None:
        source = dict(self.package, palette=dict(self.palette, accent=" #AbCdEf "))
        # Whitespace is intentionally not accepted for a color value.
        with self.assertRaises(ValueError):
            validate_theme_package(source)
        source["palette"] = dict(self.palette, accent="#ABCDEF")
        validated = validate_theme_package(source)
        self.assertEqual(validated["palette"]["accent"], "#abcdef")
        with self.assertRaisesRegex(ValueError, "six-digit"):
            validate_theme_package(dict(self.package, palette=dict(self.palette, accent="red")))

    def test_rejects_unknown_keys_and_future_schema_versions(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported theme colour"):
            validate_theme_package(dict(self.package, palette=dict(self.palette, command="run")))
        with self.assertRaisesRegex(ValueError, "schema version"):
            validate_theme_package(dict(self.package, schema_version=999))

    def test_install_list_export_import_and_remove_are_local_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "installed"
            first = install_theme_package(self.package, folder)
            second = install_theme_package(self.package, folder)
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(len(list(folder.glob("custom-*.json"))), 2)
            installed, warnings = list_installed_themes(folder)
            self.assertEqual(warnings, [])
            self.assertEqual(len(installed), 2)
            exported = Path(tmp) / "portable.json"
            export_theme_package(first, exported)
            loaded = load_theme_package(exported)
            self.assertEqual(loaded["name"], "Test Theme")
            self.assertEqual(loaded["palette"], self.palette)
            imported = install_theme_package(loaded, folder)
            self.assertNotEqual(imported["id"], first["id"])
            remove_installed_theme(first["id"], folder)
            self.assertEqual(len(list_installed_themes(folder)[0]), 2)

    def test_removal_rejects_builtin_or_traversal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for identifier in ("light", "../outside", "custom-../bad"):
                with self.assertRaises(ValueError):
                    remove_installed_theme(identifier, Path(tmp))

    def test_oversized_and_malformed_package_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{" + " " * MAX_PACKAGE_BYTES, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "512 KiB"):
                load_theme_package(path)
            path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Could not read"):
                load_theme_package(path)

    def test_corrupt_installed_theme_is_reported_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "custom-broken-12345678.json").write_text("{}", encoding="utf-8")
            themes, warnings = list_installed_themes(folder)
            self.assertEqual(themes, [])
            self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
