# HLS Tcl flow

`run_hls.tcl` is the entry point. `src/scripts/hls.bat` or `src/scripts/hls.sh` finds Vitis HLS 2022.1, changes into `src/fpga/hls/`, and runs `-f tcl/run_hls.tcl`. The other Tcl files are sourced by the entry point; they expect its configured project and are not standalone commands.

## Full build, in execution order

| Order | File | Responsibility |
|---|---|---|
| 1 | `run_hls.tcl` | Parses width, build, vector count, and mode; checks the Vitis version; calls the steps below; writes the success marker only after the requested flow finishes. |
| 2 | `nn_width.tcl` | Reads `NN_WIDTH_SELECTED` from the generated `selected_width.hpp` when no width was supplied. An explicit width wins. Vivado also uses this helper. |
| 3 | `configure.tcl` | Opens or reuses the HLS project, adds `nn_infer.cpp` and `nn_tb.cpp` with the same compile flags, opens the solution, and applies the selected build's directives. A–E differ in directives, not source. Build E derives its weight-bank count from `CONV2_K` in the generated parameter header. |
| 4 | `csim.tcl` | Runs `csim_design`: the C++ testbench checks `nn_infer.cpp` against all golden vectors in the generated C header. |
| 5 | `csynth.tcl` | Runs `csynth_design` to synthesize the C++ accelerator into RTL and produce resource and latency estimates. |
| 6 | `cosim.tcl` | Runs C/RTL co-simulation with the requested vector count. It sources `cosim_workaround.tcl` before calling the simulator. |
| 7 | `export_ip.tcl` | Runs `export_design` to package the verified RTL as an IP catalog entry for Vivado. |

`cosim_workaround.tcl` is a helper for Vitis HLS 2022.1: it retries a specific Windows testbench instrumentation file-lock failure and skips an optional `CONV2` iteration profiler that can stall final reporting. DUT output comparison, AXI adapters, deadlock detection, and top-level timing remain active.

The full flow is **C simulation → C synthesis → C/RTL co-simulation → IP export**. C simulation uses the complete golden set; the optional vector-count argument controls co-simulation only.

## Arguments and modes

```text
hls.bat [width [build [cosim_count [mode]]]]
hls.sh  [width [build [cosim_count [mode]]]]
```

The width defaults to `selected_width.hpp`; the build defaults to `A`; the co-simulation count defaults to `GOLDEN_COSIM_N` in the generated golden header. `run_hls.tcl` defines these project-specific modes using standard Vitis HLS commands:

| Mode | Steps |
|---|---|
| `full` (default) | Reset project and solution; configure → C simulation → C synthesis → C/RTL co-simulation → IP export. |
| `synth-export` | Reset project and solution; configure → C synthesis → IP export. Skips both C simulation and C/RTL co-simulation. |
| `cosim-only` | Reopen existing synthesized RTL; C/RTL co-simulation only. No IP export. |
| `cosim-export` | Reopen existing synthesized RTL; C/RTL co-simulation → IP export. The full flow invokes this mode in a fresh process on Windows after synthesis, avoiding a Vitis HLS 2022.1 instrumentation failure. |

For example, `src/scripts/hls.bat 5 A 2 cosim-only` reruns two RTL test vectors for an existing 5-bit build A. `src/scripts/hls.bat 5 A "" synth-export` produces IP without running either simulation. Reuse modes require `hls_w<N>_<build>/sol/syn/report/nn_infer_csynth.rpt`; after changing sources or directives, run `full` or `synth-export` to synthesize again.

The working directory must be `src/fpga/hls/`: `add_files` resolves C++ files there, and generated `hls_w<N>_<build>/` projects are placed there. On Windows, the HLS launcher may return success even after a Tcl failure, so `run_hls.tcl` writes `NN_HLS_STATUS_FILE` only on success and the wrapper checks that marker. See [`../../docs/run-hls.md`](../../docs/run-hls.md) for direct invocation and [`../../docs/csim.md`](../../docs/csim.md) for simulation details.
