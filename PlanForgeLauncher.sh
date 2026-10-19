#!/bin/sh
# PlanForge launcher for Linux and macOS.
#
# This file only locates a Python interpreter and delegates to PlanForgeLauncher.py.
# Environment creation, dependency installation, logging and startup logic
# all live in PlanForgeLauncher.py, so fixes there benefit every platform.
#
# Usage:
#   ./PlanForgeLauncher.sh                 start the desktop application
#   ./PlanForgeLauncher.sh --check         check the environment without changing it
#   ./PlanForgeLauncher.sh my_project.pfp  open a project when the window starts
#   ./PlanForgeLauncher.sh --import-file schedule.xml --export-file schedule.gan

set -u

# Resolve the installation directory even when started from elsewhere or via
# a symlink-free path containing spaces.  Only shell builtins are required.
case "$0" in
    */*) script_dir=${0%/*} ;;
    *)   script_dir=. ;;
esac
if ! script_dir=$(CDPATH= cd -- "$script_dir" 2>/dev/null && pwd -P); then
    echo "PlanForge: could not determine the installation directory." >&2
    exit 1
fi

system_name=$(uname -s 2>/dev/null || echo unknown)
case "$system_name" in
    Linux|Darwin)
        ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT*)
        echo "PlanForge: PlanForgeLauncher.sh is for Linux and macOS." >&2
        echo "On Windows, double-click PlanForgeLauncher.bat instead." >&2
        exit 1
        ;;
    *)
        echo "PlanForge: PlanForgeLauncher.sh supports Linux and macOS (detected: $system_name)." >&2
        echo "On other systems, use PlanForgeLauncher.py and see docs/launcher.md." >&2
        exit 1
        ;;
esac

python_command=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python_command=$candidate
        break
    fi
done

if [ -z "$python_command" ]; then
    echo "PlanForge needs Python 3.10 or newer, but no Python interpreter was found." >&2
    echo "" >&2
    case "$system_name" in
        Darwin)
            echo "Install Python from https://www.python.org/downloads/macos/" >&2
            echo "(the python.org installer includes Tkinter), or run:" >&2
            echo "  brew install python" >&2
            ;;
        *)
            echo "Install it with your distribution's package manager, for example:" >&2
            echo "  Debian/Ubuntu: sudo apt install python3 python3-venv python3-tk" >&2
            echo "  Arch Linux:    sudo pacman -S python tk" >&2
            echo "  Fedora:        sudo dnf install python3 python3-tkinter" >&2
            ;;
    esac
    echo "" >&2
    echo "Then run this file again." >&2
    exit 127
fi

exec "$python_command" "$script_dir/PlanForgeLauncher.py" "$@"
