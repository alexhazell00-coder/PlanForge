"""Tests for the universal launcher.

These tests never open a PlanForge window and never require a display.  They
combine fast unit tests (with fake interpreters and package installers) with
real subprocess launches of a small fake application tree, so the venv,
locking, path handling and exit-code behaviour are exercised for real.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import launcher

REPO_ROOT = Path(launcher.__file__).resolve().parent
POSIX = os.name == "posix"


def result(
    code: int = 0,
    stdout: str = "",
    stderr: str = "",
    *,
    timed_out: bool = False,
) -> launcher.CommandResult:
    return launcher.CommandResult(code, stdout, stderr, None, timed_out)


def info(
    executable: str,
    version: tuple[int, int, int] = (3, 11, 2),
    *,
    tkinter: bool = False,
    prefix: str = "/usr",
    base_prefix: str = "/usr",
    has_pip: bool = True,
) -> launcher.PythonInfo:
    return launcher.PythonInfo(
        executable=executable,
        version=version,
        implementation="cpython",
        prefix=prefix,
        base_prefix=base_prefix,
        tkinter=tkinter,
        tk_version="8.6" if tkinter else "",
        tkinter_error="" if tkinter else "ModuleNotFoundError: No module named 'tkinter'",
        has_venv=True,
        has_ensurepip=True,
        has_pip=has_pip,
    )


class FakeRunner:
    """Records commands and delegates results to a handler."""

    def __init__(self, handler=None) -> None:
        self.calls: list[list[str]] = []
        self.handler = handler or (lambda args, kwargs: result())

    def __call__(self, args, **kwargs):
        command = [str(arg) for arg in args]
        self.calls.append(command)
        return self.handler(command, kwargs)


def same_path(left, right) -> bool:
    """Compare paths the way the current OS does (case, separators)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(left)))) == os.path.normcase(
        os.path.normpath(os.path.abspath(str(right)))
    )


def linux_platform(**release):
    data = {"ID": "debian", "ID_LIKE": "debian", "PRETTY_NAME": "Debian GNU/Linux 12"}
    data.update(release)
    return launcher.detect_platform(system="Linux", machine="x86_64", os_release=data)


# ---------------------------------------------------------------------------
# Platform, paths and command line
# ---------------------------------------------------------------------------


class PlatformTests(unittest.TestCase):
    def test_windows_detection_and_architecture(self) -> None:
        platform = launcher.detect_platform(system="Windows", machine="AMD64", release="10")
        self.assertEqual(platform.key, "windows")
        self.assertEqual(platform.architecture, "x86_64")
        self.assertTrue(platform.supported)

    def test_macos_detection(self) -> None:
        platform = launcher.detect_platform(
            system="Darwin", machine="arm64", mac_version="14.5"
        )
        self.assertEqual(platform.key, "macos")
        self.assertEqual(platform.architecture, "arm64")
        self.assertIn("14.5", platform.display_name)

    def test_arch_and_ubuntu_package_managers(self) -> None:
        arch = launcher.detect_platform(
            system="Linux",
            machine="x86_64",
            os_release={"ID": "arch", "ID_LIKE": "arch", "PRETTY_NAME": "Arch Linux"},
        )
        self.assertEqual(arch.package_manager, "pacman")
        self.assertTrue(any("pacman" in hint for hint in launcher.tkinter_hints(arch)))

        ubuntu = launcher.detect_platform(
            system="Linux",
            machine="aarch64",
            os_release={"ID": "ubuntu", "ID_LIKE": "debian", "PRETTY_NAME": "Ubuntu 24.04"},
        )
        self.assertEqual(ubuntu.package_manager, "apt")
        self.assertEqual(ubuntu.architecture, "arm64")
        self.assertTrue(any("apt" in hint for hint in launcher.tkinter_hints(ubuntu)))

    def test_other_package_managers_and_unsupported_os(self) -> None:
        fedora = launcher.detect_platform(
            system="Linux", machine="x86_64", os_release={"ID": "fedora"}
        )
        self.assertEqual(fedora.package_manager, "dnf")
        suse = launcher.detect_platform(
            system="Linux",
            machine="x86_64",
            os_release={"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"},
        )
        self.assertEqual(suse.package_manager, "zypper")
        freebsd = launcher.detect_platform(system="FreeBSD", machine="amd64")
        self.assertEqual(freebsd.key, "unsupported")
        self.assertFalse(freebsd.supported)

    def test_architecture_normalisation(self) -> None:
        self.assertEqual(launcher.normalise_architecture("AMD64"), "x86_64")
        self.assertEqual(launcher.normalise_architecture("aarch64"), "arm64")
        self.assertEqual(launcher.normalise_architecture("i686"), "x86")
        self.assertEqual(launcher.normalise_architecture(""), "unknown")

    def test_venv_layouts(self) -> None:
        root = Path("/tmp/planforge")
        windows = launcher.venv_paths(root, "windows")
        self.assertEqual(windows.python, root / ".venv" / "Scripts" / "python.exe")
        self.assertEqual(windows.pythonw, root / ".venv" / "Scripts" / "pythonw.exe")
        linux = launcher.venv_paths(root, "linux")
        self.assertEqual(linux.python, root / ".venv" / "bin" / "python")
        self.assertIsNone(linux.pythonw)

    def test_guidance_mentions_platform_packages(self) -> None:
        ubuntu = linux_platform()
        self.assertTrue(any("python3-tk" in h for h in launcher.tkinter_hints(ubuntu)))
        self.assertTrue(any("python3-venv" in h for h in launcher.venv_failure_hints(ubuntu)))
        self.assertTrue(any("apt" in h for h in launcher.python_install_hints(ubuntu)))
        self.assertTrue(any("brew" in h for h in launcher.tkinter_hints(
            launcher.detect_platform(system="Darwin", machine="arm64", mac_version="14")
        )))


