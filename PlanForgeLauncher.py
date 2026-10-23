#!/usr/bin/env python3
"""PlanForgeLauncher - PlanForge universal launcher.

This file is the single, shared startup path for every supported platform.
The small platform wrappers (``PlanForgeLauncher.bat``,
``PlanForgeLauncher.sh`` and ``PlanForgeLauncher.command``) only
locate a Python interpreter and call this script; all environment management,
dependency installation, logging and error reporting lives here.

The launcher deliberately uses only the Python standard library so that it can
bootstrap PlanForge before any dependency has been installed.  PlanForge
itself needs Python 3.10+ and Tkinter (a system component on most platforms);
this launcher only needs Python 3.7+ so that it can explain what to install
when the application's requirements are not met.

Nothing in this module imports, patches or rewrites the PlanForge application.
It prepares ``.venv`` next to this file and then runs ``python -m planforge``
with the installation directory as the working directory.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

APP_NAME = "PlanForge"
PACKAGE_NAME = "planforge"
MINIMUM_PYTHON = (3, 10)
MINIMUM_LAUNCHER_PYTHON = (3, 7)
APP_ROOT = Path(__file__).resolve().parent
REQUIREMENTS_NAME = "requirements.txt"
VENV_NAME = ".venv"
LOCK_NAME = ".planforge-setup.lock"
LOG_DIR_NAME = "logs"

DEFAULT_COMMAND_TIMEOUT = 120
VENV_CREATE_TIMEOUT = 300
PIP_TIMEOUT = 900
LOCK_WAIT_SECONDS = 600.0

LOGGER = logging.getLogger("planforge.launcher")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False

_LOG_DIR: Path | None = None
_LOG_DIR_ROOT: Path | None = None
_LOG_PATH: Path | None = None


class ExitCode:
    """Exit statuses used by the launcher (application statuses pass through)."""

    OK = 0
    ERROR = 1
    USAGE = 2
    MISSING_PYTHON = 10
    UNSUPPORTED_PYTHON = 11
    VENV_ERROR = 12
    DEPENDENCY_ERROR = 13
    NETWORK_ERROR = 14
    SYSTEM_LIBRARY = 15
    STARTUP_ERROR = 16
    BUSY = 17
    UNSUPPORTED_PLATFORM = 18
    INTERRUPTED = 130


class LauncherError(Exception):
    """A problem the user can act on, with guidance for the error window."""

    def __init__(
        self,
        code: int,
        summary: str,
        *,
        details: str = "",
        hints: Sequence[str] = (),
    ) -> None:
        super().__init__(summary)
        self.code = int(code)
        self.summary = summary
        self.details = details or ""
        self.hints = list(hints)


class UsageError(Exception):
    """Invalid launcher command line."""


# ---------------------------------------------------------------------------
# Small shared data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        parts = [part for part in (self.stdout, self.stderr, self.error) if part]
        return "\n".join(part.strip() for part in parts if part.strip())


@dataclass(frozen=True)
class Candidate:
    label: str
    executable: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformInfo:
    key: str  # "windows", "linux", "macos" or "unsupported"
    system: str
    machine: str
    architecture: str
    display_name: str
    distro_id: str | None = None
    distro_name: str | None = None
    package_manager: str | None = None

    @property
    def supported(self) -> bool:
        return self.key in ("windows", "linux", "macos")

    @property
    def is_windows(self) -> bool:
        return self.key == "windows"

    @property
    def is_linux(self) -> bool:
        return self.key == "linux"

    @property
    def is_macos(self) -> bool:
        return self.key == "macos"


@dataclass(frozen=True)
class PythonInfo:
    executable: str
    version: tuple[int, int, int]
    implementation: str
    prefix: str
    base_prefix: str
    tkinter: bool
    tk_version: str
    tkinter_error: str
    has_venv: bool
    has_ensurepip: bool
    has_pip: bool

    @property
    def version_text(self) -> str:
        return ".".join(str(part) for part in self.version)

    @property
    def supported(self) -> bool:
        return self.version >= MINIMUM_PYTHON


@dataclass(frozen=True)
class VenvPaths:
    root: Path
    bin_dir: Path
    python: Path
    pythonw: Path | None


@dataclass(frozen=True)
class VenvState:
    status: str  # "missing", "invalid" or "ready"
    reason: str = ""
    info: PythonInfo | None = None


@dataclass(frozen=True)
class DependencyReport:
    status: str
    detail: str = ""
    output: str = ""


@dataclass(frozen=True)
class PreparedEnvironment:
    platform: PlatformInfo
    root: Path
    paths: VenvPaths
    venv: VenvState
    python: PythonInfo
    dependencies: DependencyReport
    created_venv: bool = False


@dataclass(frozen=True)
class Options:
    check: bool = False
    setup: bool = False
    gui: bool = False
    hide_console: bool = False
    recreate_venv: bool = False
    verbose: bool = False
    no_dialogs: bool = False
    help: bool = False
    app_args: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Output, logging and sanitising
# ---------------------------------------------------------------------------


def say(message: str = "", *, error: bool = False) -> None:
    """Print when a console exists (pythonw.exe has no stdout/stderr)."""
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream, flush=True)
    except (OSError, UnicodeError, ValueError):
        # A missing or closed console must never crash the launcher.
        pass


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError, ValueError):
            pass


def sanitize(text: str) -> str:
    """Redact credentials that could appear in package-index output."""
    if not text:
        return ""
    cleaned = re.sub(r"(?i)\b(https?://)([^/\s:@]+):([^/\s@]+)@", r"\1***:***@", str(text))
    cleaned = re.sub(
        r"(?i)([?&](?:token|access_token|password|passwd|secret|api[_-]?key|key)=)[^&\s]+",
        r"\1***",
        cleaned,
    )
    return cleaned


def tail_text(text: str, *, lines: int = 25, chars: int = 4000) -> str:
    if not text:
        return ""
    cleaned = sanitize(text).strip()
    split = cleaned.splitlines()
    if len(split) > lines:
        split = split[-lines:]
    joined = "\n".join(split)
    if len(joined) > chars:
        joined = "..." + joined[-chars:]
    return joined


def resolve_log_dir(root: Path) -> Path:
    """Return a writable log directory next to the app, or a temp fallback."""
    global _LOG_DIR, _LOG_DIR_ROOT
    root = Path(root).resolve()
    if _LOG_DIR is not None and _LOG_DIR_ROOT == root:
        return _LOG_DIR
    for candidate in (root / LOG_DIR_NAME, Path(tempfile.gettempdir()) / "PlanForge-logs"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".planforge-write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            _LOG_DIR = candidate
            _LOG_DIR_ROOT = root
            return candidate
        except OSError:
            continue
    _LOG_DIR = Path(tempfile.gettempdir())
    _LOG_DIR_ROOT = root
    return _LOG_DIR


def setup_logging(root: Path = APP_ROOT, verbose: bool = False) -> Path:
    """Configure file logging and return the launcher log path."""
    global _LOG_PATH
    log_dir = resolve_log_dir(root)
    log_path = log_dir / "launcher.log"
    _LOG_PATH = log_path

    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    LOGGER.setLevel(logging.DEBUG)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
        )
        LOGGER.addHandler(file_handler)
    except OSError:
        LOGGER.addHandler(logging.NullHandler())

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.DEBUG if verbose else logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        LOGGER.addHandler(console)

    return log_path


def current_log_path() -> Path | None:
    return _LOG_PATH


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

_REMOVE_FROM_CHILD_ENV = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONEXECUTABLE",
    "__PYVENV_LAUNCHER__",
    "VIRTUAL_ENV",
)


def child_environment() -> dict[str, str]:
    """A clean environment for Python probes, pip and the application."""
    env = os.environ.copy()
    for name in _REMOVE_FROM_CHILD_ENV:
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _windows_no_window_flag() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def run_capture(
    args: Sequence[object],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
    stdin: int | None = subprocess.DEVNULL,
) -> CommandResult:
    """Run a command without a shell and capture UTF-8 output."""
    command = [str(arg) for arg in args]
    kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd is not None else None,
        "env": env if env is not None else child_environment(),
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "stdin": stdin,
    }
    flag = _windows_no_window_flag()
    if flag:
        kwargs["creationflags"] = flag
    try:
        completed = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            None,
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr),
            error=f"The command timed out after {timeout} seconds.",
            timed_out=True,
        )
    except (OSError, ValueError) as exc:
        return CommandResult(None, error=str(exc))
    return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_ARCHITECTURES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",
    "x86": "x86",
    "arm64": "arm64",
    "aarch64": "arm64",
    "armv7l": "armv7",
    "armv6l": "armv6",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
}

# Ordered so that specific distributions win over broad families.
_PACKAGE_MANAGER_IDS: tuple[tuple[str, frozenset[str]], ...] = (
    ("pacman", frozenset({
        "arch", "archarm", "archlinux", "manjaro", "endeavouros", "garuda",
        "cachyos", "artix", "arcolinux", "rebornos",
    })),
    ("apt", frozenset({
        "debian", "ubuntu", "linuxmint", "mint", "pop", "elementary", "zorin",
        "kali", "raspbian", "devuan", "neon", "mx", "deepin", "parrot",
    })),
    ("dnf", frozenset({
        "fedora", "rhel", "centos", "rocky", "almalinux", "nobara", "bazzite",
        "ol", "oraclelinux",
    })),
    ("zypper", frozenset({
        "opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles", "suse",
    })),
    ("apk", frozenset({"alpine", "postmarketos"})),
    ("xbps", frozenset({"void"})),
    ("eopkg", frozenset({"solus"})),
)


def normalise_architecture(machine: str | None) -> str:
    value = (machine or "").strip().lower()
    return _ARCHITECTURES.get(value, value or "unknown")


def _read_os_release() -> dict[str, str]:
    """Read /etc/os-release in a version-tolerant way."""
    try:
        release = platform.freedesktop_os_release()  # Python 3.10+
    except (AttributeError, OSError):
        release = None
    if release:
        return {str(key).upper(): str(value) for key, value in release.items()}

    for candidate in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        data: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            data[key.strip().upper()] = value
        if data:
            return data
    return {}


def package_manager_for(distro_id: str | None, id_like: str | None = None) -> str | None:
    tokens = []
    if distro_id:
        tokens.append(distro_id.strip().lower())
    if id_like:
        tokens.extend(token.strip().lower() for token in id_like.replace(",", " ").split())
    tokens = [token for token in tokens if token]
    for token in tokens:
        for manager, known in _PACKAGE_MANAGER_IDS:
            if token in known:
                return manager
    # Handle rolling releases whose IDs gain suffixes (e.g. opensuse-tumbleweed).
    for token in tokens:
        if token.startswith("opensuse") or token.startswith("suse"):
            return "zypper"
        if token.startswith("arch"):
            return "pacman"
    return None


def detect_platform(
    *,
    system: str | None = None,
    machine: str | None = None,
    release: str | None = None,
    mac_version: str | None = None,
    os_release: dict[str, str] | None = None,
) -> PlatformInfo:
    """Detect the operating system without relying on user configuration."""
    system_name = system if system is not None else platform.system()
    machine_name = machine if machine is not None else platform.machine()
    architecture = normalise_architecture(machine_name)

    if system_name == "Windows":
        windows_release = release if release is not None else platform.release()
        display = "Windows"
        if windows_release and windows_release not in ("10", "11"):
            display = f"Windows {windows_release}"
        elif windows_release == "10":
            display = "Windows 10/11"
        return PlatformInfo(
            key="windows",
            system=system_name,
            machine=machine_name or "",
            architecture=architecture,
            display_name=display,
        )

    if system_name == "Darwin":
        version = mac_version
        if version is None:
            try:
                version = platform.mac_ver()[0]
            except Exception:
                version = ""
        display = f"macOS {version}".strip() if version else "macOS"
        return PlatformInfo(
            key="macos",
            system=system_name,
            machine=machine_name or "",
            architecture=architecture,
            display_name=display,
        )

    if system_name == "Linux":
        data = os_release if os_release is not None else _read_os_release()
        data = {str(key).upper(): str(value) for key, value in (data or {}).items()}
        distro_id = data.get("ID") or None
        pretty = data.get("PRETTY_NAME") or data.get("NAME") or distro_id
        manager = package_manager_for(distro_id, data.get("ID_LIKE"))
        display = f"Linux - {pretty}" if pretty else "Linux"
        return PlatformInfo(
            key="linux",
            system=system_name,
            machine=machine_name or "",
            architecture=architecture,
            display_name=display,
            distro_id=distro_id,
            distro_name=pretty,
            package_manager=manager,
        )

    return PlatformInfo(
        key="unsupported",
        system=system_name or "unknown",
        machine=machine_name or "",
        architecture=architecture,
        display_name=system_name or "unknown operating system",
    )


# ---------------------------------------------------------------------------
# User guidance
# ---------------------------------------------------------------------------


def _linux_install_hints(platform_info: PlatformInfo) -> list[str]:
    manager = platform_info.package_manager
    if manager == "pacman":
        return [
            "Arch Linux: sudo pacman -S python tk",
            "Also install the 'python' package before running PlanForge again.",
        ]
    if manager == "apt":
        return [
            "Debian/Ubuntu: sudo apt install python3 python3-venv python3-tk",
        ]
    if manager == "dnf":
        return ["Fedora/RHEL: sudo dnf install python3 python3-tkinter"]
    if manager == "zypper":
        return ["openSUSE: sudo zypper install python3 python3-tk"]
    if manager == "apk":
        return ["Alpine: sudo apk add python3 python3-tkinter"]
    if manager == "xbps":
        return ["Void Linux: sudo xbps-install -S python3 python3-tkinter"]
    if manager == "eopkg":
        return ["Solus: sudo eopkg install python3 python3-tkinter"]
    return [
        "Install Python 3.10+ with Tkinter using your distribution's package manager.",
        "The Tkinter package is usually called python3-tk or python3-tkinter.",
    ]


def python_install_hints(platform_info: PlatformInfo) -> list[str]:
    if platform_info.is_windows:
        return [
            "Install Python 3.10 or newer from https://www.python.org/downloads/windows/",
            "During installation tick 'Add python.exe to PATH'.",
            "If typing 'python' opens the Microsoft Store, install Python from python.org instead.",
            "Then run PlanForgeLauncher.bat again.",
        ]
    if platform_info.is_macos:
        return [
            "Install Python 3.10+ from https://www.python.org/downloads/macos/ (Tkinter is included).",
            "Or, with Homebrew: brew install python",
            "Then run PlanForgeLauncher.sh again.",
        ]
    return _linux_install_hints(platform_info) + ["Then run PlanForgeLauncher.sh again."]


def python_upgrade_hints(platform_info: PlatformInfo) -> list[str]:
    if platform_info.is_windows:
        return [
            "Install Python 3.10+ from https://www.python.org/downloads/windows/",
            "If several versions are installed, the launcher automatically uses the newest one.",
            "Then run PlanForgeLauncher.bat again.",
        ]
    if platform_info.is_macos:
        return [
            "Install Python 3.10+ from python.org or with Homebrew: brew install python",
            "Then run PlanForgeLauncher.sh again.",
        ]
    return [
        "Install Python 3.10 or newer with your package manager.",
        "Existing PlanForge projects and settings will not be changed.",
    ] + _linux_install_hints(platform_info)


def tkinter_hints(platform_info: PlatformInfo) -> list[str]:
    if platform_info.is_windows:
        return [
            "Re-run the Python installer from python.org, choose Modify, and enable 'tcl/tk and IDLE'.",
            "The Microsoft Store build of Python normally includes Tkinter.",
            "After repairing Python, run: python PlanForgeLauncher.py --recreate-venv",
        ]
    if platform_info.is_macos:
        return [
            "Install Python from python.org (its installer includes Tkinter).",
            "With Homebrew, install the matching Tk package, for example:",
            "  brew install python-tk@3.13   # match 'python3 --version'",
            "After changing Python installations, run: python3 PlanForgeLauncher.py --recreate-venv",
        ]
    manager = platform_info.package_manager
    mapping = {
        "pacman": "Arch Linux: sudo pacman -S tk",
        "apt": "Debian/Ubuntu: sudo apt install python3-tk",
        "dnf": "Fedora/RHEL: sudo dnf install python3-tkinter",
        "zypper": "openSUSE: sudo zypper install python3-tk",
        "apk": "Alpine: sudo apk add python3-tkinter",
        "xbps": "Void Linux: sudo xbps-install -S python3-tkinter",
        "eopkg": "Solus: sudo eopkg install python3-tkinter",
    }
    hints = []
    if manager in mapping:
        hints.append(mapping[manager])
    else:
        hints.append("Install the Tkinter package (often python3-tk or python3-tkinter).")
    hints.extend(
        [
            "Tkinter is a system package and cannot be installed with pip.",
            "PlanForge does not run sudo or change system packages for you.",
            "If you switched to a different Python installation, run: python3 PlanForgeLauncher.py --recreate-venv",
        ]
    )
    return hints


def venv_failure_hints(platform_info: PlatformInfo) -> list[str]:
    hints = _linux_install_hints(platform_info)
    hints.append(
        "Make sure the PlanForge folder is writable; the environment is created in .venv next to PlanForgeLauncher.py."
    )
    if platform_info.is_windows:
        hints.append(
            "Antivirus or Windows Controlled Folder Access can block .venv creation; allow PlanForge and retry."
        )
    return hints


def network_hints() -> list[str]:
    return [
        "Check this computer's internet connection.",
        "A firewall, proxy or VPN may be blocking PyPI (pypi.org / files.pythonhosted.org).",
        "If your network needs a proxy, set HTTPS_PROXY before launching.",
        "Once the dependencies are installed, PlanForge starts without an internet connection.",
        "See logs/launcher.log for the full package installer output.",
    ]


def dependency_hints(platform_info: PlatformInfo) -> list[str]:
    return [
        "Review requirements.txt: a package name, version or marker may be invalid.",
        "If the package index cannot be reached, check the internet connection or proxy settings.",
        f"A wheel may not be available for Python {platform_info.architecture} on {platform_info.display_name}.",
        "See logs/launcher.log for the full installer output.",
    ]


def startup_hints(output: str) -> list[str]:
    text = (output or "").lower()
    hints: list[str] = []
    if "no display name" in text or "couldn't connect to display" in text or "couldn't connect to display" in text:
        hints.append(
            "No graphical display is available. Start PlanForge from a desktop session, not a bare SSH session."
        )
    if "no module named 'tkinter'" in text or "no module named tkinter" in text:
        hints.append("Tkinter is missing from this Python installation. See the launcher documentation.")
    if "permission denied" in text or "read-only file system" in text:
        hints.append("Check file permissions for the PlanForge folder and for the project file you opened.")
    if "no such file or directory" in text and ".pfp" in text:
        hints.append("The project file could not be found; pass an absolute path or run from its folder.")
    hints.append("PlanForge was not restarted automatically to avoid a crash loop.")
    hints.append("See logs/application.log and logs/launcher.log for details.")
    return hints


# ---------------------------------------------------------------------------
# Paths, interpreters and probing
# ---------------------------------------------------------------------------

_PROBE_SOURCE = r"""
import json
import sys

