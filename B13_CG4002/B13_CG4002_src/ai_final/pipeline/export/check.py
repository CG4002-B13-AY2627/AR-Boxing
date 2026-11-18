"""check.py -- everything the export can be checked on before a header exists.

Two links of the chain meet here, and one Brevitas pass over one set of windows
judges both:

    raw -> standardise -> transpose -> quantise     preprocess.py, against the
                                                    quant_input hook
    quant_input -> conv1 .. fc2 -> logits           the exported description,
                                                    against every quantizer

They are checked in that order because that is the order the data moves in. The
first is the newer of the two and the reason this file exists: golden.py reads
its input integers off the hook rather than recomputing them, so csim, cosim and
the board are all handed windows that were already quantized, and none of them
can see a quantizer that is wrong. The second has been checked since the
description was first extracted, and is what decides the rounding mode.

Nothing else in the export prints; this holds all of it, the way verify.py holds
the board's. It exits non-zero on any failure, which is what makes it usable as
a pipeline stage -- and it runs before export.sh on purpose, so a header is
never emitted from arithmetic that does not reproduce Brevitas.

    src/scripts/check.sh                    both checks, the default 200 windows
    src/scripts/check.sh --vectors 20       fewer, while debugging a specific layer
    src/scripts/check.sh --rounding trunc   what a different rounding rule would cost
"""
import json

import numpy as np
import torch

import check_config
import export_config

from check_preprocess import PreprocessCheck
from extract import extract, file_sha256, load_model
from golden import integer_logits, load_windows
from int_model import IntegerModel


def load_description(path, checkpoint):
    """The description to check: extracted now, or read off disk."""
    if path is None:
        # The normal case. Nothing on disk can be stale here, because nothing
        # on disk is read.
        return extract()

    with open(path) as f:
        description = json.load(f)

    # build/description_w{}.json is a dump rather than a pipeline stage, and it
    # is gitignored, so it can easily belong to an older checkpoint than the one
    # now in qmodel/. The hash it carries is what turns that into a loud failure
    # instead of a quiet agreement with itself.
    if description["meta"]["sha256"] != file_sha256(checkpoint):
        raise SystemExit(
            f"{path} was extracted from a different checkpoint "
            f"than {checkpoint.name}. Re-run export.py, or drop --description."
        )

    # The hash catches a stale checkpoint but not a stale schema: a description
    # written before the accumulator width was derived carries the right
    # checkpoint and no width at all.
    if "accumulator_width" not in description["meta"]:
        raise SystemExit(
            f"{path} predates the derived accumulator width. "
            f"Re-run export.py, or drop --description."
        )

    return description


def brevitas_trace(model, batch):
    """Every quantizer's output, and the float logits. One pass, shared.

    quant_input is what the pre-processing check compares against; the rest is
    what the integer model compares against. Capturing them together is what
    makes the two checks statements about the same windows.
    """
    captured = {}
    handles = []

    def make_hook(name):
        def hook(module, inputs, output):
            captured[name] = output.int().detach().cpu().numpy().astype(np.int64)
        return hook

    for name in export_config.ACTIVATIONS:
        handles.append(getattr(model, name).register_forward_hook(make_hook(name)))

    with torch.no_grad():
        logits = model(batch)

    for handle in handles:
        handle.remove()

    return captured, logits.detach().cpu().numpy()


def describe(description, checkpoint, source, rounding, count):
    meta = description["meta"]

    print(f"checkpoint  {checkpoint.name}")
    print(f"sha256      {meta['sha256']}")
    print(f"bit width   {meta['bit_width']}")
    print(
        f"input       {meta['window_size']} x {meta['num_channels']}"
        f" -> {meta['num_classes']} classes"
    )
    print(f"accumulator {meta['accumulator_width']} bits (acc_t)")
    print(f"description {source}")
    print(f"rounding    {rounding}")
    print(f"windows     {count} held out, stratified, seed {check_config.SEED}")


