#!/usr/bin/env python3
"""measure_power.py -- what the board draws, and how much of it is ours.

Four regimes against the same instrument:

    idle         overlay loaded, PL clocked, nothing submitted
    spin         the busy-wait loop, running, with the PL never started
    continuous   back-to-back inference, 100 % duty -- an upper bound
    duty         POWER_PLAYERS inferences per stride, paced -- the real case

`spin` is the control that makes the rest mean something. infer() waits for
ap_done by polling, which pins a core at 100 %, so a naive idle-to-continuous
delta is the CPU spinning plus the PL computing, added together and
indistinguishable. With spin in hand:

    spin       - idle   the cost of the busy-wait
    continuous - spin   the cost of the accelerator actually computing

It slightly over-states the busy-wait: spin polls for the whole block where
continuous polls for about 84 % of one, the rest going on the buffer copy and
the cache maintenance. So continuous - spin is a mild under-estimate of the
accelerator, which is the safer direction to err.

**Regimes are interleaved, not run back to back.** The deltas of interest are
tens of milliwatts and the 3V3 rail alone wanders by ~170 mW -- it carries the
WiFi radio -- so a single long block per regime cannot distinguish a small
signal from the rail drifting. Each regime is measured in POWER_BLOCKS short
blocks spread across the run, and drift lands on all of them equally.

Two more things to read the output with:

  - `sum of rails` is indicative only. Whether these rails are disjoint is a
    board question, and 3V3's wander is larger than everything being measured.
    `INT` is the PL figure and `PSINT_FP` is the host figure; quote those.
  - This is Vivado's counterpart, and as of 2026-09-21 it is the only half
    there is. Vivado's estimate is vectorless -- it guesses switching activity
    and comes out ~3x this rail. Annotating it with activity recorded from
    cosim was tried and does not work: synthesis does not preserve HLS's net
    names, so 0 of 23,417 nets matched. What measures the supply is here; what
    would say where inside the PL it goes would need the implemented netlist
    simulated, which was judged not worth it. Quote both, with that reason.
  - Die temperature is logged per regime, from thermal.py. It is not a result
    in itself -- it is the evidence that the deltas above are a load
    difference rather than a thermal ramp, which a passively cooled board
    cannot otherwise rule out.

    python3 measure_power.py         all four regimes
    python3 measure_power.py duty    one named regime
"""

import sys
import time

import numpy as np

import thermal
from nn_driver import NNDriver
from power import PowerMonitor, combine, rails_or_explain
from u96_config import (
    AP_DONE,
    CTRL,
    GOLDEN_GLOB,
    POWER_BLOCKS,
    POWER_PLAYERS,
    POWER_SAMPLE_INTERVAL,
    POWER_SECONDS,
    POWER_SETTLE_SECONDS,
    STRIDE_SECONDS,
    one,
)


def workload_windows(nn):
    """What to feed the accelerator while measuring.

    Real windows where the run has them. Switching activity depends on the
    data, so an all-zeros input would understate the dynamic power this whole
    exercise exists to measure.
    """
    try:
        path = one(GOLDEN_GLOB, nn.build_dir)
    except SystemExit:
        rng = np.random.default_rng(0)
        shape = (64, nn.desc.channels, nn.desc.window)
        span = nn.desc.quant_input
        windows = rng.integers(
            span.clamp_low, span.clamp_high + 1, shape, dtype=np.int8
        )

        return "random (no golden set in this run)", windows

    return path.name, np.load(path)["windows"]


# --- one block of one regime ------------------------------------------------
#
# Each returns (recording, work done, seconds spent busy). "Work" is counted in
# whatever unit the regime does -- inferences, or polls for spin -- and the
# caller labels it.


def block_idle(nn, monitor, windows, seconds):
    return monitor.record(seconds, POWER_SAMPLE_INTERVAL), 0, 0.0


