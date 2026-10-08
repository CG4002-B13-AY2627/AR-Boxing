#!/usr/bin/env bash
# latency.sh -- the whole latency commitment, measured, in one table.
#
#   ./latency.sh          the full run
#   ./latency.sh 200      fewer iterations per half, for a quick look
#
# Runs both halves of the critical path in one sitting -- the PS work that
# budget.py owns and the accelerator round trip that bench.py owns -- and adds
# them up against the 50 ms we committed to, from punch peak to label emitted.
#
# This is the only entry point for either half's number: neither is worth
# quoting without the other, so neither has a script of its own.
#
# Prints which script owns each row, the bound it is held to, and whether it
# fits. The window-completion row is structural rather than measured: it is one
# stride, derived from the same constant the buffer applies.
#
# Lives at the root of a run on the board -- ~/ai/<run>/ -- beside bitstream/.
# Shipped from ultra-96/scripts/ by transfer.sh; edit it there, not here.
#
# If the run arrived from Windows the executable bit will not have survived the
# copy, since NTFS has none to send. Then:  bash latency.sh

set -uo pipefail

# The run directory is wherever this script is, not wherever it was invoked
# from -- the Python resolves the run the same way.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/src/latency.py"

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT is missing." >&2
    echo "       The build arrived but the host code did not. Re-run" >&2
    echo "       transfer.sh from the laptop." >&2
    exit 1
fi

# Loading an overlay needs root, and PYNQ lives in a virtualenv at
# /usr/local/share/pynq-venv that a plain sudo would drop: -E keeps the
# environment pointing at it.
#
# exec, so the exit status is latency.py's own -- 1 when the commitment is
# missed, which is what makes this usable from anything that checks it.
exec sudo -E python3 "$SCRIPT" "$@"
