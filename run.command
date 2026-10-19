#!/bin/sh
# Compatibility wrapper. The canonical macOS entry point is
# PlanForgeLauncher.command; this file is kept so older instructions keep
# working.

set -u
case "$0" in
    */*) command_dir=${0%/*} ;;
    *)   command_dir=. ;;
esac
if ! command_dir=$(CDPATH= cd -- "$command_dir" 2>/dev/null && pwd -P); then
    echo "PlanForge: could not determine the installation directory." >&2
    exit 1
fi
exec "$command_dir/PlanForgeLauncher.command" "$@"
