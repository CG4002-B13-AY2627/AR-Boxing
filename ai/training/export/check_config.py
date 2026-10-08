"""Configuration for the export checks: what to run them over, and how they round.

check.py asks two questions of one Brevitas pass — does the exported
description, executed as plain integers, reproduce Brevitas exactly, and does
the board's own pre-processing reproduce the quantizer at the PS/PL boundary?
Everything that changes *how those questions are asked* lives here, so the
checkers themselves stay arithmetic.

This is deliberately not part of export_config.py. That file is the contract
between the training side and the HLS build: which checkpoint, which headers,
which topology. Nothing here reaches the generated headers or the board — it
only steers a test — and mixing the two would blur a boundary that is currently
clean.
"""

import argparse

import export_config

# --- Rounding ---------------------------------------------------------------

# The requantization between every pair of layers is a right shift, and the
# three ways to round that shift are the reason this file has a mode at all:
#
#   trunc      a plain >>. Note this is *floor*, not truncation toward zero,
#              so -0.5 lands on -1. It is what C gives for free and what
#              ap_fixed does by default (AP_TRN), and it loses half an LSB
#              downward on average at every layer.
#   half_up    add half, then shift. One adder, and unbiased for negatives,
#              but every tie breaks upward.
#   half_even  round to nearest, ties to the even neighbour. Unbiased in both
#              directions. This is what torch.round does and what AP_RND_CONV
#              does in HLS.
#
# We are not choosing the best of these. We are finding the one Brevitas
# already uses, because only that one can give zero mismatches — the other two
# will land close, which is precisely the outcome that makes a later csim
# failure hard to read.
ROUNDING_MODES = ["trunc", "half_up", "half_even"]

# The expected answer, not the verified one. Brevitas rounds with torch.round,
# which is half-to-even, and section 5.2.3 already commits to AP_RND_CONV over
# the ap_fixed default. Run the other two once anyway: the point of this file
# is that the assumption gets tested rather than inherited.
DEFAULT_ROUNDING = "half_even"

# Whichever mode wins is not just a fact about this checker — it is what
# nn_infer.cpp has to implement, and it is the one piece of the arithmetic the
# description does *not* carry. extract.py emits the shift amount and the clamp
# bounds; it says nothing about the rounding rule. Record the answer here once
# it is known, and make sure it reaches params_w{}.hpp when emit.py is written.

# Ran the output, and found out the rounding is half even.
VERIFIED_ROUNDING = "half_even"

# --- Sample size ------------------------------------------------------------

# Bit exactness either holds or it does not, so this does not need to be large;
# it needs to be enough windows to exercise every layer's clamp in both
# directions. The conv loops here are explicit rather than vectorised — they
# mirror the HLS loop nest on purpose — so a few thousand windows is minutes,
# not seconds. Drop it to ~20 while debugging a specific layer.
DEFAULT_VECTORS = 200

# The same seed the training and the golden vectors use, so the windows this
# runs over are the windows the csim vectors are drawn from.
SEED = export_config.GOLDEN_SEED

# How many failing windows to name before summarising. An arithmetic error
# breaks every window, and 200 identical lines help nobody. The same reasoning,
# and the same number, as u96_config.MAX_REPORTED.
MAX_REPORTED = 5

# --- Description source -----------------------------------------------------

# None means call extract() and check the description as it exists right now.
# That is the normal case and the safe default: build/description_w{}.json is
# gitignored, is documented as a dump rather than a pipeline stage, and can
# therefore be stale against the checkpoint in qmodel/.
#
# A path is for the offline case — chasing a csim mismatch on the FPGA host,
# where reloading a checkpoint is inconvenient and only the arithmetic is in
# question. When a path is given, check() should compare the file's meta.sha256
# against the live checkpoint and stop on a mismatch, so a stale pair fails
# loudly instead of quietly agreeing with itself.
DEFAULT_DESCRIPTION = None

# --- The board's pre-processing ---------------------------------------------

# check_preprocess.py checks ultra-96/src/preprocess.py itself, so that
# directory has to be importable. Naming it here rather than in the checker
# keeps the one path that reaches out of src/ in a config file.
U96_SRC_DIR = export_config.REPO_DIR / "ultra-96" / "src"

# Where Preprocess reads norm_stats.json from. None means train/checkpoints/,
# which is where training writes it and the only copy that exists during a
# pipeline run -- the archive is assembled after every stage has passed.
#
# Point it at an archived run's bitstream/ to check the copy that actually
# shipped: that is the one case where the file preprocess.py reads and the file
# the model was trained against can be different files.
DEFAULT_RUN_DIR = None


# --- Arguments --------------------------------------------------------------

def parse_arguments(argv=None):
    """The command line, built from the defaults above.

    Kept here rather than in check.py so that the whole argument surface of
    the check is in one file, the same way export_config.py owns the export's.
    argv stays open so the sweep can call this without going through sys.argv.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Check the exported description, and the board's pre-processing, "
            "against Brevitas."
        )
    )

    parser.add_argument(
        "--vectors",
        type=int,
        default=DEFAULT_VECTORS,
        help=f"held-out windows to check (default {DEFAULT_VECTORS})",
    )

    parser.add_argument(
        "--rounding",
        default=DEFAULT_ROUNDING,
        choices=ROUNDING_MODES,
        help=f"requantization rounding mode (default {DEFAULT_ROUNDING})",
    )

    parser.add_argument(
        "--description",
        default=DEFAULT_DESCRIPTION,
        help="a description_w{}.json to check instead of re-running extract()",
    )

    parser.add_argument(
        "--run",
        default=DEFAULT_RUN_DIR,
        help="a run directory to read norm_stats.json from (default train/checkpoints)",
    )

    arguments = parser.parse_args(argv)

    if arguments.vectors < 1:
        raise SystemExit(f"--vectors must be at least 1, got {arguments.vectors}")

    return arguments