class CommandLineTests(unittest.TestCase):
    def test_launcher_flags_and_passthrough(self) -> None:
        options = launcher.parse_options(
            ["--check", "--verbose", "my project.pfp", "--export-format", "ganttproject"]
        )
        self.assertTrue(options.check)
        self.assertTrue(options.verbose)
        self.assertEqual(
            options.app_args, ("my project.pfp", "--export-format", "ganttproject")
        )

    def test_double_dash_separates_app_arguments(self) -> None:
        options = launcher.parse_options(["--gui", "--", "--help", "--check"])
        self.assertTrue(options.gui)
        self.assertFalse(options.check)
        self.assertEqual(options.app_args, ("--help", "--check"))

    def test_conflicting_modes_are_rejected(self) -> None:
        with self.assertRaises(launcher.UsageError):
            launcher.parse_options(["--check", "--setup"])
        with self.assertRaises(launcher.UsageError):
            launcher.parse_options(["--check", "--recreate-venv"])

    def test_gui_mode_detection_matches_application_cli(self) -> None:
        self.assertTrue(launcher.needs_gui([]))
        self.assertTrue(launcher.needs_gui(["my.pfp"]))
        self.assertFalse(launcher.needs_gui(["--import-file", "x.xml"]))
        self.assertFalse(launcher.needs_gui(["--import-file=x.xml"]))
        self.assertFalse(launcher.needs_gui(["--help"]))
        self.assertTrue(launcher.needs_gui(["--export-file", "out.gan"]))

    def test_relative_paths_are_resolved_against_caller(self) -> None:
        base = Path("/home/user/projects")
        args = launcher.normalize_app_args(
            [
                "--import-file",
                "inputs/schedule one.xml",
                "--export-file",
                "outputs/schedule.gan",
                "--export-format",
                "ganttproject",
            ],
            base,
        )
        self.assertEqual(args[1], str(base / "inputs" / "schedule one.xml"))
        self.assertEqual(args[3], str(base / "outputs" / "schedule.gan"))
        self.assertEqual(args[4:], ["--export-format", "ganttproject"])

    def test_project_path_and_equals_forms(self) -> None:
        args = launcher.normalize_app_args(
            ["--import-file=in.xml", "project.pfp"], "/tmp/base"
        )
        self.assertEqual(args[0], "--import-file=/tmp/base/in.xml")
        self.assertEqual(args[1], "/tmp/base/project.pfp")
        absolute = str(Path("/tmp/absolute.pfp"))
        self.assertEqual(
            launcher.normalize_app_args([absolute], "/tmp/base"), [absolute]
        )


# ---------------------------------------------------------------------------
# Interpreter discovery
# ---------------------------------------------------------------------------


class PythonSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.platform = linux_platform()

    def _which(self, mapping):
        return lambda name: mapping.get(name)

    def test_prefers_the_newest_compatible_interpreter(self) -> None:
        mapping = {
            "python3.10": "/opt/python3.10",
            "python3.12": "/opt/python3.12",
            "python3": "/opt/python3.12",
        }
        versions = {
            "/opt/python3.10": (3, 10, 9),
            "/opt/python3.12": (3, 12, 3),
        }

        def probe(executable, args=(), **kwargs):
            version = versions.get(executable)
            return info(executable, version) if version else None

        chosen = launcher.select_python(
            self.platform,
            gui=False,
            which=self._which(mapping),
            probe=probe,
            include_current=False,
        )
        self.assertEqual(chosen.executable, "/opt/python3.12")

    def test_gui_prefers_an_interpreter_with_tkinter(self) -> None:
        mapping = {"python3.10": "/opt/python3.10", "python3.12": "/opt/python3.12"}

        def probe(executable, args=(), **kwargs):
            if executable == "/opt/python3.10":
                return info(executable, (3, 10, 12), tkinter=True)
            if executable == "/opt/python3.12":
                return info(executable, (3, 12, 1), tkinter=False)
            return None

        chosen = launcher.select_python(
            self.platform,
            gui=True,
            which=self._which(mapping),
            probe=probe,
            include_current=False,
        )
        self.assertEqual(chosen.executable, "/opt/python3.10")

    def test_missing_python_has_a_clear_error(self) -> None:
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.select_python(
                self.platform,
                gui=False,
                which=lambda name: None,
                probe=lambda *a, **k: None,
                include_current=False,
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.MISSING_PYTHON)
        self.assertTrue(caught.exception.hints)

    def test_unsupported_python_version_is_reported(self) -> None:
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.select_python(
                self.platform,
                gui=False,
                which=lambda name: "/usr/bin/python3",
                probe=lambda executable, args=(), **kwargs: info(executable, (3, 9, 18)),
                include_current=False,
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.UNSUPPORTED_PYTHON)
        self.assertIn("3.9.18", caught.exception.summary)

    def test_real_probe_of_current_interpreter(self) -> None:
        probed = launcher.probe_python(sys.executable)
        self.assertIsNotNone(probed)
        assert probed is not None
        self.assertEqual(probed.version, tuple(sys.version_info[:3]))
        self.assertTrue(probed.has_venv)

    def test_probe_of_missing_executable_returns_none(self) -> None:
        self.assertIsNone(launcher.probe_python("/definitely/not/python"))


