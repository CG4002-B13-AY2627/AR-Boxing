import argparse
import ast
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SRC = SCRIPTS.parent

for _extra in (SCRIPTS, SRC / "fpga"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import build_config as config
import build_support as support
import summarize
import sweep_config

REPO = config.REPO_DIR

_TRAIN_TREE = None


def train_literal(name):
    global _TRAIN_TREE
    if _TRAIN_TREE is None:
        source = (SRC / sweep_config.TRAIN_CONFIG).read_text(encoding="utf-8")
        _TRAIN_TREE = ast.parse(source)
    for node in ast.walk(_TRAIN_TREE):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise SystemExit("%s defines no %s" % (sweep_config.TRAIN_CONFIG, name))


def checkpoint_parts():
    return train_literal(sweep_config.CHECKPOINT_SYMBOL).rsplit(".", 1)


def checkpoint_name(width):
    stem, suffix = checkpoint_parts()
    return sweep_config.CHECKPOINT_STEM.format(stem=stem, width=width, suffix=suffix)


def confusion_name(tag):
    stem, suffix = train_literal(sweep_config.CONFUSION_SYMBOL).rsplit(".", 1)
    return sweep_config.CONFUSION_STEM.format(stem=stem, tag=tag, suffix=suffix)


def selected_width():
    stem, suffix = checkpoint_parts()
    pattern = sweep_config.CHECKPOINT_GLOB.format(stem=stem, suffix=suffix)
    found = sorted((SRC / sweep_config.SELECTED_DIR).glob(pattern))
    if len(found) != 1:
        return None
    match = sweep_config.WIDTH_IN_NAME.search(found[0].name)
    return int(match.group(1)) if match else None


def header_width():
    header = SRC / config.HLS_SUBDIR / config.SELECTED_WIDTH_NAME
    if not header.is_file():
        return None
    match = re.search(config.SELECTED_WIDTH_DEFINE + r"\s+(\d+)",
                      header.read_text(encoding="utf-8", errors="replace"))
    return int(match.group(1)) if match else None


def stage_script(stage):
    return SCRIPTS / (stage + (".bat" if os.name == "nt" else ".sh"))


def utc_now():
    return datetime.now(timezone.utc).strftime(sweep_config.TIMESTAMP)


def elapsed(seconds):
    seconds = int(seconds)
    return sweep_config.ELAPSED % (seconds // 3600, (seconds % 3600) // 60,
                                   seconds % 60)


def git_revision():
    def git(*args):
        try:
            done = subprocess.run(["git", "-C", str(REPO), *args],
                                  capture_output=True, text=True)
        except OSError:
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    revision = git("rev-parse", "--short", "HEAD")
    if revision is None:
        return "unknown"
    return revision + (" (dirty)" if git("status", "--porcelain") else "")


def tee(script, args, log, env=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    line = support.command(script, args)
    process = subprocess.Popen(line, shell=isinstance(line, str), cwd=str(REPO),
                               env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, universal_newlines=True,
                               errors="replace", bufsize=1)
    with log.open("w", encoding="utf-8", errors="replace") as handle:
        for text in process.stdout:
            sys.stdout.write(text)
            sys.stdout.flush()
            handle.write(text)
        process.wait()
        handle.write("STAGE_EXIT_CODE %d\n" % process.returncode)
    return process.returncode


def parse_accuracy(log):
    if not log.is_file():
        return {}
    rows = {}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = sweep_config.ACCURACY_ROW.match(line)
        if match:
            key, accuracy, loss, within = match.groups()
            rows[key] = {"accuracy": accuracy, "loss": loss, "within": within}
    return rows


class Sweep:
    def __init__(self, args):
        self.build = args.build
        self.start = args.start
        self.cosim = args.cosim
        self.name = args.name
        self.widths = sorted(train_literal(sweep_config.WIDTHS_SYMBOL), reverse=True)
        self.run = REPO / config.OUT_NAME / config.OUT_KIND_SWEEP / self.name
        self.rel = "%s/%s/%s" % (config.OUT_NAME, config.OUT_KIND_SWEEP, self.name)
        self.logs = self.run / sweep_config.LOGS_DIR
        self.step = 0
        self.total = 1 + len(sweep_config.PER_WIDTH_STAGES) * len(self.widths) + 1
        self.missing = 0
        self.shared_missing = 0
        self.failed_at = ""
        self.results = {}
        self.stages_run = []
        self.started = 0.0
        self.started_at = ""

    def width_dir(self, width):
        return self.run / sweep_config.WIDTHS_DIR / str(width)

    def should_run(self, stage):
        return (sweep_config.STAGES.index(stage)
                >= sweep_config.STAGES.index(self.start))

    def banner(self, label, log):
        self.step += 1
        print("\n" + sweep_config.RULE)
        print("  [%d/%d] %s" % (self.step, self.total, label))
        print("  log: %s" % log)
        print(sweep_config.RULE + "\n")

    def skipped(self, label):
        self.step += 1
        print("\n--- [%d/%d] %-14s skipped (--from %s)"
              % (self.step, self.total, label, self.start))

    def take(self, source, destination):
        destination.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            try:
                shutil.copy2(str(source), str(destination / source.name))
            except OSError:
                print("    -  %s (copy failed)" % source.name)
                self.missing += 1
                return
            print("    +  %s" % source.name)
            return
        print("    -  %s (absent)" % source.name)
        self.missing += 1

    def take_glob(self, directory, pattern, destination):
        destination.mkdir(parents=True, exist_ok=True)
        found = 0
        for path in sorted(Path(directory).glob(pattern)):
            if path.is_file():
                shutil.copy2(str(path), str(destination / path.name))
                found += 1
        print("    +  %d file(s) matching %s" % (found, pattern))

    def prepare(self):
        if self.run.exists():
            raise SystemExit("ERROR: %s already exists. Pick another name, or "
                             "remove it first." % self.run)
        for width in self.widths:
            base = self.width_dir(width)
            for leaf in (sweep_config.LOGS_DIR,
                         sweep_config.HEADERS_DIR,
                         "%s/%s" % (sweep_config.REPORTS_DIR,
                                    sweep_config.HLS_REPORTS_SUBDIR),
                         "%s/%s" % (sweep_config.REPORTS_DIR,
                                    sweep_config.VIVADO_REPORTS_SUBDIR)):
                (base / leaf).mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        (self.run / sweep_config.SUMMARY_DIR).mkdir(parents=True, exist_ok=True)
        (self.run / sweep_config.REPORTS_DIR).mkdir(parents=True, exist_ok=True)

    def clean(self):
        log = sweep_config.log_name(sweep_config.CLEAN_STAGE)
        print("\n" + sweep_config.RULE)
        print("  [%d/%d] %s" % (sweep_config.CLEAN_INDEX, self.total,
                                sweep_config.CLEAN_STAGE))
        print("  log: %s/%s" % (sweep_config.LOGS_DIR, log))
        print(sweep_config.RULE + "\n")
        code = tee(stage_script(sweep_config.CLEAN_STAGE),
                   sweep_config.CLEAN_FROM[self.start], self.logs / log)
        if code != 0:
            print("\nFAILED: the cleaner refused to run, so nothing was built.",
                  file=sys.stderr)
            print("Cleanup may be partial. Inspect %s/%s/%s."
                  % (self.rel, sweep_config.LOGS_DIR, log), file=sys.stderr)
            raise SystemExit(1)

    def train(self):
        stage = sweep_config.SHARED_STAGE
        log = sweep_config.log_name(stage)
        if not self.should_run(stage):
            self.skipped(stage)
            return True
        self.banner(stage, "%s/%s" % (sweep_config.LOGS_DIR, log))
        code = tee(stage_script(stage), [], self.logs / log)
        if code != 0:
            self.failed_at = stage
            return False
        self.stages_run.append(stage)
        return True

    def order(self):
        chosen = selected_width()
        if chosen is None:
            chosen = header_width()
        if chosen is None or chosen not in self.widths:
            return list(self.widths), None
        return [chosen] + [w for w in self.widths if w != chosen], chosen

    def environment(self, width, chosen):
        env = dict(os.environ)
        env[config.VIVADO_LOG_DIR] = str(self.width_dir(width)
                                         / sweep_config.LOGS_DIR
                                         / sweep_config.VIVADO_LOG_SUBDIR)
        if width == chosen:
            env.pop(config.CHECKPOINT_OVERRIDE, None)
        else:
            env[config.CHECKPOINT_OVERRIDE] = checkpoint_name(width)
        return env

    def stage_args(self, stage, width):
        if stage == sweep_config.HLS_STAGE:
            return [str(width), self.build, self.cosim]
        if stage == sweep_config.VIVADO_STAGE:
            return [str(width), self.build]
        return []

    def one_width(self, width, chosen):
        base = self.width_dir(width)
        env = self.environment(width, chosen)
        started = time.time()
        started_at = utc_now()
        before = self.missing
        result = "OK"
        codes = {}

        for stage in sweep_config.PER_WIDTH_STAGES:
            label = "%s w%d" % (stage, width)
            if not self.should_run(stage):
                self.skipped(label)
                codes[stage] = "skipped"
                continue
            if result != "OK":
                self.step += 1
                print("\n--- [%d/%d] %-14s not run: %s"
                      % (self.step, self.total, label, result))
                codes[stage] = "not run"
                continue

            log = sweep_config.log_name(stage)
            self.banner(label, "%s/%d/%s/%s" % (sweep_config.WIDTHS_DIR, width,
                                                sweep_config.LOGS_DIR, log))

            code = tee(stage_script(stage), self.stage_args(stage, width),
                       base / sweep_config.LOGS_DIR / log, env)
            codes[stage] = code

            if code != 0:
                result = "FAILED at %s" % stage
            elif stage == sweep_config.HLS_STAGE and not self.packaged(width):
                result = "FAILED at hls (no packaged IP)"

        self.collect_width(width)
        absent = self.missing - before

        if result == "OK" and absent:
            result = "FAILED: missing or unarchived artefacts"

        self.results[width] = {
            "result": result,
            "absent": absent,
            "started": started_at,
            "finished": utc_now(),
            "elapsed": elapsed(time.time() - started),
            "codes": codes,
        }

        lines = ["width          %d" % width,
                 "result         %s" % result,
                 "build          %s" % self.build,
                 "checkpoint     %s" % checkpoint_name(width),
                 "selected       %s" % ("yes" if width == chosen else "no"),
                 "cosim_vectors  %s" % self.cosim,
                 "started        %s" % started_at,
                 "finished       %s" % utc_now(),
                 "elapsed        %s" % self.results[width]["elapsed"],
                 "absent         %d" % absent]
        for stage in sweep_config.PER_WIDTH_STAGES:
            lines.append("%-14s %s" % (stage + "_exit", codes.get(stage, "not run")))
        (base / sweep_config.STATUS_NAME).write_text("\n".join(lines) + "\n",
                                                     encoding="utf-8")

    def packaged(self, width):
        project = config.HLS_PROJECT.format(width=width, build=self.build)
        marker = (SRC / config.HLS_SUBDIR / project / config.HLS_SOLUTION
                  / config.HLS_IP / config.HLS_IP_MARKER)
        return marker.is_file()

    def collect_width(self, width):
        base = self.width_dir(width)
        project = config.HLS_PROJECT.format(width=width, build=self.build)
        solution = SRC / config.HLS_SUBDIR / project / config.HLS_SOLUTION
        stem = config.BITSTREAM_STEM.format(width=width, build=self.build)
        reports = base / sweep_config.REPORTS_DIR
        hls_reports = reports / sweep_config.HLS_REPORTS_SUBDIR
        vivado_reports = reports / sweep_config.VIVADO_REPORTS_SUBDIR

        print("\n  width %d" % width)

        for suffix in sweep_config.VIVADO_REPORT_SUFFIXES:
            self.take(SRC / config.VIVADO_SUBDIR
                      / sweep_config.VIVADO_REPORT.format(stem=stem, suffix=suffix),
                      vivado_reports)

        for relative in sweep_config.HLS_REPORTS:
            self.take(solution / relative, hls_reports)

        for directory, pattern in sweep_config.HLS_REPORT_GLOBS:
            self.take_glob(solution / directory, pattern, hls_reports)

        for template in sweep_config.WIDTH_HEADERS:
            self.take(SRC / config.HLS_SUBDIR / template.format(width=width),
                      base / sweep_config.HEADERS_DIR)

        tag = sweep_config.WIDTH_TAG.format(width=width)
        self.take(SRC / sweep_config.PLOT_DIR / confusion_name(tag), reports)

    def collect_shared(self):
        print("\n" + sweep_config.RULE)
        print("  collecting into %s" % self.rel)
        print(sweep_config.RULE)
        print("\n  shared")
        before = self.missing
        self.take(SRC / sweep_config.LOSS_CURVE,
                  self.run / sweep_config.REPORTS_DIR)
        self.take(SRC / sweep_config.PLOT_DIR / confusion_name(sweep_config.BASELINE_TAG),
                  self.run / sweep_config.REPORTS_DIR)
        self.shared_missing = self.missing - before

    def status(self):
        if self.failed_at:
            return "FAILED at %s" % self.failed_at
        if self.shared_missing:
            return "FAILED: missing or unarchived artefacts"
        failed = [w for w, r in self.results.items() if r["result"] != "OK"]
        if failed:
            return "PARTIAL, %d of %d width(s) failed" % (len(failed), len(self.widths))
        return "OK"

    def manifest(self, chosen):
        lines = [
            "run          %s" % self.name,
            "status       %s" % self.status(),
            "started      %s" % self.started_at,
            "finished     %s" % utc_now(),
            "elapsed      %s" % elapsed(time.time() - self.started),
            "host         %s" % (socket.gethostname() or "unknown"),
            "git          %s" % git_revision(),
            "",
            "widths       %s" % " ".join(str(w) for w in self.widths),
            "selected     %s" % (chosen if chosen is not None else "unresolved"),
            "build        %s" % self.build,
            "cosim        %s vectors on every width" % self.cosim,
            "from         %s" % self.start,
            "shared       %s" % (" ".join(self.stages_run) or "none"),
            "absent       %d shared artefact(s)" % self.shared_missing,
            "",
            "per width",
        ]
        for width in self.widths:
            record = self.results.get(width)
            if record is None:
                lines.append("  %d: not reached" % width)
            else:
                lines.append("  %d: %s [%s]" % (width, record["result"], record["elapsed"]))
        lines += [
            "",
            "%s/     the width curve. Start here." % sweep_config.SUMMARY_DIR,
            "%s/<N>/  one directory per width: %s, logs, HLS and"
            % (sweep_config.WIDTHS_DIR, sweep_config.STATUS_NAME),
            "             Vivado reports, its confusion matrix, and the headers",
            "             that width emitted.",
            "%s/     the training loss curve and the FP32 confusion matrix."
            % sweep_config.REPORTS_DIR,
            "%s/        stdout of the shared stages. Every width's accuracy"
            % sweep_config.LOGS_DIR,
            "             and the selection rule live only in %s."
            % sweep_config.log_name(sweep_config.SHARED_STAGE),
            "",
            "No bitstream is archived. A sweep answers what a width costs; the",
            "build that ships comes from src/pipeline, which archives one.",
        ]
        (self.run / sweep_config.MANIFEST_NAME).write_text("\n".join(lines) + "\n",
                                                           encoding="utf-8")

    def render(self, chosen):
        self.step = self.total - 1
        self.banner("summary", "%s/%s" % (sweep_config.SUMMARY_DIR,
                                          sweep_config.SUMMARY_NAME))
        try:
            text = render_summary(self, chosen)
        except Exception as error:
            print("ERROR: the summary was not written: %s" % error, file=sys.stderr)
            return False
        target = self.run / sweep_config.SUMMARY_DIR / sweep_config.SUMMARY_NAME
        target.write_text(text, encoding="utf-8")
        print("wrote %s (%d width(s))" % (target, len(self.widths)))
        return True

    def go(self):
        self.started = time.time()
        self.started_at = utc_now()
        self.prepare()

        print()
        print("run       %s" % self.name)
        print("out       %s" % self.rel)
        print("widths    %s" % " ".join(str(w) for w in self.widths))
        print("build     %s" % self.build)
        print("cosim     %s vectors on every width" % self.cosim)
        print("from      %s" % self.start)
        print("started   %s" % self.started_at)

        self.clean()

        chosen = None
        if self.train():
            order, chosen = self.order()
            if chosen is None:
                print("\nWARNING: no selected width, so every width is exported "
                      "under an override and params.hpp may find no %s."
                      % config.SELECTED_WIDTH_NAME, file=sys.stderr)
            for width in order:
                self.one_width(width, chosen)

        self.collect_shared()
        self.manifest(chosen)
        rendered = self.render(chosen)

        print()
        print((self.run / sweep_config.MANIFEST_NAME).read_text(encoding="utf-8"))

        if self.failed_at:
            print("\nRun FAILED at %s. Partial results in %s"
                  % (self.failed_at, self.rel), file=sys.stderr)
            return 1
        if self.shared_missing:
            print("\nRun finished, but %d shared artefact(s) were absent."
                  % self.shared_missing, file=sys.stderr)
            return 1
        if not rendered or any(r["result"] != "OK" for r in self.results.values()):
            print("\nSweep finished with failures. Read the summary and the "
                  "per-width logs.", file=sys.stderr)
            return 1
        print("\nRun complete. %s — read %s/%s"
              % (self.rel, sweep_config.SUMMARY_DIR, sweep_config.SUMMARY_NAME))
        return 0


def moved(values):
    numbers = [summarize.number(v) for v in values]
    numbers = [n for n in numbers if n is not None]
    if len(numbers) < 2:
        return summarize.DASH
    low, high = min(numbers), max(numbers)
    if not high:
        return "no"
    return "no" if low == high else "%+.1f %%" % (100.0 * (low - high) / high)


def render_summary(sweep, chosen):
    widths = list(sweep.widths)
    builds = [summarize.Build(str(w), sweep.width_dir(w)) for w in widths]
    found = dict(zip(widths, builds))
    period = summarize.clock_period(builds)
    train_log = sweep.logs / sweep_config.log_name(sweep_config.SHARED_STAGE)
    accuracy = parse_accuracy(train_log)
    budget = train_literal(sweep_config.BUDGET_SYMBOL)
    labels = ["w%d" % w for w in widths]

    out = ["# Fixed-point width sweep — %s" % sweep.name, "",
           summarize.manifest_line(sweep.run), "",
           "Every width below is the same network, the same data and the same "
           "directive set (`%s`); only the quantisation width differs. Training "
           "selects the narrowest width within **%s pp** of the FP32 baseline, "
           "which settles *which* width ships. This run answers the other half: "
           "**what that width actually costs in silicon, and where the network "
           "breaks.**" % (sweep.build, budget), "",
           "A width that failed is a result, not a broken run: its cells read "
           "`%s` from the stage it did not reach onwards." % summarize.DASH, ""]

    out += ["## Accuracy, and the selection rule", ""]
    if accuracy:
        out += summarize.header(["Accuracy", "Loss (pp)", "Within budget", "Selected"],
                                corner="")
        baseline = accuracy.get(sweep_config.BASELINE_ROW)
        if baseline:
            out.append(summarize.row(sweep_config.BASELINE_ROW,
                                     ["%s %%" % baseline["accuracy"],
                                      summarize.DASH, summarize.DASH,
                                      summarize.DASH]))
        for width in widths:
            row = accuracy.get(str(width))
            if row is None:
                out.append(summarize.row("w%d" % width, [summarize.DASH] * 4))
                continue
            out.append(summarize.row("w%d" % width,
                                     ["%s %%" % row["accuracy"], row["loss"],
                                      row["within"],
                                      "**yes**" if width == chosen else "no"]))
        out += ["", "Read off this run's own `%s/%s`, so the table cannot "
                    "disagree with the checkpoints the rest of the sweep was "
                    "built from." % (sweep_config.LOGS_DIR, train_log.name), ""]
    else:
        out += ["_No accuracy table in `%s/%s` — this run resumed past training, "
                "so the widths below carry area and latency only._"
                % (sweep_config.LOGS_DIR, train_log.name), ""]

    out += ["## Post-implementation area", "",
            "What the fabric actually spends, not the HLS estimate.", ""]
    out += summarize.header(labels, corner="Resource")
    for key, label in sweep_config.RESOURCES:
        cells = []
        for width in widths:
            build = found[width]
            used = build.implemented(key)
            if used is None:
                cells.append(summarize.DASH)
                continue
            cells.append(summarize.thousands(used)
                         + summarize.percent(used, build.implemented(key, "avail")))
        out.append(summarize.row(label, cells))
    out.append("")

    out += ["### Did the width move it?", "",
            "The question the sweep exists to answer. A resource that reads "
            "`no` is one the narrowing bought nothing on — a DSP48E2 holds a "
            "27x18 multiplier, so a 6-bit product and an 8-bit product can cost "
            "exactly the same.", ""]
    out += summarize.header(["Narrowest against widest"], corner="Resource")
    for key, label in sweep_config.RESOURCES:
        out.append(summarize.row(label,
                                 [moved([found[w].implemented(key) for w in widths])]))
    out.append("")

    out += ["## Latency and timing", ""]
    out += summarize.header(labels, corner="")
    out.append(summarize.row("Latency (cycles)",
                             [summarize.thousands(found[w].latency()) for w in widths]))
    out.append(summarize.row("Latency",
                             [summarize.milliseconds(found[w].latency(), period)
                              for w in widths]))
    cosim = []
    for width in widths:
        report = found[width].cosim
        cosim.append(summarize.DASH if report is None
                     else "%s, %s" % (report.get("status", summarize.DASH),
                                      summarize.thousands(report.get("cycles"))))
    out.append(summarize.row("Co-simulation", cosim))
    for field, label in (("wns", "WNS (ns)"), ("whs", "WHS (ns)")):
        cells = []
        for width in widths:
            timing = found[width].timing
            cells.append(summarize.DASH if timing is None
                         else timing.get(field, summarize.DASH))
        out.append(summarize.row(label, cells))
    out.append("")

    out += ["## Outcome", ""]
    out += summarize.header(labels, corner="")
    out.append(summarize.row("Result",
                             [sweep.results.get(w, {}).get("result", "not reached")
                              for w in widths]))
    out.append(summarize.row("Checkpoint",
                             ["`%s`" % checkpoint_name(w) for w in widths]))
    out.append(summarize.row("Elapsed",
                             [sweep.results.get(w, {}).get("elapsed", summarize.DASH)
                              for w in widths]))
    out += ["",
            "Rendered by `src/scripts/sweep.py` from this run's archive alone.", ""]

    return "\n".join(out)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="sweep",
        description="Build every fixed-point width in the training sweep and "
                    "compare what each one costs.")
    parser.add_argument("--name", default="",
                        help="name of the run; prompted for if omitted")
    parser.add_argument("--build", default="",
                        help="the directive set every width is built against "
                             "(default %s)" % config.DEFAULT_BUILD)
    parser.add_argument("--from", dest="start", default=sweep_config.SHARED_STAGE,
                        choices=sweep_config.STAGES,
                        help="first stage to run (default %s)"
                             % sweep_config.SHARED_STAGE)
    parser.add_argument("--cosim", default=sweep_config.DEFAULT_COSIM,
                        help="RTL vectors to co-simulate per width (default %s); "
                             "the curve comes from csynth and Vivado, not cosim"
                             % sweep_config.DEFAULT_COSIM)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if not args.name:
        try:
            args.name = input("name of the run: ")
        except EOFError:
            args.name = ""
    args.name = args.name.replace("\r", "").strip()

    if not args.name:
        raise SystemExit("ERROR: a run needs a name.")
    if (args.name in sweep_config.RESERVED_NAMES
            or not sweep_config.RUN_NAME.match(args.name)):
        raise SystemExit("ERROR: use letters, digits, dot, dash and underscore only.")

    try:
        args.build = support.resolve_build(args.build)
    except RuntimeError as error:
        raise SystemExit("ERROR: %s" % error)

    return Sweep(args).go()


if __name__ == "__main__":
    sys.exit(main())
