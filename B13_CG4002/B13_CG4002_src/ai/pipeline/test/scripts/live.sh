#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$(dirname "$TEST_DIR")/.venv"
REQUIREMENTS="$TEST_DIR/requirements.txt"
STAMP="$VENV_DIR/.test-requirements.sha256"

PYTHON="$VENV_DIR/bin/python"
[ -x "$PYTHON" ] || PYTHON="$VENV_DIR/Scripts/python.exe"
if [ ! -x "$PYTHON" ]; then
    echo "ERROR: no virtual environment in $VENV_DIR. Run src/scripts/train first." >&2
    exit 1
fi

if command -v shasum >/dev/null 2>&1; then
    current_hash="$(shasum -a 256 "$REQUIREMENTS" | awk '{print $1}')"
else
    current_hash="$(sha256sum "$REQUIREMENTS" | awk '{print $1}')"
fi

stored_hash=""
if [ -f "$STAMP" ]; then
    stored_hash="$(cat "$STAMP")"
fi

if [ "$current_hash" != "$stored_hash" ]; then
    echo "Installing $(basename "$REQUIREMENTS")"
    "$PYTHON" -m pip install -r "$REQUIREMENTS"
    printf '%s\n' "$current_hash" > "$STAMP"
fi

exec "$PYTHON" "$TEST_DIR/live.py" "$@"
