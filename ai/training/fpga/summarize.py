#!/usr/bin/env python3
"""summarize.py -- the builds A-D comparison, rendered from one archived run.

    python summarize.py out/all/<name>
    python summarize.py out/all/<name> -o somewhere/else.md

Reads out/all/<run>/builds/<X>/ -- the layout all.sh and all.bat write -- and
writes its summary/summary.md. scripts/sweep.py reuses the readers below over its
own widths/<N>/ directories, which have the same shape. all.sh runs it as its last stage, but it
is deliberately re-runnable afterwards: rendering is cheap and the archive is
the only input, so a better table never means another four hours of synthesis.

Nothing here is required to succeed. A build that died in HLS has no Vivado
column and a build that died before synthesis has no HLS column, and that
absence *is* the result -- every cell with no source renders as a dash rather
than raising. The only fatal error is a directory that is not a run.

Stdlib only, on purpose: it runs from whatever interpreter is at hand, without
src/.venv having to exist.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DASH = "--"

# The order the builds are compared in. Not the order they are found in: a run
# missing one must still line its columns up with a run that has them all.
BUILD_ORDER = ["A", "B", "C", "D", "E"]

# Every comparison is against this one, because it is the build with no
# directives at all -- the thing the other three are an optimisation *of*.
BASELINE = "A"


# --- reading ----------------------------------------------------------------


def read_text(path):
    """File contents, or None. Vivado's encoding is not always what it claims."""
    if path is None:
        return None

    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def first(directory, pattern):
    """The one file matching pattern, or None. Sorted, so it is repeatable."""
    matches = sorted(Path(directory).glob(pattern))
    return matches[0] if matches else None


def read_status(path):
    """builds/<X>/status.txt -- `key value` lines, written by the runner."""
    status = {}
    text = read_text(path)

    if text is None:
        return status

    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            status[parts[0]] = parts[1].strip()

    return status


# --- HLS: synthesis ---------------------------------------------------------


def metrics_from_sol_data(path):
    """Per-module latency, timing, loops and area, from sol/sol_data.json.

    The preferred source because it is one structured file holding every
    module. The top-level csynth report is top-function only, and the moment a
    build pipelines a loop that loop is lifted into a submodule report -- so
    the achieved II, which is the entire point of this comparison, leaves the
    one file the single-build pipeline archives.
    """
    text = read_text(path)
    if text is None:
        return None

    try:
        data = json.loads(text)
        modules = data["ModuleInfo"]["Metrics"]
    except (ValueError, KeyError, TypeError):
        return None

    top = data.get("Top")
    if top not in modules:
        return None

    return {
        "source": "sol_data.json",
        "period": data.get("ClockInfo", {}).get("ClockPeriod", ""),
        "modules": modules,
        "top": top,
    }


def metrics_from_xml(directory):
    """The same numbers from the csynth XMLs, when sol_data.json is unusable.

    Vitis writes both. This reads the one whose shape has been stable across
    versions and returns it in metrics_from_sol_data's form, so the renderer
    never learns there were two sources.
    """
    top_xml = Path(directory) / "nn_infer_csynth.xml"
    if not top_xml.is_file():
        return None

    modules = {}
    period = ""
    top = None

    submodules = sorted(Path(directory).glob("nn_infer_Pipeline_*_csynth.xml"))

    for path in [top_xml] + submodules:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue

        assignments = root.find("./UserAssignments")
        performance = root.find("./PerformanceEstimates")

        if assignments is None or performance is None:
            continue

        name = text_of(assignments, "TopModelName")
        if not name:
            continue

        if path == top_xml:
            top = name
            period = text_of(assignments, "TargetClockPeriod")

        latency = performance.find("SummaryOfOverallLatency")
        timing = performance.find("SummaryOfTimingAnalysis")
        loops = performance.find("SummaryOfLoopLatency")

        modules[name] = {
            "Latency": {
                "LatencyWorst": text_of(latency, "Worst-caseLatency"),
                "PipelineII": text_of(latency, "Interval-min"),
                "PipelineType": text_of(performance, "PipelineType"),
            },
            "Timing": {
                "Target": text_of(assignments, "TargetClockPeriod"),
                "Uncertainty": text_of(assignments, "ClockUncertainty"),
                "Estimate": text_of(timing, "EstimatedClockPeriod"),
            },
            "Loops": [
                {
                    "Name": loop.tag,
                    "TripCount": text_of(loop, "TripCount"),
                    "Latency": text_of(loop, "Latency"),
                    "PipelineII": text_of(loop, "PipelineII"),
                    "PipelineDepth": text_of(loop, "PipelineDepth"),
                }
                for loop in (loops if loops is not None else [])
            ],
            "Area": area_from_xml(root.find("./AreaEstimates")),
        }

    if top is None or top not in modules:
        return None

    return {
        "source": "nn_infer_csynth.xml",
        "period": period,
        "modules": modules,
        "top": top,
    }


