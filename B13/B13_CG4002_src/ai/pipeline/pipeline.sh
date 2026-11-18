#!/usr/bin/env bash
# pipeline.sh — the whole AI lane end to end, archived as one named run.
#
#   ./src/pipeline.sh                     prompt for a name, build, and HLS mode
#   ./src/pipeline.sh --name sweep-w6-B   skip the name prompt
#   ./src/pipeline.sh --build E           skip the build picker
#   ./src/pipeline.sh --from hls          resume: skip training, check and export
#
# clean.sh runs first, so every run starts from nothing. The reason is the
# archive, not the build: a run that dies in HLS never overwrites bit/ or
# reports/, so without this the run folder quietly collects the *previous*
# build's bitstream and timing numbers and presents them as its own.
#
# The five stages are the five scripts in src/scripts/, in the only order that works:
#
#   1 train    train.sh    FP32 baseline, QAT width sweep, selects a width
#   2 check    check.sh    check.py: the description, and preprocess.py, vs Brevitas
#   3 export   export.sh   headers + golden vectors for the selected width
#   4 hls      hls.sh      full flow or synthesis -> packaged IP
#   5 vivado   vivado.sh   block design -> implementation -> .bit / .hwh
#
# check runs before export on purpose: it re-extracts the description itself
# and needs no headers, so putting it first means headers are never emitted
# from arithmetic that does not reproduce Brevitas. That is also why it reads
# norm_stats.json from train/checkpoints/ rather than from a run directory --
# the archive does not exist yet when it runs.
#
# Everything worth keeping is copied into out/pipeline/<name>/ at the end -- on
# failure too, so a broken run still leaves its logs and whatever it got to.
#
# make_dummy_data.py is deliberately NOT run. Regenerating the dataset would
# reshuffle the participant split and make this run incomparable with the last.
# Run it by hand when the class list or the channel list changes.

set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SRC")"
SCRIPTS="$SRC/scripts"
if [ -z "${NN_BUILD_GUARD:-}" ] && [ "${1:-}" != "--help" ] && [ "${1:-}" != "-h" ]; then
    exec bash "$SCRIPTS/build_support.sh" guard "$SRC/pipeline.sh" "$@"
fi
OUT_KIND="pipeline"
OUT_ROOT="$ROOT/out/$OUT_KIND"

RULE="============================================================"

BUILD=""
FROM="train"
NAME=""
HLS_MODE=""

usage() {
    echo "Usage: pipeline.sh [--name <name>] [--build <letter>] [--from <stage>] [--hls-mode <mode>]"
    echo
    echo "  --name    name of the run; prompted for if omitted"
    echo "  --build   HLS/Vivado directive set; picked from a list if omitted"
    echo "  --from    first stage to run: train, check, export, hls, vivado"
    echo "  --hls-mode  full or synth-export; picked after export if omitted"
    echo
    echo "The width is not an option: it is whatever the training sweep"
    echo "selected, read from src/fpga/hls/selected_width.hpp after the export."
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)    NAME="${2:-}"; shift 2 ;;
        --name=*)  NAME="${1#*=}"; shift ;;
        --build)   BUILD="${2:-}"; shift 2 ;;
        --build=*) BUILD="${1#*=}"; shift ;;
        --from)    FROM="${2:-}"; shift 2 ;;
        --from=*)  FROM="${1#*=}"; shift ;;
        --hls-mode)   HLS_MODE="${2:-}"; shift 2 ;;
        --hls-mode=*) HLS_MODE="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

case "$FROM" in
    train|check|export|hls|vivado) ;;
    *) echo "ERROR: --from must be train, check, export, hls or vivado." >&2
       exit 1 ;;
esac

# --- the run's name and its folder ------------------------------------------

if [ -z "$NAME" ]; then
    printf 'name of the run: '
    read -r NAME
fi

# A pasted name can carry a trailing CR on Windows, which would otherwise
# become part of the directory name and stay invisible in every later listing.
NAME=$(printf '%s' "$NAME" | tr -d '\r')

if [ -z "$NAME" ]; then
    echo "ERROR: a run needs a name." >&2
    exit 1
fi

# The name becomes a path, so it may not contain anything that could leave out/.
case "$NAME" in
    .|..|*[!A-Za-z0-9._-]*)
        echo "ERROR: use letters, digits, dot, dash and underscore only." >&2
        exit 1 ;;
esac

RUN="$OUT_ROOT/$NAME"
RUN_REL="out/$OUT_KIND/$NAME"

