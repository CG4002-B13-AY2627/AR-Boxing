#!/usr/bin/env python3
"""verify.py -- tier 4: does the silicon agree with the model.

Two halves, in this order.

First it reports what it is about to test: which build is loaded, the contract
read off its description, where the DMA buffers landed, the transform the PS
will apply to real samples, and one all-zeros inference proving the PL starts
and raises ap_done. None of that is evidence -- it is the bring-up detail that
makes a failure in the second half readable, and it is gathered here so there
is one place to run and one place to look.

Then it replays the golden set and compares the raw int32 logits bit-exactly.
Not argmax: a shift one LSB wrong, a clamp off by one or half_up where the
export settled on half_even all leave the argmax unchanged on nearly every
vector, and would surface months later as an unexplained accuracy gap on real
data.

This closes the chain Brevitas -> int_model.py -> csim -> cosim -> hardware.
Every link is checked against the one above it, so a discrepancy localises to
the transformation that introduced it. This is the only link that exercises the
real PL, the real AXI path and the real cache-flush discipline -- the three
things csim and cosim simulate away.

    python3 verify.py            all vectors
    python3 verify.py 20         first 20, for a quick check
"""

import sys

import numpy as np

from nn_driver import NNDriver
from preprocess import Preprocess
from u96_config import GOLDEN_GLOB, MAX_REPORTED, one


def describe(nn):
    """Everything worth knowing about the build before testing it.

    The zeros inference at the end is liveness, not correctness -- it proves
    the IP starts and returns, and it cannot tell a working datapath from one
    returning plausible garbage. That is what the golden replay below is for.
    """
    print(f"bitstream  {nn.bitstream.name}")
    print(f"contract   {nn.desc}")
    print(f"buffers    in {nn.x.device_address:#x}  out {nn.y.device_address:#x}")

    pre = Preprocess(nn.build_dir, desc=nn.desc)
    print(f"channels   {', '.join(pre.channel_names)}")
    print("preprocess standardise from norm_stats.json, then transpose, then")
    print(
        f"           quantise x{pre.to_integer:g}, round half even, "
        f"clamp [{pre.clamp_low}, {pre.clamp_high}]"
    )

    label, logits = nn.predict(np.zeros((nn.desc.channels, nn.desc.window), np.int8))
    print(f"liveness   zeros -> {label}  {logits.tolist()}")


def load_golden(run_dir, sha256):
    """The held-out windows and the logits the model produced for them.

    Both the npz and the description derive from the same checkpoint, so a
    sha mismatch means one build's vectors are being replayed against another
    build's bitstream. Everything after that point would be noise, so stop.
    """
    path = one(GOLDEN_GLOB, run_dir)
    z = np.load(path)

    got = str(z["sha256"].item())
    if got != sha256:
        raise SystemExit(
            f"{path.name}: built from checkpoint {got[:12]}, but the bitstream "
            f"is from {sha256[:12]}. Re-export and re-transfer -- these are "
            "different builds."
        )

    return path, z["windows"], z["logits"], z["labels"]


def main(limit=None):
    with NNDriver() as nn:
        describe(nn)

        path, windows, expect, labels = load_golden(nn.build_dir, nn.desc.sha256)

        if windows.shape[1:] != (nn.desc.channels, nn.desc.window):
            raise SystemExit(
                f"{path.name}: windows are {windows.shape[1:]}, but the "
                f"contract is ({nn.desc.channels}, {nn.desc.window})."
            )

        n = len(windows) if limit is None else min(limit, len(windows))
        print(f"\ngolden     {path.name}, {n} of {len(windows)} vectors\n")

        bad = []
        agree = 0
        worst = 0

        for i in range(n):
            got = nn.infer(windows[i])
            want = expect[i]

            if not np.array_equal(got, want):
                bad.append(i)
                worst = max(worst, int(np.abs(got.astype(np.int64) - want).max()))
                if len(bad) <= MAX_REPORTED:
                    where = np.flatnonzero(got != want).tolist()
                    print(f"  MISMATCH vector {i} ({nn.desc.labels[labels[i]]})")
                    print(f"    want {want.tolist()}")
                    print(f"    got  {got.tolist()}")
                    print(f"    classes differing: {where}")

            if int(np.argmax(got)) == int(labels[i]):
                agree += 1

    if bad:
        print(
            f"\nFAIL  {len(bad)} of {n} vectors differ "
            f"(largest logit error {worst}).\n"
            "      A uniform error points at rounding, a shift or a clamp; a\n"
            "      sparse one points at the AXI path or a missing flush."
        )
        raise SystemExit(1)

    # Secondary, and evidence of nothing on its own -- the model was trained on
    # synthetic data. It is here because a logits comparison alone still passes
    # if the class order in the description and in training are permuted the
    # same way, and this would catch that.
    print(f"PASS  {n}/{n} vectors bit-exact.")
    print(f"      argmax agrees with the golden label on {agree}/{n}.")


if __name__ == "__main__":
    arg = None
    if len(sys.argv) > 1:
        try:
            arg = int(sys.argv[1])
        except ValueError:
            raise SystemExit(f"usage: {sys.argv[0]} [n_vectors]")
    main(arg)
