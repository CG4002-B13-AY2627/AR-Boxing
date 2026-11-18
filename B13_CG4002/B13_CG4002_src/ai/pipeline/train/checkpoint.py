import shutil

import torch

from config import (
    CHECKPOINT_DIR,
    CHECKPOINT_NAME,
    QAT_CHECKPOINT_NAME,
    QMODEL_DIR,
)


def save_checkpoint(model, name=CHECKPOINT_NAME):
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    path = CHECKPOINT_DIR / name
    torch.save(model.state_dict(), path)

    print(f"Saved weights to {path}")


def quant_checkpoint_name(bit_width):
    """qacnn.pt -> qacnn_w8.pt, so each width keeps its own weights."""
    stem = QAT_CHECKPOINT_NAME.rsplit(".", 1)[0]
    suffix = QAT_CHECKPOINT_NAME.rsplit(".", 1)[-1]

    return f"{stem}_w{bit_width}.{suffix}"


def clear_selected():
    """Empty qmodel/ so it only ever holds this run's selection.

    Called on both paths, the one that selects a width and the one where none
    qualifies. Leaving an earlier run's checkpoint behind would let the export
    succeed against a selection this training run did not make.
    """
    QMODEL_DIR.mkdir(exist_ok=True)

    for stale in QMODEL_DIR.glob("*.pt"):
        stale.unlink()


def save_selected(bit_width):
    """Copy the chosen width's checkpoint into qmodel/ for the exporter."""
    clear_selected()

    name = quant_checkpoint_name(bit_width)
    destination = QMODEL_DIR / name
    shutil.copy2(CHECKPOINT_DIR / name, destination)

    print(f"Selected {bit_width} bits; copied to {destination}")