def block_spin(nn, monitor, windows, seconds):
    """The poll loop from infer(), with nothing ever started.

    Reading CTRL is exactly what the busy-wait does. ap_start is never written,
    so ap_done never asserts and the PL stays idle while the core does the same
    work it would do while waiting.
    """
    polls = 0
    deadline = time.perf_counter() + seconds

    with monitor.recording(POWER_SAMPLE_INTERVAL) as result:
        started = time.perf_counter()
        while time.perf_counter() < deadline:
            nn.mmio.read(CTRL) & AP_DONE
            polls += 1
        busy = time.perf_counter() - started

    return result[0], polls, busy


def block_continuous(nn, monitor, windows, seconds):
    """Back to back, as fast as the host can submit. The upper bound."""
    count = 0
    deadline = time.perf_counter() + seconds

    with monitor.recording(POWER_SAMPLE_INTERVAL) as result:
        started = time.perf_counter()
        while time.perf_counter() < deadline:
            nn.infer(windows[count % len(windows)])
            count += 1
        busy = time.perf_counter() - started

    return result[0], count, busy


def block_duty(nn, monitor, windows, seconds):
    """POWER_PLAYERS inferences per stride, then wait for the next one.

    Both players' windows close on the same boundary, so the inferences go back
    to back and the slack follows them rather than being spread evenly.
    """
    count = 0
    busy = 0.0
    started = time.perf_counter()
    deadline = started + seconds
    stride = 0

    with monitor.recording(POWER_SAMPLE_INTERVAL) as result:
        while time.perf_counter() < deadline:
            t0 = time.perf_counter()
            for _ in range(POWER_PLAYERS):
                nn.infer(windows[count % len(windows)])
                count += 1
            busy += time.perf_counter() - t0

            stride += 1
            remaining = started + stride * STRIDE_SECONDS - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)

    return result[0], count, busy


REGIMES = {
    "idle": (block_idle, ""),
    "spin": (block_spin, "polls"),
    "continuous": (block_continuous, "inferences"),
    "duty": (block_duty, "inferences"),
}


def report_temperature(temperatures, order):
    """Die temperature per regime -- the caveat the watts need to be read with.

    The board is passively cooled and static power rises with temperature, so
    an idle reading taken cold against a loaded reading taken hot overstates
    the difference between them. Interleaving the regimes already defends
    against that; this is how you check it worked. A spread of a degree or two
    across regimes means the deltas above are a load difference. A larger one
    means they are partly a thermal ramp, and the run should be repeated after
    the board has settled.
    """
    labels = sorted({label for per in temperatures.values() for r in per for label in r})
    if not labels:
        return

    width = max(len(label) for label in labels) + 2
    print(f"\n{'die':<{width}}" + "".join(f"{n:>22}" for n in order))

    for label in labels:
        cells = ""
        for name in order:
            values = [r[label] for r in temperatures[name] if r[label] == r[label]]
            if values:
                cells += f"{sum(values) / len(values):>15.1f} C  max{max(values):5.1f}"
            else:
                cells += f"{'--':>22}"
        print(f"{label:<{width}}{cells}")


def report(results, order):
    """Per-rail means, then the deltas, then the decomposition."""
    rails = sorted(results[order[0]]["recording"].readings)
    width = max(len(r) for r in rails) + 2

    print(f"\n{'rail':<{width}}" + "".join(f"{n:>22}" for n in order))

    for rail in rails:
        cells = ""
        for name in order:
            reading = results[name]["recording"].readings[rail]
            cells += f"{reading.mean:>14.3f} W +/-{reading.spread / 2:5.3f}"
        print(f"{rail:<{width}}{cells}")

    cells = "".join(
        f"{results[n]['recording'].total:>14.3f} W      " for n in order
    )
    print(f"{'sum of rails':<{width}}{cells}")

    if "idle" not in results:
        return

    base = results["idle"]["recording"]

    print("\ndelta against idle, per rail:")
    for name in order:
        if name == "idle":
            continue
        deltas = results[name]["recording"].delta(base)
        parts = ", ".join(
            f"{rail} {w:+.3f}" for rail, w in sorted(deltas.items()) if abs(w) >= 0.001
        )
        print(f"  {name:<12} {sum(deltas.values()):+.3f} W total")
        print(f"  {'':<12} {parts or 'nothing above 1 mW'}")

    if "spin" in results and "continuous" in results:
        spin = results["spin"]["recording"]
        cont = results["continuous"]["recording"]

        busy = {r: spin.readings[r].mean - base.readings[r].mean for r in rails}
        accel = {r: cont.readings[r].mean - spin.readings[r].mean for r in rails}

        print("\nthe decomposition:")
        print(f"  busy-wait alone    {sum(busy.values()):+.3f} W total, "
              f"PSINT_FP {busy.get('PSINT_FP', float('nan')):+.3f}")
        print(f"  accelerator alone  {sum(accel.values()):+.3f} W total, "
              f"INT {accel.get('INT', float('nan')):+.3f}")
        print("\n  The second line is the accelerator's cost at 100 % duty, with")
        print("  the polling that would otherwise be counted with it removed.")