info = {
    "version": list(sys.version_info[:3]),
    "implementation": getattr(getattr(sys, "implementation", None), "name", "unknown"),
    "executable": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": getattr(sys, "base_prefix", sys.prefix),
    "tkinter": False,
    "tk_version": "",
    "tkinter_error": "",
    "venv": False,
    "ensurepip": False,
    "pip": False,
}
try:
    import tkinter
    info["tkinter"] = True
    info["tk_version"] = str(getattr(tkinter, "TkVersion", ""))
except Exception as exc:
    info["tkinter_error"] = "%s: %s" % (type(exc).__name__, exc)
for name in ("venv", "ensurepip", "pip"):
    try:
        __import__(name)
        info[name] = True
    except Exception:
        pass
print(json.dumps(info))
"""

_TK_SOURCE = r"""
import json
try:
    import tkinter
    print(json.dumps({
        "ok": True,
        "tk_version": str(getattr(tkinter, "TkVersion", "")),
        "error": "",
    }))
except Exception as exc:
    print(json.dumps({
        "ok": False,
        "tk_version": "",
        "error": "%s: %s" % (type(exc).__name__, exc),
    }))
"""


def venv_paths(root: Path, platform_key: str) -> VenvPaths:
    """Return the interpreter layout for a project-local environment."""
    venv_root = root / VENV_NAME
    if platform_key == "windows":
        bin_dir = venv_root / "Scripts"
        return VenvPaths(
            root=venv_root,
            bin_dir=bin_dir,
            python=bin_dir / "python.exe",
            pythonw=bin_dir / "pythonw.exe",
        )
    bin_dir = venv_root / "bin"
    return VenvPaths(root=venv_root, bin_dir=bin_dir, python=bin_dir / "python", pythonw=None)


def lock_path(root: Path) -> Path:
    return root / LOCK_NAME


def python_candidate_commands(
    platform_info: PlatformInfo,
    *,
    which: Callable[[str], str | None] = shutil.which,
    include_current: bool = True,
) -> list[Candidate]:
    """List plausible interpreters, most promising first."""
    candidates: list[Candidate] = []
    if include_current and sys.executable:
        candidates.append(Candidate("current interpreter", sys.executable))
        base_executable = getattr(sys, "_base_executable", None)
        if base_executable and os.path.normcase(base_executable) != os.path.normcase(sys.executable):
            candidates.append(Candidate("base interpreter", base_executable))

    if platform_info.is_windows:
        py_launcher = which("py")
        if py_launcher:
            for version in ("3.13", "3.12", "3.11", "3.10", "3"):
                candidates.append(Candidate(f"py -{version}", py_launcher, (f"-{version}",)))
        for name in ("python", "python3"):
            found = which(name)
            if found:
                candidates.append(Candidate(name, found))
    else:
        for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"):
            found = which(name)
            if found:
                candidates.append(Candidate(name, found))

    unique: list[Candidate] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for candidate in candidates:
        key = (os.path.normcase(candidate.executable), candidate.args)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def probe_python(
    executable: str,
    args: Sequence[str] = (),
    *,
    timeout: int = 30,
    run: Callable[..., CommandResult] = run_capture,
) -> PythonInfo | None:
    """Ask an interpreter for its version, Tk and venv capabilities."""
    command = [executable, *args, "-I", "-c", _PROBE_SOURCE]
    result = run(command, timeout=timeout)
    if not result.ok:
        LOGGER.debug("Interpreter probe failed for %r: %s", command[0], tail_text(result.output, lines=5))
        return None
    payload: dict[str, object] | None = None
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            decoded = json.loads(line)
        except ValueError:
            continue
        if isinstance(decoded, dict):
            payload = decoded
            break
    if payload is None:
        return None

    raw_version = payload.get("version")
    if not isinstance(raw_version, list) or len(raw_version) < 2:
        return None
    try:
        version = tuple(int(part) for part in raw_version[:3])
    except (TypeError, ValueError):
        return None
    if len(version) == 2:
        version = (version[0], version[1], 0)

    def _text(key: str) -> str:
        value = payload.get(key, "")
        return value if isinstance(value, str) else str(value or "")

    return PythonInfo(
        executable=_text("executable") or executable,
        version=(version[0], version[1], version[2]),
        implementation=_text("implementation") or "unknown",
        prefix=_text("prefix"),
        base_prefix=_text("base_prefix"),
        tkinter=bool(payload.get("tkinter")),
        tk_version=_text("tk_version"),
        tkinter_error=_text("tkinter_error"),
        has_venv=bool(payload.get("venv")),
        has_ensurepip=bool(payload.get("ensurepip")),
        has_pip=bool(payload.get("pip")),
    )


def select_python(
    platform_info: PlatformInfo,
    *,
    gui: bool,
    which: Callable[[str], str | None] = shutil.which,
    probe: Callable[..., PythonInfo | None] = probe_python,
    include_current: bool = True,
    log: logging.Logger = LOGGER,
) -> PythonInfo:
    """Pick the best compatible interpreter, preferring one with Tk for the GUI."""
    candidates = python_candidate_commands(platform_info, which=which, include_current=include_current)
    if not candidates:
        raise LauncherError(
            ExitCode.MISSING_PYTHON,
            "No Python 3 interpreter was found.",
            hints=python_install_hints(platform_info),
        )

    discovered: list[PythonInfo] = []
    for candidate in candidates:
        info = probe(candidate.executable, candidate.args)
        if info is None:
            log.debug("Python candidate unusable: %s (%s)", candidate.label, candidate.executable)
            continue
        log.debug(
            "Python candidate: %s -> %s %s (Tk=%s)",
            candidate.label,
            info.executable,
            info.version_text,
            info.tkinter,
        )
        discovered.append(info)

    # Prefer distinct interpreter paths; py -3.12 and python may resolve alike.
    unique: dict[str, PythonInfo] = {}
    for info in discovered:
        key = os.path.normcase(os.path.abspath(info.executable))
        unique.setdefault(key, info)
    interpreters = list(unique.values())
    suitable = [info for info in interpreters if info.supported]

    if not suitable:
        if interpreters:
            newest = max(interpreters, key=lambda item: item.version)
            raise LauncherError(
                ExitCode.UNSUPPORTED_PYTHON,
                (
                    f"PlanForge needs Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer, "
                    f"but the newest Python found is {newest.version_text} ({newest.executable})."
                ),
                hints=python_upgrade_hints(platform_info),
            )
        raise LauncherError(
            ExitCode.MISSING_PYTHON,
            "No working Python 3 interpreter was found.",
            details="PlanForge found no interpreter that could report a Python version.",
            hints=python_install_hints(platform_info),
        )

    def rank(info: PythonInfo) -> tuple[int, tuple[int, int, int], str]:
        return (
            1 if (gui and info.tkinter) else 0,
            info.version,
            info.executable,
        )

    chosen = max(suitable, key=rank)
    if gui and not chosen.tkinter:
        log.warning("The selected Python %s does not include Tkinter.", chosen.version_text)
    log.info(
        "Selected Python %s at %s%s",
        chosen.version_text,
        chosen.executable,
        " (Tkinter available)" if chosen.tkinter else "",
    )
    return chosen


# ---------------------------------------------------------------------------
# Virtual environment management
# ---------------------------------------------------------------------------


def validate_venv(
    paths: VenvPaths,
    *,
    probe: Callable[..., PythonInfo | None] = probe_python,
) -> VenvState:
    """Check that the environment exists, belongs here and uses Python 3.10+."""
    root = paths.root
    if not root.exists():
        return VenvState("missing", "the environment has not been created yet")
    if not root.is_dir():
        return VenvState("invalid", f"{root} exists but is not a directory")
    config = root / "pyvenv.cfg"
    if not config.is_file():
        return VenvState("invalid", f"{root} does not contain a pyvenv.cfg file")
    if not paths.python.is_file():
        return VenvState("invalid", f"the interpreter {paths.python} is missing")
    info = probe(str(paths.python))
    if info is None:
        return VenvState("invalid", "the environment's interpreter could not be started")
    if not info.supported:
        return VenvState(
            "invalid",
            f"the environment uses Python {info.version_text}, older than "
            f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}",
        )
    expected = os.path.normcase(os.path.abspath(str(root)))
    actual = os.path.normcase(os.path.abspath(info.prefix or ""))
    if actual != expected:
        return VenvState("invalid", "the interpreter does not belong to this environment")
    base = os.path.normcase(os.path.abspath(info.base_prefix or ""))
    if base == expected:
        return VenvState("invalid", "the environment does not have a base Python installation")
    return VenvState("ready", "the environment is ready", info)


_VENV_ENTRY_NAMES = frozenset(
    {
        "pyvenv.cfg",
        "bin",
        "Scripts",
        "include",
        "Include",
        "lib",
        "Lib",
        "lib64",
        "share",
    }
)


def venv_can_be_replaced(paths: VenvPaths) -> tuple[bool, str]:
    """Only ever delete something that is empty or is a real (or partial) venv."""
    root = paths.root
    try:
        if not root.exists():
            return True, "does not exist"
        if not root.is_dir():
            return False, "is a file, not a directory"
        entries = list(root.iterdir())
        if not entries:
            return True, "is empty"
        if (root / "pyvenv.cfg").is_file():
            return True, "is a virtual environment"
        names = {entry.name for entry in entries}
        if names.issubset(_VENV_ENTRY_NAMES) and names & {
            "bin",
            "Scripts",
            "lib",
            "Lib",
            "include",
            "Include",
        }:
            # The venv was interrupted before pyvenv.cfg was written; these
            # directory names cannot be confused with ordinary user projects.
            return True, "is a partially created virtual environment"
        return False, (
            "exists but is not a virtual environment (there is no pyvenv.cfg). "
            "It was left untouched to avoid deleting your files"
        )
    except OSError as exc:
        return False, f"could not be inspected ({exc})"


def remove_venv(paths: VenvPaths, *, log: logging.Logger = LOGGER) -> None:
    can_replace, reason = venv_can_be_replaced(paths)
    if not can_replace:
        raise LauncherError(
            ExitCode.VENV_ERROR,
            f"The folder {paths.root} cannot be used or replaced.",
            details=reason,
            hints=[
                f"Move or delete {paths.root} yourself, then run PlanForge again.",
                "The launcher never deletes folders that do not look like a virtual environment.",
            ],
        )
    if not paths.root.exists():
        return
    log.info("Removing virtual environment at %s (%s)", paths.root, reason)
    last_exc: OSError | None = None
    for delay in (0.0, 0.05, 0.1, 0.2, 0.4):
        if delay:
            time.sleep(delay)
        try:
            if paths.root.exists():
                shutil.rmtree(str(paths.root))
            last_exc = None
            break
        except OSError as exc:
            last_exc = exc
    if last_exc is not None:
        raise LauncherError(
            ExitCode.VENV_ERROR,
            "The existing virtual environment could not be removed.",
            details=str(last_exc),
            hints=[
                "Close any other PlanForge windows or terminals using the environment.",
                f"Delete {paths.root} manually, then try again.",
            ],
        )


def create_venv(
    interpreter: PythonInfo,
    paths: VenvPaths,
    *,
    root: Path = APP_ROOT,
    run: Callable[..., CommandResult] = run_capture,
    log: logging.Logger = LOGGER,
    platform_info: PlatformInfo | None = None,
) -> bool:
    """Create the venv.  Returns True when pip could not be bootstrapped."""
    platform_info = platform_info or detect_platform()
    base_command = [interpreter.executable, "-m", "venv", str(paths.root)]
    log.info("Creating virtual environment: %s", " ".join(base_command))
    result = run(base_command, cwd=root, timeout=VENV_CREATE_TIMEOUT)
    if result.ok:
        return False

    output = result.output
    log.warning("venv creation failed (exit %s):\n%s", result.returncode, tail_text(output))
    lower = output.lower()
    if "ensurepip" in lower or "pip is not available" in lower:
        # Some Linux distributions ship Python without ensurepip until the venv
        # helper package is installed.  PlanForge has no third-party runtime
        # requirements today, so an environment without pip is still usable;
        # dependency installation will report the problem clearly if needed.
        fallback = base_command + ["--without-pip"]
        log.warning("Retrying environment creation without pip: %s", " ".join(fallback))
        retry = run(fallback, cwd=root, timeout=VENV_CREATE_TIMEOUT)
        if retry.ok:
            log.warning("Created the environment without pip; see the log for details.")
            return True
        result = retry
        output = retry.output

    if result.timed_out:
        summary = "Creating the virtual environment timed out."
    else:
        summary = "The PlanForge virtual environment could not be created."
    raise LauncherError(
        ExitCode.VENV_ERROR,
        summary,
        details=tail_text(output),
        hints=venv_failure_hints(platform_info),
    )


# ---------------------------------------------------------------------------
# Dependency manifest and installation
# ---------------------------------------------------------------------------

DEP_NONE = "none"
DEP_SATISFIED = "satisfied"
DEP_MISSING = "missing"
DEP_PIP_MISSING = "pip-missing"
DEP_INVALID = "invalid"
DEP_PENDING = "pending"
DEP_INSTALLED = "installed"


def read_requirement_lines(root: Path) -> list[str]:
    """Return meaningful lines from requirements.txt (comments excluded)."""
    manifest = root / REQUIREMENTS_NAME
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _dry_run_unsupported(output: str) -> bool:
    lower = output.lower()
    return "no such option: --dry-run" in lower or "unrecognized arguments" in lower


def _requirements_invalid(output: str) -> bool:
    lower = output.lower()
    markers = (
        "invalid requirement",
        "could not open requirements file",
        "no such file or directory: 'requirements.txt'",
        "expected end or semicolon",
    )
    return any(marker in lower for marker in markers)


def pip_available(
    paths: VenvPaths,
    root: Path,
    *,
    run: Callable[..., CommandResult] = run_capture,
) -> CommandResult:
    return run([str(paths.python), "-m", "pip", "--version"], cwd=root, timeout=60)


def check_dependencies(
    paths: VenvPaths,
    root: Path,
    *,
    run: Callable[..., CommandResult] = run_capture,
) -> DependencyReport:
    """Offline dependency verification.

    pip is asked to resolve requirements with ``--no-index`` and ``--dry-run``;
    this never contacts the network and succeeds only when everything declared
    in requirements.txt is already importable/installed in the environment.
    """
    lines = read_requirement_lines(root)
    if not lines:
        return DependencyReport(
            DEP_NONE,
            f"{REQUIREMENTS_NAME} declares no third-party packages",
        )

    pip_check = pip_available(paths, root, run=run)
    if not pip_check.ok:
        return DependencyReport(
            DEP_PIP_MISSING,
            "pip is not available in the PlanForge environment",
            tail_text(pip_check.output, lines=8),
        )

    base = [
        str(paths.python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--disable-pip-version-check",
        "--no-input",
    ]
    attempt = run([*base, "--dry-run", "-r", REQUIREMENTS_NAME], cwd=root, timeout=180)
    if not attempt.ok and _dry_run_unsupported(attempt.output):
        # Older pip without --dry-run: a real offline install is still safe
        # because --no-index cannot fetch anything from the network.
        attempt = run([*base, "-r", REQUIREMENTS_NAME], cwd=root, timeout=180)

    if attempt.ok:
        return DependencyReport(
            DEP_SATISFIED,
            "all requirements are installed",
        )
    if _requirements_invalid(attempt.output):
        return DependencyReport(
            DEP_INVALID,
            f"{REQUIREMENTS_NAME} contains an invalid requirement",
            tail_text(attempt.output, lines=12),
        )
    return DependencyReport(
        DEP_MISSING,
        "some declared packages are not installed yet",
        tail_text(attempt.output, lines=12),
    )


_INDEX_LINE = re.compile(r"(?i)looking in indexes:\s*(\S+)")


def _index_target(output: str) -> tuple[str, int] | None:
    """Extract the first HTTP(S) package index host from pip's output."""
    match = _INDEX_LINE.search(output or "")
    if not match:
        return None
    for url in re.split(r"[,\s]+", match.group(1)):
        try:
            from urllib.parse import urlsplit

            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                continue
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return parsed.hostname, int(port)
        except (ValueError, TypeError):
            continue
    return None


