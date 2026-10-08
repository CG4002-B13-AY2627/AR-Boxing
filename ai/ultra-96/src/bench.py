#!/usr/bin/env python3
"""bench.py -- what one inference costs a caller.

Cosim already measured the fabric. This measures the system that calls it: the
copy into the DMA buffer, the cache flush, the AXI round trip, the poll and the
invalidate. The gap between the two is host overhead, and naming that gap is
the point -- "the accelerator is fast" and "the subsystem is fast" are
different claims, and only the second one is ours to make.

The fabric figure to compare against is in the run's HLS report
(nn_infer_cosim.rpt), not restated here: a number with two homes goes stale in
one of them.

Reports p99 as well as mean. A latency commitment is a promise about the worst
case, and the interesting failure here is not a slow accelerator but the Linux
scheduler preempting the busy-wait between ap_start and ap_done.

This is the AI lane's slice of the <=100 ms budget and nothing more. PS
pre-processing is stage 7 and unmeasured; BLE and the visualizer are other
people's. Do not quote this as an end-to-end figure.

    python3 bench.py             BENCH_ITERATIONS inferences
    python3 bench.py 200         fewer, for a quick look
"""

import sys
from time import perf_counter

import numpy as np

from nn_driver import NNDriver
from u96_config import BENCH_ITERATIONS, BENCH_PERCENTILES, BENCH_WARMUP
from verify import load_golden

PHASE_NAMES = ("copy", "flush", "PL wait", "invalidate")


def summarise(name, seconds, unit="ms"):
    """One line of statistics for a vector of durations."""
    ms = np.asarray(seconds) * 1e3
    cells = [f"{name:<12}", f"mean {ms.mean():7.3f}"]
    for p in BENCH_PERCENTILES:
        cells.append(f"p{p} {np.percentile(ms, p):7.3f}")
    cells.append(f"min {ms.min():7.3f}")
    cells.append(f"max {ms.max():7.3f}")
    return "  ".join(cells) + f"  {unit}"


def measure(nn, windows, expect, iterations, warmup=BENCH_WARMUP):
    """Time `iterations` inferences. Returns (total, by_phase) in seconds.

    Prints nothing, so that latency.py can put this half of the round trip
    beside the other one rather than interleaving two scripts' output. The
    same library/script split verify.py and nn_driver.py already follow.
    """
    # Warmup pays the page faults, the cold cache and PYNQ's first MMIO so
    # the timed run does not. Its results are checked, not timed: if the
    # accelerator is returning the wrong answer there is no point timing it.
    for i in range(warmup):
        j = i % len(windows)
        if not np.array_equal(nn.infer(windows[j]), expect[j]):
            raise SystemExit(
                f"warmup vector {j} does not match the golden logits. "
                "Run verify.py -- there is no point benchmarking a "
                "datapath that is returning the wrong answer."
            )

    total = np.empty(iterations)
    phases = []

    for i in range(iterations):
        w = windows[i % len(windows)]
        t0 = perf_counter()
        nn.infer(w, phases=phases)
        total[i] = perf_counter() - t0

    return total, np.asarray(phases)


def main(iterations=BENCH_ITERATIONS):
    with NNDriver() as nn:
        path, windows, expect, _ = load_golden(nn.build_dir, nn.desc.sha256)

        print(f"bitstream  {nn.bitstream.name}")
        print(f"contract   {nn.desc}")
        print(f"driving    {path.name}, cycling {len(windows)} real windows")
        print(f"iterations {iterations} timed, {BENCH_WARMUP} warmup\n")

        total, by_phase = measure(nn, windows, expect, iterations)

    print(summarise("end to end", total))
    print()

    # Where the time goes. The PL wait is the accelerator; everything else is
    # ours, and is what a faster build would leave untouched.
    for k, label in enumerate(PHASE_NAMES):
        print(summarise("  " + label, by_phase[:, k]))

    host = total.mean() - by_phase[:, 2].mean()
    print(
        f"\nhost overhead outside the PL wait: {host * 1e3:.3f} ms mean "
        f"({100 * host / total.mean():.1f} % of the round trip)."
    )


if __name__ == "__main__":
    arg = BENCH_ITERATIONS
    if len(sys.argv) > 1:
        try:
            arg = int(sys.argv[1])
        except ValueError:
            raise SystemExit(f"usage: {sys.argv[0]} [n_iterations]")
    main(arg)
