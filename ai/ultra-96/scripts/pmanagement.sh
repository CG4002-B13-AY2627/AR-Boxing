#!/usr/bin/env bash
# pmanagement.sh -- demo heading 7: measure every power configuration this
# board exposes, pick one, and leave the board in it.
#
#   ./pmanagement.sh            every combination of cores x CPU clock x PL
#                               clock, then the radios; a picker after each
#   ./pmanagement.sh --quick    the same points, two recording blocks each
#   ./pmanagement.sh apply      pick from the last sweep without re-measuring
#   ./pmanagement.sh restore    put everything back
#
# Every point replays the whole golden set and is held to latency.sh's bounds
# before it is eligible, and writes pmanagement/<timestamp>/report.md beside
# this script.
#
# power.sh answers "what does the board draw". This answers "what can we do
# about it", which is a different question and a different heading.
#
# Nothing is left applied unless it is picked. Every knob and radio is
# snapshotted first and put back however the run ends -- normally, on an
# error, on Ctrl-C, on a dropped session. pmanagement/restore.sh is written
# before the first change as the net for the case where the process dies
# without running anything at all.
#
# Lives at the root of a run on the board -- ~/ai/<run>/ -- beside bitstream/.
# Shipped from ultra-96/scripts/ by transfer.sh; edit it there, not here.
#
# If the run arrived from Windows the executable bit will not have survived the
# copy, since NTFS has none to send. Then:  bash pmanagement.sh
#
# There is no .bat counterpart on purpose: this one only ever runs on the
# board, and the board is Linux.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/src/pmanagement.py"

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT is missing." >&2
    echo "       The build arrived but the host code did not. Re-run" >&2
    echo "       transfer.sh from the laptop." >&2
    exit 1
fi

# Loading an overlay needs root, and so do the power monitors, the cpufreq
# interface, the per-core online files and the radio controls -- everything
# this turns. -E keeps the environment that points at PYNQ's virtualenv, and
# SSH_CONNECTION, which is how the radios step knows which link carries this
# session.
exec sudo -E python3 "$SCRIPT" "$@"
