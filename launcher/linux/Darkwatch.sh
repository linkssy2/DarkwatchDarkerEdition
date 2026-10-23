#!/bin/sh
set -eu
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.9 or newer is required. Install it using your Linux distribution.' >&2
    exit 1
fi
base=$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parent)' "$0")
exec python3 "$base/linux/launcher.py" "$@"
