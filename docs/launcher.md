# PlanForgeLauncher — Universal Launcher

The launcher lets a user start PlanForge without installing Python packages,
activating environments or remembering the correct startup command. It detects
the operating system, finds a compatible Python interpreter, prepares a
project-local `.venv`, checks the declared dependencies and then starts the
real application.

The canonical launcher is **`PlanForgeLauncher`**. On Windows use
`PlanForgeLauncher.bat`, on Linux/macOS use `PlanForgeLauncher.sh`, and on
macOS Finder use `PlanForgeLauncher.command`. The older `run.bat`, `run.sh` and
`run.command` names remain as thin compatibility wrappers for existing
instructions and shortcuts.

The launcher does **not** modify the PlanForge application, its UI or its data.
It only reads `requirements.txt`, writes `.venv/`, `logs/` and a short-lived
setup lock, and runs `python -m planforge` from the installation directory.

---

## Launch PlanForge

| System | Normal launch | Command-line use |
| --- | --- | --- |
| Windows 10/11 | Double-click **`PlanForgeLauncher.bat`** | `PlanForgeLauncher.bat --check` |
| Linux | `./PlanForgeLauncher.sh` | `./PlanForgeLauncher.sh --check` |
| macOS (Terminal) | `./PlanForgeLauncher.sh` | `./PlanForgeLauncher.sh --check` |
| macOS (Finder) | Double-click **`PlanForgeLauncher.command`** | `./PlanForgeLauncher.command --check` |
| Any system | `python PlanForgeLauncher.py` (or `python3`) | `python PlanForgeLauncher.py --check` |

Double-clicking with no arguments starts the desktop application. If you pass a
command-line operation such as `--import-file` or `--help`, output stays in the
console; passing a project file opens the desktop application.

The launcher works from any current directory. Relative project paths are
resolved against the directory you launched from, and the application itself
always runs with the PlanForge installation directory as its working directory.

### Windows

1. Install Python 3.10 or newer from
   <https://www.python.org/downloads/windows/>. Tick **Add python.exe to PATH**
   and leave **tcl/tk and IDLE** enabled.
2. Double-click `PlanForgeLauncher.bat`.

`PlanForgeLauncher.bat` uses the Python launcher (`py -3`) when available, otherwise
`python` from `PATH`. It starts the launcher through `pythonw.exe`, so no
console window appears during normal use. On the first launch a small setup
window reports progress, and errors are shown in a Windows dialog (or a Tk
window when Tkinter is available). No administrator rights are requested.

If Windows SmartScreen warns about `PlanForgeLauncher.bat`, choose **More info → Run anyway**.
The script is plain text; it does not download or execute installers.

For diagnostics, open Command Prompt in the PlanForge folder and run:

```bat
PlanForgeLauncher.bat --check
PlanForgeLauncher.bat --import-file schedule.xml --export-file schedule.gan --export-format ganttproject
```

### Linux

```bash
cd PlanForge
./PlanForgeLauncher.sh
```

If the archive lost the executable bit:

```bash
chmod +x PlanForgeLauncher.sh PlanForgeLauncher.py
```

`PlanForgeLauncher.sh` checks that it is running on Linux or macOS and then delegates to
`PlanForgeLauncher.py`. It never runs `sudo`, never edits system Python and never
installs operating-system packages. If Tkinter is missing, it prints the exact
package command for your distribution and stops.

Common Tkinter packages:

| Distribution | Command |
| --- | --- |
| Debian, Ubuntu, Linux Mint, Pop!_OS | `sudo apt install python3-tk` |
| Arch Linux, Manjaro, EndeavourOS | `sudo pacman -S tk` |
| Fedora, RHEL, Rocky, AlmaLinux | `sudo dnf install python3-tkinter` |
| openSUSE | `sudo zypper install python3-tk` |
| Alpine | `sudo apk add python3-tkinter` |
| Void Linux | `sudo xbps-install -S python3-tkinter` |
| Solus | `sudo eopkg install python3-tkinter` |

Installing Tkinter requires administrator rights, so the launcher explains it
rather than doing it. PlanForge itself never needs root.

### macOS

- **Finder:** double-click `PlanForgeLauncher.command`. Terminal opens, runs `PlanForgeLauncher.sh`, and
  stays open so diagnostics remain visible.
- **Terminal:** `./PlanForgeLauncher.sh` or `python3 PlanForgeLauncher.py`.

Python from **python.org** includes Tkinter and is the recommended choice.
Homebrew Python needs the matching Tk package:

```bash
brew install python-tk@3.13   # use the version reported by python3 --version
```

