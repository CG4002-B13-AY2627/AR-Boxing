"""Central configuration for the build scripts: where things are, and what they are called.

The counterpart to train/config.py and u96_config.py, and the same rule
applies: nothing that varies is written as a literal anywhere else. Every
location the wrappers touch, every generated name they match, and every
environment variable they pass between one another has its one home here.

Note what is deliberately *not* here. Nothing describing the network or the
export: the width a build runs at is read out of the header the export writes,
and the accelerator's dimensions are description_w<N>.json's business. This
file knows file *names*, never what is inside them.

The .sh and .bat wrappers cannot import Python, so each resolves two paths of
its own -- this directory, from $0 or %~dp0, and src/ one level above it.
Those are the only duplicates of anything below, and they are structural: a
script has to find itself before it can find anything else.
"""

from pathlib import Path

# --- Roots ------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPTS_DIR.parent
REPO_DIR = SRC_DIR.parent

# --- Locations, relative to a root ------------------------------------------

# Relative, and joined at the point of use rather than resolved here. The
# checks in check_build.py run this whole layer against a disposable copy of
# the tree by moving the two roots above, and an absolute path frozen at import
# time would quietly reach past that copy into the real workspace.

HLS_SUBDIR = "fpga/hls"
VIVADO_SUBDIR = "fpga/vivado"

# The one generated header not named for a width, because its job is to carry
# one. The width is read back out of it rather than handed from stage to
# stage, so a resume agrees with the export by construction, not by argument.
SELECTED_WIDTH_NAME = "selected_width.hpp"
SELECTED_WIDTH_DEFINE = "NN_WIDTH_SELECTED"

# The OS lock one build, comparison or cleanup holds for its whole run,
# including artefact collection. At the repository root because a clean deletes
# inside src/, and the file the workspace is locked against must not be one of
# its own targets.
LOCK_NAME = ".build.lock"

# --- Environment ------------------------------------------------------------

# Set by guard() for the whole process tree. A nested stage that finds its own
# parent's token inherits the lock instead of deadlocking against it.
GUARD_TOKEN = "NN_BUILD_GUARD"

# The bash the wrappers were started from, spelled the way the other platform's
# tooling can read. build_support.sh sets it; command() honours it.
BASH_OVERRIDE = "NN_BUILD_BASH"

# Where a Vivado run leaves its phase logs, journals and input-hash manifest.
# pipeline.* and all.* point this at the archive so the diagnostics land with
# the run; a standalone build leaves it unset and gets VIVADO_SUBDIR/logs.
VIVADO_LOG_DIR = "NN_VIVADO_LOG_DIR"

# Written by the Tcl on success. Vivado's exit code alone does not prove the
# script ran to the end, so both must agree before a bitstream is published.
VIVADO_STATUS_FILE = "NN_VIVADO_STATUS_FILE"

# The checkpoint an export reads instead of the one training selected, so a
# width sweep can build a width that was not chosen. emit.py leaves
# selected_width.hpp alone when it is set: a sweep entry is not a selection.
CHECKPOINT_OVERRIDE = "NN_CHECKPOINT_OVERRIDE"

# NN_HLS_STATUS_FILE is the same idea for Vitis HLS, and is deliberately absent
# here: hls.sh and hls.bat create it and run_hls.tcl writes it, so no Python
# ever sees the name and putting it here would imply otherwise.

# --- Archives ---------------------------------------------------------------

# out/<kind>/<name>/, one kind per script that writes runs, so a reader knows
# which question a run was answering before opening it. pipeline/ ships, all/
# compares directives, sweep/ compares widths. The wrappers spell their own
# kind the way they spell their own roots -- that duplicate is structural.
OUT_NAME = "out"
OUT_KIND_PIPELINE = "pipeline"
OUT_KIND_ALL = "all"
OUT_KIND_SWEEP = "sweep"
OUT_KINDS = (OUT_KIND_PIPELINE, OUT_KIND_ALL, OUT_KIND_SWEEP)

# --- Vendor tools -----------------------------------------------------------

# Process names that mean a build is already under way. A live tool holds
# handles inside the directories a clean is about to remove, so preflight
# refuses rather than leaving a half-deleted workspace behind.
TOOLS = ("vivado", "vivado_lab", "vitis_hls", "xsim", "xelab", "xvlog", "xvhdl")

# Vivado runs much of its flow inside a bare tclsh, which is far too common a
# name to reject on sight. One is ours only if its path says so.
TCLSH = "tclsh"
TOOL_PATH_PATTERN = r"xilinx|vitis|vivado"

# --- Cleanup ----------------------------------------------------------------

# Files that must exist before anything is deleted. A missing one means
# SRC_DIR is not the workspace we think it is, and the safest thing to do with
# a path that is not what we think it is, is nothing.
WORKSPACE_MARKERS = ("train/config.py", "export/export_config.py",
                     "fpga/hls/tcl/run_hls.tcl")

