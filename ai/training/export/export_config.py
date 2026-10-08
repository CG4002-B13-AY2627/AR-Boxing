"""Configuration for the weight export: where things go and how they are emitted.

Everything describing the *trained network* — window size, channel count, class
count, layer sizes, the width sweep — is owned by train/config.py and reached
through train_config below. Nothing on that list is restated here. Restating a
dimension is how a header ends up disagreeing with the checkpoint it was
generated from, which is a bug that survives csim and only appears on hardware.

What lives here is the other half: which checkpoint to read, the shape of the
C++ we emit, and the wiring the extractor walks — which weight layer sits
between which pair of activation quantizers — none of which the training side
has any reason to know about. The wiring names modules, it does not restate
their sizes; those are still read off the checkpoint at export time.

Everything below is meant to be the only file touched when the export changes.
"""

import os
import re
import sys

from pathlib import Path

# --- Paths ------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
TRAIN_DIR = BASE_DIR.parent / "train"
REPO_DIR = BASE_DIR.parent.parent

# train/config.py and train/qacnn.py are imported by the extractor, so train/
# has to be importable. Resolved from __file__ and not from the working
# directory, because export.sh and the IDE will not agree on the latter.
if str(TRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(TRAIN_DIR))

import config as train_config  # noqa: E402

# build_config.py owns every environment variable this layer is driven by,
# CHECKPOINT_OVERRIDE's among them. Reached the same way train/ is, and for
# the same reason: the name must have one home or the sweep and the export
# can disagree about it silently.
SCRIPTS_DIR = BASE_DIR.parent / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_config  # noqa: E402

# The generated headers. Committed, unlike the checkpoints: Vitis HLS and
# Vivado run on a machine that has no virtual environment of ours, so the
# header is the interface between the two halves of the project.
SRC_DIR = BASE_DIR.parent
OUT_DIR = SRC_DIR / "fpga" / "hls"

# The intermediate description, dumped for inspection and diffing between
# exports. Not consumed by the HLS build.
BUILD_DIR = BASE_DIR / "build"

# --- Input checkpoint -------------------------------------------------------

# The directory the checkpoint comes from is train_config.QMODEL_DIR and is
# deliberately not restated here: renaming it on the training side would
# otherwise leave the extractor happily reading a stale copy.
#
# What is stated here is how to pick a file out of it. train.py sweeps
# BIT_WIDTH_SWEEP, keeps the narrowest width still within MAX_QUANT_LOSS_PP of
# the FP32 baseline, copies that one checkpoint into qmodel/ and deletes
# whatever was there before. So there is exactly one candidate by construction,
# and the extractor is not told a width — it discovers both.

# qacnn.pt -> qacnn_w*.pt, the convention train.py's quant_checkpoint_name()
# writes. Built from QAT_CHECKPOINT_NAME rather than spelled out, so a rename
# there follows through instead of silently matching nothing here.
CHECKPOINT_STEM, CHECKPOINT_SUFFIX = train_config.QAT_CHECKPOINT_NAME.rsplit(".", 1)

CHECKPOINT_GLOB = f"{CHECKPOINT_STEM}_w*.{CHECKPOINT_SUFFIX}"

# A filename in train/checkpoints/, or an absolute path, to export some other
# width than the selected one — comparing utilisation across the sweep for
# section 5.6 wants exactly that. None takes whatever train.py selected.
#
# Read from the environment so scripts/sweep.py sets it per width without editing
# source. Assigning here still works and is what a one-off export does.
CHECKPOINT_OVERRIDE = os.environ.get(build_config.CHECKPOINT_OVERRIDE) or None


def checkpoint_width(path):
    """The bit width a checkpoint was trained at, read off its filename.

    Not cosmetic: QuantCNN has to be constructed at the same width before the
    state dict will load into it, and the name is the only record we have. A
    state dict stores tensors, not the width they were quantized to.
    """
    match = re.search(rf"_w(\d+)\.{re.escape(CHECKPOINT_SUFFIX)}$", path.name)

    if match is None:
        raise SystemExit(
            f"{path.name} does not carry a width, so the network cannot be "
            f"rebuilt to load it. Expected a name like {CHECKPOINT_GLOB}."
        )

    return int(match.group(1))