def text_of(element, child):
    """Text of a child element, or "" -- for XML whose shape may have moved."""
    if element is None:
        return ""

    found = element.find(child)
    return (found.text or "").strip() if found is not None else ""


def area_from_xml(area):
    """<Resources> and <AvailableResources>, flattened the way sol_data has it."""
    if area is None:
        return {}

    flat = {}

    for element, prefix in ((area.find("Resources"), ""),
                            (area.find("AvailableResources"), "AVAIL_")):
        if element is None:
            continue

        for child in element:
            # sol_data spells the pair BRAM_18K / AVAIL_BRAM. The XML uses
            # BRAM_18K for both, so the available side loses the suffix here
            # and the two sources stay interchangeable downstream.
            key = child.tag if not prefix else prefix + child.tag.replace("_18K", "")
            flat[key] = (child.text or "").strip()

    return flat


def load_metrics(hls_dir):
    """Synthesis numbers for one build, from whichever source is readable."""
    return (metrics_from_sol_data(Path(hls_dir) / "sol_data.json")
            or metrics_from_xml(hls_dir))


def loop_table(metrics):
    """Every loop in the design, flattened across modules.

    Loop names are unique across the hierarchy -- each pipelined loop is lifted
    into a submodule named after it -- so one flat dict per build lines the
    builds up without tracking where each loop ended up in each of them.
    """
    loops = {}

    if metrics is None:
        return loops

    for module in metrics["modules"].values():
        for loop in module.get("Loops") or []:
            name = loop.get("Name")
            if name:
                loops[name] = loop

    return loops


# --- HLS: simulation --------------------------------------------------------


def parse_cosim(path):
    """The Verilog row of the co-simulation report: status and real cycles."""
    text = read_text(path)
    if text is None:
        return None

    for line in text.splitlines():
        if not line.startswith("|") or "Verilog" not in line:
            continue

        # RTL, Status, latency min/avg/max, interval min/avg/max, total.
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 11:
            continue

        return {
            "status": cells[2],
            "latency_min": cells[3],
            "latency_avg": cells[4],
            "latency_max": cells[5],
            "interval_min": cells[6],
        }

    return None


def parse_csim(path):
    """Mismatches from the C simulation log -- the tier that runs every vector."""
    text = read_text(path)
    if text is None:
        return None

    errors = re.search(r"CSim done with (\d+) errors", text)
    vectors = re.search(r"(\d+) of (\d+) vectors mismatched", text)

    return {
        "errors": errors.group(1) if errors else None,
        "mismatched": vectors.group(1) if vectors else None,
        "vectors": vectors.group(2) if vectors else None,
    }


# --- Vivado -----------------------------------------------------------------


def parse_timing(path):
    """WNS/TNS/WHS/THS from the design timing summary.

    The numbers are on the line after the WNS(ns) header and its rule, and the
    first such block in the file is the whole-design one. A build that failed
    placement wrote no report at all, which is why this returns None rather
    than zeros.
    """
    text = read_text(path)
    if text is None:
        return None

    lines = text.splitlines()

    for index, line in enumerate(lines):
        if "WNS(ns)" not in line or "WHS(ns)" not in line:
            continue

        for candidate in lines[index + 1:index + 4]:
            fields = candidate.split()
            if len(fields) >= 8 and re.match(r"^-?\d+\.\d+$", fields[0]):
                return {"wns": fields[0], "tns": fields[1],
                        "whs": fields[4], "ths": fields[5]}

    return None


