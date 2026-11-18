#!/usr/bin/env bash
# Checked cleanup shared with clean.bat.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$script_dir/build_support.sh" clean "$@"
