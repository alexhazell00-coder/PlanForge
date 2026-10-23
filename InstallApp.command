#!/bin/sh
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec /bin/sh "$ROOT_DIR/InstallApp.sh" "$@"
