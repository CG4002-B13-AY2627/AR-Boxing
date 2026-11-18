#!/usr/bin/env bash
# test.sh -- the whole PS path end to end, on dummy data or on a shipped segment.
#
#   ./test.sh          four windows, or the whole segment
#   ./test.sh 10       ten, when there is no segment
#
# A sample stream through WindowBuffer, Preprocess, NNDriver and Postprocess to
# action events. It checks that the four join up, and holds the buffer to its
# two claims -- every window equals its own slice of the stream, and carries
# the timestamp of its last sample.
#
# With no sample/ beside this script the input is random, so it cannot check
# the labels. That is verify.sh's job. With sample/segment.txt -- sent from the
# laptop by individual-subcomponent-test/scripts/sample -- it prints every
# window's logits and predicted class as a table and saves it as
# sample/hardware_logits.txt, to compare against the laptop's software run.
#
# Lives at the root of a run on the board -- ~/ai/<run>/ -- beside bitstream/.
# Shipped from ultra-96/scripts/ by transfer.sh; edit it there, not here.
#
# If the run arrived from Windows the executable bit will not have survived the
# copy, since NTFS has none to send. Then:  bash test.sh

set -uo pipefail

# The run directory is wherever this script is, not wherever it was invoked
# from -- the Python resolves the run the same way.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/src/test.py"

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT is missing." >&2
    echo "       The build arrived but the host code did not. Re-run" >&2
    echo "       transfer.sh from the laptop." >&2
    exit 1
fi

# Loading an overlay needs root, and PYNQ lives in a virtualenv at
# /usr/local/share/pynq-venv that a plain sudo would drop: -E keeps the
# environment pointing at it.
exec sudo -E python3 "$SCRIPT" "$@"