UTILIZATION_ROWS = {
    "CLB LUTs": "lut",
    "CLB Registers": "ff",
    "Block RAM Tile": "bram",
    "DSPs": "dsp",
}


def parse_utilization(path):
    """Post-implementation resource use, the numbers 5.6 quotes.

    First match only: `CLB Registers` appears again in the register-type
    breakdown further down, where it is a subset of the first row.
    """
    text = read_text(path)
    if text is None:
        return None

    found = {}

    for line in text.splitlines():
        if not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6:
            continue

        key = UTILIZATION_ROWS.get(cells[1])
        if key is None or key in found:
            continue

        # Counted from the right: the middle columns differ between the
        # hierarchical and the flat sections of the report.
        found[key] = {"used": cells[2], "avail": cells[-3], "util": cells[-2]}

    return found or None


POWER_ROWS = (
    ("Total On-Chip Power (W)", "total"),
    ("Dynamic (W)", "dynamic"),
    ("Device Static (W)", "static"),
    ("Confidence Level", "confidence"),
    ("Simulation Activity File", "activity"),
    ("PS8", "ps8"),
)


def parse_power(path):
    """Total, dynamic, static, the PS8 share, and how much to trust them.

    PS8 is pulled out separately because it dominates: quoting the total as the
    accelerator's power overstates it several times over. The activity-file row
    is carried through because it says which kind of estimate this is; it will
    read vectorless, since annotating from cosim does not work here.
    """
    text = read_text(path)
    if text is None:
        return None

    summary = {}

    for line in text.splitlines():
        if not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 3:
            continue

        for label, key in POWER_ROWS:
            if cells[1] == label and key not in summary:
                summary[key] = cells[2]

    if not summary:
        return None

    dynamic, ps8 = number(summary.get("dynamic")), number(summary.get("ps8"))
    if dynamic is not None and ps8 is not None:
        summary["pl_dynamic"] = "%.3f" % (dynamic - ps8)

    return summary


# --- directives -------------------------------------------------------------


def parse_directives(path):
    """What was applied to this solution, from sol/sol.directive.

    Vitis writes this file as it applies the pragmas, so it records the build
    that ran rather than the Tcl as it reads today. TOP is dropped: every build
    carries it, so it is not one of the differences being compared.
    """
    text = read_text(path)
    if text is None:
        return None

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    applied = []

    for directive in root.iter():
        if strip_namespace(directive.tag) != "directive":
            continue

        target = directive.get("functionName", "")
        label = directive.get("label", "")
        if label:
            target = "%s/%s" % (target, label)

        for pragma in directive:
            if strip_namespace(pragma.tag) != "pragma":
                continue

            kind = pragma.get("name", "")
            if kind == "TOP":
                continue

            options = ["%s=%s" % (option.get("name", ""), option.get("value", ""))
                       for option in pragma
                       if strip_namespace(option.tag) == "option"]

            entry = "%s %s" % (kind, target)
            if options:
                entry += " (%s)" % ", ".join(options)

            applied.append(entry)

    return applied


def strip_namespace(tag):
    return tag.split("}", 1)[-1]


# --- formatting -------------------------------------------------------------


def number(value):
    """A float, or None. Everything read out of a report arrives as text."""
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def thousands(value):
    count = number(value)
    return DASH if count is None else "{:,}".format(int(count))


def percent(used, avail):
    """A share of the device, computed rather than read off a second row."""
    a, b = number(used), number(avail)
    if a is None or not b:
        return ""
    return " (%.2f %%)" % (100.0 * a / b)


def ratio(value, reference):
    """The baseline's number over this one -- a speedup when value is a time."""
    a, b = number(value), number(reference)
    if not a or b is None:
        return DASH
    return "%.2fx" % (b / a)


