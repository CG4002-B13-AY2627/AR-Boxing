"""Configuration for the width sweep: what it builds, where it lands, and what it reads back.

The counterpart to build_config.py and the same rule applies: nothing that
varies is written as a literal in sweep.py. Every stage name, archive
directory, report path and pattern the sweep depends on has its one home here.

Note what is deliberately *not* here.

Nothing build_config.py already owns -- the out/ kinds, the generated project,
solution and bitstream names, the environment variables, the directive letters.
sweep.py reaches those through build_config and restates none of them.

Nothing describing the network either. The widths swept, the accuracy budget
and the checkpoint name belong to train/config.py, so this file names only the
*symbols* to read out of it and sweep.py reads them at run time. That is why
the sweep tracks a retrain instead of having to be edited alongside one.

The one deliberate duplicate is WIDTH_HEADERS, which export_config.py also
spells. sweep.py cannot import export_config: that module reaches train/config.py,
which imports torch, and the sweep has to run from whatever interpreter is at
hand. The pattern is asserted against the real names by check_build.py instead.
"""

import re

# --- Stages -----------------------------------------------------------------

# The pipeline's five stages in the only order that works. The sweep splits
# them in one place: training runs once and produces every checkpoint, so only
# the four below it are paid per width.
STAGES = ("train", "check", "export", "hls", "vivado")
SHARED_STAGE = STAGES[0]
PER_WIDTH_STAGES = STAGES[1:]

# The two stages that take arguments rather than reading their inputs off
# disk. Named because sweep.py branches on them: the width and the directive
# letter are positional to both, and the vector count to the first.
HLS_STAGE = "hls"
VIVADO_STAGE = "vivado"

# A stage's log is numbered by its place in the pipeline, with the clean before
# it at zero -- the same numbering pipeline.* uses, so a sweep's per-width logs
# and a pipeline run's logs can be read side by side without translation.
CLEAN_STAGE = "clean"
CLEAN_INDEX = 0
STAGE_LOG = "{index}-{stage}.log"


def log_name(stage):
    """The log file a stage writes, numbered the way pipeline.* numbers it."""
    if stage == CLEAN_STAGE:
        return STAGE_LOG.format(index=CLEAN_INDEX, stage=stage)
    return STAGE_LOG.format(index=STAGES.index(stage) + 1, stage=stage)


# --- Cleaning ---------------------------------------------------------------

# Which artefact groups a resume may delete, keyed by the stage it resumes
# from. Only the groups at or after the resume point: --from hls must not
# delete the headers the HLS stage is about to consume, and check writes
# nothing of its own so it cleans from export onward like export does.
#
# The sweep cleans once, before any width. The per-width names are disjoint --
# params_w8.hpp beside params_w6.hpp, hls_w8_A beside hls_w6_A -- so the five
# widths coexist and cleaning between them would destroy the run.
CLEAN_FROM = {
    "train": ["train", "export", "hls", "vivado"],
    "check": ["export", "hls", "vivado"],
    "export": ["export", "hls", "vivado"],
    "hls": ["hls", "vivado"],
    "vivado": ["vivado"],
}

# --- Co-simulation ----------------------------------------------------------

# Vectors each width co-simulates. Short on purpose and short on every width,
# unlike all.*, which gives its deploy build the full set: nothing a sweep
# builds is going to the board, and the curve comes from csynth and Vivado
# rather than from cosim. What the short run gives up is verification depth.
DEFAULT_COSIM = "5"

# --- Symbols read out of train/config.py ------------------------------------

# Read by AST rather than by import, because train/config.py imports torch and
# the sweep must run from any interpreter. Names, never values: the sweep
# follows a retrain instead of needing an edit beside one.
TRAIN_CONFIG = "train/config.py"
WIDTHS_SYMBOL = "BIT_WIDTH_SWEEP"
BUDGET_SYMBOL = "MAX_QUANT_LOSS_PP"
CHECKPOINT_SYMBOL = "QAT_CHECKPOINT_NAME"
CONFUSION_SYMBOL = "CONFUSION_PLOT_NAME"

# Where training leaves what the sweep consumes, relative to SRC_DIR. The
# selected checkpoint is alone in SELECTED_DIR by construction -- train.py
# empties it on every run -- which is what makes the selected width knowable
# without being told.
SELECTED_DIR = "train/qmodel"
LOSS_CURVE = "train/plots/training_loss.png"

