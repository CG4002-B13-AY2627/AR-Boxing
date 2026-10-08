# `vivado/tcl/` — what each script does

The Tcl half of the Vivado flow, kept apart from the project directories, `bit/` and `reports/`
it writes one level up. Nothing here is launched by hand: `src/scripts/vivado.sh` / `.bat` finds
Vivado 2022.1 and runs `install_board.tcl` then `block_design.tcl`, passing every argument
straight through. It consumes the IP `hls/tcl/run_hls.tcl` packaged and produces
`bit/nn_w<N>_<B>.{bit,hwh}`.

Listed in the order they run: make the board visible, build the design, implement it — and the
file all three source first.

| Script | What it does |
|---|---|
| `install_board.tcl` | **Once per Vivado installation.** Pulls the Avnet `ultra96v2:part0:1.2` board definition from Vivado's own XHub store and confirms it is visible afterwards. Idempotent — it queries the catalog and installs only what is missing — so the wrapper can run it before every build and a fresh machine works unattended. |
| `block_design.tcl` | **The build.** Creates the project, the PS from the board preset, the `nn_infer` IP, and the two AXI paths: `M_AXI_HPM0_FPD` → AXI4-Lite control, and the accelerator's `m_axi_gmem` → `S_AXI_HP0_FPD`, each through its own SmartConnect. Then `assign_bd_address`, validate, save. `-tclargs 6 A bd` stops there — **two minutes instead of twenty** when you only want to know the diagram is sound. The part comes from the board file and the width from `hls/tcl/nn_width.tcl`, so neither is restated here. It refuses when the packaged IP for that width and build is missing, and refuses an existing project directory outright: deleting one is the wrapper's job, not a build script's. |
| `implement.tcl` | Sourced only by the second process `block_design.tcl` starts, never on its own. Generates the targets, wraps the block design, runs implementation through `write_bitstream`, and writes the timing, utilisation and power reports into `reports/`. **It is also the gate**: WNS and WHS are read back and a missing or negative one is an error, so a build that misses timing never reaches `bit/` and no latency or power number is ever quoted for one. The `.bit` and `.hwh` are copied out under the same basename, which is how PYNQ finds the handoff from the bitstream. |
| `session.tcl` | Not a phase. Sourced first by each of the three: the 2022.1 version check, a thread cap, and `nn_vivado_finish`, which writes the status file the wrappers gate on instead of trusting an exit code. |

`block_design.tcl` runs in two processes on purpose — the block design has to be closed before
output generation and implementation, and a fresh process per phase is also what keeps one
phase's scratch state out of the next. The second Vivado invocation in the log is expected.

**Four warnings during the block design are expected and none is worth chasing:** `PSU-1` DDR at
479.995 MHz (the Ultra96 preset cannot hit 500 from the PS reference clock, and PYNQ's own FSBL
configured DDR at boot, so it never reaches hardware), `BD 41-2384` AWLOCK/ARLOCK width (the HLS
IP emits an AXI3-style lock and never issues exclusive accesses), `BD 41-237` AWUSER/ARUSER
mismatch (SmartConnect ties them low), and SmartConnect's low-area-mode note about WRAP bursts on
the control path, which PYNQ's single-beat MMIO never issues.
