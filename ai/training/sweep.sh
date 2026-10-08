#!/usr/bin/env bash
# sweep.sh — every fixed-point width in the training sweep, under one run name.
#
#   ./src/sweep.sh                    prompt for a name, sweep every width
#   ./src/sweep.sh --name mark-7      skip the prompt
#   ./src/sweep.sh --build E          sweep the widths against a directive set
#   ./src/sweep.sh --from export      resume: reuse the trained checkpoints
#
# pipeline.sh builds the one width training selected. all.sh builds one width
# against every directive set. This builds every width against one directive
# set, into out/sweep/<name>/, and answers the question neither of the others
# does: what a bit of precision actually costs in silicon, and where the
# network finally breaks.
#
# No bitstream is archived and none is meant to be. A sweep is evidence for
# section 5.6, not something to load: the width that ships comes from
# pipeline.sh, which archives one. transfer.sh will say so if asked.
#
# Training already sweeps the widths and leaves one checkpoint per entry in
# train/checkpoints/, so this adds only the hardware half -- check, export,
# hls and vivado per width, driven through CHECKPOINT_OVERRIDE.
#
# The selected width is built first and without an override, because it is the
# export that writes selected_width.hpp and params.hpp includes that file
# unconditionally. An override export deliberately does not write it: a sweep
# entry is not a change of selection.
#
# The work is in scripts/sweep.py, beside the stage wrappers it drives and the
# build_config.py it takes its paths from. Five widths by four stages is the
# same procedure on both platforms, and writing it twice in two shells is how
# the two drift. This file is the entry point, and sits with pipeline.sh and
# all.sh because that is where you look for something to run.

set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$SRC/scripts"

if [ -z "${NN_BUILD_GUARD:-}" ] && [ "${1:-}" != "--help" ] && [ "${1:-}" != "-h" ]; then
    exec bash "$SCRIPTS/build_support.sh" guard "$SRC/sweep.sh" "$@"
fi

# scripts/sweep.py is standard library only, so any working interpreter will do.
# src/.venv is preferred because a full run has certainly created it, and
# because the stages it calls use it too.
#
# Each candidate is made to execute something before it is accepted. Windows
# ships a `python` on PATH that is not an interpreter at all but an App
# Execution Alias, and it answers `command -v` cheerfully before printing a
# Microsoft Store advertisement instead of running the script.
find_python() {
    local candidate
    for candidate in "$SRC/.venv/bin/python" "$SRC/.venv/Scripts/python.exe" \
                     python3 python py
    do
        if "$candidate" -c "import sys" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done

    return 1
}

if ! PYTHON=$(find_python); then
    echo "ERROR: Python 3 is required to run the width sweep." >&2
    exit 1
fi

exec "$PYTHON" "$SRC/scripts/sweep.py" "$@"
