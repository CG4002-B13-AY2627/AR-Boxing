import math

import pm_rank
from u96_config import (
    LATENCY_BUDGET_MS,
    PL_BUDGET_MS,
    PL_RAIL,
    PS_BUDGET_MS,
    PS_RAIL,
    RADIO_RAIL,
    RAIL_RESOLUTION_W,
    RESTORE_NAME,
    STRIDE_SECONDS,
)
from commitment import PL_OWNS, PS_OWNS


def start_point(results):
    return next((p for p in results["points"] if p.get("start")), None)


def setting(results, p):
    return " · ".join(p["achieved"][k["name"]] for k in results["knobs"])


def versus(p, start):
    if start is None or not pm_rank.eligible(start) or "rails" not in p:
        return "--"
    mw = (pm_rank.score(p) - pm_rank.score(start)) * 1e3
    if "latency" not in p:
        return f"{mw:+.0f} mW"
    cost = 100 * (pm_rank.speed(p) / pm_rank.speed(start) - 1)
    return f"{mw:+.0f} mW, {cost:+.0f} % latency"


def cells(results, p, start):
    good, n = p["checked"]
    out = [setting(results, p), f"{good}/{n}"]
    if "latency" in p:
        out += [
            f"{pm_rank.row(p, PS_OWNS)['p99']:.3f}",
            f"{pm_rank.row(p, PL_OWNS)['p99']:.3f}",
            f"{pm_rank.total(p):.2f}",
        ]
    else:
        out += ["--"] * 3
    if "rails" in p:
        duty = p["rails"]["duty"]
        out += [
            f"{duty.get(PL_RAIL, math.nan):.3f}",
            f"{duty.get(PS_RAIL, math.nan):.3f}",
            f"**{pm_rank.score(p):.3f}**",
            f"{pm_rank.board(p):.3f}",
        ]
    else:
        out += ["--"] * 4
    out.append(versus(p, start))
    out.append("yes" if pm_rank.eligible(p) else "; ".join(pm_rank.reasons(p)))
    return "| " + " | ".join(out) + " |"


