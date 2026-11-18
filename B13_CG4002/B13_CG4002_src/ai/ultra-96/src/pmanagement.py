#!/usr/bin/env python3
import itertools
import json
import sys
import time
from datetime import datetime, timezone

import pm_measure
import pm_radios
import pm_rank
import pm_report
import thermal
from commitment import PL_OWNS
from nn_driver import NNDriver
from pm_guard import Deadman, Guard, give_back, read_snapshot
from pm_knobs import board_knobs
from power import PowerMonitor, rails_or_explain
from u96_config import (
    DEADMAN_MARGIN_SECONDS,
    PM_DIR_NAME,
    PM_QUICK_BLOCKS,
    PM_REGIMES,
    POWER_BLOCKS,
    RADIO_RAIL,
    RADIO_SETTLE_SECONDS,
    REPORT_NAME,
    RESTORE_NAME,
    RESULTS_NAME,
)
from verify import load_golden

COLUMN = 11
USAGE = "usage: pmanagement.sh [sweep|apply|restore] [--quick]"


class RadioRefused(Exception):
    pass


def say(label, text=""):
    print(f"{label:<{COLUMN}}{text}", flush=True)


def setting(knobs, values):
    return " · ".join(k.label(v) for k, v in zip(knobs, values))


def save(stamp, results):
    report, data = stamp / REPORT_NAME, stamp / RESULTS_NAME
    data.write_text(json.dumps(results, indent=2, default=float), encoding="utf-8")
    pm_report.write(report, results)
    for path in (stamp, report, data):
        give_back(path)
    return report


def pick(title, options):
    print()
    say("pick", title)
    for i, text in enumerate(options, 1):
        print(f"{'':<{COLUMN}}{i:>3}  {text}")
    print(f"{'':<{COLUMN}}{0:>3}  none -- leave it as the run found it")

    if not sys.stdin.isatty():
        say("", "no terminal to answer on, so: none")
        return None

    while True:
        try:
            answer = input(f"{'':<{COLUMN}}choice [0-{len(options)}]: ").strip()
        except EOFError:
            return None
        if answer in ("", "0"):
            return None
        if answer.isdigit() and int(answer) <= len(options):
            return int(answer) - 1
        say("", "not one of the options")


def restore_or_die(guard, names=None):
    if not guard.restore(names):
        failed = ", ".join(f"{name} ({exc})" for name, exc in guard.failed)
        raise SystemExit(f"could not restore {failed}. Run pmanagement.sh restore.")


# --- the knobs --------------------------------------------------------------


def grid(knobs, snapshot):
    combos = list(itertools.product(*(k.settings() for k in knobs)))
    start = tuple(k.setting_of(snapshot[k.name]) for k in knobs)
    return combos, start, start in combos


def narrate(i, n, entry):
    good, total = entry["checked"]
    text = f"{entry['setting']}   golden {good}/{total}"
    if "latency" in entry:
        text += (f"   PL p99 {pm_rank.row(entry, PL_OWNS)['p99']:.3f}"
                 f"   peak->label p99 {pm_rank.total(entry):.2f} ms")
    if "rails" in entry:
        text += f"   score {pm_rank.score(entry):.3f} W"
    verdict = "eligible" if pm_rank.eligible(entry) else "; ".join(pm_rank.reasons(entry))
    say(f"{i}/{n}", f"{text}   {verdict}")


def sweep_knobs(nn, knobs, guard, monitor, thermometer, windows, expect, blocks):
    names = [k.name for k in knobs]
    combos, start, in_grid = grid(knobs, guard.snapshot)
    todo = combos if in_grid else [start] + combos
    points = []

    for i, combo in enumerate(todo, 1):
        restore_or_die(guard, names)
        for k, value in zip(knobs, combo):
            k.apply(value)

        entry = pm_measure.point(nn, monitor, windows, expect, blocks, thermometer)
        entry["requested"] = dict(zip(names, combo))
        entry["setting"] = setting(knobs, combo)
        entry["achieved"] = {k.name: k.label(k.read()) for k in knobs}
        if combo == start:
            entry["start"] = True
            entry["in_grid"] = in_grid
        narrate(i, len(todo), entry)
        points.append(entry)

    restore_or_die(guard, names)
    return points


