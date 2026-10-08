from collections import namedtuple

import numpy as np

import budget
from bench import PHASE_NAMES as PL_PHASE_NAMES
from u96_config import LATENCY_BUDGET_MS, PL_BUDGET_MS, PS_BUDGET_MS, STRIDE_SECONDS

Row = namedtuple("Row", "half owns bound mean p99 structural")

PS_OWNS = ", ".join(budget.PHASE_NAMES)
PL_OWNS = ", ".join(PL_PHASE_NAMES)
AFTER_OWNS = "after the window closes"
WINDOW_OWNS = "window completion (one stride)"
TOTAL_OWNS = "punch peak -> label"


def rows(ps_seconds, pl_seconds):
    ps = np.asarray(ps_seconds) * 1e3
    pl = np.asarray(pl_seconds) * 1e3

    # A punch peak arrives uniformly inside a stride and waits for the next
    # window boundary: half a stride on average, a whole one at worst. Derived
    # from STRIDE_SECONDS rather than written down, so it cannot disagree with
    # the buffer that actually applies it.
    stride_ms = STRIDE_SECONDS * 1e3
    wait_mean, wait_p99 = stride_ms / 2, stride_ms * 0.99

    ps_p99, pl_p99 = float(np.percentile(ps, 99)), float(np.percentile(pl, 99))
    after_mean, after_p99 = float(ps.mean() + pl.mean()), ps_p99 + pl_p99

    return [
        Row("PS", PS_OWNS, PS_BUDGET_MS, float(ps.mean()), ps_p99, False),
        Row("PL", PL_OWNS, PL_BUDGET_MS, float(pl.mean()), pl_p99, False),
        Row("", AFTER_OWNS, PS_BUDGET_MS + PL_BUDGET_MS, after_mean, after_p99, False),
        Row("", WINDOW_OWNS, stride_ms, wait_mean, wait_p99, True),
        Row("", TOTAL_OWNS, LATENCY_BUDGET_MS,
            after_mean + wait_mean, after_p99 + wait_p99, False),
    ]


def missed(table):
    return [r for r in table if not r.structural and r.p99 > r.bound]