# ---------------------------------------------------------------------------
# Virtual environments and locking
# ---------------------------------------------------------------------------


class VenvStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = launcher.venv_paths(self.root, "linux")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_replaceability_is_conservative(self) -> None:
        self.assertTrue(launcher.venv_can_be_replaced(self.paths)[0])
        self.paths.root.mkdir()
        self.assertTrue(launcher.venv_can_be_replaced(self.paths)[0])
        (self.paths.root / "bin").mkdir()
        self.assertTrue(launcher.venv_can_be_replaced(self.paths)[0])
        (self.paths.root / "important.txt").write_text("keep me")
        self.assertFalse(launcher.venv_can_be_replaced(self.paths)[0])
        with self.assertRaises(launcher.LauncherError):
            launcher.remove_venv(self.paths)
        self.assertTrue((self.paths.root / "important.txt").exists())

    def test_validation_states(self) -> None:
        self.assertEqual(launcher.validate_venv(self.paths).status, "missing")
        self.paths.root.mkdir()
        self.assertEqual(launcher.validate_venv(self.paths).status, "invalid")
        (self.paths.root / "pyvenv.cfg").write_text("home = /usr/bin\n")
        self.assertEqual(launcher.validate_venv(self.paths).status, "invalid")

    def test_real_venv_is_validated(self) -> None:
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(self.paths.root)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        state = launcher.validate_venv(self.paths)
        self.assertEqual(state.status, "ready", state.reason)
        assert state.info is not None
        self.assertEqual(state.info.version, tuple(sys.version_info[:3]))

    def test_interrupted_venv_is_recognised(self) -> None:
        (self.paths.root / "bin").mkdir(parents=True)
        (self.paths.root / "lib").mkdir()
        can_replace, reason = launcher.venv_can_be_replaced(self.paths)
        self.assertTrue(can_replace)
        self.assertIn("partial", reason)


class LockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / ".planforge-setup.lock"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lock_is_created_and_released(self) -> None:
        with launcher.SetupLock(self.path, wait_seconds=0.1) as lock:
            self.assertTrue(self.path.exists())
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
        self.assertFalse(self.path.exists())

    def test_lock_released_after_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with launcher.SetupLock(self.path, wait_seconds=0.1):
                raise RuntimeError("setup failed")
        self.assertFalse(self.path.exists())

    def test_busy_lock_times_out(self) -> None:
        self.path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        with self.assertRaises(launcher.LauncherError) as caught:
            with launcher.SetupLock(
                self.path,
                wait_seconds=0.15,
                poll_seconds=0.02,
                alive_check=lambda pid: True,
            ):
                pass
        self.assertEqual(caught.exception.code, launcher.ExitCode.BUSY)
        self.assertTrue(self.path.exists())

    def test_stale_lock_is_replaced(self) -> None:
        self.path.write_text(json.dumps({"pid": 424242}), encoding="utf-8")
        with launcher.SetupLock(
            self.path, wait_seconds=0.2, alive_check=lambda pid: False
        ):
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
        self.assertFalse(self.path.exists())


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class DependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = launcher.venv_paths(self.root, "linux")
        self.paths.bin_dir.mkdir(parents=True)
        self.paths.python.write_text("")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_manifest(self, text: str) -> None:
        (self.root / "requirements.txt").write_text(text, encoding="utf-8")

    def test_manifest_parser_ignores_comments(self) -> None:
        self.write_manifest("# comment\n\npackaging>=23\n  # indented\n")
        self.assertEqual(launcher.read_requirement_lines(self.root), ["packaging>=23"])

    def test_no_manifest_means_no_pip_call(self) -> None:
        runner = FakeRunner(lambda args, kwargs: self.fail("pip should not run"))
        report = launcher.check_dependencies(self.paths, self.root, run=runner)
        self.assertEqual(report.status, launcher.DEP_NONE)

    def test_offline_check_reports_missing(self) -> None:
        self.write_manifest("packaging==24.2\n")
        runner = FakeRunner(
            lambda args, kwargs: result(0)
            if "--version" in args
            else result(1, "ERROR: No matching distribution found for packaging")
        )
        report = launcher.check_dependencies(self.paths, self.root, run=runner)
        self.assertEqual(report.status, launcher.DEP_MISSING)

    def test_offline_check_reports_invalid_requirement(self) -> None:
        self.write_manifest("this is not a requirement\n")
        runner = FakeRunner(
            lambda args, kwargs: result(0)
            if "--version" in args
            else result(1, "ERROR: Invalid requirement: 'this is not a requirement'")
        )
        report = launcher.check_dependencies(self.paths, self.root, run=runner)
        self.assertEqual(report.status, launcher.DEP_INVALID)

    def test_old_pip_without_dry_run_falls_back(self) -> None:
        self.write_manifest("packaging==24.2\n")
        commands = []

        def handler(args, kwargs):
            commands.append(args)
            if "--version" in args:
                return result(0, "pip 20.3")
            if "--dry-run" in args:
                return result(1, "no such option: --dry-run")
            return result(0, "Requirement already satisfied")

        report = launcher.check_dependencies(self.paths, self.root, run=FakeRunner(handler))
        self.assertEqual(report.status, launcher.DEP_SATISFIED)
        self.assertTrue(any("--dry-run" not in cmd for cmd in commands))

    def test_pip_missing_is_reported(self) -> None:
        self.write_manifest("packaging==24.2\n")
        runner = FakeRunner(lambda args, kwargs: result(1, "No module named pip"))
        report = launcher.check_dependencies(self.paths, self.root, run=runner)
        self.assertEqual(report.status, launcher.DEP_PIP_MISSING)

    def test_install_success_is_verified(self) -> None:
        self.write_manifest("packaging==24.2\n")
        state = {"installed": False}

        def handler(args, kwargs):
            if "--version" in args:
                return result(0, "pip 24")
            if "--no-index" in args:
                return result(0) if state["installed"] else result(1, "not found")
            state["installed"] = True
            return result(0, "Successfully installed packaging")

        report = launcher.ensure_dependencies(
            self.paths,
            self.root,
            platform_info=linux_platform(),
            run=FakeRunner(handler),
        )
        self.assertEqual(report.status, launcher.DEP_INSTALLED)

    def test_network_failure_is_classified(self) -> None:
        self.write_manifest("packaging==24.2\n")

        def handler(args, kwargs):
            if "--version" in args:
                return result(0, "pip 24")
            if "--no-index" in args:
                return result(1, "not installed")
            return result(1, "Temporary failure in name resolution")

        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.ensure_dependencies(
                self.paths,
                self.root,
                platform_info=linux_platform(),
                run=FakeRunner(handler),
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.NETWORK_ERROR)
        self.assertTrue(any("internet" in hint.lower() for hint in caught.exception.hints))

    def test_bad_package_is_a_dependency_error(self) -> None:
        self.write_manifest("no-such-package==9.9\n")

        def handler(args, kwargs):
            if "--version" in args:
                return result(0, "pip 24")
            if "--no-index" in args:
                return result(1, "not installed")
            return result(1, "ERROR: No matching distribution found for no-such-package")

        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.ensure_dependencies(
                self.paths,
                self.root,
                platform_info=linux_platform(),
                run=FakeRunner(handler),
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.DEPENDENCY_ERROR)

    def test_false_success_is_not_reported_as_installed(self) -> None:
        self.write_manifest("packaging==24.2\n")

        def handler(args, kwargs):
            if "--version" in args:
                return result(0, "pip 24")
            if "--no-index" in args:
                return result(1, "not installed")
            return result(0, "Successfully installed (but nothing changed)")

        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.ensure_dependencies(
                self.paths,
                self.root,
                platform_info=linux_platform(),
                run=FakeRunner(handler),
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.DEPENDENCY_ERROR)
        self.assertIn("reported success", caught.exception.summary)

    def test_missing_pip_is_repaired(self) -> None:
        self.write_manifest("packaging==24.2\n")
        state = {"pip": False, "installed": False}

        def handler(args, kwargs):
            if "ensurepip" in args:
                state["pip"] = True
                return result(0, "Successfully installed pip")
            if "--version" in args:
                return result(0, "pip 24") if state["pip"] else result(1, "No module named pip")
            if "--no-index" in args:
                return result(0) if state["installed"] else result(1, "not installed")
            state["installed"] = True
            return result(0, "installed")

        report = launcher.ensure_dependencies(
            self.paths,
            self.root,
            platform_info=linux_platform(),
            run=FakeRunner(handler),
        )
        self.assertEqual(report.status, launcher.DEP_INSTALLED)

    def test_failed_ensurepip_is_an_error(self) -> None:
        self.write_manifest("packaging==24.2\n")
        runner = FakeRunner(
            lambda args, kwargs: result(1, "No module named ensurepip")
            if "ensurepip" in args
            else result(1, "No module named pip")
        )
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.ensure_dependencies(
                self.paths,
                self.root,
                platform_info=linux_platform(),
                run=runner,
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.DEPENDENCY_ERROR)

    def test_failure_classifier(self) -> None:
        self.assertEqual(
            launcher.classify_install_failure(result(1, "connection reset by peer")),
            "network",
        )
        self.assertEqual(
            launcher.classify_install_failure(result(1, "Invalid requirement")),
            "dependency",
        )
        self.assertEqual(
            launcher.classify_install_failure(result(1, "", timed_out=True)), "network"
        )
        index_output = (
            "Looking in indexes: http://127.0.0.1:9/simple\n"
            "ERROR: No matching distribution found for packaging"
        )

        def refused(target, timeout=5.0):
            raise ConnectionRefusedError("refused")

        def reachable(target, timeout=5.0):
            class Connection:
                def close(self):
                    pass

            return Connection()

        self.assertEqual(
            launcher.classify_install_failure(result(1, index_output), connect=refused),
            "network",
        )
        self.assertEqual(
            launcher.classify_install_failure(result(1, index_output), connect=reachable),
            "dependency",
        )
        self.assertIsNone(launcher.index_reachable("No index mentioned"))


