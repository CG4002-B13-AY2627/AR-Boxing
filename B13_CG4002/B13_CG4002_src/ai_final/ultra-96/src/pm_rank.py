import math

from commitment import AFTER_OWNS, PL_OWNS, TOTAL_OWNS
from u96_config import PL_BUDGET_MS, PL_RAIL, PS_RAIL, RADIO_RAIL, RAIL_RESOLUTION_W


def row(entry, owns):
    return next(r for r in entry["latency"] if r["owns"] == owns)


def missed(entry):
    return [r for r in entry.get("latency", []) if not r["structural"] and r["p99"] > r["bound"]]


def holds(entry):
    return entry["bit_exact"] and "latency" in entry and not missed(entry)


def eligible(entry):
    return holds(entry) and "rails" in entry


def reasons(entry):
    if not entry["bit_exact"]:
        good, n = entry["checked"]
        return [f"golden {good}/{n}"]
    return [
        f"{r['half'] or r['owns']} p99 {r['p99']:.3f} > {r['bound']:.3f} ms"
        for r in missed(entry)
    ]


def score(entry, regime="duty"):
    rails = entry["rails"][regime]
    return rails.get(PL_RAIL, math.nan) + rails.get(PS_RAIL, math.nan)


def board(entry, regime="duty"):
    return sum(entry["rails"][regime].values())


def speed(entry):
    return row(entry, AFTER_OWNS)["p99"]


def total(entry):
    return row(entry, TOTAL_OWNS)["p99"]


def ranked(points):
    return sorted((p for p in points if eligible(p)), key=score)


def pareto(points):
    front, fastest = [], math.inf
    for p in ranked(points):
        if speed(p) < fastest:
            front.append(p)
            fastest = speed(p)
    return front


def within_resolution(points):
    order = ranked(points)
    if not order:
        return []
    floor = score(order[0])
    return [p for p in order if score(p) - floor <= RAIL_RESOLUTION_W]


def pl_floor_mhz(entry, pl_mhz):
    pl = row(entry, PL_OWNS)
    wait = entry["pl_wait_ms"]
    host = pl["p99"] - wait
    room = PL_BUDGET_MS - host
    return pl_mhz * wait / room if room > 0 else math.inf


def _stats(values):
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, math.nan
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(var / n)


def radio_effect(pairs, regime="duty"):
    boards = [sum(p["off"][regime].values()) - sum(p["on"][regime].values()) for p in pairs]
    radio = [
        p["off"][regime].get(RADIO_RAIL, math.nan) - p["on"][regime].get(RADIO_RAIL, math.nan)
        for p in pairs
    ]
    board_mean, board_se = _stats(boards)
    radio_mean, radio_se = _stats(radio)
    floor = max(RAIL_RESOLUTION_W, 2 * board_se) if not math.isnan(board_se) else math.inf
    return {
        "rounds": len(pairs),
        "board_delta_w": board_mean,
        "board_se_w": board_se,
        "radio_rail_delta_w": radio_mean,
        "radio_rail_se_w": radio_se,
        "threshold_w": floor,
        "verified": -board_mean > floor,
    }
