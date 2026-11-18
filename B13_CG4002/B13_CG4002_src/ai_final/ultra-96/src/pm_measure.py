import time

import numpy as np

import budget
import commitment
from bench import measure as measure_pl
from measure_power import REGIMES
from power import combine
from u96_config import (
    PM_BENCH_ITERATIONS,
    PM_REGIMES,
    POWER_BLOCKS,
    POWER_SECONDS,
    POWER_SETTLE_SECONDS,
    RADIO_SETTLE_SECONDS,
)


def golden(nn, windows, expect):
    good = sum(1 for w, e in zip(windows, expect) if np.array_equal(nn.infer(w), e))
    return good, len(windows)


def latency(nn, windows, expect):
    pl_total, phases = measure_pl(nn, windows, expect, PM_BENCH_ITERATIONS)
    ps_total, _ = budget.measure(nn.build_dir, desc=nn.desc, iterations=PM_BENCH_ITERATIONS)
    table = commitment.rows(ps_total, pl_total)
    return [r._asdict() for r in table], float(phases[:, 2].mean()) * 1e3


def check(nn, windows, expect):
    good, n = golden(nn, windows, expect)
    entry = {"checked": [good, n], "bit_exact": good == n}
    if good == n:
        entry["latency"], entry["pl_wait_ms"] = latency(nn, windows, expect)
    return entry


def record(nn, monitor, windows, blocks):
    seconds = POWER_SECONDS / POWER_BLOCKS
    collected = {name: [] for name in PM_REGIMES}

    for _ in range(blocks):
        for name in PM_REGIMES:
            run, _unit = REGIMES[name]
            time.sleep(POWER_SETTLE_SECONDS)
            recording, _count, _busy = run(nn, monitor, windows, seconds)
            collected[name].append(recording)

    return {name: combine(runs) for name, runs in collected.items()}


def means(recordings):
    return {
        regime: {rail: reading.mean for rail, reading in rec.readings.items()}
        for regime, rec in recordings.items()
    }


def point(nn, monitor, windows, expect, blocks, thermometer=None):
    entry = check(nn, windows, expect)
    if entry["bit_exact"]:
        entry["rails"] = means(record(nn, monitor, windows, blocks))
        entry["temperature"] = thermometer.read() if thermometer is not None else None
    return entry


def paired(nn, monitor, windows, rounds, enable, disable):
    pairs = []
    for _ in range(rounds):
        pair = {}
        for state, switch in (("on", enable), ("off", disable)):
            switch()
            time.sleep(RADIO_SETTLE_SECONDS)
            pair[state] = means(record(nn, monitor, windows, 1))
        pairs.append(pair)
    enable()
    return pairs


def round_seconds():
    return RADIO_SETTLE_SECONDS + len(PM_REGIMES) * (
        POWER_SETTLE_SECONDS + POWER_SECONDS / POWER_BLOCKS
    )


def point_seconds(blocks):
    return blocks * len(PM_REGIMES) * (POWER_SETTLE_SECONDS + POWER_SECONDS / POWER_BLOCKS)