def config_options(points):
    order = pm_rank.ranked(points)
    front = {id(p) for p in pm_rank.pareto(points)}
    start = next((p for p in points if p.get("start")), None)
    options = []
    for rank, p in enumerate(order):
        tags = []
        if rank == 0:
            tags.append("lowest power")
        if id(p) in front:
            tags.append("speed/power front")
        if p is start:
            tags.append("start")
        options.append(
            f"{p['setting']:<34} score {pm_rank.score(p):.3f} W   "
            f"peak->label p99 {pm_rank.total(p):6.2f} ms   "
            f"{pm_report.versus(p, start):<24} {', '.join(tags)}"
        )
    return order, options


def apply_config(nn, knobs, entry, windows, expect):
    for k in knobs:
        say("now", f"{k.name}: {k.apply(entry['requested'][k.name])}")
    confirmation = pm_measure.check(nn, windows, expect)
    good, n = confirmation["checked"]
    text = f"golden {good}/{n}"
    if "latency" in confirmation:
        text += f", peak->label p99 {pm_rank.total(confirmation):.2f} ms"
    if not pm_rank.holds(confirmation):
        text += " -- " + "; ".join(pm_rank.reasons(confirmation))
    say("check", text)
    return pm_rank.holds(confirmation), text


def choose_config(nn, knobs, guard, points, windows, expect):
    order, options = config_options(points)
    if not order:
        say("pick", "no configuration was eligible, so there is nothing to apply")
        return None
    choice = pick("which configuration to leave the board in", options)
    if choice is None:
        restore_or_die(guard, [k.name for k in knobs])
        say("kept", "the starting configuration")
        return None

    entry = order[choice]
    print()
    ok, text = apply_config(nn, knobs, entry, windows, expect)
    if not ok:
        say("refused", "it no longer holds the bounds -- putting the start back")
        restore_or_die(guard, [k.name for k in knobs])
        return None
    return {"setting": entry["setting"], "requested": entry["requested"], "confirmation": text}


# --- the radios -------------------------------------------------------------


def radio_links(radios):
    links = pm_radios.links()
    inventory = pm_radios.inventory()

    print()
    for iface in inventory["interfaces"]:
        kind = "wireless" if iface["wireless"] else "wired"
        say("interface", f"{iface['name']}  {kind}, {iface['driver'] or 'no driver'}, "
                         f"{iface['operstate']}")
    say("rfkill", ", ".join(f"{r['entry']} {r['type']} {r['name']}" for r in inventory["rfkill"])
        or "none exposed")
    say("bluetooth", ", ".join(inventory["bluetooth"]) or "no hci device")
    say("session", f"{links['peer'] or 'unknown peer'} via {links['session'] or 'unknown'}")
    say("default", f"via {links['default'] or 'no default route'}")
    say("radios", ", ".join(f"{r.name} ({r.control})" for r in radios) or "none controllable")
    return links, inventory


def refusal(radio, links):
    if not radio.controllable():
        return "not controllable here (absent, or hard-blocked)"
    if radio.disabled():
        return "already off"
    carried = radio.carries([links["session"], links["default"]])
    if carried:
        return f"{', '.join(carried)} carries this session or the default route"
    return None


