#!/usr/bin/env bash
# all.sh — every HLS directive set, A through D, under one run name.
#
#   ./src/all.sh                     prompt for a name, build A B C D
#   ./src/all.sh --name mark-5       skip the prompt
#   ./src/all.sh --from hls          resume: skip training, check and export
#
# pipeline.sh builds one directive set. This builds all four and compares them,
# which is a different job with a different shape, so it is a different script:
# pipeline.sh is the one in daily use and the one that feeds the board, and it
# is left exactly as it is.
#
# Why all four. run_hls.tcl's builds A–D differ in directives only, never in
# source, so any difference between them was caused by a pragma and nothing
# else. That is what makes the comparison worth making — and the comparison is
# what answers "describe and outline the optimizations implemented" in demo
# heading 6, and what §5.6 selects a build with. Four separate runs would
# scatter the numbers across four directories to be compared by hand.
#
#   A   no directives — the baseline the other three are an optimisation of
#   B   pipeline the two convolution time-loops
#   C   B + unroll the input-channel loops
#   D   C + cyclic array partition on a1/p1
#
# Resource/timing failures are comparison results. Attempt every variant,
# retain their reports, then return nonzero if any build or summary failed.
#
# The layout differs from pipeline.sh's, because four builds cannot share one
# reports/ directory and out/all/<run>/bitstream/ may hold exactly one .bit
# (transfer.sh aborts on two):
#
#   out/all/<name>/
#   ├── manifest.txt          the run, plus a per-build result block
#   ├── summary/summary.md    the comparison table — the point of the exercise
#   ├── bitstream/            the deploy build's .bit/.hwh + the 3 shared files
#   ├── headers/  model/      shared: one export feeds all four builds
#   ├── reports/              training_loss.png, confusion_*.png
#   ├── logs/                 0-clean 1-train 2-check 3-export, and the summary
#   └── builds/<X>/           status.txt, logs/, reports/hls/, reports/vivado/
#
# So transfer.sh and transfer.bat need no changes: bitstream/ looks exactly as
# it does after a pipeline.sh run. Builds B–D's bitstreams are deliberately not
# archived — out/ is git-tracked with no LFS, and every number the report
# quotes comes from the reports, not from an overlay nobody will load. They
# survive in src/fpga/vivado/bit/ until the next clean.
#
# Cosim is 65 % of the HLS stage and its cost tracks simulated cycles, so only
# the build that goes to the board pays for it in full; the rest run
# QUICK_COSIM vectors. The achieved II — the number this comparison is actually
# about — comes from csynth, not from cosim. What the short run gives up is
# verification depth, which is why the summary carries a vector-count row.

set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SRC")"
SCRIPTS="$SRC/scripts"
if [ -z "${NN_BUILD_GUARD:-}" ] && [ "${1:-}" != "--help" ] && [ "${1:-}" != "-h" ]; then
    exec bash "$SCRIPTS/build_support.sh" guard "$SRC/all.sh" "$@"
fi
OUT_KIND="all"
OUT_ROOT="$ROOT/out/$OUT_KIND"

RULE="============================================================"

# Canonical order, always. Not an option: the whole point of this script is
# that it runs all four, and a fixed order keeps two runs' logs diffable.
BUILDS="A B C D"

# Vectors the non-deploy builds co-simulate. Enough to prove the RTL runs and
# to measure its real latency; not enough to call it verified.
QUICK_COSIM=5

FROM="train"
NAME=""

usage() {
    echo "Usage: all.sh [--name <name>] [--from <stage>]"
    echo
    echo "  --name    name of the run; prompted for if omitted"
    echo "  --from    first stage to run: train, check, export, hls, vivado"
    echo
    echo "Builds A, B, C and D, in that order, always. Use pipeline.sh to"
    echo "build one. The width is not an option either: it is whatever the"
    echo "training sweep selected, read from src/fpga/hls/selected_width.hpp."
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)    NAME="${2:-}"; shift 2 ;;
        --name=*)  NAME="${1#*=}"; shift ;;
        --from)    FROM="${2:-}"; shift 2 ;;
        --from=*)  FROM="${1#*=}"; shift ;;
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

LOGS="$RUN/logs"
mkdir -p "$RUN/bitstream" "$RUN/headers" "$RUN/model" "$RUN/reports" \
         "$RUN/summary" "$LOGS"

