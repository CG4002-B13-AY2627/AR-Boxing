#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$(dirname "$SCRIPT_DIR")/pipeline/.venv"
PYTHON="$VENV_DIR/bin/python"
[ -x "$PYTHON" ] || PYTHON="$VENV_DIR/Scripts/python.exe"

if [ ! -x "$PYTHON" ]; then
    echo "ERROR: no environment in $VENV_DIR. Run pipeline/scripts/train.sh once first." >&2
    exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/convert.py" "$@"