# ---------------------------------------------------------------------------
# Environment preparation with a fake creator
# ---------------------------------------------------------------------------


class PrepareEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="planforge prepare ")
        self.root = Path(self.temp.name) / "Plan Forge Tëst"
        self.root.mkdir()
        self.venv_root = self.root / ".venv"
        self.platform = linux_platform()
        (self.root / "requirements.txt").write_text("# no dependencies\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _probe(self, executable, args=(), **kwargs):
        return info(
            str(executable),
            (3, 11, 2),
            prefix=str(self.venv_root),
            base_prefix="/usr",
        )

    def _runner(self) -> FakeRunner:
        venv_root = self.venv_root

        def handler(args, kwargs):
            if args[1:3] == ["-m", "venv"]:
                if len(args) > 4 and args[4] == "--without-pip":
                    return result(1, "ensurepip unavailable")
                target = Path(args[3])
                (target / "bin").mkdir(parents=True, exist_ok=True)
                (target / "pyvenv.cfg").write_text("home = /usr/bin\n")
                (target / "bin" / "python").write_text("")
                return result()
            return result(0)

        return FakeRunner(handler)

    def test_first_prepare_creates_environment_and_second_reuses_it(self) -> None:
        runner = self._runner()
        messages: list[str] = []
        prepared = launcher.prepare_environment(
            self.platform,
            self.root,
            gui=False,
            which=lambda name: None,
            probe=self._probe,
            run=runner,
            on_progress=messages.append,
        )
        self.assertTrue(prepared.created_venv)
        self.assertEqual(prepared.dependencies.status, launcher.DEP_NONE)
        self.assertTrue((self.venv_root / "pyvenv.cfg").exists())
        self.assertFalse((self.root / ".planforge-setup.lock").exists())
        self.assertTrue(any("Creating" in message for message in messages))
        venv_calls = [call for call in runner.calls if call[1:3] == ["-m", "venv"]]
        self.assertEqual(len(venv_calls), 1)

        runner.calls.clear()
        prepared_again = launcher.prepare_environment(
            self.platform,
            self.root,
            gui=False,
            which=lambda name: None,
            probe=self._probe,
            run=runner,
        )
        self.assertFalse(prepared_again.created_venv)
        self.assertEqual(runner.calls, [])

    def test_interrupted_environment_is_repaired(self) -> None:
        (self.venv_root / "bin").mkdir(parents=True)
        (self.venv_root / "bin" / "python").write_text("broken")
        prepared = launcher.prepare_environment(
            self.platform,
            self.root,
            gui=False,
            which=lambda name: None,
            probe=self._probe,
            run=self._runner(),
        )
        self.assertTrue(prepared.created_venv)
        self.assertTrue((self.venv_root / "pyvenv.cfg").exists())

    def test_unrelated_folder_is_never_deleted(self) -> None:
        (self.venv_root).mkdir()
        keep = self.venv_root / "notes.txt"
        keep.write_text("important user file", encoding="utf-8")
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.prepare_environment(
                self.platform,
                self.root,
                gui=False,
                which=lambda name: None,
                probe=self._probe,
                run=self._runner(),
            )
        self.assertEqual(caught.exception.code, launcher.ExitCode.VENV_ERROR)
        self.assertTrue(keep.exists())

    def test_recreate_environment_removes_only_the_venv(self) -> None:
        runner = self._runner()
        launcher.prepare_environment(
            self.platform,
            self.root,
            gui=False,
            which=lambda name: None,
            probe=self._probe,
            run=runner,
        )
        marker = self.venv_root / "old-marker.txt"
        marker.write_text("old", encoding="utf-8")
        project = self.root / "Existing Project.pfp"
        project.write_bytes(b"project data")
        launcher.recreate_environment(
            launcher.venv_paths(self.root, "linux"), probe=self._probe
        )
        self.assertFalse(self.venv_root.exists())
        self.assertTrue(project.exists())
        prepared = launcher.prepare_environment(
            self.platform,
            self.root,
            gui=False,
            which=lambda name: None,
            probe=self._probe,
            run=runner,
        )
        self.assertTrue(prepared.created_venv)
        self.assertFalse(marker.exists())


# ---------------------------------------------------------------------------
# Read-only readiness report
# ---------------------------------------------------------------------------


class EnvironmentReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "Plan Forge Report"
        self.root.mkdir()
        (self.root / "requirements.txt").write_text("# none\n", encoding="utf-8")
        self.venv_root = self.root / ".venv"
        self.platform = linux_platform()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_venv(self) -> launcher.PythonInfo:
        (self.venv_root / "bin").mkdir(parents=True)
        (self.venv_root / "pyvenv.cfg").write_text("home = /usr/bin\n")
        python = self.venv_root / "bin" / "python"
        python.write_text("")
        return info(
            str(python),
            (3, 11, 2),
            prefix=str(self.venv_root),
            base_prefix="/usr",
        )

    def test_ready_report(self) -> None:
        python = self._make_venv()
        report = launcher.inspect_environment(
            self.platform,
            self.root,
            gui=True,
            probe=lambda *a, **k: python,
            which=lambda name: None,
            tk_status=lambda executable: (True, "", "8.6"),
        )
        self.assertTrue(report.ready)
        self.assertEqual(report.exit_code, 0)
        text = launcher.format_environment_report(report)
        self.assertIn("Ready to launch: yes", text)
        self.assertIn("Tkinter         : available", text)

    def test_missing_tkinter_is_a_problem(self) -> None:
        python = self._make_venv()
        report = launcher.inspect_environment(
            self.platform,
            self.root,
            gui=True,
            probe=lambda *a, **k: python,
            which=lambda name: None,
            tk_status=lambda executable: (False, "No module named tkinter", ""),
        )
        self.assertFalse(report.ready)
        self.assertEqual(report.exit_code, launcher.ExitCode.SYSTEM_LIBRARY)
        self.assertIn("Ready to launch: no", launcher.format_environment_report(report))

    def test_missing_python_is_reported_without_writing(self) -> None:
        report = launcher.inspect_environment(
            self.platform,
            self.root,
            gui=False,
            probe=lambda *a, **k: None,
            which=lambda name: None,
        )
        self.assertFalse(report.ready)
        self.assertEqual(report.exit_code, launcher.ExitCode.MISSING_PYTHON)
        self.assertFalse(self.venv_root.exists())

    def test_old_python_is_reported(self) -> None:
        report = launcher.inspect_environment(
            self.platform,
            self.root,
            gui=False,
            probe=lambda *a, **k: info("/usr/bin/python3", (3, 8, 10)),
            which=lambda name: None,
        )
        self.assertEqual(report.exit_code, launcher.ExitCode.UNSUPPORTED_PYTHON)

    def test_unrelated_venv_folder_blocks_readiness(self) -> None:
        self.venv_root.mkdir()
        (self.venv_root / "user-notes.txt").write_text("keep", encoding="utf-8")
        report = launcher.inspect_environment(
            self.platform,
            self.root,
            gui=False,
            probe=lambda *a, **k: None,
            which=lambda name: None,
        )
        self.assertEqual(report.exit_code, launcher.ExitCode.VENV_ERROR)
        self.assertTrue((self.venv_root / "user-notes.txt").exists())


# ---------------------------------------------------------------------------
# Real launches of a fake application
# ---------------------------------------------------------------------------

FAKE_APP_SOURCE = '''\
"""A stand-in PlanForge package used by the launcher tests."""
import json
import os
import sys
from pathlib import Path

counter = os.environ.get("PLANFORGE_FAKE_COUNT")
if counter:
    with open(counter, "a", encoding="utf-8") as handle:
        handle.write("launch\\n")

record = os.environ.get("PLANFORGE_FAKE_RECORD")
if record:
    payload = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "prefix": sys.prefix,
        "executable": sys.executable,
    }
    Path(record).write_text(json.dumps(payload), encoding="utf-8")

if os.environ.get("PLANFORGE_FAKE_MODE") == "fail":
    print("fake application failure", file=sys.stderr)
    raise SystemExit(int(os.environ.get("PLANFORGE_FAKE_CODE", "3")))

print("fake application ok")
'''


def build_fake_root(base: Path, name: str = "Plan Forge Tëst") -> Path:
    root = base / name
    root.mkdir()
    shutil.copy2(REPO_ROOT / "launcher.py", root / "launcher.py")
    shutil.copy2(REPO_ROOT / "run.sh", root / "run.sh")
    (root / "requirements.txt").write_text("# no third-party dependencies\n", encoding="utf-8")
    package = root / "planforge"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "0.0-test"\n', encoding="utf-8")
    (package / "__main__.py").write_text(FAKE_APP_SOURCE, encoding="utf-8")
    (root / "Existing Project.pfp").write_bytes(b"existing project bytes")
    (root / "notes.txt").write_text("user notes\n", encoding="utf-8")
    (root / "nested folder").mkdir()
    (root / "nested folder" / "résumé.txt").write_text("keep\n", encoding="utf-8")
    return root


class FakeAppTestCase(unittest.TestCase):
    root: Path

    @classmethod
    def build_root(cls, prefix: str) -> Path:
        cls.temp = tempfile.TemporaryDirectory(prefix=prefix)
        cls.base = Path(cls.temp.name)
        cls.root = build_fake_root(cls.base)
        return cls.root

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def invoke(self, *args, cwd=None, env=None):
        environment = os.environ.copy()
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, str(self.root / "launcher.py"), *args],
            cwd=str(cwd if cwd is not None else self.base),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )

    def ensure_environment(self) -> None:
        if not (self.root / ".venv" / "pyvenv.cfg").exists():
            completed = self.invoke("--import-file", "bootstrap.xml")
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