def index_reachable(
    output: str,
    *,
    connect: Callable[..., object] | None = None,
    timeout: float = 5.0,
) -> bool | None:
    """Check the index host only after an install failed.

    Returns None when pip did not name an HTTP index (for example when
    dependencies are installed offline), True when a TCP connection succeeds
    and False when the host cannot be reached.
    """
    target = _index_target(output)
    if target is None:
        return None
    connector = connect or socket.create_connection
    try:
        connection = connector(target, timeout=timeout)
    except OSError:
        return False
    except Exception:
        return None
    try:
        close = getattr(connection, "close", None)
        if callable(close):
            close()
    except Exception:
        pass
    return True


def classify_install_failure(
    result: CommandResult,
    *,
    connect: Callable[..., object] | None = None,
) -> str:
    """Distinguish network failures from bad package declarations."""
    if result.timed_out:
        return "network"
    lower = (result.output or "").lower()
    markers = (
        "temporary failure in name resolution",
        "name or service not known",
        "nodename nor servname",
        "connection refused",
        "connection reset",
        "connection aborted",
        "network is unreachable",
        "no route to host",
        "max retries exceeded",
        "failed to establish a new connection",
        "newconnectionerror",
        "proxyerror",
        "ssl",
        "certificate verify failed",
        "timed out",
        "read timed out",
        "could not fetch url",
        "unable to download",
        "blocked by",
        "offline",
    )
    if any(marker in lower for marker in markers):
        return "network"
    if index_reachable(result.output, connect=connect) is False:
        return "network"
    return "dependency"


