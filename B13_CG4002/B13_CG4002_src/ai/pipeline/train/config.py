"""Central configuration for the AI subsystem: data, model and training."""

import torch
import torch.nn as nn
import torch.optim as optim

from pathlib import Path

# This is our config file. Modify our configurations and parameters here. 
# Hopefully we won't have to visit this file too much.

# --- Paths ------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"

# The sweep leaves one checkpoint per width in CHECKPOINT_DIR. The single
# width we take to hardware is copied here, so the exporter has one
# unambiguous input and does not have to re-derive the selection.
QMODEL_DIR = BASE_DIR / "qmodel"
PLOT_DIR = BASE_DIR / "plots"

CSV_NAME = "mike-tyson.csv"
NORM_STATS_NAME = "norm_stats.json"
CHECKPOINT_NAME = "cnn.pt"
QAT_CHECKPOINT_NAME = "qacnn.pt"
LOSS_PLOT_NAME = "training_loss.png"
CONFUSION_PLOT_NAME = "confusion.png"

# --- Data -------------------------------------------------------------------

# Rows per sample. At 100 Hz, 32 samples is a 320 ms window.
WINDOW_SIZE = 32
BATCH_SIZE = 32

TEST_SIZE = 0.2
RANDOM_SEED = 42

# Which participant a row came from.
PARTICIPANT_COLUMN = "participant"

# For cosmetic (this field should remain constant), we add a variable denoting the label column
LABEL_COLUMN = "label"

# Folds for the cross validation inside fit(), stratified by action.
K_FOLDS = 3

FEATURE_COLUMNS = [
    "l_ax", "l_ay", "l_az",
    "l_gx", "l_gy", "l_gz",
    "r_ax", "r_ay", "r_az",
    "r_gx", "r_gy", "r_gz"
]

LABEL_TO_ID = {
    "l_straight": 0,
    "r_straight": 1,
    "l_hook": 2,
    "r_hook": 3,
    "l_uppercut": 4,
    "r_uppercut": 5,
    "block": 6,
    "weave": 7,
    "pickup": 8,
    # "use": 9,
    "idle": 9
}

ID_TO_LABEL = {index: label for label, index in LABEL_TO_ID.items()}

# --- Model ------------------------------------------------------------------

NUM_CHANNELS = len(FEATURE_COLUMNS)
NUM_CLASSES = len(LABEL_TO_ID)

CONV1_FILTERS = 32
CONV1_KERNEL = 5

POOL_KERNEL = 2
POOL_STRIDE = 2

CONV2_FILTERS = 64
CONV2_KERNEL = 3

HIDDEN_UNITS = 32

# --- Quantization -----------------------------------------------------------

# Widths for the QuantCNN in qacnn.py. These are the W of the ap_fixed<W, I>
# words the HLS core will hold. Note that we only choose W here: QAT chooses I
# for us, as the power-of-two scale it learns per tensor is a binary point
# position, which we read back at export.
WEIGHT_BIT_WIDTH = 8
ACT_BIT_WIDTH = 8

# The width sweep. Train one QuantCNN per entry, and the narrowest one still
# within MAX_QUANT_LOSS_PP of the FP32 baseline is the one we take to hardware.
BIT_WIDTH_SWEEP = [8, 7, 6, 5, 4]

# Section 5.4.5 sets the budget: quantization may cost at most this much
# accuracy against the FP32 baseline, measured on the held-out set.
MAX_QUANT_LOSS_PP = 2.0
# MAX_QUANT_LOSS_PP = 7.0

# --- Training ---------------------------------------------------------------

NUM_EPOCHS = 500
LEARNING_RATE = 0.001

# L2 regularisation, applied through Adam's weight decay.
WEIGHT_DECAY = 0.0001

# Stop once the validation loss has not improved for this many epochs, and
# restore the weights of the best epoch rather than the last one.
EARLY_STOPPING_PATIENCE = 10

# Cut the learning rate by this factor when the validation loss plateaus.
LR_PLATEAU_FACTOR = 0.1
LR_PLATEAU_PATIENCE = 5

# QAT is a fine-tune of the trained FP32 weights rather than a fresh run, so it
# wants a smaller step and fewer epochs than the baseline above.
QAT_NUM_EPOCHS = 100
QAT_LEARNING_RATE = 0.0001


def get_device():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def get_criterion():
    return nn.CrossEntropyLoss()


def get_optimizer(model):
    return optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)


def get_qat_optimizer(model):
    return optim.Adam(model.parameters(), lr=QAT_LEARNING_RATE, weight_decay=WEIGHT_DECAY)


def get_scheduler(optimizer):
    """Cut the learning rate when the validation loss stops improving."""
    return optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        factor=LR_PLATEAU_FACTOR,
        patience=LR_PLATEAU_PATIENCE
    )
