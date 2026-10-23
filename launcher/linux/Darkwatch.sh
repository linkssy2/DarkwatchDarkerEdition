#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.9 or newer is required. Install it using your Linux distribution.' >&2
    exit 1
fi
exec python3 "$base/linux/launcher.py" "$@"
