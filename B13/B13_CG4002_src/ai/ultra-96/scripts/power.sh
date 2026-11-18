#!/usr/bin/env bash
# power.sh -- measure what the board draws, idle and inferencing.
#
#   ./power.sh             all three regimes, about two minutes
#   ./power.sh idle        one regime
#   ./power.sh continuous
#   ./power.sh duty
#
# Reads the board's own INA226 rails through PYNQ while the accelerator is
# idle, saturated, and paced at the real stride. The deltas against idle are
# the marginal cost of inference; the totals are what the wearable draws.
#
# This is the board half of the power evaluation, and as of 2026-09-21 the
# only half. Vivado's own estimate is vectorless and reads ~3x this rail;
# annotating it with recorded switching activity does not work, because
# synthesis does not preserve HLS's net names. Quote both, and say why.
#
# Lives at the root of a run on the board -- ~/ai/<run>/ -- beside bitstream/.
# Shipped from ultra-96/scripts/ by transfer.sh; edit it there, not here.
#
# If the run arrived from Windows the executable bit will not have survived the
# copy, since NTFS has none to send. Then:  bash power.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/src/measure_power.py"

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT is missing." >&2
    echo "       The build arrived but the host code did not. Re-run" >&2
    echo "       transfer.sh from the laptop." >&2
    exit 1
fi

# Loading an overlay needs root, and so does reading the I2C power monitors.
# -E keeps the environment that points at PYNQ's virtualenv.
exec sudo -E python3 "$SCRIPT" "$@"
