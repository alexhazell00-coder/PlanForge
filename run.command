#!/bin/sh
# Double-clickable macOS entry point.
#
# Finder runs .command files in Terminal; this wrapper delegates to run.sh so
# that Linux, macOS and direct launcher.py invocation share one code path.
# You can also run ./run.command from a terminal.

set -u

case "$0" in
    */*) command_dir=${0%/*} ;;
    *)   command_dir=. ;;
esac
if ! command_dir=$(CDPATH= cd -- "$command_dir" 2>/dev/null && pwd -P); then
    echo "PlanForge: could not determine the installation directory." >&2
    exit 1
fi

exec "$command_dir/run.sh" "$@"