# confusion.png -> confusion_fp32.png and confusion_w6.png: one matrix per model
# train.py fitted, tagged the way it tags them. The baseline's is shared like
# the loss curve; each width's is archived beside that width's area and timing,
# because where a class collapses is half of what the width costs.
PLOT_DIR = "train/plots"
CONFUSION_STEM = "{stem}_{tag}.{suffix}"
BASELINE_TAG = "fp32"
WIDTH_TAG = "w{width}"

# qacnn.pt -> qacnn_w6.pt. The width a checkpoint was trained at is recoverable
# only from its name: a state dict stores tensors, not the width they were
# quantized to.
CHECKPOINT_STEM = "{stem}_w{width}.{suffix}"
CHECKPOINT_GLOB = "{stem}_w*.{suffix}"
WIDTH_IN_NAME = re.compile(r"_w(\d+)\.")

# --- The archive ------------------------------------------------------------

# out/sweep/<name>/. One directory per width rather than per build, and
# deliberately the same shape all.* writes under builds/<letter>/ -- status.txt
# beside reports/hls/ and reports/vivado/ -- so summarize.py's readers work
# over it unchanged instead of being copied and diverging.
WIDTHS_DIR = "widths"
LOGS_DIR = "logs"
REPORTS_DIR = "reports"
SUMMARY_DIR = "summary"
HEADERS_DIR = "headers"
HLS_REPORTS_SUBDIR = "hls"
VIVADO_REPORTS_SUBDIR = "vivado"

# Where a width's Vivado run leaves its phase logs, under that width's logs/.
VIVADO_LOG_SUBDIR = "vivado"

MANIFEST_NAME = "manifest.txt"
STATUS_NAME = "status.txt"
SUMMARY_NAME = "summary.md"

# No bitstream directory appears in this list and none is written. A sweep
# answers what a width costs, not what ships; transfer.* refuses a run without
# one and says so. The build that goes to the board comes from pipeline.*.

# --- What a width leaves behind ---------------------------------------------

# Collected out of the HLS solution, relative to it. sol_data.json is first
# because it is the one structured file holding every module: the top-level
# csynth report is top-function only, and the moment a build pipelines a loop
# that loop is lifted into a submodule report.
HLS_REPORTS = (
    "sol_data.json",
    "sol.directive",
    "syn/report/csynth.rpt",
    "syn/report/nn_infer_csynth.rpt",
    "syn/report/nn_infer_csynth.xml",
    "sim/report/nn_infer_cosim.rpt",
    "sim/report/verilog/lat.rpt",
    "csim/report/nn_infer_csim.log",
)

# Zero matches is not a failure: which submodule reports exist depends on which
# loops the build pipelined, and at a fixed directive set that can still differ
# between widths.
HLS_REPORT_GLOBS = (("syn/report", "nn_infer_Pipeline_*_csynth.xml"),)

# Post-implementation, which is what section 5.6 quotes -- not the HLS
# estimates. Refines build_config.REPORT_GLOB, which carries the same directory
# with the suffix left open.
VIVADO_REPORT = "reports/{stem}_{suffix}.rpt"
VIVADO_REPORT_SUFFIXES = ("timing", "utilization", "power")

# The headers that width emitted, which are the evidence of what was actually
# built. The golden header is deliberately absent: it is ~670 KB of test
# vectors per width and says nothing about cost.
WIDTH_HEADERS = ("params_w{width}.hpp", "weights_w{width}.hpp")

# --- Reading the archive back -----------------------------------------------

# train.py's quantization-loss table, the one place every width's accuracy is
# written down. Matched out of the run's own log so the summary cannot disagree
# with the checkpoints the rest of the sweep was built from.
ACCURACY_ROW = re.compile(r"^\s*(FP32|\d+)\s+([\d.]+)%\s+(\S+)\s+(\S+)\s*$")
BASELINE_ROW = "FP32"

# The four resources the summary compares, as summarize.py's keys and the names
# the Vivado report gives them. Order is the order they are tabulated in.
RESOURCES = (("lut", "CLB LUT"), ("ff", "CLB Register"),
             ("dsp", "DSP48E2"), ("bram", "Block RAM tile"))

# --- Presentation -----------------------------------------------------------

# Matched against the whole name, which becomes a path: anything outside this
# set is refused rather than sanitised.
RUN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
RESERVED_NAMES = (".", "..")

RULE = "=" * 60
TIMESTAMP = "%Y-%m-%d %H:%M:%SZ"
ELAPSED = "%02dh %02dm %02ds"