NBUILDS=0
for build in $BUILDS; do
    mkdir -p "$RUN/builds/$build/logs" \
             "$RUN/builds/$build/reports/hls" \
             "$RUN/builds/$build/reports/vivado"
    NBUILDS=$((NBUILDS + 1))
done

# The first build in the list is the one that gets a full co-simulation, and
# the one deploy falls to first. Known before anything runs, so the decision
# never depends on a result.
FULL_COSIM_BUILD="${BUILDS%% *}"

# train, check, export + hls and vivado per build + the summary.
TOTAL=$((3 + 2 * NBUILDS + 1))

STARTED_AT=$(date -u '+%Y-%m-%d %H:%M:%SZ')
STARTED_EPOCH=$(date '+%s')

echo
echo "run       $NAME"
echo "out       $RUN_REL"
echo "builds    $BUILDS"
echo "cosim     full on $FULL_COSIM_BUILD, $QUICK_COSIM vectors on the rest"
echo "from      $FROM"
echo "started   $STARTED_AT"

# --- clean ------------------------------------------------------------------

# Once, before every build. clean.sh's globs are build-blind — hls_w*_* and
# vivado_w*_* — so one clean covers all four, and the four builds that follow
# write disjoint names and cannot tread on each other.
#
# Only the groups at or after the resume point. --from hls must not delete the
# headers and checkpoints the HLS stage is about to consume; check writes
# nothing of its own, so it cleans from export onward like export does.
case "$FROM" in
    train)        CLEAN_STAGES="train export hls vivado" ;;
    check|export) CLEAN_STAGES="export hls vivado" ;;
    hls)          CLEAN_STAGES="hls vivado" ;;
    vivado)       CLEAN_STAGES="vivado" ;;
esac

echo
echo "$RULE"
echo "  [0/$TOTAL] clean"
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
STATUS=0
STAGES_RUN=""
FAILED_AT=""
LAST_RC=0
WIDTH=""

# --from is a resume, not a filter: everything from that stage onward runs.
# Expressed as a rank and tested freshly on every call, never as a latch the
# first match switches on — with four builds a latch set by build A's hls stays
# set, and B, C and D then run an hls that --from vivado asked to skip.
rank() {
    case "$1" in
        train)  echo 1 ;;
        check)  echo 2 ;;
        export) echo 3 ;;
        hls)    echo 4 ;;
        vivado) echo 5 ;;
        *)      echo 99 ;;
    esac
}

FROM_RANK=$(rank "$FROM")

should_run() {
    [ "$(rank "$1")" -ge "$FROM_RANK" ]
}

duration() {
    total="$1"
    printf '%02dh %02dm %02ds' \
        $((total / 3600)) $(((total % 3600) / 60)) $((total % 60))
}

