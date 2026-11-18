#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cg4002_python="${CG4002_PYTHON:-python3}"

cd "${repo_root}"

if [[ ! -x .venv/bin/python ]]; then
    "${cg4002_python}" -m venv .venv
fi

.venv/bin/python -m pip install -r tools/requirements.txt
.venv/bin/python tools/validate_contracts.py

printf 'Python environment is ready at %s/.venv\n' "${repo_root}"
