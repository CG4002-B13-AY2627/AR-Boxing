import json

import torch

from config import (
    CHECKPOINT_DIR,
    NORM_STATS_NAME,
    FEATURE_COLUMNS,
)

# The nodes hand us raw IMU readings: acceleration in m/s^2, which sits near
# 9.8 on whichever axis gravity falls down, and angular rate in rad/s, which
# sits near 0. Those two live on completely different scales, and the network
# should not have to spend capacity discovering that.
#
# It matters more for QuantCNN than for CNN. A quantizer shares one scale
# across a whole tensor, so if one channel reaches 20 and another reaches 0.3,
# almost every level goes to the loud channel and the quiet one is left with a
# handful of steps. Normalising first is what lets the width sweep measure
# quantization rather than measuring our failure to scale the inputs.
#
# We standardise per channel: subtract the mean, divide by the standard
# deviation. Both are computed on the training participants only, because
# statistics taken over the test set would leak it into training.
#
# The PS on the Ultra96 must apply this exact same transform before handing a
# window to the accelerator, so the numbers are saved to JSON alongside the
# weights.

# Guards against dividing by zero on a channel that never moves.
EPSILON = 1e-8


def fit_stats(dataset, indices):
    """Per-channel mean and standard deviation over the given windows."""
    features = dataset.features[indices]
    flattened = features.reshape(-1, features.shape[-1])

    mean = flattened.mean(dim=0)
    std = flattened.std(dim=0).clamp(min=EPSILON)

    return {"mean": mean, "std": std}


def apply_stats(dataset, stats):
    """Standardise every window in the dataset, in place."""
    dataset.features = (dataset.features - stats["mean"]) / stats["std"]

    return dataset


def normalize_for_training(train_loader):
    """Fit on the training windows, then apply to the whole dataset.

    train_loader wraps a Subset, so .dataset is the IMUDataset every split
    shares and .indices are the training windows within it. Normalising that
    one tensor therefore reaches the test loader and the fold loaders too,
    which is what we want: one transform, fitted once, applied everywhere.
    """
    subset = train_loader.dataset

    stats = fit_stats(subset.dataset, subset.indices)
    apply_stats(subset.dataset, stats)

    return stats


def save_stats(stats, name=NORM_STATS_NAME):
    """Write the statistics out for the PS to apply at inference time."""
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    path = CHECKPOINT_DIR / name

    payload = {
        "channels": FEATURE_COLUMNS,
        "mean": stats["mean"].tolist(),
        "std": stats["std"].tolist(),
    }

    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Saved normalization statistics to {path}")

    return path


def load_stats(name=NORM_STATS_NAME):
    """Read back what save_stats wrote."""
    path = CHECKPOINT_DIR / name

    with open(path) as f:
        payload = json.load(f)

    return {
        "mean": torch.tensor(payload["mean"], dtype=torch.float32),
        "std": torch.tensor(payload["std"], dtype=torch.float32),
    }