if [ -e "$RUN" ]; then
    echo "ERROR: $RUN already exists. Pick another name, or remove it first." >&2
    exit 1
fi

# The build is asked for the same way the name is, and only when the command
# line did not settle it. The list and the default come from build_config.py,
# so this script spells no letter of its own. An empty answer takes the
# default, and so does a closed stdin -- a scripted run must not stop on a
# question. resolve-build is what rejects a letter that does not exist.
if [ -z "$BUILD" ]; then
    echo
    echo "which build?"
    bash "$SCRIPTS/build_support.sh" list-builds
    printf 'build: '
    read -r BUILD || BUILD=""
fi

if ! BUILD=$(bash "$SCRIPTS/build_support.sh" resolve-build "$BUILD"); then
    exit 1
fi

LOGS="$RUN/logs"
export NN_VIVADO_LOG_DIR="$LOGS/vivado"
mkdir -p "$RUN/bitstream" "$RUN/headers" "$RUN/model" \
         "$RUN/reports/vivado" "$RUN/reports/hls" "$LOGS" || exit 1

STARTED_AT=$(date -u '+%Y-%m-%d %H:%M:%SZ')

echo
echo "run       $NAME"
echo "out       $RUN_REL"
echo "build     $BUILD"
echo "from      $FROM"
echo "started   $STARTED_AT"

# --- clean ------------------------------------------------------------------

# Only the groups at or after the resume point. --from hls must not delete the
# headers and checkpoints stage 4 is about to consume; check writes nothing of
# its own, so it cleans from export onward like export does.
case "$FROM" in
    train)        CLEAN_STAGES="train export hls vivado" ;;
    check|export) CLEAN_STAGES="export hls vivado" ;;
    hls)          CLEAN_STAGES="hls vivado" ;;
    vivado)       CLEAN_STAGES="vivado" ;;
esac

echo
echo "$RULE"
echo "  [0/5] clean"
echo "  log: logs/0-clean.log"
echo "$RULE"
echo

# Unquoted on purpose: CLEAN_STAGES is a list of arguments, not one argument.
if ! bash "$SCRIPTS/clean.sh" $CLEAN_STAGES 2>&1 | tee "$LOGS/0-clean.log"; then
    echo >&2
    echo "FAILED: the cleaner refused to run, so nothing was built." >&2
    echo "Cleanup may be partial. Inspect $RUN_REL/logs/0-clean.log." >&2
    exit 1
fi

# --- stages -----------------------------------------------------------------

STEP=0
REACHED=0
STAGES_RUN=""
FAILED_AT=""

# Stages are named in order, so the first match switches execution on and
# everything after it follows. --from is a resume, not a filter.
should_run() {
    if [ "$1" = "$FROM" ]; then
        REACHED=1
    fi

    [ "$REACHED" = "1" ]
}

run_stage() {
    label="$1"
    shift
    script="$1"
    shift

    STEP=$((STEP + 1))

    if ! should_run "$label"; then
        printf '\n--- [%d/5] %-7s skipped (--from %s)\n' "$STEP" "$label" "$FROM"
        return 0
    fi

    log="$LOGS/$STEP-$label.log"

    printf '\n%s\n' "$RULE"
    printf '  [%d/5] %s\n' "$STEP" "$label"
    printf '  log: logs/%s\n' "$STEP-$label.log"
    printf '%s\n\n' "$RULE"

    # The pipe into tee is load-bearing, not just convenient. Vitis HLS 2022.1
    # on Windows fails cosim's testbench instrumentation when its stdout is a
    # plain file handle; a pipe or a console works. Do not "simplify" this to
    # a > redirect -- that is exactly the bug pipeline.bat had.
    #
    # pipefail is set, so the pipeline's status is the script's, not tee's.
    bash "$script" "$@" 2>&1 | tee "$log"
    local rc=$?
    printf 'STAGE_EXIT_CODE %s\n' "$rc" >> "$log"
    if [ "$rc" -eq 0 ]; then
        STAGES_RUN="$STAGES_RUN $label"
        return 0
    fi

    FAILED_AT="$label"
    printf '\nFAILED at stage %s. Full output in %s/logs/%s\n' \
        "$label" "$RUN_REL" "$STEP-$label.log" >&2
    return 1
}

# The width is discovered, not chosen: emit.py writes it into
# selected_width.hpp from the checkpoint filename and nn_width.tcl reads the
# same file, so this agrees with the Tcl by construction rather than by luck.
selected_width() {
    header="$SRC/fpga/hls/selected_width.hpp"

    if [ ! -f "$header" ]; then
        return 1
    fi

    sed -n 's/.*NN_WIDTH_SELECTED[[:space:]]\{1,\}\([0-9]\{1,\}\).*/\1/p' \
        "$header" | head -n 1
}

