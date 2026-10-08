import matplotlib.pyplot as plt

from config import (
    PLOT_DIR,
    LOSS_PLOT_NAME,
)


def plot_loss_curves(histories, show=True):
    """Plot one loss curve per entry in histories, keyed by label."""
    plt.figure(figsize=(10, 5))

    for label, loss_history in histories.items():
        plt.plot(range(1, len(loss_history) + 1), loss_history, label=label)

    plt.title("Training Loss Curve")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.grid(True)
    plt.legend()

    PLOT_DIR.mkdir(exist_ok=True)
    path = PLOT_DIR / LOSS_PLOT_NAME
    plt.savefig(path, dpi=400, bbox_inches="tight")
    print(f"\nSaved loss curve to {path}")

    if show:
        plt.show()

    plt.close()
