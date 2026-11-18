#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src_dir="$(dirname "$script_dir")"
export NN_BUILD_BASH="$BASH"
if command -v cygpath >/dev/null 2>&1; then
    NN_BUILD_BASH="$(cygpath -w "$BASH")"
    export NN_BUILD_BASH
fi
for candidate in "$src_dir/.venv/bin/python" "$src_dir/.venv/Scripts/python.exe" python3 python py; do
    if "$candidate" -c 'import sys' >/dev/null 2>&1; then
        exec "$candidate" "$script_dir/build_support.py" "$@"
    fi
done
echo 'ERROR: Python 3 is required to run the build helpers.' >&2
exit 1