def measure_radios(nn, guard, deadman, monitor, windows, expect, subset, rounds):
    names = [r.name for r in subset]
    entry = {"subset": names, "control": " + ".join(r.control for r in subset)}
    seconds = pm_measure.round_seconds() + DEADMAN_MARGIN_SECONDS
    fired = []

    def disable():
        deadman.arm(subset, guard.snapshot, seconds)
        for r in subset:
            r.disable()
        if not all(r.disabled() for r in subset):
            raise RadioRefused("the control was written but the radio reads back as on")

    def enable():
        guard.restore(names)
        if deadman.disarm():
            fired.append(True)
        if guard.failed:
            raise SystemExit(f"could not restore {names}: {guard.failed}")

    print()
    say("radios", f"{' + '.join(names)} off, by {entry['control']}")
    say("", f"a dead-man timer restores it after {seconds:.0f} s if this session is lost")
    try:
        disable()
        time.sleep(RADIO_SETTLE_SECONDS)
        entry["check"] = pm_measure.check(nn, windows, expect)
        enable()
        entry["pairs"] = pm_measure.paired(nn, monitor, windows, rounds, enable, disable)
    except RadioRefused as exc:
        enable()
        entry["skipped"] = str(exc)
    if fired:
        entry["skipped"] = "the dead-man timer fired, so a round overran and was discarded"
    if "skipped" in entry:
        entry.pop("pairs", None)
        say("", f"skipped: {entry['skipped']}")
        return entry

    entry["effect"] = {regime: pm_rank.radio_effect(entry["pairs"], regime) for regime in PM_REGIMES}
    entry["restored"] = {r.name: r.label_state(r.snapshot()) for r in subset}
    duty = entry["effect"]["duty"]
    say("effect", f"board {duty['board_delta_w'] * 1e3:+.0f} ± {duty['board_se_w'] * 1e3:.0f} mW, "
                  f"{RADIO_RAIL} {duty['radio_rail_delta_w'] * 1e3:+.0f} mW at duty   "
                  + ("saving verified" if duty["verified"] else "saving not verified"))
    say("restored", ", ".join(f"{k} {v}" for k, v in entry["restored"].items()))
    return entry


def sweep_radios(nn, guard, deadman, monitor, windows, expect, radios, rounds):
    links, inventory = radio_links(radios)
    measured, usable = [], []

    for radio in radios:
        reason = refusal(radio, links)
        if reason:
            measured.append({"subset": [radio.name], "control": radio.control, "skipped": reason})
            say("skip", f"{radio.name}: {reason}")
        else:
            usable.append(radio)

    singles = {}
    for radio in usable:
        entry = measure_radios(nn, guard, deadman, monitor, windows, expect, [radio], rounds)
        singles[radio.name] = entry
        measured.append(entry)

    verified = [r for r in usable if radio_offered(singles[r.name])]
    for size in range(2, len(verified) + 1):
        for subset in itertools.combinations(verified, size):
            measured.append(
                measure_radios(nn, guard, deadman, monitor, windows, expect, list(subset), rounds)
            )

    return {"links": links, "inventory": inventory, "rounds": rounds, "measured": measured}


def radio_offered(entry):
    return ("skipped" not in entry and pm_rank.holds(entry["check"])
            and entry["effect"]["duty"]["verified"])


def choose_radios(radios, stage):
    offered = [e for e in stage["measured"] if radio_offered(e)]
    if not offered:
        print()
        say("pick", "no radio saving was verified, so the radios stay as found")
        return None

    by_name = {r.name: r for r in radios}
    links = pm_radios.links()
    options = []
    for e in offered:
        duty = e["effect"]["duty"]
        options.append(f"{' + '.join(e['subset']):<28} board {duty['board_delta_w'] * 1e3:+.0f} "
                       f"± {duty['board_se_w'] * 1e3:.0f} mW at duty")
    choice = pick("which radios to leave off", options)
    if choice is None:
        return None

    subset = [by_name[name] for name in offered[choice]["subset"] if name in by_name]
    blocked = [r for r in subset if refusal(r, links)]
    if len(subset) != len(offered[choice]["subset"]) or blocked:
        say("refused", "the board no longer matches what was measured -- radios left as found")
        return None
    for r in subset:
        r.disable()
        say("now", f"{r.name}: {r.label_state(r.snapshot())}")
    return [r.name for r in subset]


# --- the modes --------------------------------------------------------------