def main(only=None):
    order = list(REGIMES) if only is None else [only]
    seconds = POWER_SECONDS / POWER_BLOCKS

    rails = rails_or_explain()
    monitor = PowerMonitor(rails)

    # Wanted, not required. A missing AMS costs the thermal caveat, not the
    # power measurement this script exists for -- so it is named and the run
    # continues. See thermal.find().
    thermometer, why_not = thermal.find()

    with NNDriver() as nn:
        source, windows = workload_windows(nn)

        print(f"bitstream  {nn.bitstream.name}")
        print(f"contract   {nn.desc}")
        print(f"rails      {', '.join(sorted(monitor.rails))}")
        if monitor.dropped:
            print(
                f"           ({len(monitor.dropped)} without a power sensor "
                f"ignored: {', '.join(monitor.dropped)})"
            )
        print(f"thermal    {thermometer if thermometer else why_not}")
        print(f"workload   {source}, {len(windows)} windows")
        print(
            f"pacing     {POWER_PLAYERS} inferences per "
            f"{STRIDE_SECONDS * 1e3:.0f} ms stride"
        )
        print(
            f"recording  {POWER_BLOCKS} x {seconds:.1f} s per regime, "
            f"interleaved, {POWER_SETTLE_SECONDS:.0f} s settling before each, "
            f"every {POWER_SAMPLE_INTERVAL * 1e3:.0f} ms"
        )

        # Warm the path once so no block pays a first-call cost.
        nn.infer(windows[0])

        blocks = {name: [] for name in order}
        work = {name: 0 for name in order}
        busy = {name: 0.0 for name in order}
        temperatures = {name: [] for name in order}

        for round_ in range(POWER_BLOCKS):
            print(f"\nblock {round_ + 1}/{POWER_BLOCKS} ", end="", flush=True)
            for name in order:
                run, _ = REGIMES[name]
                time.sleep(POWER_SETTLE_SECONDS)
                recording, count, spent = run(nn, monitor, windows, seconds)

                blocks[name].append(recording)
                work[name] += count
                busy[name] += spent

                # Read at the end of the block, not the start: that is where
                # the regime has actually been running for `seconds`, so it is
                # the temperature the watts just above were drawn at.
                if thermometer is not None:
                    temperatures[name].append(thermometer.read())

                print(f" {name}", end="", flush=True)

        print()

    results = {}
    for name in order:
        recording = combine(blocks[name])
        results[name] = {"recording": recording}

        unit = REGIMES[name][1]
        detail = f"{recording.samples} samples over {recording.seconds:.1f} s"
        if unit:
            rate = work[name] / recording.seconds
            detail += f", {work[name]} {unit} ({rate:.0f}/s"
            detail += f", {100 * busy[name] / recording.seconds:.1f} % busy)"
        print(f"{name:<12} {detail}")

    report(results, order)
    report_temperature(temperatures, order)


if __name__ == "__main__":
    arg = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg not in REGIMES:
            raise SystemExit(f"usage: {sys.argv[0]} [{' | '.join(REGIMES)}]")
    main(arg)