macOS support depends on the installed Python/Tk combination. If Tk is absent
or incompatible, the launcher reports the exact problem instead of failing at
window creation. Downloaded `.command` files may be quarantined by Gatekeeper;
if macOS refuses to run it, right-click → **Open**, or run `./PlanForgeLauncher.sh` from
Terminal.

---

## What the launcher does

1. Detects the platform with `platform` and `sys` (Windows, Linux, macOS, or an
   explicit "unsupported" result). Linux distribution and package manager are
   read from `/etc/os-release`; architecture is normalised (`AMD64` → `x86_64`,
   `aarch64` → `arm64`).
2. Selects an interpreter. It probes `py -3.x`, `python3.x`, `python3`,
   `python` and the current interpreter, then chooses Python 3.10+ — preferring
   one with Tkinter for graphical launches.
3. Validates `.venv` (interpreter present, `pyvenv.cfg` present, interpreter
   belongs to that environment, Python version compatible).
4. Creates or repairs `.venv` under a lock. Interrupted setups are rebuilt;
   folders that are not recognisably a virtual environment are never deleted.
5. Checks `requirements.txt` **offline** with
   `pip install --no-index --dry-run -r requirements.txt`. This performs no
   downloads and only contacts the network if something is missing.
6. Installs missing dependencies into `.venv` only. It never installs globally
   and never passes `--user`, `sudo` or an arbitrary shell command.
7. Verifies the environment again and re-runs `ensurepip` if pip was damaged by
   an interrupted installation.
8. Checks Tkinter for graphical launches and prints platform-specific install
   guidance if it is missing.
9. Starts `python -m planforge` with the installation folder as the working
   directory, passing through project paths and conversion options.
10. Logs everything relevant and reports failures without restarting the
    application in a loop.

If `.venv` is already valid and the manifest declares nothing new, no installer
runs at all. A typical repeat launch takes a fraction of a second.

---

## Files, logs and user data

The launcher writes only these locations:

| Path | Purpose |
| --- | --- |
| `.venv/` | Disposable project-local environment |
| `logs/launcher.log` | Setup and diagnostic log (rotated at 1 MB) |
| `logs/application.log` | Output/tracebacks from PlanForge (rotated at 1 MB) |
| `.planforge-setup.lock` | Temporary lock held only during setup |

The lock is removed after setup. If a launcher is killed mid-setup, the next
launch detects the dead PID or an old lock file and removes it.

PlanForge projects (`.pfp`, `.xml`, `.gan`, `.json`, `.csv`), existing files and
the user's settings in `~/.config/PlanForge/PlanForge.conf` are never modified.
`--recreate-venv` deletes only `.venv`.

If the PlanForge folder is not writable, `logs/` falls back to the system
temporary directory (`%TEMP%\PlanForge-logs` or `/tmp/PlanForge-logs`). The
error dialog shows the log path in use.

---

## Options and exit codes

```text
python PlanForgeLauncher.py [launcher options] [--] [PlanForge arguments]

  --check           Check the environment without changing anything
  --setup           Prepare .venv and dependencies, then exit
  --gui             Force graphical feedback while starting
  --recreate-venv   Delete and rebuild the project-local .venv
  --hide-console    Windows: hide the launcher console before starting the GUI
  --no-dialogs      Never show graphical error dialogs
  -v, --verbose     Extra diagnostic detail in the console and log
  -h, --help        Show launcher help
```

Arguments not understood by the launcher are passed to PlanForge:

```bash
./PlanForgeLauncher.sh my_project.pfp
./PlanForgeLauncher.sh --import-file schedule.xml --export-file schedule.gan --export-format ganttproject
./PlanForgeLauncher.sh --import-file schedule.gan
```

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success (and the application exited normally) |
| 1 | Unexpected launcher error |
| 2 | Invalid launcher command line |
| 10 | No Python 3 interpreter found |
| 11 | Python found, but older than 3.10 |
| 12 | Virtual environment could not be created, validated or replaced |
| 13 | Dependency installation failed (invalid package, wheel unavailable, pip broken) |
| 14 | Dependencies could not be downloaded (network/index unavailable) |
| 15 | Missing system component (Tkinter) |
| 16 | PlanForge process could not be started |
| 17 | Another launcher is still preparing the environment |
| 18 | Unsupported operating system |
| 130 | Interrupted with Ctrl+C |

When PlanForge starts but closes with a non-zero status, the launcher exits with
that same status so scripts and shortcuts can react to it.

---

## Offline and network behaviour