WIDTH=""

choose_hls_mode() {
    if [ -z "$HLS_MODE" ]; then
        echo
        echo "which HLS flow?"
        echo "  1  full: C simulation, synthesis, RTL co-simulation, IP export"
        echo "  2  synth-export: synthesis and IP export only"
        printf 'HLS mode [1]: '
        read -r HLS_MODE || HLS_MODE=""
    fi
    HLS_MODE=$(printf '%s' "$HLS_MODE" | tr -d '\r')

    case "$HLS_MODE" in
        ""|1|full) HLS_MODE=full ;;
        2|synth-export) HLS_MODE=synth-export ;;
        *) echo "ERROR: HLS mode must be full or synth-export." >&2; return 1 ;;
    esac
    echo "hls mode  $HLS_MODE"
}

run_all() {
    run_stage train  "$SCRIPTS/train.sh"  || return 1
    run_stage check  "$SCRIPTS/check.sh"  || return 1
    run_stage export "$SCRIPTS/export.sh" || return 1

    WIDTH=$(selected_width) || WIDTH=""

    if [ -z "$WIDTH" ]; then
        echo "ERROR: no width in src/fpga/hls/selected_width.hpp." >&2
        echo "       Run the export before using --from hls." >&2
        FAILED_AT="width"
        return 1
    fi

    echo
    echo "width     $WIDTH (from selected_width.hpp)"

    if [ "$FROM" = "vivado" ] && [ -z "$HLS_MODE" ]; then
        HLS_MODE=full
    fi
    choose_hls_mode || { FAILED_AT="hls-mode"; return 1; }

    run_stage hls    "$SCRIPTS/hls.sh"    "$WIDTH" "$BUILD" "" "$HLS_MODE" || return 1

    # Require the packaged deliverable in addition to the completion marker.
    if [ ! -f "$SRC/fpga/hls/hls_w${WIDTH}_${BUILD}/sol/impl/ip/component.xml" ]; then
        echo >&2
        echo "ERROR: HLS reported success but packaged no IP." >&2
        echo "       Read the end of the hls log for the export_design failure." >&2
        FAILED_AT="hls"
        return 1
    fi

    run_stage vivado "$SCRIPTS/vivado.sh" "$WIDTH" "$BUILD" || return 1
}

run_all
STATUS=$?

# The width is needed to find the artefacts even when a stage failed after the
# export, so recover it here if run_all bailed before setting it.
if [ -z "$WIDTH" ]; then
    WIDTH=$(selected_width) || WIDTH=""
fi

# --- collect ----------------------------------------------------------------

MISSING=0

take() {
    from="$1"
    to="$2"

    if [ -f "$from" ]; then
        if cp -f "$from" "$to/"; then
            printf '    +  %s\n' "${from#$SRC/}"
        else
            printf '    -  %s (copy failed)\n' "$from" >&2
            MISSING=$((MISSING + 1))
        fi
    else
        printf '    -  %s (absent)\n' "${from#$SRC/}"
        MISSING=$((MISSING + 1))
    fi
}

printf '\n%s\n' "$RULE"
printf '  collecting into %s\n' "$RUN_REL"
printf '%s\n\n' "$RULE"