def ensure_pip(
    paths: VenvPaths,
    root: Path,
    *,
    platform_info: PlatformInfo,
    run: Callable[..., CommandResult] = run_capture,
    log: logging.Logger = LOGGER,
) -> None:
    log.info("pip is missing or damaged; running ensurepip")
    result = run(
        [str(paths.python), "-m", "ensurepip", "--upgrade"],
        cwd=root,
        timeout=300,
    )
    if not result.ok:
        raise LauncherError(
            ExitCode.DEPENDENCY_ERROR,
            "pip could not be installed into the PlanForge environment.",
            details=tail_text(result.output),
            hints=venv_failure_hints(platform_info),
        )
    verify = pip_available(paths, root, run=run)
    if not verify.ok:
        raise LauncherError(
            ExitCode.DEPENDENCY_ERROR,
            "pip is still unavailable after repairing the environment.",
            details=tail_text(verify.output),
            hints=venv_failure_hints(platform_info),
        )


def ensure_dependencies(
    paths: VenvPaths,
    root: Path,
    *,
    platform_info: PlatformInfo,
    run: Callable[..., CommandResult] = run_capture,
    log: logging.Logger = LOGGER,
    on_progress: Callable[[str], None] | None = None,
) -> DependencyReport:
    """Install declared dependencies only when they are actually missing."""
    report = check_dependencies(paths, root, run=run)
    if report.status in (DEP_NONE, DEP_SATISFIED):
        return report
    if report.status == DEP_INVALID:
        raise LauncherError(
            ExitCode.DEPENDENCY_ERROR,
            f"{REQUIREMENTS_NAME} could not be read by pip.",
            details=report.output,
            hints=dependency_hints(platform_info),
        )
    if report.status == DEP_PIP_MISSING:
        ensure_pip(paths, root, platform_info=platform_info, run=run, log=log)
        report = check_dependencies(paths, root, run=run)
        if report.status in (DEP_NONE, DEP_SATISFIED):
            return report
        if report.status == DEP_PIP_MISSING:
            raise LauncherError(
                ExitCode.DEPENDENCY_ERROR,
                "pip is not available in the PlanForge environment.",
                details=report.output,
                hints=venv_failure_hints(platform_info),
            )
        if report.status == DEP_INVALID:
            raise LauncherError(
                ExitCode.DEPENDENCY_ERROR,
                f"{REQUIREMENTS_NAME} could not be read by pip.",
                details=report.output,
                hints=dependency_hints(platform_info),
            )

    if on_progress is not None:
        on_progress("Installing PlanForge dependencies (first time only)...")
    install = run(
        [
            str(paths.python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "-r",
            REQUIREMENTS_NAME,
        ],
        cwd=root,
        timeout=PIP_TIMEOUT,
    )
    if install.output:
        log.debug("pip install output:\n%s", sanitize(install.output))
    if not install.ok:
        kind = classify_install_failure(install)
        if kind == "network":
            raise LauncherError(
                ExitCode.NETWORK_ERROR,
                "PlanForge's dependencies could not be downloaded.",
                details=tail_text(install.output),
                hints=network_hints(),
            )
        raise LauncherError(
            ExitCode.DEPENDENCY_ERROR,
            "PlanForge's dependencies could not be installed.",
            details=tail_text(install.output),
            hints=dependency_hints(platform_info),
        )

    # Never assume success: pip's exit status alone is not proof.
    verify = check_dependencies(paths, root, run=run)
    if verify.status not in (DEP_NONE, DEP_SATISFIED):
        raise LauncherError(
            ExitCode.DEPENDENCY_ERROR,
            "The package installer reported success, but dependencies are still missing.",
            details=verify.output,
            hints=[
                "Run the launcher again; an interrupted installation can usually be resumed.",
                "See logs/launcher.log for the complete output.",
            ],
        )
    log.info("Dependencies installed successfully.")
    return DependencyReport(DEP_INSTALLED, "dependencies were installed", verify.output)


# ---------------------------------------------------------------------------
# Concurrency guard
# ---------------------------------------------------------------------------


def pid_is_alive(pid: int) -> bool:
    """Best-effort process check that is safe on Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                # ERROR_ACCESS_DENIED means the process exists but belongs to
                # another user; assume it is alive rather than stealing a lock.
                return kernel32.GetLastError() == 5
            try:
                code = ctypes.c_ulong()
                ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return bool(ok) and code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # If the check itself fails, assume the process is alive and rely
            # on the lock timeout instead of stealing an active lock.
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


class SetupLock:
    """A small cross-platform lock file protecting environment changes."""

    def __init__(
        self,
        path: Path,
        *,
        wait_seconds: float = LOCK_WAIT_SECONDS,
        poll_seconds: float = 0.25,
        alive_check: Callable[[int], bool] | None = None,
        log: logging.Logger = LOGGER,
    ) -> None:
        self.path = path
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self._alive_check = alive_check or pid_is_alive
        self.log = log
        self._owned = False
        self._fd: int | None = None

    def _read(self) -> dict[str, object]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _is_stale(self) -> bool:
        data = self._read()
        try:
            pid = int(data.get("pid", 0))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pid = 0
        if pid and not self._alive_check(pid):
            return True
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return False
        if not pid and age > 300:
            return True
        return False

    def __enter__(self) -> "SetupLock":
        deadline = time.monotonic() + self.wait_seconds
        announced = False
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._is_stale():
                    self.log.warning("Removing stale setup lock: %s", self.path)
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if not announced:
                    say("Another PlanForge launch is preparing the environment; waiting...")
                    self.log.info("Waiting for setup lock %s", self.path)
                    announced = True
                if time.monotonic() >= deadline:
                    raise LauncherError(
                        ExitCode.BUSY,
                        "Another PlanForge launcher is still preparing the environment.",
                        details=f"The setup lock {self.path} is held by another process.",
                        hints=[
                            "Wait for the other PlanForge launch to finish, then try again.",
                            f"If no other launch is running, delete {self.path} and retry.",
                        ],
                    )
                time.sleep(self.poll_seconds)
                continue
            except OSError as exc:
                raise LauncherError(
                    ExitCode.VENV_ERROR,
                    "The setup lock could not be created.",
                    details=str(exc),
                    hints=[
                        "Make sure the PlanForge folder is writable.",
                        "Close other programs that may be scanning the folder and try again.",
                    ],
                )
            self._fd = fd
            self._owned = True
            payload = json.dumps(
                {
                    "pid": os.getpid(),
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "application": APP_NAME,
                }
            )
            try:
                os.write(fd, payload.encode("utf-8"))
            except OSError:
                pass
            return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._owned:
            try:
                self.path.unlink()
            except OSError:
                pass
            self._owned = False
        return False


# ---------------------------------------------------------------------------
# Environment preparation and inspection
# ---------------------------------------------------------------------------


def _progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def prepare_environment(
    platform_info: PlatformInfo,
    root: Path = APP_ROOT,
    *,
    gui: bool,
    which: Callable[[str], str | None] = shutil.which,
    probe: Callable[..., PythonInfo | None] = probe_python,
    run: Callable[..., CommandResult] = run_capture,
    log: logging.Logger = LOGGER,
    on_progress: Callable[[str], None] | None = None,
) -> PreparedEnvironment:
    """Create or validate .venv and make sure declared dependencies exist."""
    paths = venv_paths(root, platform_info.key)
    state = validate_venv(paths, probe=probe)
    created = False

    if state.status != "ready":
        with SetupLock(lock_path(root), log=log):
            # Another launcher may have repaired the environment while we waited.
            state = validate_venv(paths, probe=probe)
            if state.status != "ready":
                can_replace, reason = venv_can_be_replaced(paths)
                if not can_replace:
                    raise LauncherError(
                        ExitCode.VENV_ERROR,
                        f"The folder {paths.root} cannot be used as PlanForge's environment.",
                        details=reason,
                        hints=[
                            f"Move or delete {paths.root} yourself, then run PlanForge again.",
                            "Your project files and settings are stored elsewhere and are not affected.",
                        ],
                    )
                if paths.root.exists():
                    _progress(on_progress, "Repairing the PlanForge environment...")
                    remove_venv(paths, log=log)
                interpreter = select_python(platform_info, gui=gui, which=which, probe=probe, log=log)
                _progress(on_progress, "Creating the PlanForge environment (first time only)...")
                create_venv(
                    interpreter,
                    paths,
                    root=root,
                    run=run,
                    log=log,
                    platform_info=platform_info,
                )
                state = validate_venv(paths, probe=probe)
                if state.status != "ready" or state.info is None:
                    raise LauncherError(
                        ExitCode.VENV_ERROR,
                        "The new PlanForge environment could not be validated.",
                        details=state.reason,
                        hints=venv_failure_hints(platform_info),
                    )
                created = True

            dependencies = check_dependencies(paths, root, run=run)
            if dependencies.status not in (DEP_NONE, DEP_SATISFIED):
                dependencies = ensure_dependencies(
                    paths,
                    root,
                    platform_info=platform_info,
                    run=run,
                    log=log,
                    on_progress=on_progress,
                )
    else:
        dependencies = check_dependencies(paths, root, run=run)
        if dependencies.status not in (DEP_NONE, DEP_SATISFIED):
            with SetupLock(lock_path(root), log=log):
                dependencies = check_dependencies(paths, root, run=run)
                if dependencies.status not in (DEP_NONE, DEP_SATISFIED):
                    dependencies = ensure_dependencies(
                        paths,
                        root,
                        platform_info=platform_info,
                        run=run,
                        log=log,
                        on_progress=on_progress,
                    )

    if state.info is None:
        raise LauncherError(
            ExitCode.VENV_ERROR,
            "The PlanForge environment is not usable.",
            details=state.reason,
            hints=venv_failure_hints(platform_info),
        )
    return PreparedEnvironment(
        platform=platform_info,
        root=root,
        paths=paths,
        venv=state,
        python=state.info,
        dependencies=dependencies,
        created_venv=created,
    )


def recreate_environment(
    paths: VenvPaths,
    *,
    probe: Callable[..., PythonInfo | None] = probe_python,
    log: logging.Logger = LOGGER,
) -> None:
    """Delete and rebuild the project-local environment (explicit user request)."""
    with SetupLock(lock_path(paths.root.parent), log=log):
        state = validate_venv(paths, probe=probe)
        if state.status == "ready":
            say("Removing the existing PlanForge environment...")
            log.info("Recreating environment on request.")
            remove_venv(paths, log=log)
            return
        if paths.root.exists():
            remove_venv(paths, log=log)


def tkinter_status(
    executable: str,
    *,
    run: Callable[..., CommandResult] = run_capture,
) -> tuple[bool, str, str]:
    """Return (available, error, Tk version) for an interpreter."""
    result = run([executable, "-I", "-c", _TK_SOURCE], timeout=30)
    if not result.ok:
        return False, tail_text(result.output, lines=8), ""
    payload: dict[str, object] | None = None
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            decoded = json.loads(line)
        except ValueError:
            continue
        if isinstance(decoded, dict):
            payload = decoded
            break
    if payload is None:
        return False, "Tkinter could not be checked (unexpected interpreter output).", ""
    if payload.get("ok"):
        return True, "", str(payload.get("tk_version") or "")
    return False, str(payload.get("error") or "Tkinter is unavailable"), ""


@dataclass
class EnvironmentReport:
    platform: PlatformInfo
    root: Path
    paths: VenvPaths
    gui: bool
    venv: VenvState
    python: PythonInfo | None = None
    python_source: str = "not found"
    dependencies: DependencyReport | None = None
    tkinter_ok: bool | None = None
    tkinter_error: str = ""
    tkinter_version: str = ""
    problems: list[LauncherError] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.problems

    @property
    def exit_code(self) -> int:
        if self.problems:
            return self.problems[0].code
        return ExitCode.OK


def inspect_environment(
    platform_info: PlatformInfo,
    root: Path = APP_ROOT,
    *,
    gui: bool,
    which: Callable[[str], str | None] = shutil.which,
    probe: Callable[..., PythonInfo | None] = probe_python,
    run: Callable[..., CommandResult] = run_capture,
    tk_status: Callable[..., tuple[bool, str, str]] = tkinter_status,
) -> EnvironmentReport:
    """Read-only readiness report used by ``--check``."""
    paths = venv_paths(root, platform_info.key)
    state = validate_venv(paths, probe=probe)
    report = EnvironmentReport(
        platform=platform_info,
        root=root,
        paths=paths,
        gui=gui,
        venv=state,
    )

    if state.status == "ready":
        report.python = state.info
        report.python_source = f"project environment ({paths.python})"
    else:
        if state.status == "invalid":
            can_replace, reason = venv_can_be_replaced(paths)
            if not can_replace:
                report.problems.append(
                    LauncherError(
                        ExitCode.VENV_ERROR,
                        f"The folder {paths.root} cannot be used as PlanForge's environment.",
                        details=reason,
                        hints=[f"Move or delete {paths.root} yourself, then run PlanForge again."],
                    )
                )
        try:
            report.python = select_python(
                platform_info,
                gui=gui,
                which=which,
                probe=probe,
                log=LOGGER,
            )
            report.python_source = "system Python (the environment is created on first launch)"
        except LauncherError as exc:
            report.problems.append(exc)

    manifest_lines = read_requirement_lines(root)
    if state.status == "ready":
        report.dependencies = check_dependencies(paths, root, run=run)
        if report.dependencies.status == DEP_INVALID:
            report.problems.append(
                LauncherError(
                    ExitCode.DEPENDENCY_ERROR,
                    f"{REQUIREMENTS_NAME} could not be read by pip.",
                    details=report.dependencies.output,
                    hints=dependency_hints(platform_info),
                )
            )
    elif manifest_lines:
        report.dependencies = DependencyReport(
            DEP_PENDING,
            "checked when the environment is created on first launch",
        )
    else:
        report.dependencies = DependencyReport(
            DEP_NONE,
            f"{REQUIREMENTS_NAME} declares no third-party packages",
        )

    if report.python is not None and gui:
        ok, error, version = tk_status(report.python.executable)
        report.tkinter_ok = ok
        report.tkinter_error = error
        report.tkinter_version = version
        if not ok:
            report.problems.append(
                LauncherError(
                    ExitCode.SYSTEM_LIBRARY,
                    f"The selected Python ({report.python.executable}) does not include Tkinter, "
                    "which PlanForge needs for its window.",
                    details=error,
                    hints=tkinter_hints(platform_info),
                )
            )
    return report


def _dependency_label(report: DependencyReport | None) -> str:
    if report is None:
        return "not checked"
    mapping = {
        DEP_NONE: "none declared in requirements.txt",
        DEP_SATISFIED: "all requirements satisfied",
        DEP_MISSING: "missing - installed on next launch (needs internet)",
        DEP_PENDING: "checked when the environment is created",
        DEP_PIP_MISSING: "pip unavailable in .venv (repaired on next launch)",
        DEP_INVALID: "requirements.txt has a problem",
        DEP_INSTALLED: "installed",
    }
    return mapping.get(report.status, report.status)


def format_environment_report(report: EnvironmentReport) -> str:
    lines = [
        f"{APP_NAME}Launcher check",
        f"  Platform        : {report.platform.display_name} ({report.platform.architecture})",
        f"  Application dir : {report.root}",
    ]
    if report.python is not None:
        tk_text = ""
        if report.tkinter_ok is True:
            tk_text = f", Tk {report.tkinter_version}" if report.tkinter_version else ", Tkinter available"
        elif report.tkinter_ok is False:
            tk_text = ", Tkinter MISSING"
        lines.append(
            f"  Python          : {report.python.executable} "
            f"({report.python.version_text}{tk_text})"
        )
        lines.append(f"  Python source   : {report.python_source}")
    else:
        lines.append("  Python          : not found")

    if report.venv.status == "ready":
        version = report.venv.info.version_text if report.venv.info else "unknown"
        lines.append(f"  Virtual env     : ready - {report.paths.root} (Python {version})")
    elif report.venv.status == "missing":
        lines.append(f"  Virtual env     : not created yet - {report.paths.root}")
    else:
        replaceable, _ = venv_can_be_replaced(report.paths)
        action = "rebuilt on next launch" if replaceable else "must be repaired manually"
        lines.append(f"  Virtual env     : needs repair ({action}) - {report.venv.reason}")

    lines.append(f"  Dependencies    : {_dependency_label(report.dependencies)}")
    if report.gui:
        if report.tkinter_ok is True:
            tk_line = f"available (Tk {report.tkinter_version})" if report.tkinter_version else "available"
        elif report.tkinter_ok is False:
            tk_line = f"NOT available - {report.tkinter_error}"
        else:
            tk_line = "not checked"
        lines.append(f"  Tkinter         : {tk_line}")
    else:
        lines.append("  Launch mode     : command line (no window)")

    log_path = current_log_path()
    if log_path is not None:
        lines.append(f"  Log file        : {log_path}")
    lines.append("")
    lines.append(f"Ready to launch: {'yes' if report.ready else 'no'}")
    if report.problems:
        lines.append("")
        lines.append("Problems:")
        for problem in report.problems:
            lines.append(f"  - {problem.summary}")
            if problem.details:
                for detail_line in tail_text(problem.details, lines=6, chars=1000).splitlines():
                    lines.append(f"      {detail_line}")
            for hint in problem.hints:
                lines.append(f"      {hint}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Application startup
# ---------------------------------------------------------------------------


def needs_gui(app_args: Sequence[str]) -> bool:
    """Mirror PlanForge's own CLI: import/help modes do not open a window."""
    for arg in app_args:
        if arg in ("--import-file", "--help", "-h"):
            return False
        if arg.startswith("--import-file="):
            return False
    return True


_PATH_OPTIONS = ("--import-file", "--export-file")
_VALUE_OPTIONS = ("--export-format",)


def normalize_app_args(app_args: Sequence[str], base_cwd: Path | str) -> list[str]:
    """Resolve relative paths against the caller's cwd before changing cwd."""
    base = Path(base_cwd)
    result: list[str] = []
    index = 0
    positional_seen = False

    def absolute(value: str) -> str:
        expanded = os.path.expanduser(value)
        if os.path.isabs(expanded):
            return os.path.normpath(expanded)
        return os.path.normpath(os.path.join(str(base), expanded))

    while index < len(app_args):
        arg = app_args[index]
        if arg == "--":
            result.extend(app_args[index + 1:])
            break
        if arg in _PATH_OPTIONS and index + 1 < len(app_args):
            result.extend([arg, absolute(app_args[index + 1])])
            index += 2
            continue
        matched_path_option = next(
            (option for option in _PATH_OPTIONS if arg.startswith(option + "=")),
            None,
        )
        if matched_path_option:
            result.append(f"{matched_path_option}={absolute(arg.split('=', 1)[1])}")
            index += 1
            continue
        if arg in _VALUE_OPTIONS and index + 1 < len(app_args):
            result.extend([arg, app_args[index + 1]])
            index += 2
            continue
        if any(arg.startswith(option + "=") for option in _VALUE_OPTIONS):
            result.append(arg)
            index += 1
            continue
        if not arg.startswith("-") and not positional_seen:
            result.append(absolute(arg))
            positional_seen = True
            index += 1
            continue
        result.append(arg)
        index += 1
    return result


def _app_log_path(root: Path) -> Path:
    return resolve_log_dir(root) / "application.log"


def _rotate_application_log(path: Path) -> None:
    try:
        if path.stat().st_size > 1_000_000:
            backup = path.with_name(path.name + ".1")
            try:
                if backup.exists():
                    backup.unlink()
            except OSError:
                pass
            path.replace(backup)
    except OSError:
        pass


def _read_from(path: Path, offset: int, *, limit: int = 8000) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    start = max(0, min(offset, size))
    if size - start > limit:
        start = size - limit
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            data = handle.read(limit)
    except OSError:
        return ""
    return data.decode("utf-8", "replace").strip()


def _append_application_output(path: Path, stdout: str, stderr: str) -> None:
    if not stdout and not stderr:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="replace") as handle:
            if stdout:
                handle.write(stdout if stdout.endswith("\n") else stdout + "\n")
            if stderr:
                handle.write(stderr if stderr.endswith("\n") else stderr + "\n")
    except OSError:
        pass


