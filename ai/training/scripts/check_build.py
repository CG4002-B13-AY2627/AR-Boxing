"""Build-control regression checks using disposable workspaces and fake tools.

Run: python src/scripts/check_build.py
No training, FPGA compilation or deletion in the real workspace is performed.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_config as config
import build_support as support
import sweep_config

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
if os.name == "nt" and Path("C:/Program Files/Git/bin/bash.exe").is_file():
    BASH = "C:/Program Files/Git/bin/bash.exe"
TCLSH = shutil.which("tclsh")
if not TCLSH and os.name == "nt":
    bundled_tclsh = Path("C:/Xilinx/Vitis_HLS/2022.1/tps/win64/git-2.16.2/mingw64/bin/tclsh.exe")
    if bundled_tclsh.is_file():
        TCLSH = str(bundled_tclsh)

FAKE_STAGE = r'''
import json, os, sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
stage, *args = sys.argv[1:]
override = os.environ.get("NN_CHECKPOINT_OVERRIDE", "")
if stage == "export":
    args = [override or "selected"]
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps([stage, args]) + "\n")
def emit(path, text="fixture\n"):
    p = root / "src" / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
if stage == "train":
    emit("train/checkpoints/norm_stats.json", "{}")
    for w in [8, 7, 6, 5, 4]:
        emit(f"train/checkpoints/qacnn_w{w}.pt")
        emit(f"train/plots/confusion_w{w}.png")
    emit("train/qmodel/qacnn_w6.pt")
    emit("train/plots/training_loss.png")
    emit("train/plots/confusion_fp32.png")
elif stage == "export":
    w = override.split("_w")[-1].split(".")[0] if override else "6"
    if not override:
        emit("fpga/hls/selected_width.hpp", "#define NN_WIDTH_SELECTED 6\n")
    emit(f"export/build/description_w{w}.json", "{}")
    for name in [f"params_w{w}.hpp", f"weights_w{w}.hpp", f"golden_w{w}.npz"]:
        emit("fpga/hls/" + name)
    emit(f"fpga/hls/golden_w{w}.h", "#define GOLDEN_COSIM_N 200\n")
elif stage == "hls":
    w, b, *cosim = args
    if os.environ.get("FAIL_BUILD") in {b, "ALL"}:
        sys.exit(7)
    base = f"fpga/hls/hls_w{w}_{b}/sol/"
    reports = ["impl/ip/component.xml", "sol_data.json", "sol.directive",
               "syn/report/csynth.rpt", "syn/report/nn_infer_csynth.rpt",
               "syn/report/nn_infer_csynth.xml"]
    if "synth-export" not in cosim:
        reports += ["sim/report/nn_infer_cosim.rpt", "sim/report/verilog/lat.rpt",
                    "csim/report/nn_infer_csim.log"]
    for name in reports:
        emit(base + name)
elif stage == "vivado":
    w, b = args
    for suffix in ["bit", "hwh"]:
        emit(f"fpga/vivado/bit/nn_w{w}_{b}.{suffix}")
    for kind in ["timing", "utilization", "power"]:
        emit(f"fpga/vivado/reports/nn_w{w}_{b}_{kind}.rpt")
'''


class BuildChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cg4002 build checks ", dir=ROOT)
        self.root = Path(self.temp.name)
        self.src = self.root / "src"
        self.scripts = self.src / "scripts"
        self.scripts.mkdir(parents=True)
        self.env = dict(os.environ)
        self.env.pop(config.GUARD_TOKEN, None)
        self.env["NN_BUILD_BASH"] = BASH or "bash"
        # The sandbox has a different owner from the user's repository.
        self.env["GIT_CONFIG_COUNT"] = "1"
        self.env["GIT_CONFIG_KEY_0"] = "safe.directory"
        self.env["GIT_CONFIG_VALUE_0"] = str(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def scoped(self):
        return patch.multiple(support, ROOT=self.root, SRC=self.src, LOCK=self.root / ".build.lock")

    def fixture(self):
        for relative in ["src/pipeline.bat", "src/pipeline.sh", "src/all.bat", "src/all.sh",
                         "src/sweep.bat", "src/sweep.sh", "src/scripts/sweep.py",
                         "src/scripts/sweep_config.py",
                         "src/scripts/build_config.py", "src/scripts/build_support.py",
                         "src/scripts/build_support.bat",
                         "src/scripts/build_support.sh", "src/scripts/clean.bat",
                         "src/scripts/clean.sh", "src/fpga/summarize.py"]:
            dst = self.root / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, dst)
            if dst.suffix == ".sh":
                dst.chmod(0o755)
        for marker in ["export/export_config.py", "fpga/hls/tcl/run_hls.tcl"]:
            self.write("src/" + marker, "# marker\n")
        # sweep.py reads these four out of train/config.py by AST rather than
        # importing it, so the marker has to carry them for the sweep to run.
        self.write("src/train/config.py",
                   'BIT_WIDTH_SWEEP = [8, 7, 6, 5, 4]\n'
                   'MAX_QUANT_LOSS_PP = 2.0\n'
                   'QAT_CHECKPOINT_NAME = "qacnn.pt"\n'
                   'CONFUSION_PLOT_NAME = "confusion.png"\n')
        self.write("src/scripts/fake_stage.py", FAKE_STAGE)
        for stage in ["train", "check", "export", "hls", "vivado"]:
            self.write(f"src/scripts/{stage}.bat",
                       f'@echo off\n"{sys.executable}" "%~dp0fake_stage.py" {stage} %*\nexit /b %errorlevel%\n')
            script = self.write(f"src/scripts/{stage}.sh",
                                '#!/usr/bin/env bash\n' +
                                f'exec "{sys.executable}" "$(dirname "$0")/fake_stage.py" {stage} "$@"\n')
            script.chmod(0o755)

    def run_script(self, script, args, expected=0, stdin=None):
        if script.endswith(".sh"):
            cmd = [BASH, str(self.root / script), *args]
        else:
            cmd = support.command(self.root / script, args)
        result = subprocess.run(cmd, env=self.env, cwd=self.root, text=True, input=stdin,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=100)
        self.assertEqual(result.returncode, expected, result.stdout[-12000:])
        return result.stdout

    def test_checked_cleanup_failure_and_scope(self):
        target = self.write("src/fpga/vivado/vivado_w6_A/test.txt", "generated")
        with self.scoped(), patch.object(support.shutil, "rmtree", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                support.checked_remove(target.parent, self.src)
            self.assertTrue(target.exists())
            with self.assertRaises(RuntimeError):
                support.checked_remove(self.root, self.src)
            with self.assertRaises(RuntimeError):
                support.checked_remove(self.src, self.src)
        with self.scoped():
            support.checked_remove(target.parent, self.src)
            self.assertFalse(target.exists())

    def test_preflight_refuses_live_tools(self):
        with patch.object(support, "active_tools", return_value=["PID 123: vivado"]):
            with self.assertRaisesRegex(RuntimeError, "PID 123"):
                support.preflight()

    @staticmethod
    def tcl_value(call, flag):
        """One flag's value out of a captured set_directive_* call."""
        return int(call[call.index(flag) + 1])

    def header_define(self, name):
        """One #define from the generated params header, as the Tcl reads it."""
        header = (self.root / "src/fpga/hls/params_w6.hpp").read_text()
        return int(re.search(rf"^\s*#define\s+{name}\s+(-?\d+)", header, re.M)[1])

    def test_hls_selects_actual_build_directives(self):
        if not TCLSH:
            self.skipTest("Tcl interpreter unavailable")
        hls_dir = self.root / "src/fpga/hls"
        tcl_dir = hls_dir / "tcl"
        tcl_dir.mkdir(parents=True)
        for name in ("run_hls.tcl", "configure.tcl", "nn_width.tcl", "csim.tcl"):
            shutil.copy2(ROOT / "src/fpga/hls/tcl" / name, tcl_dir / name)
        self.write("src/fpga/hls/params_w6.hpp", "#define CONV2_K 3\n")
        expected = {
            "A": [],
            "B": ["set_directive_pipeline", "set_directive_pipeline"],
            "C": ["set_directive_pipeline", "set_directive_pipeline",
                  "set_directive_unroll", "set_directive_unroll"],
            "D": ["set_directive_pipeline", "set_directive_pipeline",
                  "set_directive_unroll", "set_directive_unroll",
                  "set_directive_array_partition", "set_directive_array_partition"],
            "E": ["set_directive_unroll", "set_directive_pipeline",
                  "set_directive_array_partition", "set_directive_array_partition"],
        }
        for build, directives in expected.items():
            with self.subTest(build=build):
                script = r'''
                    set calls {}
                    proc version {args} { return 2022.1 }
                    proc unknown {command args} {
                        if {[string match set_directive_* $command]} {
                            lappend ::calls [join [linsert $args 0 $command] |]
                        }
                    }
                    proc csim_design {args} {
                        foreach call $::calls { puts "CALL $call" }
                        exit 0
                    }
                    set argv [list -f run_hls.tcl -tclargs 6 BUILD]
                    source {TCL_FILE}
                    exit 1
                '''.replace("BUILD", build).replace(
                    "TCL_FILE", str(tcl_dir / "run_hls.tcl").replace("\\", "/"))
                result = subprocess.run([TCLSH], input=script, text=True,
                                        capture_output=True, cwd=hls_dir, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [line[5:].split("|") for line in result.stdout.splitlines()
                         if line.startswith("CALL ")]
                self.assertEqual([call[0] for call in calls], directives)
                if build == "D":
                    self.assertEqual([call[-1] for call in calls[-2:]], ["a1", "p1"])
                if build == "E":
                    self.assertEqual([call[-1] for call in calls[-2:]], ["p1", "conv2_w"])
                    # One weight bank per product in flight, so the banks times
                    # the II is the product count. Both come from the header,
                    # and this is the only check that they still do rather than
                    # being numbers typed once and left to rot.
                    # The weight ROM needs one bank per product in flight, which is
                    # the unroll factor times the kernel. Derived from the header,
                    # and this is the only check that it still is rather than a
                    # number typed once and left to rot.
                    self.assertEqual(self.tcl_value(calls[0], "-factor")
                                     * self.header_define("CONV2_K"),
                                     self.tcl_value(calls[-1], "-factor"))

    def test_hls_synth_export_skips_both_simulations(self):
        if not TCLSH:
            self.skipTest("Tcl interpreter unavailable")
        script = r'''
            set calls {}
            proc version {args} { return 2022.1 }
            proc unknown {command args} {
                if {$command eq "nn_cosim::run"} { error UNEXPECTED_COSIM }
            }
            proc csim_design {args} { error UNEXPECTED_CSIM }
            proc cosim_design {args} { error UNEXPECTED_COSIM }
            proc csynth_design {args} { lappend ::calls csynth }
            proc export_design {args} { lappend ::calls export }
            rename exit native_exit
            proc exit {args} { error FLOW_FINISHED }
            set argv [list -f run_hls.tcl -tclargs 6 A {} synth-export]
            if {[catch {source {TCL_FILE}} result] && $result ne "FLOW_FINISHED"} {
                puts stderr $result
                native_exit 1
            }
            if {$calls ne {csynth export}} {
                puts stderr "unexpected HLS phases: $calls"
                native_exit 1
            }
            native_exit 0
        '''.replace("TCL_FILE", str(ROOT / "src/fpga/hls/tcl/run_hls.tcl").replace("\\", "/"))
        result = subprocess.run([TCLSH], input=script, text=True, capture_output=True,
                                cwd=ROOT / "src/fpga/hls", timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lock_rejects_overlap_and_releases(self):
        code = ("import sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'src/scripts')!r}); import build_support as b; "
                f"b.LOCK=Path({str(self.root / '.build.lock')!r}); "
                "b.preflight=lambda:None; "
                "\nwith b.guard(): print('acquired')")
        with self.scoped(), patch.object(support, "preflight"):
            with support.guard():
                # Normal descendants inherit the guard without deadlocking.
                with support.guard():
                    pass
                competing = subprocess.run([sys.executable, "-c", code], env=self.env,
                                           capture_output=True, text=True)
                self.assertNotEqual(competing.returncode, 0)
                self.assertIn("Another build", competing.stderr)
            self.assertFalse((self.root / ".build.lock").exists())
            after = subprocess.run([sys.executable, "-c", code], env=self.env,
                                   capture_output=True, text=True)
            self.assertEqual(after.returncode, 0, after.stderr)
            self.assertFalse((self.root / ".build.lock").exists())

    def test_clean_preserves_inputs_on_vivado_resume(self):
        self.fixture()
        model = self.write("src/train/qmodel/model.pt", "keep")
        ip = self.write("src/fpga/hls/hls_w6_A/sol/impl/ip/component.xml", "keep")
        bd = self.write("src/fpga/vivado/vivado_w6_A/project.xpr", "delete")
        archive = self.write("out/old/bitstream/nn.bit", "keep")
        with self.scoped():
            support.clean(["vivado"], True)
            self.assertTrue(bd.exists())
            support.clean(["vivado"])
        self.assertFalse(bd.exists())
        self.assertTrue(all(p.exists() for p in (model, ip, archive)))

    def test_bytecode_caches_swept_outside_the_virtualenv(self):
        self.fixture()
        stale = [self.write(f"{where}/__pycache__/stale.pyc", "stale")
                 for where in ("src/train", "src/export", "src/scripts",
                               "src/fpga/hls", "ultra-96/src")]
        installed = self.write("src/.venv/lib/__pycache__/torch.pyc", "installed")
        with self.scoped():
            support.clean([])
        self.assertEqual([p for p in stale if p.exists()], [])
        self.assertTrue(installed.exists())

    def check_runner(self, extension):
        self.fixture()
        self.run_script("src/pipeline." + extension, ["--name", "single", "--build", "a" if extension == "bat" else "A"])
        self.assertIn("status       OK", (self.root / "out/pipeline/single/manifest.txt").read_text())
        self.assertIn("hls mode     full", (self.root / "out/pipeline/single/manifest.txt").read_text())
        # FP32 plus the five widths: the glob follows the sweep without naming it.
        self.assertEqual(len(list((self.root / "out/pipeline/single/reports").glob("confusion_*.png"))), 6)
        self.run_script("src/all." + extension, ["--name", "four"])
        self.assertEqual(len(list((self.root / "out/all/four/reports").glob("confusion_*.png"))), 6)
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([args for name, args in calls if name == "hls"][0],
                         ["6", "A", "", "full"])
        self.assertEqual([args for name, args in calls if name == "hls"][-4:],
                         [["6", "A"], ["6", "B", "5"], ["6", "C", "5"], ["6", "D", "5"]])
        self.assertTrue((self.root / "out/all/four/summary/summary.md").is_file())
        self.assertEqual(len(list((self.root / "out/all/four/bitstream").glob("*.bit"))), 1)
        before = len(calls)
        self.run_script("src/all." + extension, ["--name", "resume", "--from", "vivado"])
        resumed = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()][before:]
        self.assertEqual(resumed, [["vivado", ["6", b]] for b in "ABCD"])
        self.env["FAIL_BUILD"] = "B"
        self.run_script("src/all." + extension, ["--name", "partial", "--from", "hls"], expected=1)
        self.assertIn("FAILED at hls", (self.root / "out/all/partial/builds/B/status.txt").read_text())
        self.assertIn("result         OK", (self.root / "out/all/partial/builds/D/status.txt").read_text())
        self.assertIn("PARTIAL", (self.root / "out/all/partial/manifest.txt").read_text())
        self.assertFalse((self.root / "out/all/partial/builds/B/logs/5-vivado.log").exists())
        self.env["FAIL_BUILD"] = "ALL"
        self.run_script("src/all." + extension, ["--name", "failed", "--from", "hls"], expected=1)
        self.assertEqual(list((self.root / "out/all/failed/bitstream").glob("*.bit")), [])
        self.assertTrue((self.root / "out/all/failed/summary/summary.md").is_file())
        self.env.pop("FAIL_BUILD", None)
        self.check_sweep(extension)

    def check_pipeline_synth_export(self, extension):
        self.fixture()
        output = self.run_script("src/pipeline." + extension,
                                 ["--name", "ip-only", "--build", "A",
                                  "--hls-mode", "synth-export"])
        run = self.root / "out/pipeline/ip-only"
        manifest = (run / "manifest.txt").read_text()
        self.assertIn("status       OK", manifest)
        self.assertIn("hls mode     synth-export", manifest)
        self.assertIn("HLS simulation reports skipped", output)
        self.assertTrue((run / "reports/hls/nn_infer_csynth.rpt").exists())
        self.assertFalse((run / "reports/hls/nn_infer_cosim.rpt").exists())
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([args for name, args in calls if name == "hls"],
                         [["6", "A", "", "synth-export"]])

        output = self.run_script("src/pipeline." + extension,
                                 ["--name", "picked", "--build", "A"], stdin="2\n")
        self.assertIn("which HLS flow?", output)
        self.assertLess(output.index("[3/5] export"), output.index("which HLS flow?"))
        self.assertLess(output.index("which HLS flow?"), output.index("[4/5] hls"))
        self.assertIn("status       OK", (self.root / "out/pipeline/picked/manifest.txt").read_text())
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([args for name, args in calls if name == "hls"][-1],
                         ["6", "A", "", "synth-export"])

    def check_sweep(self, extension):
        before = len((self.root / "calls.jsonl").read_text().splitlines())
        self.run_script("src/sweep." + extension, ["--name", "widths", "--build", "A"])
        run = self.root / "out/sweep/widths"
        calls = [json.loads(line) for line
                 in (self.root / "calls.jsonl").read_text().splitlines()][before:]

        # The selected width is built first and without an override, because
        # its export is the one that writes selected_width.hpp.
        exports = [args for name, args in calls if name == "export"]
        self.assertEqual(exports[0], ["selected"])
        self.assertEqual(sorted(exports[1:]),
                         [["qacnn_w4.pt"], ["qacnn_w5.pt"],
                          ["qacnn_w7.pt"], ["qacnn_w8.pt"]])

        self.assertEqual([args for name, args in calls if name == "hls"],
                         [["6", "A", "5"], ["8", "A", "5"], ["7", "A", "5"],
                          ["5", "A", "5"], ["4", "A", "5"]])
        self.assertEqual([args for name, args in calls if name == "train"], [[]])

        self.assertIn("status       OK", (run / "manifest.txt").read_text())
        self.assertTrue((run / "summary/summary.md").is_file())
        for width in (8, 7, 6, 5, 4):
            self.assertIn("result         OK",
                          (run / f"widths/{width}/status.txt").read_text())
            self.assertTrue((run / f"widths/{width}/reports/vivado"
                             f"/nn_w{width}_A_timing.rpt").is_file())
            self.assertTrue((run / f"widths/{width}/reports/confusion_w{width}.png").is_file())
        self.assertTrue((run / "reports/confusion_fp32.png").is_file())

        # A sweep archives evidence, never an overlay: transfer.* refuses it,
        # and that refusal is the whole reason the directory is absent.
        self.assertFalse((run / "bitstream").exists())

    @unittest.skipUnless(os.name == "nt", "Windows file sharing")
    def test_actual_locked_file_is_not_reported_removed(self):
        import ctypes
        from ctypes import wintypes
        target = self.write("src/fpga/vivado/vivado_w6_A/locked.txt", "locked")
        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = ctypes.windll.kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        handle = create(str(target), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            with self.assertRaises(OSError):
                support.checked_remove(target.parent, self.src)
            self.assertTrue(target.is_file())
        finally:
            close(handle)

    @unittest.skipUnless(BASH, "Bash required")
    def test_sweep_config_header_names_match_the_exporter(self):
        # sweep.py cannot import export_config -- that module reaches
        # train/config.py, which imports torch -- so the header names are
        # spelled twice. This is the only thing keeping the two spellings
        # together, and a rename on the export side fails here rather than
        # silently archiving nothing.
        source = (ROOT / "src/export/export_config.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'^(?:WEIGHTS|PARAMS)_NAME = "([^"]+)"',
                                 source, re.MULTILINE))
        self.assertEqual({t.replace("{width}", "{}")
                          for t in sweep_config.WIDTH_HEADERS}, emitted)

    def test_sweep_config_confusion_tags_match_training(self):
        # train.py imports torch, so the sweep cannot ask it how it tagged each
        # matrix and the tags are spelled twice. A retag in training fails here
        # rather than leaving every width's matrix reported absent.
        source = (ROOT / "src/train/train.py").read_text(encoding="utf-8")
        tags = set(re.findall(r'save_confusion\(.*, f?"([^"]+)"\)', source))
        self.assertEqual(tags, {sweep_config.BASELINE_TAG,
                                sweep_config.WIDTH_TAG.replace("{width}", "{bit_width}")})

    def test_sweep_stage_logs_are_numbered_like_the_pipeline(self):
        # A sweep's per-width logs sit beside a pipeline run's in the reader's
        # head, so 2-check.log has to mean the same thing in both.
        self.assertEqual([sweep_config.log_name(s) for s in
                          (sweep_config.CLEAN_STAGE, *sweep_config.STAGES)],
                         ["0-clean.log", "1-train.log", "2-check.log",
                          "3-export.log", "4-hls.log", "5-vivado.log"])

    def test_hls_requires_completion_marker(self):
        for extension in (["bat", "sh"] if os.name == "nt" else ["sh"]):
            with self.subTest(extension=extension):
                self.fixture()
                shutil.copy2(ROOT / f"src/scripts/hls.{extension}",
                             self.scripts / f"hls.{extension}")
                if extension == "bat":
                    fake = self.write("tool.bat", "@echo off\nexit /b 0\n")
                else:
                    fake = self.write("tool.sh", "#!/usr/bin/env bash\nexit 0\n")
                    fake.chmod(0o755)
                self.env["VITIS_HLS"] = str(fake).replace("\\", "/")
                output = self.run_script(f"src/scripts/hls.{extension}", ["6", "A"], expected=1)
                self.assertIn("did not complete", output)

    @unittest.skipUnless(os.name == "nt", "Windows batch runner")
    def test_batch_pipeline_and_all(self):
        self.check_runner("bat")

    @unittest.skipUnless(os.name == "nt", "Windows batch runner")
    def test_batch_pipeline_synth_export(self):
        self.check_pipeline_synth_export("bat")

    @unittest.skipUnless(BASH, "Bash required")
    def test_shell_pipeline_and_all(self):
        self.check_runner("sh")

    @unittest.skipUnless(BASH, "Bash required")
    def test_shell_pipeline_synth_export(self):
        self.check_pipeline_synth_export("sh")

    def test_vivado_failure_does_not_launch_later_phases(self):
        self.write("src/fpga/hls/hls_w6_A/sol/impl/ip/component.xml", "ip")
        (self.src / "fpga/vivado").mkdir(parents=True)
        calls = []
        def fake_tool(cmd, cwd, env):
            calls.append(Path(cwd).name)
            if calls[-1] == "board":
                Path(env["NN_VIVADO_STATUS_FILE"]).write_text("0\n")
            # An exit code of zero without Tcl's marker must still fail.
            return 0
        with self.scoped(), patch.object(support, "preflight"), patch.object(support.subprocess, "call", fake_tool):
            with self.assertRaisesRegex(RuntimeError, "Vivado bd failed"):
                support.vivado("fake-vivado", ["6", "A"])
        self.assertEqual(calls, ["board", "bd"])
        manifests = list((self.src / "fpga/vivado/logs").glob("*/build.json"))
        self.assertEqual(len(manifests), 1)
        self.assertIn("FAILED", json.loads(manifests[0].read_text())["result"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
