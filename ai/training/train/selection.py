from config import MAX_QUANT_LOSS_PP


def print_comparison(baseline_accuracy, results):
    """The Section 5.4.5 table: quantization loss against the FP32 baseline."""
    print("\nQuantization loss against the FP32 baseline")
    print(f"{'Width':>7}  {'Accuracy':>9}  {'Loss (pp)':>10}  {'Within budget':>14}")
    print(f"{'FP32':>7}  {100 * baseline_accuracy:>8.2f}%  {'-':>10}  {'-':>14}")

    for bit_width, accuracy in results:
        loss = (baseline_accuracy - accuracy) * 100
        within = "yes" if loss <= MAX_QUANT_LOSS_PP else "no"

        print(f"{bit_width:>7}  {100 * accuracy:>8.2f}%  {loss:>10.2f}  {within:>14}")

    print(f"\nWe take the narrowest width whose loss stays within {MAX_QUANT_LOSS_PP} pp.")


def select_width(baseline_accuracy, results):
    """The narrowest width inside the budget, or None if every width missed it."""
    within = [
        bit_width
        for bit_width, accuracy in results
        if (baseline_accuracy - accuracy) * 100 <= MAX_QUANT_LOSS_PP
    ]

    return min(within) if within else None