def points_table(results, points, start):
    head = " · ".join(k["name"] for k in results["knobs"])
    return [
        f"| {head} | golden | PS p99 | PL p99 | peak→label p99 | `{PL_RAIL}` | "
        f"`{PS_RAIL}` | score | board | vs start | eligible |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ] + [cells(results, p, start) for p in points]


def configurations(results):
    points = results["points"]
    start = start_point(results)
    order = pm_rank.ranked(points)
    rest = [p for p in points if not pm_rank.eligible(p)]
    lines = [
        "## Configurations",
        "",
        f"{len(points)} points: every combination of "
        + ", ".join(f"{len(k['settings'])} {k['name']} settings" for k in results["knobs"])
        + (", plus the starting configuration" if start is not None and not start.get("in_grid") else "")
        + f". **{len(order)} eligible.**",
        "",
        f"A point is eligible only if all {results['workload']['windows']} golden windows",
        "come back bit-exact and every bounded row of latency.py holds at p99: PS",
        f"≤ {PS_BUDGET_MS:.0f} ms, PL round trip ≤ {PL_BUDGET_MS:.0f} ms, both ≤ "
        f"{PS_BUDGET_MS + PL_BUDGET_MS:.0f} ms, punch peak → label ≤ {LATENCY_BUDGET_MS:.0f} ms.",
        "",
        f"**score** is `{PL_RAIL}` + `{PS_RAIL}` in the duty regime — the two rails a knob",
        f"moves and the only two quiet enough to read it off. `{RADIO_RAIL}` wanders by more",
        "than any knob saves, so **board** (every rail summed) is shown and not ranked on.",
        f"Rail resolution is about {RAIL_RESOLUTION_W * 1e3:.0f} mW; scores closer than",
        "that are not distinguishable.",
        "",
    ]
    if order:
        best = order[0]
        near = pm_rank.within_resolution(points)
        front = pm_rank.pareto(points)
        lines += [
            "### Lowest power",
            "",
            f"`{setting(results, best)}` — score **{pm_rank.score(best):.3f} W**, "
            f"punch peak → label p99 **{pm_rank.total(best):.2f} ms**, "
            f"{versus(best, start)} against the start.",
            "",
            f"This is the lowest of the {len(order)} eligible points measured here, at this",
            "workload — golden windows, two inferences per stride. It is not a claim",
            "about settings this sweep did not visit.",
            "",
            "### Speed against power",
            "",
            "Each point below is faster than every eligible point that draws less:",
            "",
        ] + points_table(results, front, start) + [""]
        if len(near) > 1:
            lines += [
                f"{len(near)} points sit within {RAIL_RESOLUTION_W * 1e3:.0f} mW of the lowest. "
                f"Of those, `{setting(results, min(near, key=pm_rank.speed))}` is the fastest.",
                "",
            ]
    lines += ["### Every eligible point, lowest score first", ""]
    lines += points_table(results, order, start) + [""]
    if rest:
        lines += ["### Not eligible", ""] + points_table(results, rest, start) + [""]
    return lines


def pl_bound(results):
    points = results["points"]
    names = [k["name"] for k in results["knobs"]]
    if "pl clock" not in names:
        return []
    rates = sorted({p["requested"]["pl clock"] for p in points}, reverse=True)
    lines = [
        "## The PL row at each PL clock",
        "",
        f"The PL round trip is held to {PL_BUDGET_MS:.0f} ms at p99. The PL wait scales as",
        "1/f while the host's copy, flush and invalidate do not, so below some clock",
        "no CPU setting can hold the row.",
        "",
        "| PL clock | points | eligible | best PL p99 | lowest clock that can hold it |",
        "|---|---|---|---|---|",
    ]
    for rate in rates:
        group = [p for p in points if p["requested"]["pl clock"] == rate and "latency" in p]
        if not group:
            continue
        best = min(group, key=lambda p: pm_rank.row(p, PL_OWNS)["p99"])
        floor = pm_rank.pl_floor_mhz(best, rate)
        lines.append(
            f"| {rate:.0f} MHz | {len(group)} | {sum(pm_rank.eligible(p) for p in group)} "
            f"| {pm_rank.row(best, PL_OWNS)['p99']:.3f} ms | ~{floor:.0f} MHz |"
        )
    lines += [
        "",
        "The last column is extrapolated from that point's own PL wait and host",
        f"overhead. A point that holds the {LATENCY_BUDGET_MS:.0f} ms total can still miss",
        f"this row: {STRIDE_SECONDS * 1e3:.0f} ms of the total is the stride, so the total",
        "alone cannot catch a PL round trip that has doubled.",
        "",
    ]
    return lines


def radios(results):
    stage = results.get("radios")
    if not stage:
        return []
    links = stage["links"]
    lines = [
        "## Radios",
        "",
        f"SSH peer `{links['peer'] or 'unknown'}` routes via `{links['session'] or 'unknown'}`; "
        f"the default route is via `{links['default'] or 'none'}`.",
        "",
        "| interface | driver | wireless | up |",
        "|---|---|---|---|",
    ]
    for iface in stage["inventory"]["interfaces"]:
        lines.append(
            f"| `{iface['name']}` | {iface['driver'] or '--'} | "
            f"{'yes' if iface['wireless'] else 'no'} | {iface['operstate']} |"
        )
    lines += [
        "",
        "rfkill: " + (", ".join(
            f"`{r['entry']}` {r['type']} {r['name']} soft {r['soft']} hard {r['hard']}"
            for r in stage["inventory"]["rfkill"]) or "none exposed") + "  ",
        "bluetooth: " + (", ".join(f"`{h}`" for h in stage["inventory"]["bluetooth"])
                         or "no hci device"),
        "",
        f"Each state is measured against the radios as found, in {stage['rounds']} paired",
        f"rounds, on then off, {RADIO_RAIL} and every rail recorded. A saving counts only",
        f"when the board total falls by more than the rail resolution"
        f" ({RAIL_RESOLUTION_W * 1e3:.0f} mW) and by more than twice its standard error.",
        f"Disabling a radio is not switching off `{RADIO_RAIL}`: that rail feeds more than",
        "the radio, so only the measured difference is a saving.",
        "",
        f"| radios off | control | golden | board Δ duty | `{RADIO_RAIL}` Δ duty | "
        "board Δ idle | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in stage["measured"]:
        if c.get("skipped"):
            lines.append(f"| {' + '.join(c['subset'])} | {c['control']} | -- | -- | -- | -- "
                         f"| skipped: {c['skipped']} |")
            continue
        duty, idle = c["effect"]["duty"], c["effect"]["idle"]
        good, n = c["check"]["checked"]
        verdict = "**saving verified**" if duty["verified"] else "not verified"
        lines.append(
            f"| {' + '.join(c['subset'])} | {c['control']} | {good}/{n} "
            f"| {duty['board_delta_w'] * 1e3:+.0f} ± {duty['board_se_w'] * 1e3:.0f} mW "
            f"| {duty['radio_rail_delta_w'] * 1e3:+.0f} mW "
            f"| {idle['board_delta_w'] * 1e3:+.0f} mW | {verdict} |"
        )
    lines.append("")
    return lines


def picked(results):
    if "picked" not in results:
        return []
    lines = ["## Left applied", ""]
    config = results["picked"]
    if config is None:
        lines.append("Knobs: none picked; the starting configuration was put back.")
    else:
        lines.append(f"Knobs: `{config['setting']}`, confirmed after applying: "
                     f"{config['confirmation']}.")
    chosen = results.get("picked_radios")
    lines.append("")
    lines.append("Radios: " + (", ".join(f"`{r}` disabled" for r in chosen)
                               if chosen else "as found."))
    lines += [
        "",
        f"`{RESTORE_NAME}` beside the sweep directories restores the state this run",
        "found, without needing Python. `pmanagement.sh restore` does the same.",
        "",
    ]
    return lines


def write(path, results):
    lines = [
        f"# Power management — {results['run']}",
        "",
        f"`{results['bitstream']}`, {results['contract']}  ",
        f"{results['started']} UTC, {'quick pass' if results['quick'] else 'full sweep'}, "
        f"{results['blocks']} interleaved blocks of "
        + ", ".join(results["regimes"]) + " per point.",
        "",
        "Started from: " + ", ".join(
            f"{name} {label}" for name, label in results["start"].items()) + ".",
        "",
    ]
    lines += configurations(results)
    lines += pl_bound(results)
    lines += radios(results)
    lines += picked(results)
    path.write_text("\n".join(lines), encoding="utf-8")