def sweep(nn, knobs, radios, windows, expect, quick, out, started):
    monitor = PowerMonitor(rails_or_explain())
    thermometer, why_not = thermal.find()
    blocks = PM_QUICK_BLOCKS if quick else POWER_BLOCKS
    stamp = out / started.strftime("%Y%m%dT%H%M%SZ")
    stamp.mkdir(exist_ok=True)
    deadman = Deadman(out)

    with Guard(knobs + radios, out) as guard:
        combos, _start, in_grid = grid(knobs, guard.snapshot)
        n = len(combos) + (0 if in_grid else 1)
        say("thermal", str(thermometer) if thermometer else why_not)
        say("plan", f"{n} points, {pm_measure.point_seconds(blocks) / 60:.1f} min of recording "
                    f"each: at least {n * pm_measure.point_seconds(blocks) / 60:.0f} min")
        say("undo", f"bash {out / RESTORE_NAME}, if this process dies without restoring")
        print()

        results = {
            "run": nn.run_dir.name,
            "bitstream": nn.bitstream.name,
            "contract": str(nn.desc),
            "started": started.strftime("%Y-%m-%d %H:%M"),
            "quick": quick,
            "blocks": blocks,
            "regimes": list(PM_REGIMES),
            "workload": {"windows": len(windows)},
            "knobs": [
                {"name": k.name, "why": k.why, "settings": [k.label(v) for v in k.settings()]}
                for k in knobs
            ],
            "start": {c.name: c.label_state(guard.snapshot[c.name]) for c in knobs + radios},
        }
        results["points"] = sweep_knobs(
            nn, knobs, guard, monitor, thermometer, windows, expect, blocks
        )
        save(stamp, results)

        results["picked"] = choose_config(nn, knobs, guard, results["points"], windows, expect)
        save(stamp, results)

        results["radios"] = sweep_radios(nn, guard, deadman, monitor, windows, expect,
                                         radios, blocks)
        save(stamp, results)

        results["picked_radios"] = choose_radios(radios, results["radios"])
        report = save(stamp, results)

        if results["picked"] is None and results["picked_radios"] is None:
            restore_or_die(guard)
        guard.keep()

    print()
    say("written", str(report))
    say("undo", f"pmanagement.sh restore, or bash {out / RESTORE_NAME}")
    return 0


def newest(out, bitstream):
    for path in sorted(out.glob(f"*/{RESULTS_NAME}"), reverse=True):
        results = json.loads(path.read_text(encoding="utf-8"))
        if results.get("bitstream") == bitstream and results.get("points"):
            return results, path
    return None, None


def apply(nn, knobs, radios, windows, expect, out):
    results, path = newest(out, nn.bitstream.name)
    if results is None:
        say("refused", f"no sweep of {nn.bitstream.name} here to choose from, and apply "
                       "does not measure. Run pmanagement.sh first.")
        return 1

    restore(knobs, radios, out, quiet=True)
    say("from", f"{path.parent.name}, {'quick pass' if results.get('quick') else 'full sweep'}")

    with Guard(knobs + radios, out) as guard:
        picked = choose_config(nn, knobs, guard, results["points"], windows, expect)
        chosen = choose_radios(radios, results["radios"]) if results.get("radios") else None
        if picked is None and chosen is None:
            restore_or_die(guard)
        guard.keep()

    print()
    say("undo", f"pmanagement.sh restore, or bash {out / RESTORE_NAME}")
    return 0


def restore(knobs, radios, out, quiet=False):
    snapshot = read_snapshot(out) or {}
    for control in knobs + radios:
        if control.name in snapshot:
            text = control.restore(snapshot[control.name])
        elif control in knobs:
            text = control.apply(control.settings()[0])
        else:
            control.enable()
            text = control.label_state(control.snapshot())
        if not quiet:
            say("now", f"{control.name}: {text}")
    if not quiet:
        print()
        say("restored", "to the state the last run found" if snapshot
            else "all cores, full clock, PL nominal, radios on")
    return 0


def main(argv):
    mode, quick = "sweep", False
    for arg in argv:
        if arg in ("sweep", "apply", "restore"):
            mode = arg
        elif arg == "--quick":
            quick = True
        else:
            raise SystemExit(USAGE)

    started = datetime.now(timezone.utc)

    with NNDriver() as nn:
        knobs = board_knobs()
        radios = pm_radios.discover()

        say("bitstream", nn.bitstream.name)
        say("contract", str(nn.desc))
        say("knobs", ", ".join(f"{k.name} ({len(k.settings())})" for k in knobs))
        say("radios", ", ".join(r.name for r in radios) or "none exposed")

        out = nn.run_dir / PM_DIR_NAME
        out.mkdir(exist_ok=True)
        give_back(out)

        if mode == "restore":
            return restore(knobs, radios, out)

        golden, windows, expect, _labels = load_golden(nn.build_dir, nn.desc.sha256)
        say("workload", f"{golden.name}, {len(windows)} windows")

        if mode == "apply":
            return apply(nn, knobs, radios, windows, expect, out)
        return sweep(nn, knobs, radios, windows, expect, quick, out, started)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
