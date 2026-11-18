"""Frozen input/output pairs, so the C++ can check itself where Python cannot.

int_model.py proves the exported description is arithmetically correct while
both sides are still in Python. Everything after it — Vitis csim, RTL cosim,
and eventually the board over AXI — has no Python at all, so the answers have
to travel with the questions. This writes both into a header nn_tb.cpp compiles
straight in.

The testbench compares bit exactly, not by argmax. An argmax check passes with
a shift that is one LSB wrong, and that bug then surfaces much later, on the
windows where two classes are close, with nothing left pointing at the cause.
"""

import numpy as np
import torch

import export_config

from emit import format_array, guard, provenance
from extract import load_model

from dataload import build_dataset, split_train_test
from normalize import apply_stats, load_stats


def stratified(dataset, indices, count, generator):
    """`count` windows spread evenly over the classes, rather than drawn at random.

    An unstratified draw follows the natural distribution, which is mostly
    idle, and would prove very little about block — the class where a
    misclassification costs a round rather than a point.
    """
    by_class = {}

    for index in indices:
        by_class.setdefault(int(dataset.labels[index]), []).append(int(index))

    for label in by_class:
        generator.shuffle(by_class[label])

    chosen = []

    # Round robin over the classes in a fixed order, so a class that runs out
    # early costs only its own share and the rest keep filling.
    while len(chosen) < count:
        taken = 0

        for label in sorted(by_class):
            if not by_class[label]:
                continue

            chosen.append(by_class[label].pop())
            taken += 1

            if len(chosen) == count:
                break

        if taken == 0:
            # Every class is exhausted: the held-out set is simply smaller than
            # the number asked for, which is normal on the synthetic data.
            break

    return chosen


def load_windows(count):
    """`count` held-out windows, standardised exactly as training left them.

    This lives here rather than in int_model.py so that the windows the integer
    checker validates are the same windows that ship to the testbench. Two
    copies of this selection drifting apart would stay invisible until csim
    disagreed with a check that had already passed — the one failure this whole
    export is arranged to make impossible.

    Returns (batch, labels).
    """
    dataset = build_dataset()
    _, test_indices = split_train_test(dataset)

    # The PS applies this same transform before every inference, so the vectors
    # have to carry it too or the testbench would be feeding raw IMU units.
    apply_stats(dataset, load_stats())

    generator = np.random.default_rng(export_config.GOLDEN_SEED)

    if export_config.GOLDEN_STRATIFY:
        chosen = stratified(dataset, test_indices, count, generator)
    else:
        chosen = generator.choice(
            test_indices,
            size=min(count, len(test_indices)),
            replace=False,
        ).tolist()

    batch = torch.stack([dataset[index][0] for index in chosen])
    labels = [int(dataset.labels[index]) for index in chosen]

    return batch, labels


def boundary(model, batch):
    """What the PL is handed, and what it has to produce.

    The input integers are read off the quant_input hook rather than recomputed
    from its scale. Reimplementing Brevitas' input quantization here would be
    exactly the kind of assumption int_model.py exists to remove, and it would
    be reimplemented in the one place nothing downstream could catch it.
    """
    captured = {}

    def hook(module, inputs, output):
        captured["quant_input"] = (
            output.int().detach().cpu().numpy().astype(np.int64)
        )

    handle = model.quant_input.register_forward_hook(hook)

    with torch.no_grad():
        logits = model(batch)

    handle.remove()

    return captured["quant_input"], logits.detach().cpu().numpy()


def integer_logits(description, float_logits):
    """fc2 emits raw accumulators, so the header stores integers, not floats.

    Nothing requantizes the logits — argmax is scale invariant — so the scale
    to divide by is fc2's accumulator scale, the same one int_model.py compares
    against.
    """
    log2_scale = next(
        layer["accumulator_log2_scale"]
        for layer in description["layers"]
        if layer["name"] == "fc2"
    )

    return np.round(float_logits / 2.0**log2_scale).astype(np.int64)


def render(description, windows, logits, labels):
    meta = description["meta"]
    width = meta["bit_width"]

    filename = export_config.GOLDEN_NAME.format(width)
    name = guard(filename)
    params_include = export_config.PARAMS_NAME.format(width)

    count = len(labels)
    cosim = min(export_config.GOLDEN_COSIM_VECTORS, count)

    parts = [
        provenance(meta, tool="golden.py"),
        "",
        f"#ifndef {name}",
        f"#define {name}",
        "",
        f'#include "{params_include}"',
        "",
        "// Held-out windows and the logits Brevitas produced for them.",
        "// Compare bit exactly, not by argmax: an argmax check passes with a",
        "// shift that is one LSB wrong.",
        "",
        f"#define GOLDEN_N        {count}",
        # Cosim runs a prefix of this same array rather than a second draw, so
        # the two tiers can never disagree about which windows they ran.
        "// Cosim is slow, so it runs the first GOLDEN_COSIM_N of the same",
        "// vectors. The draw is stratified, so a prefix still covers the",
        "// classes rather than favouring whichever came first.",
        f"#define GOLDEN_COSIM_N  {cosim}",
        "",
        format_array(
            name="golden_in",
            ctype="quant_input_t",
            values=windows.tolist(),
            comment=(
                "Input windows, channel-major, already quantized. Index "
                "[v][c][t] = (v * NN_CH + c) * NN_WINDOW + t"
            ),
        ),
        "",
        format_array(
            name="golden_out",
            ctype="acc_t",
            values=logits.tolist(),
            comment="Expected raw fc2 accumulators. Index [v][k] = v * NN_CLASSES + k",
        ),
        "",
        format_array(
            name="golden_label",
            ctype="int",
            values=labels,
            comment="True class per vector, so a failure names an action rather than an index",
        ),
        "",
        f"#endif  // {name}",
    ]

    return "\n".join(parts) + "\n"


def archive(description, windows, logits, labels, path):
    """The same vectors as a .npz, for the board.

    The header is C array initialisers, which nothing on the Ultra96 can read.
    Written from the arrays the header was rendered from, in the same call, so
    the two can never end up being different draws.
    """
    np.savez(
        path,
        windows=windows.astype(np.int8),
        logits=logits.astype(np.int32),
        labels=np.asarray(labels, dtype=np.int32),
        sha256=description["meta"]["sha256"],
    )


def golden(description, out_dir=None):
    """Write the golden header and its .npz counterpart. Returns both paths.

    The checkpoint is resolved the same way extract() resolved it, so an
    override set for a width sweep reaches the vectors as well as the weights.
    """
    path, width = export_config.selected_checkpoint()
    model = load_model(path, width)

    batch, labels = load_windows(export_config.GOLDEN_CSIM_VECTORS)
    windows, float_logits = boundary(model, batch)
    logits = integer_logits(description, float_logits)

    out_dir = out_dir or export_config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    file_path = out_dir / export_config.GOLDEN_NAME.format(width)

    with open(file_path, "w") as f:
        f.write(render(
            description=description,
            windows=windows,
            logits=logits,
            labels=labels,
        ))

    npz_path = out_dir / export_config.GOLDEN_NPZ_NAME.format(width)
    archive(description, windows, logits, labels, npz_path)

    return [file_path, npz_path]