# What each stage generates, relative to SRC_DIR. A resume cleans from its own
# stage onward, so these are grouped by which stage *writes* them and never by
# which stage reads them. Datasets, the virtual environment and out/ appear
# nowhere here and are therefore never at risk.
CLEAN_PATTERNS = {
    "train": ["train/checkpoints/*", "train/qmodel/*", "train/plots/*"],
    "export": ["fpga/hls/params_w*.hpp", "fpga/hls/weights_w*.hpp",
               "fpga/hls/golden_w*.h", "fpga/hls/golden_w*.npz",
               "fpga/hls/selected_width.hpp", "export/build/*"],
    "hls": ["fpga/hls/hls_w*_*", "fpga/hls/nn_csim", "fpga/hls/vitis_hls.log"],
    "vivado": ["fpga/vivado/vivado_w*_*", "fpga/vivado/bit/*",
               "fpga/vivado/reports/*", "fpga/vivado/.Xil",
               "fpga/vivado/.crashReporter", "fpga/vivado/*.log",
               "fpga/vivado/*.jou", "fpga/vivado/*.str", "fpga/vivado/logs"],
}

# --- Bytecode caches --------------------------------------------------------

# Swept on every clean whatever stages were named: bytecode belongs to no
# stage, is regenerated on the next import, and a cache left by a module that
# has since moved is exactly what makes a resume behave differently from a
# fresh run.
PYCACHE_NAME = "__pycache__"

# Both halves of the Python, relative to REPO_DIR. ultra-96/ is outside src/
# because it ships to the board, and picks up caches whenever check.py imports
# preprocess.py to check it. A root that does not exist is skipped, not an
# error: a workspace may hold only one of the two.
PYCACHE_ROOTS = ("src", "ultra-96")

# Skipped whole. The virtual environment's caches belong to the installed
# packages rather than to us, and re-creating them costs an import of torch.
PYCACHE_EXCLUDE = {".venv"}

# --- Builds -----------------------------------------------------------------

# The HLS directive sets. Letters, not names, because they differ only in which
# pragmas run_hls.tcl applies and the letter is what it selects on. A is the
# unoptimised baseline and the build that ships -- it is selected on latency
# margin, area and energy, which is why DEFAULT_BUILD is it. E is the optimised
# build: it fits and meets timing, but buys 1.29x for 1.8x the DSPs and 23% more
# energy per window. B-D are the record of an unrolling that does not fit at all.
BUILDS = ("A", "B", "C", "D", "E")
DEFAULT_BUILD = BUILDS[0]

# One line each, for the picker the pipeline scripts show when no --build was
# given. A prompt, not documentation: run_hls.tcl carries the directives and
# the reasoning, and this says only enough to choose between them.
BUILD_LABELS = {
    "A": "no directives -- the baseline the others are measured against",
    "B": "both convolution time loops pipelined -- 10x over the part",
    "C": "B plus unrolls that pipelining already did -- identical to B",
    "D": "C plus a 4-way partition -- larger than C, and slower",
    "E": "conv2's input loop widened -- the optimised build",
}

# "bd" stops after validate_bd_design; "full" goes through to a bitstream.
VIVADO_MODE_FULL = "full"
VIVADO_MODE_BD = "bd"
VIVADO_MODES = (VIVADO_MODE_FULL, VIVADO_MODE_BD)
DEFAULT_VIVADO_MODE = VIVADO_MODE_FULL

# --- Generated names --------------------------------------------------------

# The Tcl creates these; nothing here may spell one differently from the script
# that writes it. {width} is the bit width and {build} the directive letter, so
# two builds never collide and a clean's globs can stay build-blind.
HLS_PROJECT = "hls_w{width}_{build}"
HLS_SOLUTION = "sol"

# The packaged RTL IP, and the file whose presence means packaging finished.
# export_design can fail after csynth has reported success, so the deliverable
# is checked rather than inferred from an exit code.
HLS_IP = "impl/ip"
HLS_IP_MARKER = "component.xml"

VIVADO_PROJECT = "vivado_w{width}_{build}"

# The overlay pair. Both keep this stem and sit side by side: PYNQ's Overlay()
# finds the .hwh from the .bit by replacing the suffix.
BITSTREAM_STEM = "nn_w{width}_{build}"
BITSTREAM_SUFFIXES = ("bit", "hwh")
BIT_SUBDIR = "bit"

# Post-implementation timing, utilisation and power, which is what section 5.6
# quotes. Globbed by stem, so a build removes its own and leaves the others.
REPORT_GLOB = "reports/{stem}_*.rpt"

# Both halves keep their Tcl in a tcl/ subdirectory, so the flow scripts sit
# apart from the sources, headers and generated projects beside them. One name
# here rather than a prefix on each script below.
TCL_SUBDIR = "tcl"

# The two Tcl phases, each run in a fresh process. install_board.tcl is
# idempotent and installs the Avnet board part only when it is missing;
# block_design.tcl builds the design and then implements it.
BOARD_SCRIPT = "install_board.tcl"
DESIGN_SCRIPT = "block_design.tcl"

# block_design.tcl takes the mode as its third argument: VIVADO_MODE_BD to
# stop at the validated design, this to carry the same design on to a
# bitstream in a second, separate process.
DESIGN_IMPL_ARG = "impl"

# --- Vivado diagnostics -----------------------------------------------------

# One directory per invocation, holding a per-phase log and journal, the run
# logs Vivado generated inside the project, and a manifest of tool, inputs and
# per-phase outcome. Retained on failure: a blind retry that hides the original
# error is worse than no retry at all.
LOG_SUBDIR = "logs"
MANIFEST_NAME = "build.json"

# Vivado's own per-run logs, copied out of the project before it is removed.
# .rst files are the report-strategy dumps the runs leave beside them.
RUN_LOG_SUFFIXES = {".log", ".jou"}
RUN_LOG_EXTRA = ".rst"