class FirstLaunchTests(FakeAppTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.build_root("planforge first launch ")
        cls.project_digest = cls.digest(cls.root / "Existing Project.pfp")
        cls.notes_digest = cls.digest(cls.root / "notes.txt")
        cls.nested_digest = cls.digest(cls.root / "nested folder" / "résumé.txt")

    def test_01_first_launch_creates_venv_and_runs_application(self) -> None:
        shutil.rmtree(self.root / ".venv", ignore_errors=True)
        record = self.base / "record.json"
        completed = self.invoke(
            "--import-file",
            "input project.xml",
            env={"PLANFORGE_FAKE_RECORD": str(record)},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Creating the PlanForge environment", completed.stdout)
        self.assertIn("fake application ok", completed.stdout)
        self.assertTrue((self.root / ".venv" / "pyvenv.cfg").exists())
        self.assertTrue((self.root / "logs" / "launcher.log").exists())

        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["argv"][0], "--import-file")
        self.assertTrue(
            same_path(payload["argv"][1], self.base / "input project.xml")
        )
        self.assertTrue(same_path(payload["cwd"], self.root))
        self.assertTrue(same_path(payload["prefix"], self.root / ".venv"))
        self.assertTrue(
            same_path(Path(payload["executable"]).parent.parent, self.root / ".venv")
        )

    def test_02_second_launch_reuses_the_environment(self) -> None:
        self.ensure_environment()
        config = self.root / ".venv" / "pyvenv.cfg"
        before = config.stat().st_mtime_ns
        completed = self.invoke("--import-file", "input.xml")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("Creating the PlanForge environment", completed.stdout)
        self.assertEqual(config.stat().st_mtime_ns, before)

    def test_03_check_mode_reports_ready(self) -> None:
        self.ensure_environment()
        completed = self.invoke("--check", "--import-file", "anything.xml")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Ready to launch: yes", completed.stdout)
        self.assertIn("Virtual env     : ready", completed.stdout)

    def test_04_launch_from_another_directory_with_spaces(self) -> None:
        self.ensure_environment()
        elsewhere = self.base / "different working dir"
        elsewhere.mkdir(exist_ok=True)
        record = self.base / "record cwd.json"
        completed = self.invoke(
            "--import-file",
            "nested folder/input file.xml",
            cwd=elsewhere,
            env={"PLANFORGE_FAKE_RECORD": str(record)},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertTrue(
            same_path(payload["argv"][1], elsewhere / "nested folder" / "input file.xml")
        )
        self.assertTrue(same_path(payload["cwd"], self.root))

    def test_05_user_files_are_untouched(self) -> None:
        self.ensure_environment()
        self.assertEqual(self.project_digest, self.digest(self.root / "Existing Project.pfp"))
        self.assertEqual(self.notes_digest, self.digest(self.root / "notes.txt"))
        self.assertEqual(
            self.nested_digest, self.digest(self.root / "nested folder" / "résumé.txt")
        )
        self.assertFalse((self.root / ".planforge-setup.lock").exists())

    @unittest.skipUnless(POSIX, "POSIX shell required")
    def test_07_run_sh_launches_from_another_directory(self) -> None:
        self.ensure_environment()
        elsewhere = self.base / "run sh cwd"
        elsewhere.mkdir(exist_ok=True)
        record = self.base / "record run sh.json"
        environment = os.environ.copy()
        environment["PLANFORGE_FAKE_RECORD"] = str(record)
        completed = subprocess.run(
            ["/bin/sh", str(self.root / "run.sh"), "--import-file", "shell input.xml"],
            cwd=str(elsewhere),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertTrue(same_path(payload["argv"][1], elsewhere / "shell input.xml"))
        self.assertTrue(same_path(payload["cwd"], self.root))

    def test_06_recreate_venv_rebuilds_only_the_environment(self) -> None:
        self.ensure_environment()
        marker = self.root / ".venv" / "old-environment-marker"
        marker.write_text("old", encoding="utf-8")
        record = self.base / "record recreate.json"
        completed = self.invoke(
            "--recreate-venv",
            "--import-file",
            "input.xml",
            env={"PLANFORGE_FAKE_RECORD": str(record)},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue((self.root / ".venv" / "pyvenv.cfg").exists())
        self.assertFalse(marker.exists())
        self.assertTrue(record.exists())
        self.assertEqual(self.project_digest, self.digest(self.root / "Existing Project.pfp"))


class ApplicationFailureTests(FakeAppTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.build_root("planforge app failure ")
        completed = subprocess.run(
            [sys.executable, str(cls.root / "launcher.py"), "--import-file", "setup.xml"],
            cwd=str(cls.base),
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_application_crash_propagates_code_and_logs_once(self) -> None:
        counter = self.base / "launches.txt"
        completed = self.invoke(
            "--import-file",
            "input.xml",
            env={
                "PLANFORGE_FAKE_MODE": "fail",
                "PLANFORGE_FAKE_CODE": "7",
                "PLANFORGE_FAKE_COUNT": str(counter),
            },
        )
        self.assertEqual(completed.returncode, 7)
        self.assertIn("exit code 7", completed.stderr)
        self.assertIn("not restarted automatically", completed.stderr)
        counter_lines = counter.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(counter_lines), 1, "the launcher must not restart a crashed app")
        application_log = self.root / "logs" / "application.log"
        self.assertTrue(application_log.exists())
        self.assertIn("fake application failure", application_log.read_text(encoding="utf-8"))


class DependencyFailureTests(FakeAppTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.build_root("planforge dependency failure ")
        (cls.root / "requirements.txt").write_text(
            "this-package-does-not-exist-planforge==9.9.9\n", encoding="utf-8"
        )

    def test_first_setup_without_network_fails_cleanly(self) -> None:
        record = self.base / "should-not-exist.json"
        completed = self.invoke(
            "--import-file",
            "input.xml",
            env={
                "PIP_NO_INDEX": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PLANFORGE_FAKE_RECORD": str(record),
            },
        )
        self.assertEqual(
            completed.returncode,
            launcher.ExitCode.DEPENDENCY_ERROR,
            completed.stdout + completed.stderr,
        )
        combined = completed.stdout + completed.stderr
        self.assertIn("dependencies could not be installed", combined)
        self.assertNotIn("Starting PlanForge", combined)
        self.assertFalse(record.exists(), "the application must not start after a failed install")
        self.assertTrue((self.root / ".venv" / "pyvenv.cfg").exists())


# ---------------------------------------------------------------------------
# Wrapper scripts, logging helpers and security helpers
# ---------------------------------------------------------------------------


class WrapperScriptTests(unittest.TestCase):
    def test_run_sh_is_executable_and_delegates_only(self) -> None:
        script = REPO_ROOT / "run.sh"
        if POSIX:
            self.assertTrue(os.access(script, os.X_OK))
        text = script.read_text(encoding="utf-8")
        self.assertIn("launcher.py", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("-m venv", text)
        self.assertNotIn(".venv", text)
        self.assertIn("run.bat", text)

    @unittest.skipUnless(POSIX, "POSIX shell required")
    def test_run_sh_rejects_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            shim = Path(temp) / "uname"
            shim.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
            shim.chmod(0o755)
            completed = subprocess.run(
                ["/bin/sh", str(REPO_ROOT / "run.sh")],
                env={"PATH": temp},
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("run.bat", completed.stderr)

    @unittest.skipUnless(POSIX, "POSIX shell required")
    def test_run_sh_without_python_gives_install_help(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            shim = Path(temp) / "uname"
            shim.write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
            shim.chmod(0o755)
            completed = subprocess.run(
                ["/bin/sh", str(REPO_ROOT / "run.sh")],
                env={"PATH": temp},
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 127)
        self.assertIn("Python", completed.stderr)
        self.assertIn("apt", completed.stderr)

    @unittest.skipUnless(POSIX, "POSIX shell required")
    def test_run_sh_and_command_have_valid_shell_syntax(self) -> None:
        for name in ("run.sh", "run.command"):
            completed = subprocess.run(
                ["/bin/sh", "-n", str(REPO_ROOT / name)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_run_bat_is_crlf_and_delegates_only(self) -> None:
        data = (REPO_ROOT / "run.bat").read_bytes()
        self.assertIn(b"\r\n", data)
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "run.bat must use CRLF")
        text = data.decode("ascii")
        self.assertIn("launcher.py", text)
        self.assertIn("py -3", text)
        self.assertIn("start", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("sudo", text)

    def test_macos_command_wrapper_delegates(self) -> None:
        script = REPO_ROOT / "run.command"
        if POSIX:
            self.assertTrue(os.access(script, os.X_OK))
        text = script.read_text(encoding="utf-8")
        self.assertIn("run.sh", text)
        self.assertIn("exec", text)


class HelperTests(unittest.TestCase):
    def test_sanitize_redacts_credentials(self) -> None:
        cleaned = launcher.sanitize(
            "https://user:secret@example.com/simple?token=abc123&x=1"
        )
        self.assertNotIn("secret", cleaned)
        self.assertNotIn("abc123", cleaned)
        self.assertIn("***", cleaned)

    def test_tail_text_limits_output(self) -> None:
        text = "\n".join(f"line {number}" for number in range(1, 51))
        tail = launcher.tail_text(text, lines=3, chars=100)
        self.assertIn("line 50", tail)
        self.assertNotIn("line 1\n", tail)

    def test_child_environment_is_clean(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/bad",
                "PYTHONHOME": "/bad",
                "__PYVENV_LAUNCHER__": "/bad",
                "VIRTUAL_ENV": "/bad",
            },
            clear=False,
        ):
            env = launcher.child_environment()
        for name in ("PYTHONPATH", "PYTHONHOME", "__PYVENV_LAUNCHER__", "VIRTUAL_ENV"):
            self.assertNotIn(name, env)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_help_is_available(self) -> None:
        options = launcher.parse_options(["--help"])
        self.assertTrue(options.help)
        self.assertIn("--check", launcher.HELP_TEXT)
        self.assertIn("run.bat", launcher.HELP_TEXT)


if __name__ == "__main__":
    unittest.main()