def delta(value, reference):
    """Signed percentage change against the reference."""
    a, b = number(value), number(reference)
    if a is None or not b:
        return DASH
    return "%+.0f %%" % (100.0 * (a - b) / b)


def row(label, cells):
    return "| %s | %s |" % (label, " | ".join(cells))


def header(builds, corner=""):
    return ["| %s | %s |" % (corner, " | ".join(builds)),
            "|---|%s" % ("---|" * len(builds))]


def milliseconds(cycles, period_ns):
    count = number(cycles)
    if count is None or period_ns is None:
        return DASH
    return "%.3f ms" % (count * period_ns / 1e6)


# --- one build --------------------------------------------------------------


class Build:
    """Everything one build left behind, read once."""

    def __init__(self, letter, directory):
        self.letter = letter
        self.dir = Path(directory)

        hls = self.dir / "reports" / "hls"
        vivado = self.dir / "reports" / "vivado"

        self.status = read_status(self.dir / "status.txt")
        self.metrics = load_metrics(hls)
        self.loops = loop_table(self.metrics)
        self.directives = parse_directives(hls / "sol.directive")
        self.cosim = parse_cosim(hls / "nn_infer_cosim.rpt")
        self.csim = parse_csim(hls / "nn_infer_csim.log")

        self.timing = parse_timing(first(vivado, "*_timing.rpt"))
        self.utilization = parse_utilization(first(vivado, "*_utilization.rpt"))
        self.power = parse_power(first(vivado, "*_power.rpt"))

    @property
    def top(self):
        if self.metrics is None:
            return {}
        return self.metrics["modules"][self.metrics["top"]]

    def latency(self):
        return self.top.get("Latency", {}).get("LatencyWorst")

    def interval(self):
        return self.top.get("Latency", {}).get("PipelineII")

    def area(self, key):
        return self.top.get("Area", {}).get(key)

    def implemented(self, key, field="used"):
        if self.utilization is None:
            return None
        return self.utilization.get(key, {}).get(field)


def clock_period(builds):
    """The target period, off whichever build synthesised -- never a literal."""
    for build in builds:
        if build.metrics and number(build.metrics.get("period")):
            return number(build.metrics["period"])

        target = build.top.get("Timing", {}).get("Target")
        if number(target):
            return number(target)

    return None


# --- the report -------------------------------------------------------------


def render(run, builds):
    period = clock_period(builds)
    letters = [build.letter for build in builds]
    base = next((b for b in builds if b.letter == BASELINE), None)

    out = ["# HLS directive comparison -- %s" % run.name, "",
           manifest_line(run), "",
           "Builds A-D differ in HLS directives only, never in source, so every "
           "difference below was caused by a pragma and nothing else. A build "
           "that failed is a result, not a broken run: its cells read `%s` from "
           "the stage it did not reach onwards." % DASH,
           ""]

    out += section_directives(builds)
    out += section_outcome(builds, letters)
    out += section_synthesis(builds, letters, base, period)
    out += section_loops(builds, letters)
    out += section_verification(builds, letters)
    out += section_implementation(builds, letters, base)
    out += section_power(builds, letters)
    out += section_estimate_against_implementation(builds, letters)

    out.append("Rendered by `src/fpga/summarize.py` from this run's archive alone.")
    out.append("")

    return "\n".join(out)


def manifest_line(run):
    """The run's identity, quoted from its manifest rather than restated."""
    text = read_text(run / "manifest.txt")
    if text is None:
        return "_No manifest.txt in %s._" % run.name

    wanted = ("run", "status", "started", "finished", "git",
              "width", "builds", "deploy")
    fields = []

    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] in wanted:
            fields.append("**%s** %s" % (parts[0], parts[1].strip()))

    return " &middot; ".join(fields) if fields else "_manifest.txt is empty._"


def section_directives(builds):
    out = ["## 1. What each build asks for", "",
           "| Build | Directives applied, from `sol/sol.directive` |",
           "|---|---|"]

    for build in builds:
        applied = build.directives

        if applied is None:
            cell = "no solution -- HLS did not get that far"
        elif not applied:
            cell = "none -- the unoptimised baseline"
        else:
            cell = "<br>".join("`%s`" % entry for entry in applied)

        out.append("| %s | %s |" % (build.letter, cell))

    out.append("")
    return out