def selected_checkpoint():
    """The checkpoint to export, and the width it was trained at.

    Anything other than one candidate is a broken assumption rather than a
    choice to make quietly: none means the sweep never met the accuracy budget
    and train.py wrote nothing, several means a stale file was put back by
    hand. Either way, stop instead of exporting an arbitrary one.
    """
    if CHECKPOINT_OVERRIDE is not None:
        path = Path(CHECKPOINT_OVERRIDE)

        if not path.is_absolute():
            path = train_config.CHECKPOINT_DIR / path

        if not path.is_file():
            raise SystemExit(f"CHECKPOINT_OVERRIDE points at no file: {path}")

        return path, checkpoint_width(path)

    found = sorted(train_config.QMODEL_DIR.glob(CHECKPOINT_GLOB))

    if not found:
        raise SystemExit(
            f"No checkpoint in {train_config.QMODEL_DIR}. Run the training "
            f"sweep first, or set CHECKPOINT_OVERRIDE in export_config.py."
        )

    if len(found) > 1:
        raise SystemExit(
            f"{len(found)} checkpoints in {train_config.QMODEL_DIR} "
            f"({', '.join(p.name for p in found)}). One run selects one width, "
            f"so leave only the selected one or set CHECKPOINT_OVERRIDE."
        )

    return found[0], checkpoint_width(found[0])


# --- Output files -----------------------------------------------------------

# {} is the bit width, so an export never silently overwrites a different one.
WEIGHTS_NAME = "weights_w{}.hpp"
PARAMS_NAME = "params_w{}.hpp"
GOLDEN_NAME = "golden_w{}.h"
# The same vectors the header carries, in a form the board can load.
GOLDEN_NPZ_NAME = "golden_w{}.npz"
DESCRIPTION_NAME = "description_w{}.json"

# The one generated file not named for a width, because its job is to carry
# one: it records the width the export selected, so nothing hand-written
# downstream has to name a default. Written only when exporting the selected
# checkpoint -- a CHECKPOINT_OVERRIDE export is a sweep entry, not a change of
# selection, and must not drag the default along with it.
SELECTED_NAME = "selected_width.hpp"

INCLUDE_GUARD_PREFIX = "CG4002_NN_"

# --- Emission style ---------------------------------------------------------

# "int" emits ap_int<W> arrays and keeps the scales as explicit compile-time
# shifts; "fixed" emits ap_fixed<W, W + log2(scale)> and lets HLS align the
# binary points. They synthesise to the same logic. We emit integers because
# the datapath then matches what Brevitas actually computed term for term,
# which makes the co-simulation comparison a direct one rather than an
# argument about implicit alignment.
EMIT_STYLE = "int"

# PyTorch stores Conv1d weights as (out_channels, in_channels, kernel) and
# Linear as (out_features, in_features). We flatten in that order and emit the
# index formula as a comment above each array, so nn_infer.cpp has one stated
# convention to follow rather than an inferred one.
CONV_WEIGHT_ORDER = ("out", "in", "k")
LINEAR_WEIGHT_ORDER = ("out", "in")

# --- Network topology -------------------------------------------------------

# The layers that carry weights, and the activation quantizers on either side
# of each. The exporter reads the topology off this table, which keeps the
# shift arithmetic in one loop instead of four near-identical blocks — and
# makes a change to qacnn.py a matter of editing the rows below.
#
# Each row is (attribute on QuantCNN, kind, input activation, output
# activation). The kind is how the fan-in of a single output is counted when
# sizing the accumulator: a conv sums in_channels x kernel terms, a linear
# sums in_features. Both counts are read off the weight tensor, so the kind
# selects the formula and never states a size.
WEIGHT_LAYERS = [
    # attribute, kind, input activation, output activation
    ("conv1", "conv", "quant_input", "relu1"),
    ("conv2", "conv", "relu1", "relu2"),
    ("fc1", "linear", "quant_pool", "relu3"),
    # fc2 is the exception, hence the None: the logits leave as a plain tensor
    # because argmax is scale invariant, so there is nothing to requantize to.
    ("fc2", "linear", "relu3", None),
]