# run_stage <label> <log dir> <log name> <tag> <script> [args...]
#
# Sets LAST_RC to the exit code, or to "skipped". Returns non-zero on failure
# but never decides what that means: a shared stage failing ends the run, a
# build's stage failing is a result the next build follows.
run_stage() {
    local label="$1" logdir="$2" logname="$3" tag="$4"
    shift 4
    local script="$1"
    shift

    STEP=$((STEP + 1))

    local shown="$label"
    if [ -n "$tag" ]; then
        shown="$label $tag"
    fi

    if ! should_run "$label"; then
        printf '\n--- [%d/%d] %-12s skipped (--from %s)\n' \
            "$STEP" "$TOTAL" "$shown" "$FROM"
        LAST_RC="skipped"
        return 0
    fi

    local log="$logdir/$logname"

    printf '\n%s\n' "$RULE"
    printf '  [%d/%d] %s\n' "$STEP" "$TOTAL" "$shown"
    printf '  log: %s\n' "${log#$RUN/}"
    printf '%s\n\n' "$RULE"

    # The pipe into tee is load-bearing, not just convenient. Vitis HLS 2022.1
    # on Windows fails cosim's testbench instrumentation when its stdout is a
    # plain file handle; a pipe or a console works. Do not "simplify" this to
    # a > redirect -- that is exactly the bug pipeline.bat had.
    #
    # pipefail is set, so the pipeline's status is the script's, not tee's.
    bash "$script" "$@" 2>&1 | tee "$log"
    LAST_RC=$?
    printf 'STAGE_EXIT_CODE %s\n' "$LAST_RC" >> "$log"

    if [ "$LAST_RC" -eq 0 ]; then
        STAGES_RUN="$STAGES_RUN $shown"
        return 0
    fi

    printf '\n%s exited %s. Full output in %s/%s\n' \
        "$shown" "$LAST_RC" "$RUN_REL" "${log#$RUN/}" >&2
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

# What a full co-simulation actually is, read off the generated header rather
# than restated here -- golden.py owns the number and may change it.
full_cosim_vectors() {
    header="$SRC/fpga/hls/golden_w${WIDTH}.h"

    if [ ! -f "$header" ]; then
        echo "all"
        return 0
    fi

    sed -n 's/.*GOLDEN_COSIM_N[[:space:]]\{1,\}\([0-9]\{1,\}\).*/\1/p' \
        "$header" | head -n 1
}

# --- collecting -------------------------------------------------------------

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

# Zero matches is not a failure here: which submodule reports exist depends on
# which loops the build pipelined, and that is one of the things being measured.
take_glob() {
    pattern="$1"
    to="$2"
    found=0

    while IFS= read -r path; do
        [ -f "$path" ] || continue
        cp -f "$path" "$to/" || MISSING=$((MISSING + 1))
        found=$((found + 1))
    done < <(compgen -G "$pattern")

    printf '    +  %d file(s) matching %s\n' "$found" "${pattern#$SRC/}"
}

# collect_build <letter>
#
# Runs whatever the build's outcome, because a timing-failed build still wrote
# its Vivado reports and that negative slack is evidence §5.6 wants. Only a
# build that failed *placement* wrote none, and that absence is its own result.
collect_build() {
    b="$1"
    bdir="$RUN/builds/$b"
    stem="nn_w${WIDTH}_${b}"
    project="$SRC/fpga/hls/hls_w${WIDTH}_${b}/sol"

    printf '\n  build %s\n' "$b"

    # Post-implementation, which is what §5.6 quotes -- not the HLS estimates.
    take "$SRC/fpga/vivado/reports/${stem}_timing.rpt"      "$bdir/reports/vivado"
    take "$SRC/fpga/vivado/reports/${stem}_utilization.rpt" "$bdir/reports/vivado"
    take "$SRC/fpga/vivado/reports/${stem}_power.rpt"       "$bdir/reports/vivado"

    # sol_data.json first: it is the one structured file holding every module,
    # and nn_infer_csynth.rpt is top-function only. The moment a build
    # pipelines a loop, that loop moves into a submodule report -- so the
    # achieved II, the entire point of this run, leaves the top-level file.
    take "$project/sol_data.json" "$bdir/reports/hls"
    # What Vitis actually applied to this solution, rather than what the Tcl
    # reads today. It survives even a build that never reached synthesis.
    take "$project/sol.directive" "$bdir/reports/hls"

    take "$project/syn/report/csynth.rpt"          "$bdir/reports/hls"
    take "$project/syn/report/nn_infer_csynth.rpt" "$bdir/reports/hls"
    take "$project/syn/report/nn_infer_csynth.xml" "$bdir/reports/hls"
    take_glob "$project/syn/report/nn_infer_Pipeline_*_csynth.xml" \
              "$bdir/reports/hls"

    take "$project/sim/report/nn_infer_cosim.rpt" "$bdir/reports/hls"
    take "$project/sim/report/verilog/lat.rpt"    "$bdir/reports/hls"
    take "$project/csim/report/nn_infer_csim.log" "$bdir/reports/hls"
}

# The one build whose overlay is archived: the first in canonical order that
# produced both files PYNQ needs. Normally A; B, C or D only if the ones before
# it failed, in which case it was short-cosimmed and the manifest says so.
DEPLOY=""

claim_deploy() {
    b="$1"
    stem="nn_w${WIDTH}_${b}"

    if [ -n "$DEPLOY" ]; then
        return 0
    fi
    [ "$result" = "OK" ] && [ "$MISSING" -eq "$missing_before" ] || return 0

    if [ ! -f "$SRC/fpga/vivado/bit/$stem.bit" ] ||
       [ ! -f "$SRC/fpga/vivado/bit/$stem.hwh" ]; then
        return 0
    fi

    DEPLOY="$b"

    # The .bit and .hwh must keep the same basename and sit side by side, which
    # is how PYNQ's Overlay() finds the second from the first.
    take "$SRC/fpga/vivado/bit/$stem.bit" "$RUN/bitstream"
    take "$SRC/fpga/vivado/bit/$stem.hwh" "$RUN/bitstream"
}

# --- one build --------------------------------------------------------------

BUILD_RESULTS=""
BUILD_MISSING=0
FAILED_BUILDS=0
SUSPECT_BUILDS=0

run_build() {
    b="$1"
    bdir="$RUN/builds/$b"
    export NN_VIVADO_LOG_DIR="$bdir/logs/vivado"

    build_started=$(date -u '+%Y-%m-%d %H:%M:%SZ')
    build_started_epoch=$(date '+%s')
    missing_before="$MISSING"

    if [ "$b" = "$FULL_COSIM_BUILD" ]; then
        cosim_n=""
        cosim_depth="full"
        cosim_shown=$(full_cosim_vectors)
    else
        cosim_n="$QUICK_COSIM"
        cosim_depth="quick"
        cosim_shown="$QUICK_COSIM"
    fi

    result="OK"
    vivado_rc="skipped"

    # cosim_n is unquoted so that an empty value disappears rather than
    # arriving as an empty argument: run_hls.tcl then uses the header's own
    # GOLDEN_COSIM_N, which is what "full" means.
    run_stage hls "$bdir/logs" "4-hls.log" "$b" \
        "$SCRIPTS/hls.sh" "$WIDTH" "$b" $cosim_n
    hls_rc="$LAST_RC"

    if [ "$hls_rc" = "skipped" ]; then
        cosim_depth="skipped"
        cosim_shown="-"
    fi

    if [ "$hls_rc" != "0" ] && [ "$hls_rc" != "skipped" ]; then
        result="FAILED at hls"
        skip_vivado "$b" "its HLS stage failed"
    elif [ ! -f "$SRC/fpga/hls/hls_w${WIDTH}_${b}/sol/impl/ip/component.xml" ]; then
        # Require the packaged deliverable in addition to the completion marker.
        echo >&2
        if [ "$hls_rc" = "skipped" ]; then
            echo "ERROR: build $b has no packaged IP and --from skipped its HLS." >&2
            echo "       Only a build already synthesised can be resumed at vivado." >&2
            result="no packaged IP to resume from"
        else
            echo "ERROR: build $b reported HLS success but packaged no IP." >&2
            echo "       Read the end of its hls log: cosim or export_design failed." >&2
            result="FAILED at hls (no packaged IP)"
        fi
        skip_vivado "$b" "there is no IP to implement"
    else
        run_stage vivado "$bdir/logs" "5-vivado.log" "$b" \
            "$SCRIPTS/vivado.sh" "$WIDTH" "$b"
        vivado_rc="$LAST_RC"

        if [ "$vivado_rc" != "0" ] && [ "$vivado_rc" != "skipped" ]; then
            result="FAILED at vivado"
        fi
    fi

    collect_build "$b"
    claim_deploy "$b"

    build_absent=$((MISSING - missing_before))
    BUILD_MISSING=$((BUILD_MISSING + build_absent))

    # A failed build's absent artefacts are expected, so they are not counted
    # against the run. A build that reported success and is still missing
    # something is the case worth a non-zero exit.
    if [ "$result" = "OK" ]; then
        if [ "$build_absent" -ne 0 ]; then
            SUSPECT_BUILDS=$((SUSPECT_BUILDS + 1))
            result="FAILED: missing or unarchived artefacts"
        fi
    else
        FAILED_BUILDS=$((FAILED_BUILDS + 1))
    fi

    build_finished=$(date -u '+%Y-%m-%d %H:%M:%SZ')
    elapsed=$(duration $(( $(date '+%s') - build_started_epoch )))

    deployed="no"
    if [ "$DEPLOY" = "$b" ]; then
        deployed="yes"
    fi

    {
        echo "build          $b"
        echo "result         $result"
        echo "hls_exit       $hls_rc"
        echo "vivado_exit    $vivado_rc"
        echo "cosim_vectors  $cosim_shown"
        echo "cosim_depth    $cosim_depth"
        echo "started        $build_started"
        echo "finished       $build_finished"
        echo "elapsed        $elapsed"
        echo "absent         $build_absent"
        echo "deploy         $deployed"
    } > "$bdir/status.txt"

    BUILD_RESULTS="$BUILD_RESULTS$b: $result [$elapsed]
"

    # Always. A build's failure is this run's data, not its end.
    return 0
}

# The step counter has to advance even when a stage does not run, or the
# banners stop agreeing with TOTAL halfway through the first failed build.
skip_vivado() {
    STEP=$((STEP + 1))
    printf '\n--- [%d/%d] vivado %s not run: %s\n' \
        "$STEP" "$TOTAL" "$1" "$2"
}

# --- run --------------------------------------------------------------------

run_shared() {
    run_stage train  "$LOGS" "1-train.log"  "" "$SCRIPTS/train.sh" \
        || { FAILED_AT="train"; return 1; }
    run_stage check  "$LOGS" "2-check.log"  "" "$SCRIPTS/check.sh" \
        || { FAILED_AT="check"; return 1; }
    run_stage export "$LOGS" "3-export.log" "" "$SCRIPTS/export.sh" \
        || { FAILED_AT="export"; return 1; }
    return 0
}

if run_shared; then
    WIDTH=$(selected_width) || WIDTH=""

    if [ -z "$WIDTH" ]; then
        echo >&2
        echo "ERROR: no width in src/fpga/hls/selected_width.hpp." >&2
        echo "       Run the export before using --from hls." >&2
        FAILED_AT="width"
        STATUS=1
    else
        echo
        echo "width     $WIDTH (from selected_width.hpp)"

        for build in $BUILDS; do
            run_build "$build"
        done
    fi
else
    STATUS="$LAST_RC"
fi

# The width is needed to name the shared artefacts even when a stage failed
# after the export, so recover it here if the run bailed before setting it.
if [ -z "$WIDTH" ]; then
    WIDTH=$(selected_width) || WIDTH=""
fi

# --- collect the shared half ------------------------------------------------

printf '\n%s\n' "$RULE"
printf '  collecting into %s\n' "$RUN_REL"
printf '%s\n' "$RULE"

if [ -n "$WIDTH" ]; then
    printf '\n  shared\n'

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
else
    echo
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

SHARED_MISSING=$((MISSING - BUILD_MISSING))

# --- manifest ---------------------------------------------------------------

# Written before the summary rather than after it, because summarize.py quotes
# the manifest's own header line back into the table. That puts the render one
# second outside the elapsed time below, which is noise next to four builds.

FINISHED_AT=$(date -u '+%Y-%m-%d %H:%M:%SZ')
ELAPSED=$(duration $(( $(date '+%s') - STARTED_EPOCH )))

GIT_REV=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) || GIT_REV="unknown"

