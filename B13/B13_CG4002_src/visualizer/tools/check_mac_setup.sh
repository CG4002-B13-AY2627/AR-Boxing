#!/usr/bin/env bash

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
unity_version_file="${repo_root}/VisualizerApp/ProjectSettings/ProjectVersion.txt"
expected_unity="$(awk '/^m_EditorVersion:/{print $2}' "${unity_version_file}")"
unity_app="/Applications/Unity/Hub/Editor/${expected_unity}/Unity.app"
failure_count=0

pass() {
    printf 'PASS  %s\n' "$1"
}

fail() {
    printf 'FAIL  %s\n' "$1"
    failure_count=$((failure_count + 1))
}

printf 'CG4002 Mac setup check\n'
printf 'Repository: %s\n\n' "${repo_root}"

if [[ "$(uname -m)" == "arm64" ]]; then
    pass "Apple-silicon host ($(uname -m))"
else
    fail "Expected Apple silicon; found $(uname -m)"
fi

if [[ -d /Applications/Xcode.app ]] && xcode-select -p >/dev/null 2>&1; then
    pass "Xcode installed and command-line tools selected"
    xcodebuild -version | sed 's/^/      /'
else
    fail "Xcode or its selected developer directory is missing"
fi

if [[ -d "${unity_app}" ]]; then
    pass "Unity ${expected_unity} installed"
else
    fail "Unity ${expected_unity} is missing from Unity Hub"
fi

if command -v python3 >/dev/null 2>&1; then
    pass "Python available ($(python3 --version 2>&1))"
else
    fail "python3 is unavailable"
fi

if command -v git >/dev/null 2>&1; then
    pass "Git available ($(git --version))"
else
    fail "Git is unavailable"
fi

cd "${repo_root}"
printf '\nGit state\n'
git status --short --branch

if [[ "$(git branch --show-current)" == "OpponentTracker" ]]; then
    pass "Active branch is OpponentTracker"
else
    fail "Expected OpponentTracker; found $(git branch --show-current)"
fi

if [[ -f docs/macbook-development-handoff.md ]]; then
    pass "Handoff is present on the current branch"
elif git cat-file -e main:docs/macbook-development-handoff.md 2>/dev/null; then
    pass "Handoff is available on main (read with git show main:docs/macbook-development-handoff.md)"
else
    fail "MacBook handoff document is unavailable"
fi

if [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import jsonschema, websockets' >/dev/null 2>&1; then
    pass "Project Python environment is ready"
else
    fail "Project Python environment is not ready; run ./tools/bootstrap_python_env.sh"
fi

if (( failure_count > 0 )); then
    printf '\nSetup check completed with %d failure(s).\n' "${failure_count}"
    exit 1
fi

printf '\nSetup check passed.\n'