| Situation | Behaviour |
| --- | --- |
| Environment valid, manifest satisfied | Starts immediately, no network access |
| Requirements declared and already installed | Offline `--no-index --dry-run` check passes; no download |
| Requirements missing, network available | Installs into `.venv`, then verifies |
| Requirements missing, network unavailable | Exits 14 with connection/proxy guidance; never claims success |
| Manifest invalid | Exits 13 and points at `requirements.txt` |
| pip missing or damaged | Runs `ensurepip --upgrade`, rechecks, then continues or explains |
| First launch with no third-party dependencies | No download is needed at all (PlanForge currently has none) |
| Package index reachable but package/version absent | Exits 13 with package guidance |

PlanForge uses only the Python standard library at runtime. Its only system
dependency is Tkinter, which the launcher cannot install without administrator
rights; it reports the exact package command for the detected distribution.

---

## Security properties

- Commands are executed as argument lists; no shell, `eval` or string-built
  command line is used.
- The dependency source is the repository's `requirements.txt`; there is no
  hard-coded package list.
- No global installs, no `--user`, no `sudo`, no administrator prompt.
- No arbitrary scripts are downloaded or executed.
- Package-index credentials in pip output are redacted before logging.
- The launcher never deletes a folder unless it is empty, contains
  `pyvenv.cfg`, or contains only the expected partial-venv directory names.
- Concurrent setup is serialised with a PID lock to prevent environment
  corruption; user files are outside the lock's scope.
- `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONEXECUTABLE`,
  `__PYVENV_LAUNCHER__` and `VIRTUAL_ENV` are removed from child processes so a
  previously activated environment cannot leak into PlanForge.

---

## Troubleshooting

| Symptom | Action |
| --- | --- |
| "Python was not found" | Install Python 3.10+; on Windows tick *Add to PATH* and avoid the Microsoft Store alias |
| "Python ... is older than 3.10" | Install a newer Python; the launcher chooses the newest one it finds |
| "Tkinter is missing" | Install the system package for your distribution (table above) |
| "The folder .venv ... is not a virtual environment" | Move/delete it manually; the launcher will not risk your files |
| "Another PlanForge launch is preparing" | Wait; if no launch is running, delete `.planforge-setup.lock` |
| Setup fails behind a proxy | Set `HTTPS_PROXY`/`HTTP_PROXY` before launching |
| Application exits immediately | Check `logs/application.log`; the dialog shows the last lines and exit code |
| Window does not appear on Linux | Start from a desktop session; Tk needs `DISPLAY` or Wayland |
| Windows blocks `.venv` creation | Allow the PlanForge folder in antivirus / Controlled Folder Access |

Run `./PlanForgeLauncher.sh --check` (or `PlanForgeLauncher.bat --check`) for a full, read-only report. Use
`--recreate-venv` if you changed Python installations and want PlanForge to
rebuild `.venv` with the new interpreter.

---

## Verification performed

The launcher was developed and tested in the following environment:

- **Linux:** Debian GNU/Linux 12 (bookworm), x86_64, CPython 3.11.2, no Tkinter
  and no display in the sandbox.
- **Automated tests:** `python3 -m unittest discover tests -v` → 141 tests pass,
  4 existing Tk GUI tests skipped because the sandbox has no Tk/display.
  This includes 69 new launcher tests in `tests/test_launcher.py`.
- **Real application:** `PlanForgeLauncher.sh --import-file tests/fixtures/sample_projectlibre.xml`
  created `.venv` on first launch, converted the fixture correctly, and reused
  the environment on subsequent launches.
- **Missing Tkinter:** `--check`, `--setup` and a normal GUI launch exit 15 with
  Debian-specific `python3-tk` guidance.
- **Real dependency install:** in a temporary copy, `packaging==24.2` was
  installed from PyPI into `.venv`; a later launch with an unreachable index
  reused it without any network access.
- **No network on first setup:** a temporary root with a missing package and a
  dead index exits 14; with `PIP_NO_INDEX` it exits 13. Neither starts the
  application or claims success.
- **Launch from elsewhere / spaces / non-ASCII:** a fake application in
  `Plan Forge Tëst` launched from a different working directory, with relative
  paths containing spaces, resolved arguments to absolute paths and used the
  installation folder as its cwd.
- **Repeated launches:** second launch reused `.venv` and did not recreate it.
- **Crash handling:** a fake application exiting 7 produced exit 7, one launch
  only (no restart loop), and a populated `logs/application.log`.
- **User data:** project and notes files were byte-identical after setup,
  `--check`, repeated launches and `--recreate-venv`.
- **Concurrency:** lock acquisition, timeout, stale-lock takeover and release
  after exceptions are unit-tested.