# Every activation quantizer whose scale, width and saturation bounds the
# header needs. Written out rather than derived from WEIGHT_LAYERS, because a
# quantizer that sits outside a weight layer — quant_pool, which re-establishes
# the scale after the global average pool — would otherwise be missed.
ACTIVATIONS = ["quant_input", "relu1", "relu2", "quant_pool", "relu3"]

# The max pool between conv1 and conv2. It carries no weights and no quantizer
# — max is quant invariant, which is why qacnn.py uses the plain layer — so it
# appears in neither table above and would otherwise reach the header as
# nothing at all, leaving nn_infer.cpp to hardcode a stride the training side
# owns. Named apart from POOL_ below, which is the global average pool.
MAXPOOL_KERNEL = train_config.POOL_KERNEL
MAXPOOL_STRIDE = train_config.POOL_STRIDE

# How many timesteps the max pool leaves, by PyTorch's MaxPool1d rule:
# floor((L - K) / S) + 1, which drops the final partial window the kernel
# cannot fill. Writing it as L // S is right only while K == S, and that is an
# assumption nothing downstream stated -- nn_infer.cpp made it on its own, and
# with an overlapping kernel it would have run its loop one step too far and
# read past the end of its buffer. Derived once, here, and emitted, so the C++
# reads a number rather than recomputing one from two thirds of the geometry.
MAXPOOL_OUTPUT = (
    train_config.WINDOW_SIZE - MAXPOOL_KERNEL
) // MAXPOOL_STRIDE + 1

# The global average pool between conv2 and fc1: the quantizer that feeds it
# and the one that follows it. It carries no weights, so it is not a row above,
# but it still needs a shift and a clamp emitted for it.
POOL_INPUT_ACTIVATION = "relu2"
POOL_OUTPUT_ACTIVATION = "quant_pool"

# How many timesteps AdaptiveAvgPool1d(1) collapses: whatever conv2 leaves
# after the max pool. conv2 pads to keep its length, so that is the max pool's
# output length and not a second quantity -- one derivation under two names,
# because the two are used for different things and a reader of either should
# not have to work out that they are the same number.
POOL_SIZE = MAXPOOL_OUTPUT

# --- Checkpoint loading -----------------------------------------------------

# The export is arithmetic over stored tensors, never a training run, so the
# checkpoint is mapped to the CPU whatever trained it. Without this, a
# GPU-trained checkpoint refuses to load on a machine with no CUDA device.
LOAD_DEVICE = "cpu"

# Bytes read at a time while hashing a checkpoint. Affects only how many read
# calls the digest costs, never the digest itself.
HASH_BLOCK_SIZE = 65536

# --- Arithmetic -------------------------------------------------------------

# Dot product accumulators. The width is derived, not chosen: extract.py sizes
# every accumulator in the network -- each weight layer from its fan-in, its
# operand widths and its trained bias magnitudes, and the global pool from what
# its sum can reach -- and takes the widest. That number reaches the header as
# NN_ACC_W and is recorded in the description's meta, so a build states the
# width it was given rather than inheriting one written down here.
#
# What stays here is the ceiling, which is not the value but the point past
# which a result is not worth emitting. An accumulator wider than this means a
# layer has grown past anything the sweep was meant to cover, and the export
# should stop and be looked at rather than quietly widening the datapath.
#
# Raising it is a deliberate act. Setting it below what the network needs is
# caught on the next export rather than silently obeyed.
ACCUMULATOR_WIDTH_MAX = 32

# --- Golden vectors ---------------------------------------------------------

# Two sets. Co-simulation is slow, so it gets the small one; C simulation is
# cheap and gets enough windows to be worth trusting.
GOLDEN_COSIM_VECTORS = 200
GOLDEN_CSIM_VECTORS = 2000

# Sample evenly across the classes rather than from the natural distribution.
# An unstratified draw is mostly idle and would prove very little about block,
# which is the class a misclassification costs us gameplay rather than a point.
GOLDEN_STRATIFY = True

# The same seed the training used, so the vectors are reproducible.
GOLDEN_SEED = train_config.RANDOM_SEED