def launch_application(
    prepared: PreparedEnvironment,
    app_args: Sequence[str],
    *,
    gui: bool,
    log: logging.Logger = LOGGER,
) -> tuple[int, str]:
    """Run ``python -m planforge`` and return (exit code, captured output)."""
    executable = prepared.paths.python
    if gui and prepared.platform.is_windows and prepared.paths.pythonw is not None:
        if prepared.paths.pythonw.is_file():
            executable = prepared.paths.pythonw

    command = [str(executable), "-m", PACKAGE_NAME, *[str(arg) for arg in app_args]]
    log.info("Starting PlanForge: %s", command)
    log.info("Working directory: %s", prepared.root)
    app_log = _app_log_path(prepared.root)
    _rotate_application_log(app_log)

    if not gui:
        # Command-line conversions own the terminal, but their output is also
        # copied to application.log so a failed import can be diagnosed later.
        try:
            process = subprocess.Popen(
                command,
                cwd=str(prepared.root),
                env=child_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise LauncherError(
                ExitCode.STARTUP_ERROR,
                "The PlanForge process could not be started.",
                details=str(exc),
                hints=[
                    "Make sure the PlanForge folder has not been moved or deleted.",
                    "Run the launcher with --check for a full environment report.",
                ],
            )
        try:
            stdout, stderr = process.communicate()
        except KeyboardInterrupt:
            _terminate_process(process, log)
            raise
        stdout = stdout or ""
        stderr = stderr or ""
        if stdout.strip():
            say(stdout.rstrip())
        if stderr.strip():
            say(stderr.rstrip(), error=True)
        _append_application_output(app_log, stdout, stderr)
        combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
        return int(process.returncode or 0), combined

    try:
        offset = app_log.stat().st_size if app_log.exists() else 0
    except OSError:
        offset = 0

    try:
        handle = open(app_log, "a", encoding="utf-8", errors="replace")
    except OSError:
        handle = None
    try:
        output_target = handle if handle is not None else subprocess.DEVNULL
        try:
            process = subprocess.Popen(
                command,
                cwd=str(prepared.root),
                env=child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=output_target,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            raise LauncherError(
                ExitCode.STARTUP_ERROR,
                "The PlanForge process could not be started.",
                details=str(exc),
                hints=[
                    "Make sure the PlanForge folder has not been moved or deleted.",
                    "Run the launcher with --check for a full environment report.",
                ],
            )
        try:
            returncode = int(process.wait())
        except KeyboardInterrupt:
            _terminate_process(process, log)
            raise
    finally:
        if handle is not None:
            handle.close()

    return returncode, _read_from(app_log, offset)


def _terminate_process(process: subprocess.Popen, log: logging.Logger) -> None:
    log.info("Interrupted; asking PlanForge to close.")
    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        pass


def hide_console_window(log: logging.Logger = LOGGER) -> bool:
    """Hide our own console on Windows, but never a user's shared terminal."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        window = user32.GetConsoleWindow()
        if not window:
            return False
        process_ids = (ctypes.c_uint * 4)()
        count = kernel32.GetConsoleProcessList(process_ids, 4)
        if count > 1:
            # The console belongs to a terminal the user opened; leave it alone.
            log.debug("Console is shared with %s process(es); not hiding it.", count)
            return False
        user32.ShowWindow(window, 0)  # SW_HIDE
        log.info("Hidden the launcher console window.")
        return True
    except Exception as exc:
        log.debug("Could not hide the console: %s", exc)
        return False


# ---------------------------------------------------------------------------
# GUI feedback (progress and error windows)
# ---------------------------------------------------------------------------


class ProgressWindow:
    """A tiny Tk window shown only while first-time setup runs."""

    def __init__(self, title: str = f"{APP_NAME} is starting") -> None:
        self._root = None
        self._label = None
        self._closed = False
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title(title)
            root.resizable(False, False)
            frame = tk.Frame(root, padx=24, pady=20)
            frame.pack(fill="both", expand=True)
            heading = tk.Label(frame, text=f"Preparing {APP_NAME}", font=("TkDefaultFont", 13, "bold"))
            heading.pack(anchor="w")
            self._label = tk.Label(frame, text="Checking the environment...", anchor="w", justify="left")
            self._label.pack(anchor="w", pady=(8, 0))
            note = tk.Label(
                frame,
                text="This only happens on the first launch or after an update.",
                anchor="w",
                justify="left",
            )
            note.pack(anchor="w", pady=(12, 0))
            root.protocol("WM_DELETE_WINDOW", self._hide)
            root.update_idletasks()
            width = max(460, root.winfo_reqwidth())
            height = max(150, root.winfo_reqheight())
            x = max(0, (root.winfo_screenwidth() - width) // 2)
            y = max(0, (root.winfo_screenheight() - height) // 3)
            root.geometry(f"{width}x{height}+{x}+{y}")
            root.deiconify()
            root.lift()
            root.update()
            self._root = root
        except Exception:
            self._root = None

    def _hide(self) -> None:
        if self._root is not None:
            try:
                self._root.withdraw()
            except Exception:
                self._closed = True

    def set(self, message: str) -> None:
        if self._closed or self._root is None or self._label is None:
            return
        try:
            self._label.config(text=message)
            self._root.update_idletasks()
            self._root.update()
        except Exception:
            self.close()

    def close(self) -> None:
        self._closed = True
        if self._root is not None:
            try:
                self._root.destroy()
            except Exception:
                pass
            self._root = None


class ProgressReporter:
    """Print progress and, when appropriate, show it in a small window."""

    def __init__(self, *, window_enabled: bool) -> None:
        self.window_enabled = window_enabled
        self._window: ProgressWindow | None = None
        self._closed = False

    def __call__(self, message: str) -> None:
        if self._closed:
            return
        say(message)
        if not self.window_enabled:
            return
        if self._window is None:
            self._window = ProgressWindow()
        self._window.set(message)

    def close(self) -> None:
        self._closed = True
        if self._window is not None:
            self._window.close()
            self._window = None


def _open_log_folder(log_path: Path | None) -> None:
    if log_path is None:
        return
    folder = log_path.parent
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        pass


def show_error_dialog(
    summary: str,
    *,
    details: str = "",
    hints: Sequence[str] = (),
    log_path: Path | None = None,
    title: str = f"{APP_NAME} could not start",
) -> None:
    """Show a Tk error window; fall back to a native Windows message box."""
    log_path = log_path or current_log_path()
    detail_parts = []
    if details:
        detail_parts.append("Technical details:\n" + details)
    if hints:
        detail_parts.append("What you can do:\n" + "\n".join(f"- {hint}" for hint in hints))
    if log_path is not None:
        detail_parts.append(f"Log file:\n{log_path}")
    full_details = "\n\n".join(detail_parts)

    try:
        import tkinter as tk
        from tkinter import scrolledtext

        root = tk.Tk()
        root.withdraw()
        root.title(title)
        frame = tk.Frame(root, padx=18, pady=16)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text=f"{APP_NAME} could not start",
            font=("TkDefaultFont", 14, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            frame,
            text=summary,
            anchor="w",
            justify="left",
            wraplength=640,
        ).pack(fill="x", pady=(8, 10))
        text_box = scrolledtext.ScrolledText(frame, width=88, height=16, wrap="word")
        text_box.pack(fill="both", expand=True)
        text_box.insert("1.0", full_details)
        text_box.configure(state="disabled")
        buttons = tk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        if log_path is not None:
            tk.Button(
                buttons,
                text="Open log folder",
                command=lambda: _open_log_folder(log_path),
            ).pack(side="left")
        tk.Button(buttons, text="Close", command=root.destroy).pack(side="right")
        root.update_idletasks()
        width = 720
        height = 480
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 3)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.after(250, lambda: root.attributes("-topmost", False))
        root.mainloop()
        return
    except Exception:
        pass

    if os.name == "nt":
        try:
            import ctypes

            message = f"{summary}\n\n{full_details}"
            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                None, message, title, 0x00000010  # MB_ICONERROR
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Command line and main
# ---------------------------------------------------------------------------

HELP_TEXT = f"""{APP_NAME}Launcher - PlanForge universal launcher

Usage:
  python PlanForgeLauncher.py [launcher options] [--] [PlanForge arguments]

Launcher options:
  --check           Check the environment without changing anything
  --setup           Prepare .venv and dependencies, then exit
  --gui             Force graphical feedback while starting
  --recreate-venv   Delete and rebuild the project-local .venv
  --hide-console    Windows: hide the launcher console before starting the GUI
  --no-dialogs      Never show graphical error dialogs
  -v, --verbose     Write extra diagnostic detail to the console and log
  -h, --help        Show this help and exit

Everything else is passed to PlanForge, for example:
  python PlanForgeLauncher.py my_project.pfp
  python PlanForgeLauncher.py --import-file schedule.xml --export-file schedule.gan
  python PlanForgeLauncher.py --import-file schedule.gan

Entry points:
  Windows:      double-click PlanForgeLauncher.bat
  Linux/macOS:  ./PlanForgeLauncher.sh
  macOS:        double-click PlanForgeLauncher.command
  run.bat, run.sh and run.command remain as compatibility wrappers.

Logs are written to logs/launcher.log next to this file.
Exit codes: 0 ok, 10 Python missing, 11 Python too old, 12 environment error,
13 dependency error, 14 network error, 15 missing system component,
16 startup error, 17 another setup is running, 18 unsupported platform.
"""


def parse_options(argv: Sequence[str]) -> Options:
    check = setup = gui = hide_console = recreate = verbose = no_dialogs = help_flag = False
    app_args: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            app_args.extend(argv[index + 1:])
            break
        if arg in ("-h", "--help"):
            help_flag = True
        elif arg == "--check":
            check = True
        elif arg == "--setup":
            setup = True
        elif arg == "--gui":
            gui = True
        elif arg == "--hide-console":
            hide_console = True
        elif arg == "--recreate-venv":
            recreate = True
        elif arg in ("-v", "--verbose"):
            verbose = True
        elif arg == "--no-dialogs":
            no_dialogs = True
        else:
            app_args.append(arg)
        index += 1
    if check and setup:
        raise UsageError("--check and --setup cannot be used together.")
    if recreate and check:
        raise UsageError("--check does not change anything and cannot be combined with --recreate-venv.")
    return Options(
        check=check,
        setup=setup,
        gui=gui,
        hide_console=hide_console,
        recreate_venv=recreate,
        verbose=verbose,
        no_dialogs=no_dialogs,
        help=help_flag,
        app_args=tuple(app_args),
    )


def _platform_unsupported_error(platform_info: PlatformInfo) -> LauncherError:
    return LauncherError(
        ExitCode.UNSUPPORTED_PLATFORM,
        f"{APP_NAME} does not support this operating system yet ({platform_info.system}).",
        hints=[
            "Supported platforms are Windows 10/11, Linux and macOS.",
            "If you are on a Unix-like system, check whether a build of Python with Tkinter is available.",
            f"The launcher did not start {APP_NAME}.",
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        options = parse_options(arguments)
    except UsageError as exc:
        say(f"{APP_NAME} launcher: {exc}", error=True)
        say("Run with --help for usage.", error=True)
        return ExitCode.USAGE

    if options.help:
        say(HELP_TEXT)
        return ExitCode.OK

    _configure_streams()
    log_path = setup_logging(APP_ROOT, options.verbose)
    app_gui = needs_gui(options.app_args)
    ui = options.gui or app_gui
    try:
        caller_cwd = Path.cwd()
    except OSError:
        # A deleted working directory must not prevent PlanForge from starting.
        caller_cwd = APP_ROOT
    LOGGER.info(
        "Launcher start: args=%r cwd=%s python=%s launcher=%s",
        arguments,
        caller_cwd,
        sys.version.split()[0],
        APP_ROOT,
    )

    try:
        if sys.version_info[:2] < MINIMUM_LAUNCHER_PYTHON:
            raise LauncherError(
                ExitCode.UNSUPPORTED_PYTHON,
                (
                    f"The launcher needs Python {MINIMUM_LAUNCHER_PYTHON[0]}."
                    f"{MINIMUM_LAUNCHER_PYTHON[1]}+ to run, but this is "
                    f"{sys.version.split()[0]}."
                ),
                hints=python_upgrade_hints(detect_platform()),
            )

        platform_info = detect_platform()
        if not platform_info.supported:
            raise _platform_unsupported_error(platform_info)

        paths = venv_paths(APP_ROOT, platform_info.key)

        if options.check:
            report = inspect_environment(platform_info, APP_ROOT, gui=app_gui)
            say(format_environment_report(report))
            LOGGER.info("Environment check result: ready=%s code=%s", report.ready, report.exit_code)
            return report.exit_code

        if app_gui:
            say(f"{APP_NAME}Launcher")
            say(f"  Platform: {platform_info.display_name} ({platform_info.architecture})")
        else:
            say(f"{APP_NAME}Launcher ({platform_info.display_name}, {platform_info.architecture})")

        if options.recreate_venv:
            recreate_environment(paths)
            LOGGER.info("Existing environment removed at user request.")

        reporter = ProgressReporter(window_enabled=bool(ui and not options.no_dialogs))
        try:
            prepared = prepare_environment(
                platform_info,
                APP_ROOT,
                gui=app_gui,
                log=LOGGER,
                on_progress=reporter,
            )
        finally:
            reporter.close()

        say(
            f"  Virtual environment: {prepared.paths.root} "
            f"(Python {prepared.python.version_text})"
        )
        say(f"  Dependencies: {_dependency_label(prepared.dependencies)}")

        if options.setup:
            if app_gui:
                ok, error, version = tkinter_status(prepared.python.executable)
                if not ok:
                    raise LauncherError(
                        ExitCode.SYSTEM_LIBRARY,
                        "The environment is prepared, but PlanForge's window cannot start because Tkinter is missing.",
                        details=error,
                        hints=tkinter_hints(platform_info),
                    )
                say(f"  Tkinter: available (Tk {version})" if version else "  Tkinter: available")
            say(f"{APP_NAME}'s environment is ready.")
            return ExitCode.OK

        if app_gui:
            ok, error, version = tkinter_status(prepared.python.executable)
            LOGGER.info("Tkinter check: available=%s version=%s error=%s", ok, version, error)
            if not ok:
                raise LauncherError(
                    ExitCode.SYSTEM_LIBRARY,
                    "PlanForge needs Tkinter for its window, but it is not available in this Python installation.",
                    details=error,
                    hints=tkinter_hints(platform_info),
                )

        if options.hide_console and app_gui:
            hide_console_window(LOGGER)

        app_args = normalize_app_args(options.app_args, caller_cwd)
        say(f"Starting {APP_NAME}...")
        returncode, output = launch_application(prepared, app_args, gui=app_gui, log=LOGGER)
        LOGGER.info("PlanForge exited with status %s", returncode)
        if returncode != 0:
            hints = startup_hints(output)
            summary = f"PlanForge closed with exit code {returncode}."
            if output:
                LOGGER.error("PlanForge output:\n%s", sanitize(output))
            else:
                LOGGER.error("PlanForge produced no console output.")
            say("")
            say(summary, error=True)
            for hint in hints:
                say(f"  - {hint}", error=True)
            if ui and not options.no_dialogs:
                show_error_dialog(
                    summary,
                    details=tail_text(output, lines=25),
                    hints=hints,
                    log_path=log_path,
                    title=f"{APP_NAME} stopped unexpectedly",
                )
            return returncode
        return ExitCode.OK

    except LauncherError as exc:
        LOGGER.error("Launcher error [%s]: %s", exc.code, exc.summary)
        if exc.details:
            LOGGER.error("Details:\n%s", sanitize(exc.details))
        say("")
        say(f"{APP_NAME} could not start: {exc.summary}", error=True)
        for hint in exc.hints:
            say(f"  - {hint}", error=True)
        say(f"Log file: {log_path}", error=True)
        if ui and not options.no_dialogs:
            show_error_dialog(
                exc.summary,
                details=exc.details,
                hints=exc.hints,
                log_path=log_path,
            )
        return exc.code
    except KeyboardInterrupt:
        LOGGER.info("Launcher interrupted by the user.")
        say("Interrupted.", error=True)
        return ExitCode.INTERRUPTED
    except Exception as exc:  # never leave a pythonw launch with no feedback
        LOGGER.exception("Unexpected launcher failure")
        summary = f"An unexpected launcher error occurred: {exc}"
        say("")
        say(f"{APP_NAME} could not start: {summary}", error=True)
        say(f"Log file: {log_path}", error=True)
        if ui and not options.no_dialogs:
            show_error_dialog(
                summary,
                details="The full traceback is in the launcher log.",
                hints=[f"Open {log_path} for details.", "Run the launcher with --check to diagnose the environment."],
                log_path=log_path,
            )
        return ExitCode.ERROR


if __name__ == "__main__":
    sys.exit(main())