if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    GIT_REV="$GIT_REV (dirty)"
fi

if [ -n "$FAILED_AT" ]; then
    RESULT="FAILED at $FAILED_AT"
elif [ "$SHARED_MISSING" -ne 0 ] || [ "$SUSPECT_BUILDS" -ne 0 ]; then
    RESULT="FAILED: missing or unarchived artefacts"
elif [ "$FAILED_BUILDS" -ne 0 ]; then
    RESULT="PARTIAL, $FAILED_BUILDS of $NBUILDS build(s) failed"
else
    RESULT="OK"
fi

{
    echo "run          $NAME"
    echo "status       $RESULT"
    echo "started      $STARTED_AT"
    echo "finished     $FINISHED_AT"
    echo "elapsed      $ELAPSED"
    echo "host         $(hostname 2>/dev/null || echo unknown)"
    echo "git          $GIT_REV"
    echo
    echo "width        ${WIDTH:-unresolved}"
    echo "builds       $BUILDS"
    echo "deploy       ${DEPLOY:-none}"
    echo "from         $FROM"
    echo "stages run  ${STAGES_RUN:- none}"
    echo "absent       $SHARED_MISSING shared artefact(s)"
    echo

    if [ -n "$DEPLOY" ] && [ "$DEPLOY" != "$FULL_COSIM_BUILD" ]; then
        echo "WARNING      bitstream/ holds build $DEPLOY, which was"
        echo "             co-simulated on $QUICK_COSIM vectors only, because"
        echo "             $FULL_COSIM_BUILD produced no bitstream. Re-run it at"
        echo "             full cosim before it goes near the board:"
        echo "               ./src/pipeline.sh --name <name> --build $DEPLOY --from hls"
        echo
    fi

    echo "per build"
    printf '%s' "$BUILD_RESULTS" | sed 's/^/  /'
    echo
    echo "summary/     the A-D comparison table. Start here."
    echo "builds/<X>/  one directory per build: status.txt, logs, HLS and"
    echo "             Vivado reports. A failed build has fewer of them, and"
    echo "             that absence is its result."
    if [ -n "$DEPLOY" ]; then
        echo "bitstream/   build $DEPLOY's .bit + .hwh, plus norm_stats.json, the"
    else
        echo "bitstream/   no build produced a bitstream, so norm_stats.json, the"
    fi
    echo "             description json and the golden npz -- everything needed"
    echo "             to run the model on the Ultra96, and nothing from the"
    echo "             other builds: transfer.sh expects exactly one .bit."
    echo "headers/     the generated PL interface. Shared: one export fed all"
    echo "             $NBUILDS builds, which is what makes them comparable."
    echo "model/       the quantized checkpoint everything else derives from."
    echo "reports/     the training loss curve and a confusion matrix per"
    echo "             trained model."
    echo "logs/        stdout of the shared stages. The accuracy numbers, the"
    echo "             layer table and the accumulator peaks live only here."
    echo "             Each build's own stdout is under builds/<X>/logs/."
} > "$RUN/manifest.txt"

