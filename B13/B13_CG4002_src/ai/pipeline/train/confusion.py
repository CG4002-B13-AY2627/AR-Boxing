import numpy as np

import matplotlib.pyplot as plt

from config import (
    PLOT_DIR,
    CONFUSION_PLOT_NAME,
)

# Section 5.4.5 bounds precision and recall per class, so the matrix is the
# figure that shows whether a failure is spread thinly or sits on one action.
# Shading is by the fraction of each true class rather than by raw count:
# classes are not collected in equal numbers, and a count-shaded matrix makes
# the biggest class look like the best one.


def plot_confusion(matrix, names, title, path):
    """Save a confusion matrix, rows true and columns predicted, as an image.

    Each cell is shaded by its share of the true class and labelled with its
    raw count. Returns the path written.
    """
    matrix = np.asarray(matrix)
    totals = matrix.sum(axis=1, keepdims=True)

    # A class can be predicted without appearing in the labels, which leaves
    # its row empty. Shade that row as zero rather than divide by it.
    shares = np.divide(
        matrix,
        totals,
        out=np.zeros(matrix.shape, dtype=float),
        where=totals > 0
    )

    accuracy = np.trace(matrix) / matrix.sum()

    side = len(names)
    figure, axes = plt.subplots(figsize=(side * 0.7 + 3, side * 0.7 + 2))

    image = axes.imshow(shares, cmap="Blues", vmin=0, vmax=1)
    figure.colorbar(image, ax=axes, fraction=0.046, pad=0.04, label="Share of true class")

    for row in range(side):
        for column in range(side):
            # White on the dark cells, black on the light ones.
            colour = "white" if shares[row, column] > 0.5 else "black"
            axes.text(column, row, matrix[row, column], ha="center", va="center", color=colour)

    axes.set_xticks(range(side), names, rotation=45, ha="right")
    axes.set_yticks(range(side), names)
    axes.set_xlabel("Predicted")
    axes.set_ylabel("True")
    axes.set_title(f"{title}\nAccuracy {100 * accuracy:.2f}%")

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=800, bbox_inches="tight")
    plt.close(figure)

    return path


def confusion_plot_name(tag):
    """confusion.png -> confusion_fp32.png, so each model keeps its own matrix."""
    stem, suffix = CONFUSION_PLOT_NAME.rsplit(".", 1)

    return f"{stem}_{tag}.{suffix}"


def save_confusion(matrix, names, title, tag):
    path = PLOT_DIR / confusion_plot_name(tag)
    plot_confusion(matrix, names, f"{title} on the test set", path)

    print(f"Saved confusion matrix to {path}")
