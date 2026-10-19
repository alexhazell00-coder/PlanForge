#!/bin/sh
# Compatibility wrapper. The canonical Linux/macOS launcher is
# PlanForgeLauncher.sh; this file is kept so older instructions keep working.

set -u
case "$0" in
    */*) script_dir=${0%/*} ;;
    *)   script_dir=. ;;
esac
if ! script_dir=$(CDPATH= cd -- "$script_dir" 2>/dev/null && pwd -P); then
    echo "PlanForge: could not determine the installation directory." >&2
    exit 1
fi
exec "$script_dir/PlanForgeLauncher.sh" "$@"