- **Wrapper scripts:** `PlanForgeLauncher.sh`, `PlanForgeLauncher.command` and the
  `run.*` compatibility wrappers pass POSIX syntax checks;
  `PlanForgeLauncher.sh` was executed with a Windows `uname` shim (helpful message, exit 1)
  and with no Python on `PATH` (install guidance, exit 127). `PlanForgeLauncher.bat` is
  statically checked for CRLF and delegation but cannot be executed here.

### Not yet verified on real hardware

This development environment is Linux-only and has no Tkinter. The following
must be validated before Windows and macOS support is described as fully
verified:

- Double-clicking `PlanForgeLauncher.bat` on Windows 10 and 11 (including pythonw behaviour,
  first-run setup window and error dialogs).
- Installing/repairing Python and Tkinter on Windows.
- Double-clicking `PlanForgeLauncher.command` on macOS, Gatekeeper quarantine behaviour, and
  python.org vs Homebrew Tkinter combinations.
- Opening the actual Tk window on any platform (the existing 4 GUI tests were
  skipped for the same reason).

The platform detection, Windows path layout, interpreter selection, exit codes
and error guidance for those systems are covered by unit tests with simulated
platform data, but simulation is not a substitute for running on the target OS.

---

## Known limitations

- **Tkinter cannot be installed by the launcher.** It is a system package and
  needs administrator rights on Linux; the launcher explains the command.
- **The launcher itself needs Python 3.7+** to run and print useful errors.
  PlanForge needs Python 3.10+, so on a machine with only Python 3.6 or older
  the user must install a newer Python first.
- **Windows scripts are unsigned.** SmartScreen may show a warning; no code
  signing certificate is configured in this repository.
- **macOS may quarantine downloaded scripts.** Use right-click → Open or run
  `./PlanForgeLauncher.sh` from Terminal. Tk compatibility depends on the Python build.
- **Setup is single-instance; the application is not.** The lock prevents two
  setups from corrupting `.venv`, but two rapid double-clicks can still open
  two PlanForge windows after setup completes.
- **No automatic updates.** The launcher runs the files it is distributed with.
- **No standalone executables are included yet.** See the packaging evaluation
  below.
- **Windows and macOS have not been executed in this environment.** See the
  verification section for exactly what was tested.

---

## Standalone packaging evaluation (optional distribution path)

The shared launcher remains the primary distribution method. Standalone
packages are an additional path and must be built separately for each operating
system; one binary cannot cover all platforms.

| Tool | License | Strengths | Considerations |
| --- | --- | --- | --- |
| **PyInstaller** | GPL-2.0-or-later with bootloader exception | Mature; Windows `.exe`, macOS `.app`, Linux binaries; handles Tk with hooks; `--onedir` is faster and easier to debug | Build on each target OS; onefile extracts to temp at startup; macOS signing/notarisation still required; 15–30 MB with Tk |
| **Briefcase** | Apache-2.0 | Produces native installers (MSI, DMG, AppImage/deb) from one project definition | More project scaffolding; packaging backends and platform toolchains required |
| **Nuitka** | Apache-2.0 | Compiles Python to C; good startup and obfuscation | Long build times; Tk plugin support; larger artefacts |
| **py2app** | MIT | Native macOS `.app` bundles | macOS only |
| **pynsist** | BSD | MSI installers for Windows | Windows only; bundles its own Python |

Recommendation: keep `PlanForgeLauncher.py` as the supported entry point, then add
PyInstaller `--onedir` builds in CI on `windows-latest`, `ubuntu-latest` and
`macos-14`. Sign Windows builds and notarise macOS builds before public
distribution, and publish separate artefacts per OS. No standalone artefacts
are built or committed here: the sandbox has no Tkinter or target-OS runners,
and shipping untested binaries would contradict the "test each platform"
requirement.

---

## Files added by the launcher feature

```
PlanForge/
├── PlanForgeLauncher.py        Shared OS detection, environment, logging, startup
├── PlanForgeLauncher.bat       Windows double-click entry point
├── PlanForgeLauncher.sh        Linux/macOS entry point
├── PlanForgeLauncher.command   macOS Finder entry point
├── run.bat                     Compatibility wrapper for older instructions
├── run.sh                      Compatibility wrapper for older instructions
├── run.command                 Compatibility wrapper for older instructions
├── requirements.txt            Runtime dependency manifest (no third-party deps today)
├── docs/launcher.md            This document
└── tests/test_launcher.py      Automated launcher tests
```

`bin/planforge` and `python -m planforge` continue to work unchanged for users
who already manage their own Python environment.