def section_outcome(builds, letters):
    out = ["## 2. Outcome", ""] + header(letters)

    for label, key in (("result", "result"),
                       ("hls exit", "hls_exit"),
                       ("vivado exit", "vivado_exit"),
                       ("wall clock", "elapsed"),
                       ("artefacts absent", "absent"),
                       ("archived for the board", "deploy")):
        out.append(row(label, [b.status.get(key, DASH) for b in builds]))

    out.append("")
    return out


def section_synthesis(builds, letters, base, period):
    out = ["## 3. Synthesis estimate (csynth)", ""]

    if period:
        out.append("Latency in time is the cycle count at the %g ns target "
                   "period this run synthesised against." % period)
        out.append("")

    out += header(letters)
    out.append(row("latency (cycles)", [thousands(b.latency()) for b in builds]))
    out.append(row("latency (time)",
                   [milliseconds(b.latency(), period) for b in builds]))
    out.append(row("interval II (cycles)", [thousands(b.interval()) for b in builds]))
    out.append(row("top-level pipeline",
                   [b.top.get("Latency", {}).get("PipelineType") or DASH
                    for b in builds]))
    out.append(row("estimated clock (ns)",
                   [b.top.get("Timing", {}).get("Estimate") or DASH
                    for b in builds]))

    if base is not None:
        out.append(row("speedup vs %s" % BASELINE,
                       [ratio(b.latency(), base.latency()) for b in builds]))

    for key in ("BRAM_18K", "DSP", "FF", "LUT"):
        cells = []
        for build in builds:
            used = build.area(key)
            if used is None:
                cells.append(DASH)
            else:
                avail = build.area("AVAIL_" + key.replace("_18K", ""))
                cells.append(thousands(used) + percent(used, avail))

        out.append(row("%s (estimate)" % key, cells))

    out.append("")
    return out


def section_loops(builds, letters):
    """Where the directives landed -- the achieved II, loop by loop."""
    out = ["## 4. Achieved initiation interval, per loop", ""]

    names = []
    for build in builds:
        for name in build.loops:
            if name not in names:
                names.append(name)

    if not names:
        return out + ["_No loop data: no build reached synthesis._", ""]

    out.append("Cells read `II / loop latency in cycles`. An II of `%s` means "
               "the loop was not pipelined in that build." % DASH)
    out.append("")
    out += header(letters, corner="Loop")

    for name in names:
        cells = []
        for build in builds:
            loop = build.loops.get(name)
            if loop is None:
                cells.append(DASH)
            else:
                cells.append("%s / %s" % (loop.get("PipelineII") or DASH,
                                          thousands(loop.get("Latency"))))

        out.append(row("`%s`" % name, cells))

    out.append("")
    return out


def section_verification(builds, letters):
    out = ["## 5. Verification", "",
           "The builds are **not** verified to the same depth: only the one "
           "that goes to the board pays for a full co-simulation. The vector "
           "counts are here so the pass marks are not read as equivalent.",
           ""] + header(letters)

    def csim(build, key):
        return DASH if build.csim is None else (build.csim.get(key) or DASH)

    def cosim(build, key):
        return DASH if build.cosim is None else (build.cosim.get(key) or DASH)

    out.append(row("csim vectors", [csim(b, "vectors") for b in builds]))
    out.append(row("csim mismatches", [csim(b, "mismatched") for b in builds]))
    out.append(row("cosim vectors",
                   [b.status.get("cosim_vectors", DASH) for b in builds]))
    out.append(row("cosim depth",
                   [b.status.get("cosim_depth", DASH) for b in builds]))
    out.append(row("cosim status", [cosim(b, "status") for b in builds]))
    out.append(row("cosim latency min",
                   [thousands(cosim(b, "latency_min")) for b in builds]))
    out.append(row("cosim latency max",
                   [thousands(cosim(b, "latency_max")) for b in builds]))
    out.append("")
    return out