if [ -n "$WIDTH" ]; then
    STEM="nn_w${WIDTH}_${BUILD}"
    HLS_PROJECT="$SRC/fpga/hls/hls_w${WIDTH}_${BUILD}/sol"

    # Everything the Ultra96 needs and nothing it does not. The .bit and .hwh
    # must keep the same basename and sit side by side, which is how PYNQ's
    # Overlay() finds the second from the first.
    take "$SRC/fpga/vivado/bit/$STEM.bit" "$RUN/bitstream"
    take "$SRC/fpga/vivado/bit/$STEM.hwh" "$RUN/bitstream"
    # The PS applies this standardisation before every DMA. Without it the
    # board feeds the accelerator raw IMU units it was never trained on.
    take "$SRC/train/checkpoints/norm_stats.json" "$RUN/bitstream"
    # Class order, window, channels and the accumulator width: the host's half
    # of the interface contract, in the one file that is machine readable.
    take "$SRC/export/build/description_w$WIDTH.json" "$RUN/bitstream"
    # The golden header is C initialisers, which the board cannot read. Same
    # vectors, same run, in the form verify.py loads.
    take "$SRC/fpga/hls/golden_w$WIDTH.npz" "$RUN/bitstream"

    take "$SRC/fpga/hls/params_w$WIDTH.hpp"  "$RUN/headers"
    take "$SRC/fpga/hls/weights_w$WIDTH.hpp" "$RUN/headers"
    take "$SRC/fpga/hls/golden_w$WIDTH.h"    "$RUN/headers"
    take "$SRC/fpga/hls/selected_width.hpp"  "$RUN/headers"

    take "$SRC/train/qmodel/qacnn_w$WIDTH.pt" "$RUN/model"

    # Post-implementation, which is what section 5.6 quotes -- not the HLS
    # estimates, which are in the csynth report below for the comparison.
    take "$SRC/fpga/vivado/reports/${STEM}_timing.rpt"      "$RUN/reports/vivado"
    take "$SRC/fpga/vivado/reports/${STEM}_utilization.rpt" "$RUN/reports/vivado"
    take "$SRC/fpga/vivado/reports/${STEM}_power.rpt"       "$RUN/reports/vivado"

    take "$HLS_PROJECT/syn/report/nn_infer_csynth.rpt" "$RUN/reports/hls"
    if [ "$HLS_MODE" = "synth-export" ]; then
        echo "    -  HLS simulation reports skipped (synth-export mode)"
    else
        take "$HLS_PROJECT/sim/report/nn_infer_cosim.rpt"  "$RUN/reports/hls"
        take "$HLS_PROJECT/sim/report/verilog/lat.rpt"     "$RUN/reports/hls"
        take "$HLS_PROJECT/csim/report/nn_infer_csim.log"  "$RUN/reports/hls"
    fi
else
    echo "    no width resolved, so nothing named for one could be collected"
    MISSING=$((MISSING + 1))
fi

take "$SRC/train/plots/training_loss.png" "$RUN/reports"

# One confusion matrix per trained model: the FP32 baseline and every width the
# sweep tried. Globbed, because the widths belong to train/config.py. An
# unmatched glob stays literal, so a run that wrote none reports it absent.
for plot in "$SRC"/train/plots/confusion_*.png; do
    take "$plot" "$RUN/reports"
done

# --- manifest ---------------------------------------------------------------

FINISHED_AT=$(date -u '+%Y-%m-%d %H:%M:%SZ')

GIT_REV=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) || GIT_REV="unknown"

if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    GIT_REV="$GIT_REV (dirty)"
fi

if [ "$STATUS" -eq 0 ] && [ "$MISSING" -eq 0 ]; then
    RESULT="OK"
elif [ "$STATUS" -eq 0 ]; then
    RESULT="FAILED: missing or unarchived artefacts"
else
    RESULT="FAILED at ${FAILED_AT:-unknown}"
fi

{
    echo "run          $NAME"
    echo "status       $RESULT"
    echo "started      $STARTED_AT"
    echo "finished     $FINISHED_AT"
    echo "host         $(hostname 2>/dev/null || echo unknown)"
    echo "git          $GIT_REV"
    echo
    echo "width        ${WIDTH:-unresolved}"
    echo "build        $BUILD"
    echo "from         $FROM"
    echo "hls mode     ${HLS_MODE:-not selected}"
    echo "stages run  ${STAGES_RUN:- none}"
    echo "absent       $MISSING artefact(s)"
    echo
    echo "bitstream/   .bit + .hwh + norm_stats.json + description json + golden npz."
    echo "             Everything needed to run the model on the Ultra96."
    echo "headers/     the generated PL interface, exactly as this run built it."
    echo "model/       the quantized checkpoint everything else derives from."
    echo "reports/     vivado post-implementation and HLS estimates; simulation"
    echo "             reports are included when HLS mode is full. The"
    echo "             loss curve and a confusion matrix per trained model."
    echo "logs/        stdout of every stage. The accuracy numbers, the layer"
    echo "             table and the accumulator peaks live only here."
} > "$RUN/manifest.txt"

echo
cat "$RUN/manifest.txt"

if [ "$STATUS" -ne 0 ]; then
    echo
    echo "Run FAILED at stage ${FAILED_AT:-unknown}. Partial results in $RUN_REL" >&2
    exit "$STATUS"
fi

if [ "$MISSING" -ne 0 ]; then
    echo
    echo "Run finished, but $MISSING expected artefact(s) were absent." >&2
    exit 1
fi

echo
echo "Run complete. $RUN_REL"