def report_preprocess(check, standardised, expected):
    """preprocess.py against the hook. True if it holds."""
    print("\n[1/2] preprocess.py: standardise, transpose, quantise")
    print(f"      stats      {check.stats_path}")
    print(
        f"      quantise   x{check.preprocess.to_integer:g}, round half even, "
        f"clamp [{check.preprocess.clamp_low}, {check.preprocess.clamp_high}]"
    )

    differ = check.check_stats()
    if differ:
        print(
            f"\n      FAIL  norm_stats.json is not what training fitted "
            f"({', '.join(differ)}).\n"
            "            The stats that would ship belong to a different run\n"
            "            than the weights beside them."
        )
        return False

    got, bad = check.check(standardised, expected)
    count = len(got)

    if len(bad):
        print(f"\n      FAIL  {len(bad)} of {count} windows differ from the hook.")

        # The first one, in full. A quantizer is wrong everywhere or nowhere, so
        # the remaining ones say the same thing at more length.
        sample = int(bad[0])
        difference = np.abs(got[sample].astype(np.int64) - expected[sample])
        print(
            f"            window {sample}: "
            f"{int((difference != 0).sum())} of {difference.size} elements, "
            f"max |diff| {int(difference.max())}"
        )
        print(
            "            A max |diff| of 1 is the rounding rule; a larger one is\n"
            "            the scale; values pinned at a bound are the clamp."
        )
        return False

    print(f"\n      PASS  {count}/{count} windows reproduce the quant_input hook.")
    return True


def report_int_model(model, captured, expected_logits):
    """The exported description against Brevitas. True if it holds."""
    print(f"\n[2/2] the exported description, in integers, at {model.mode}")

    mismatches, peaks = model.check(captured, expected_logits)

    # acc_t is derived from a worst-case bound. This is what the accumulators
    # actually reach on real windows, so the gap between the two right-hand
    # columns is headroom the data never uses -- the number to look at before
    # deciding the bound is too conservative.
    budget = model.budget

    print(f"\n      {'layer':<8}{'peak |acc|':>14}{'bits':>7}{'budgeted':>10}")
    for name, value in peaks.items():
        print(
            f"      {name:<8}{value:>14}{int(value).bit_length() + 1:>7}"
            f"{budget.get(name, '-'):>10}"
        )

    count = len(expected_logits)

    if mismatches:
        print(f"\n      FAIL  {len(mismatches)} of {count} windows differ.")
        for item in mismatches[:check_config.MAX_REPORTED]:
            print(
                f"            window {item.sample}: {item.stage} differs, "
                f"{item.differing} of {item.size} elements, "
                f"max |diff| {item.max_diff}"
            )

        if len(mismatches) > check_config.MAX_REPORTED:
            print(f"            ... and {len(mismatches) - check_config.MAX_REPORTED} more")

        print(
            "            The named stage is the first to differ, so the shift and\n"
            "            the clamp to look at are that layer's."
        )
        return False

    print(f"\n      PASS  {count}/{count} windows reproduce Brevitas exactly.")
    return True


def main():
    arguments = check_config.parse_arguments()

    # The checkpoint is resolved first either way: a description read off disk
    # only means anything beside the checkpoint it was extracted from.
    checkpoint, width = export_config.selected_checkpoint()

    description = load_description(arguments.description, checkpoint)
    source = arguments.description or "extracted now"

    model = load_model(checkpoint, width)

    # The same selection golden.py ships to the testbench, so this checks the
    # windows csim will actually run rather than a second draw that only looks
    # like them.
    batch, _ = load_windows(arguments.vectors)
    captured, float_logits = brevitas_trace(model, batch)

    describe(description, checkpoint, source, arguments.rounding, len(batch))

    preprocess = PreprocessCheck(description, checkpoint, arguments.run)

    # (N, T, C) is what the dataset holds and what qacnn.forward() transposes;
    # the hook sees the result of that transpose, so the check happens on its
    # side of it.
    passed = report_preprocess(
        check=preprocess,
        standardised=batch.numpy().transpose(0, 2, 1),
        expected=captured["quant_input"],
    )

    passed &= report_int_model(
        model=IntegerModel(description, arguments.rounding),
        captured=captured,
        expected_logits=integer_logits(description, float_logits),
    )

    if not passed:
        raise SystemExit("\nFAIL: the export is not usable. Nothing downstream is worth building.")

    print("\nOK: both halves of the boundary reproduce Brevitas exactly.")


if __name__ == "__main__":
    main()