def section_implementation(builds, letters, base):
    out = ["## 6. Post-implementation (Vivado)", "",
           "These are the numbers 5.6 quotes, not the HLS estimates above.",
           ""] + header(letters)

    for label, key in (("WNS (ns)", "wns"), ("TNS (ns)", "tns"),
                       ("WHS (ns)", "whs"), ("THS (ns)", "ths")):
        out.append(row(label, [DASH if b.timing is None else b.timing.get(key, DASH)
                               for b in builds]))

    for key, label in (("lut", "CLB LUT"), ("ff", "CLB FF"),
                       ("bram", "Block RAM tile"), ("dsp", "DSP")):
        cells = []
        for build in builds:
            used = build.implemented(key)
            if used is None:
                cells.append(DASH)
            else:
                cells.append("%s (%s %%)" % (thousands(used),
                                             build.implemented(key, "util")))

        out.append(row(label, cells))

    if base is not None:
        for key, label in (("lut", "CLB LUT"), ("dsp", "DSP")):
            out.append(row("%s vs %s" % (label, BASELINE),
                           [delta(b.implemented(key), base.implemented(key))
                            for b in builds]))

    out.append("")
    return out


def section_power(builds, letters):
    out = ["## 7. Power", "",
           "PL dynamic is **dynamic minus PS8**: the PS dominates the total, so "
           "quoting the total as the accelerator's power overstates it several "
           "times over. An activity file of `---` means a vectorless estimate, "
           "which is what 5.6.3 quotes: annotating it from co-simulation was "
           "tried and matched 0 of 23,417 nets, because synthesis does not "
           "preserve HLS's net names.",
           ""] + header(letters)

    def power(build, key):
        return DASH if build.power is None else (build.power.get(key) or DASH)

    for label, key in (("total on-chip (W)", "total"),
                       ("dynamic (W)", "dynamic"),
                       ("PS8 (W)", "ps8"),
                       ("**PL dynamic (W)**", "pl_dynamic"),
                       ("device static (W)", "static"),
                       ("confidence", "confidence"),
                       ("activity file", "activity")):
        out.append(row(label, [power(b, key) for b in builds]))

    out.append("")
    return out


def section_estimate_against_implementation(builds, letters):
    """HLS guesses; Vivado decides. The gap between them is worth its own row."""
    out = ["## 8. HLS estimate against what was implemented", ""] + header(letters)

    for area_key, impl_key in (("LUT", "lut"), ("FF", "ff"), ("DSP", "dsp")):
        cells = []
        for build in builds:
            estimate, actual = build.area(area_key), build.implemented(impl_key)

            if estimate is None or actual is None:
                cells.append(DASH)
            else:
                cells.append("%s -> %s (%s)" % (thousands(estimate),
                                                thousands(actual),
                                                delta(actual, estimate)))

        out.append(row(area_key, cells))

    out.append("")
    return out


# --- entry point ------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render the builds A-D comparison for one archived run.")
    parser.add_argument("run", help="the run directory, e.g. out/all/<name>")
    parser.add_argument("-o", "--output", default=None,
                        help="where to write it; default <run>/summary/summary.md")
    args = parser.parse_args(argv)

    run = Path(args.run)
    builds_dir = run / "builds"

    if not builds_dir.is_dir():
        print("ERROR: %s has no builds/ -- is it an all.sh run?" % run,
              file=sys.stderr)
        return 1

    found = {path.name: path for path in builds_dir.iterdir() if path.is_dir()}
    if not found:
        print("ERROR: %s holds no builds." % builds_dir, file=sys.stderr)
        return 1

    # Canonical order first, then anything else, so a directory nobody expected
    # is reported rather than silently dropped.
    letters = [letter for letter in BUILD_ORDER if letter in found]
    letters += sorted(name for name in found if name not in BUILD_ORDER)

    builds = [Build(letter, found[letter]) for letter in letters]

    output = Path(args.output) if args.output else run / "summary" / "summary.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(run, builds), encoding="utf-8")

    print("wrote %s (%d build(s): %s)" % (output, len(builds), ", ".join(letters)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
