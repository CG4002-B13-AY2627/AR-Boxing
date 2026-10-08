#!/usr/bin/env python3
"""latency.py -- the whole latency commitment, measured, in one table.

Two halves of the critical path are ours, and each already has a script that
owns it: bench.py the accelerator and its driver, budget.py the PS work around
them. This runs both in one sitting and adds them up against the number we
actually committed to -- 50 ms from punch peak to label emitted.

    punch peak
      |
      |  window completion   <= 40 ms   structural: a peak lands uniformly
      |                                 inside a stride, so it waits one
      v                                 stride at worst and half on average
    window closes
      |
      |  PS   <= 8 ms   budget.py   windowing, preprocess, postprocess
      |  PL   <= 2 ms   bench.py    copy, flush, PL wait, invalidate
      v
    label emitted                   <= 50 ms

**The two halves are timed in separate loops, and the p99 row is therefore a
sum of p99s rather than a jointly measured one.** That assumes both tails land
on the same window, which is pessimistic -- and pessimistic is the right
direction for a number quoted as a commitment. Measuring them jointly would
not be more honest, only slower: at a 6.8 % duty cycle there is no contention
between the two, and the real path hits a *warmer* cache than the benchmark
does, since Preprocess writes the window immediately before copy reads it.

    python3 latency.py          BENCH_ITERATIONS each half
    python3 latency.py 200      fewer, for a quick look
"""

import sys

import numpy as np

import budget
import commitment
from bench import measure as measure_pl
from nn_driver import NNDriver
from u96_config import BENCH_ITERATIONS, LATENCY_BUDGET_MS
from verify import load_golden

HEAD = f"{'half':<5}{'owns':<34}{'bound':>8}{'mean':>9}{'p99':>9}   state"
RULE = "-" * len(HEAD)


def row(r):
    """Print one line of the table.

    Every bounded row is checked by commitment.missed(), not just the last --
    which is the failure the PS row would otherwise hide: 40 ms of the 50 is
    window completion, so the PS half can miss 8 ms while the total still
    passes.
    """
    if r.structural:
        state = "structural"
    else:
        state = "ok" if r.p99 <= r.bound else "OVER"

    print(f"{r.half:<5}{r.owns:<34}{r.bound:8.3f}{r.mean:9.3f}{r.p99:9.3f}   {state}")


def main(iterations=BENCH_ITERATIONS):
    with NNDriver() as nn:
        path, windows, expect, _ = load_golden(nn.build_dir, nn.desc.sha256)

        print(f"bitstream  {nn.bitstream.name}")
        print(f"contract   {nn.desc}")
        print(f"cpu        {budget.cpu_note()}")
        print(f"driving    {path.name}, cycling {len(windows)} real windows")
        print(f"iterations {iterations} per half\n")

        # PL first: its warmup replays the golden set and refuses to time a
        # datapath that is returning the wrong answer. No point measuring the
        # PS half of a chain whose other half is broken.
        pl_total, _ = measure_pl(nn, windows, expect, iterations)
        ps_total, ps_phases = budget.measure(
            nn.build_dir, desc=nn.desc, iterations=iterations
        )

    table = commitment.rows(ps_total, pl_total)
    ps, pl, after, window, total = table

    print(HEAD)
    print(RULE)
    row(ps)
    row(pl)
    print(RULE)
    row(after)
    row(window)
    print(RULE)
    row(total)
    print(RULE)

    print("\nPS phases:")
    for k, label in enumerate(budget.PHASE_NAMES):
        column = ps_phases[:, k] * 1e3
        print(f"  {label:<14}mean {column.mean():7.3f}  "
              f"p99 {np.percentile(column, 99):7.3f}  ms")

    print(
        f"\np99 {total.p99:.3f} ms against the {LATENCY_BUDGET_MS:.0f} ms "
        f"commitment: {LATENCY_BUDGET_MS / total.p99:.1f}x inside."
    )
    print("The two p99s are summed, not jointly measured -- both tails are")
    print("assumed to land on the same window, which they seldom do.")

    # Every bounded row, not just the last: see row(). Non-zero so a pipeline
    # can gate on it, per the house rule for anything runnable.
    over = commitment.missed(table)
    if over:
        print()
        for r in over:
            print(f"OVER: {r.owns} -- p99 {r.p99:.3f} ms against {r.bound:.3f}.")
        raise SystemExit(1)


if __name__ == "__main__":
    arg = BENCH_ITERATIONS
    if len(sys.argv) > 1:
        try:
            arg = int(sys.argv[1])
        except ValueError:
            raise SystemExit(f"usage: {sys.argv[0]} [n_iterations]")
    main(arg)
