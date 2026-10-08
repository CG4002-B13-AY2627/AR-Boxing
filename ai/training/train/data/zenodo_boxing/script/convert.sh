#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PYTHON="$SRC_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$SRC_DIR/.venv/Scripts/python.exe"

if [ ! -x "$PYTHON" ]; then
    echo "ERROR: no environment in $SRC_DIR/.venv. Run src/scripts/train.sh once first." >&2
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$PYTHON" convert.py "$@"
