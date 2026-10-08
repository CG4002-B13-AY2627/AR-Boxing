#!/usr/bin/env python3
"""budget.py -- what one window costs the PS, against its 8 ms slice.

bench.py measures the accelerator and the driver around it. Everything else on
the critical path is here, and until now it was the one row of the latency
table nobody had ever timed:

    WindowBuffer.push   x stride    ring writes, and the assembly copy
    Preprocess.window                standardise -> transpose -> quantise
    Postprocess.push                 softmax -> threshold -> intensity ->
                                     debounce
    ----------------------------------------------------------------
    <= 8 ms, interpreted on a Cortex-A53

A library, not a script: latency.sh is the one entry point, because the PS
number is only ever quoted beside the PL one. Printing nothing is what lets it
be, and it is the same split verify.py and nn_driver.py already follow.

Postprocess is fed real logits out of golden_w<N>.npz rather than out of the
accelerator. That is what the 8 ms row means anyway -- it is a claim about the
CPU, and the PL has its own row that bench.py owns -- and it keeps this half
measurable without programming the PL.

**The frequency is part of the result, not decoration.** The 2026-09-21 sweep
found every host phase linear in 1/f with R^2 >= 0.9995 and an intercept of
statistically zero -- these costs are fixed in CPU *cycles*, not in time, so
they are 3.6x larger at 300 MHz than at 1.2 GHz. A number quoted without the
clock it was taken at is true of one governor setting and no other, which is
why cpu_note() exists and why latency.py prints it.
"""

from time import perf_counter

import numpy as np

from description import Description
from pm_knobs import CpuFreq
from postprocess import Postprocess
from preprocess import Preprocess
from u96_config import (
    BENCH_ITERATIONS,
    BENCH_WARMUP,
    BUILD_DIR,
    DESCRIPTION_GLOB,
    one,
)
from verify import load_golden
from window import WindowBuffer

PHASE_NAMES = ("window", "preprocess", "postprocess")

SEED = 0


def cpu_note():
    """The clock these timings are true of, or why it could not be read."""
    knob = CpuFreq()

    try:
        if not knob.available():
            return "unknown (no userspace governor)"
        return knob.label(knob.read())
    except OSError as exc:
        return f"unknown ({exc})"


def measure(build_dir=BUILD_DIR, desc=None, iterations=BENCH_ITERATIONS,
            warmup=BENCH_WARMUP, seed=SEED):
    """Time the PS path over `iterations` windows.

    Returns (total, by_phase) in seconds, and prints nothing -- latency.py
    wants these numbers beside the PL's, not interleaved with them.
    """
    desc = desc or Description(one(DESCRIPTION_GLOB, build_dir))
    pre = Preprocess(build_dir, desc=desc)
    buf = WindowBuffer(desc.window, desc.channels)
    post = Postprocess(desc, pre.channel_names)

    _, _, logits, _ = load_golden(build_dir, desc.sha256)

    # Unlike test.py, the distribution genuinely does not matter here: every
    # step above is a fixed-size numpy operation over the whole window, so the
    # cost does not depend on the values. What does matter is that Postprocess
    # sees real logits, because it is the one step that branches -- on the
    # threshold, on the refractory, on whether a posture is held.
    rng = np.random.default_rng(seed)
    runs = warmup + iterations
    stream = (
        pre.mean + pre.std * rng.standard_normal(
            (buf.samples_for(runs), desc.channels)
        )
    ).astype(np.float32)

    # Prime the ring to one stride short of full, so that the very first timed
    # iteration emits a window like every one after it. Timing an iteration
    # that emitted nothing would quietly average in a cost that never occurs.
    cursor = 0
    while cursor < buf.window - buf.stride:
        buf.push(stream[cursor])
        cursor += 1

    total = np.empty(runs)
    phases = np.empty((runs, len(PHASE_NAMES)))

    for i in range(runs):
        t0 = perf_counter()

        got = None
        for _ in range(buf.stride):
            emitted = buf.push(stream[cursor])
            cursor += 1
            if emitted is not None:
                got = emitted
        t1 = perf_counter()

        if got is None:
            raise SystemExit(
                f"iteration {i}: {buf.stride} samples produced no window. "
                "The ring buffer and the stride disagree about the steady "
                "state, and every timing below it would be of the wrong work."
            )

        raw, t = got
        pre.window(raw)
        t2 = perf_counter()

        post.push(logits[i % len(logits)], raw, t)
        t3 = perf_counter()

        phases[i] = (t1 - t0, t2 - t1, t3 - t2)
        total[i] = t3 - t0

    # The warmup pays the page faults and the first-call cost of every numpy
    # path here; folding it into the mean would flatter the result and into
    # the p99 would libel it. Discarded rather than never run.
    return total[warmup:], phases[warmup:]
