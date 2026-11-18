#!/usr/bin/env bash
# verify.sh -- run the tier-4 verification against this run's bitstream.
#
#   ./verify.sh          every golden vector
#   ./verify.sh 20       the first 20, for a quick check
#
# Lives at the root of a run on the board -- ~/ai/<run>/ -- beside the bitstream/ it
# tests and above the src/ holding the host code. Shipped from
# ultra-96/scripts/ by transfer.sh; edit it there, not here.
#
# If the run arrived from Windows the executable bit will not have survived the
# copy, since NTFS has none to send. Then:  bash verify.sh
#
# There is no .bat counterpart on purpose: this one only ever runs on the
# board, and the board is Linux.

set -uo pipefail

# The run directory is wherever this script is, not wherever it was invoked
# from. verify.py works the same way -- it resolves the run from its own
# location -- so both agree no matter what the current directory is.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/src/verify.py"

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
# exec, so the exit status is verify.py's own -- 1 on a bit-exactness failure,
# which is what makes this usable from anything that checks it.
exec sudo -E python3 "$SCRIPT" "$@"