# --- summary ----------------------------------------------------------------

# summarize.py is stdlib only, so it runs from whatever interpreter is at hand;
# src/.venv is preferred only because it is certainly there after a full run.
#
# Each candidate is made to execute something before it is accepted. Windows
# ships a `python` on PATH that is not an interpreter at all but an App
# Execution Alias, and it answers `command -v` cheerfully before printing a
# Microsoft Store advertisement instead of running the script.
find_python() {
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

# The summary is by definition the last stage, whatever happened before it.
STEP="$TOTAL"

printf '\n%s\n' "$RULE"
printf '  [%d/%d] summary\n' "$STEP" "$TOTAL"
printf '  log: logs/%d-summary.log\n' "$STEP"
printf '%s\n\n' "$RULE"

SUMMARY_OK=0

if PYTHON=$(find_python); then
    "$PYTHON" "$SRC/fpga/summarize.py" "$RUN" 2>&1 \
        | tee "$LOGS/$STEP-summary.log"
    SUMMARY_RC=$?
else
    echo "ERROR: no working Python found." | tee "$LOGS/$STEP-summary.log" >&2
    SUMMARY_RC=127
fi

if [ "$SUMMARY_RC" -eq 0 ]; then
    SUMMARY_OK=1
else
    echo >&2
    echo "The comparison table was NOT written. Everything it reads is" >&2
    echo "already archived, so render it whenever Python is available:" >&2
    echo "    python src/fpga/summarize.py $RUN_REL" >&2
fi

echo
cat "$RUN/manifest.txt"

# --- what the exit code means -----------------------------------------------

# Continue after variant failures, but never report a partial run as success.
if [ -n "$FAILED_AT" ]; then
    echo
    echo "Run FAILED at $FAILED_AT. Partial results in $RUN_REL" >&2
    if [ "$STATUS" = "0" ] || [ "$STATUS" = "skipped" ]; then
        STATUS=1
    fi
    exit "$STATUS"
fi

if [ "$SHARED_MISSING" -ne 0 ]; then
    echo
    echo "Run finished, but $SHARED_MISSING shared artefact(s) were absent." >&2
    exit 1
fi

if [ "$SUSPECT_BUILDS" -ne 0 ]; then
    echo
    echo "Run finished, but $SUSPECT_BUILDS build(s) reported success and are" >&2
    echo "still missing artefacts. Read their status.txt." >&2
    exit 1
fi

echo
if [ "$SUMMARY_OK" -ne 1 ] || [ "$FAILED_BUILDS" -ne 0 ]; then
    echo "Comparison finished with failures. Read the summary and per-build logs." >&2
    exit 1
fi
if [ "$SUMMARY_OK" -eq 1 ]; then
    echo "Run complete. $RUN_REL — read summary/summary.md"
else
    echo "Run complete. $RUN_REL — the comparison table is still to render."
fi
