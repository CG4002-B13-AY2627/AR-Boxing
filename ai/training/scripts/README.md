# `src/scripts/` — build stages and helpers

Run the stages below in order. On Windows, use the `.bat` files; on macOS or Linux, use the matching `.sh` files. Each pair has the same role. Run commands from the repository root.

For a complete, named run, use the orchestrator in `src/`:

```powershell
.\src\pipeline.bat --name my-run --build A
```

```bash
bash src/pipeline.sh --name my-run --build A
```

`pipeline` cleans, runs the five stages, and archives the outputs under `out/pipeline/my-run/`. The build letter selects an HLS directive set; the quantization width comes from the checkpoint selected by training. After export, the pipeline asks whether HLS should run the full flow or only synthesize and export IP. Use `--hls-mode full` or `--hls-mode synth-export` to skip that picker. `--from <stage>` resumes at a stage and retains the inputs that stage needs; when resuming from Vivado after a synthesis-only HLS run, pass `--hls-mode synth-export` so report collection expects no simulation reports.

## Execution order

| Order | Script | What it does | Main result |
|---|---|---|---|
| 0 | `clean.bat` / `clean.sh` | Removes generated artifacts from an earlier build. `pipeline` runs this before starting; a resumed run cleans only the stages it will repeat. Run `clean --dry-run` to preview or `clean hls vivado` to limit the cleanup. | A clean set of outputs for the requested stages. |
| 1 | `train.bat` / `train.sh` | Creates or updates `src/.venv` when needed, trains an FP32 baseline, then fine-tunes and evaluates Brevitas quantized models at the configured bit widths. Selects the narrowest width within the accuracy-loss budget. | One selected checkpoint in `src/train/qmodel/`, plus normalization statistics, plots, and checkpoints for the width sweep. |
| 2 | `check.bat` / `check.sh` | Re-extracts the integer model from the selected checkpoint. Checks the board's input preprocessing against Brevitas's input quantizer, then checks each integer-model stage against Brevitas. A mismatch stops the pipeline. | A pass/fail gate before any hardware headers are generated. |
| 3 | `export.bat` / `export.sh` | Extracts the checked checkpoint's integer description, emits HLS parameters and weights, and generates golden input/output vectors. | `description_w<N>.json`, `params_w<N>.hpp`, `weights_w<N>.hpp`, `golden_w<N>.h`/`.npz`, and `selected_width.hpp`. |
| 4 | `hls.bat` / `hls.sh` | Uses Vitis HLS to run C simulation, synthesize the C++ accelerator, run C/RTL co-simulation, and package the RTL as an IP block. The `synth-export` mode runs only synthesis and IP export. Accepts optional width, build letter, vector count, and mode arguments. | Packaged HLS IP and reports for the steps run. |
| 5 | `vivado.bat` / `vivado.sh` | Ensures the Ultra96-V2 board definition is installed, connects the packaged IP to the processing system, implements the design, checks timing, and writes the overlay. The optional `bd` mode stops after block-design validation. | `nn_w<N>_<build>.bit` and matching `.hwh`, plus timing, utilization, and power reports. |

By default, `<N>` is the selected quantization width. When no width is passed to HLS or Vivado, their Tcl scripts read `selected_width.hpp`; an explicit width is used for comparison builds. A width shown in an example comment is not the build's source of truth. The `.bit` and `.hwh` must have the same stem so PYNQ can load them together.

The stage wrappers can also be run individually while iterating. `train`, `check`, and `export` share `src/.venv`; their wrappers install the training requirements when the environment is missing or the requirements change. `hls` and `vivado` need the project's Vitis HLS and Vivado toolchain. The complete flow and archive layout are described in [`../README.md`](../README.md).

## Other files in this directory

These support the stages or a separate comparison run; they are not additional steps after Vivado.

| File | Role |
|---|---|
| `build_support.bat` / `build_support.sh` | Entry points used by the build orchestrators, cleanup script, and hardware wrappers to call the shared Python build helper. |
| `build_support.py` | Holds the workspace lock, checks for active FPGA tools, performs checked cleanup, runs isolated Vivado phases, and resolves the A–E build menu. It also prevents two builds or a build and a clean from using the same workspace at once. |
| `build_config.py` | Central source for build paths, generated filenames, cleanup targets, environment variable names, and directive-set labels. It is imported, not run as a stage. |
| `sweep.py` | Controller called by `src/sweep.bat` or `src/sweep.sh`. It trains once, then runs `check` → `export` → `hls` → `vivado` for each configured width and writes a comparison under `out/sweep/<name>/`. It does not archive a deployable bitstream. |
| `sweep_config.py` | Central source for the width sweep's stage order, archive layout, report names, and short co-simulation setting. It is imported by `sweep.py`. |
| `check_build.py` | Regression checks for the build scripts using disposable workspaces and fake vendor tools. Run it separately with `python src/scripts/check_build.py`; it does not train or compile the FPGA design. |

To compare HLS directive sets at one width, use `src/all.bat` or `src/all.sh`. To compare quantization widths at one directive set, use `src/sweep.bat` or `src/sweep.sh`. For the board-ready result, use `src/pipeline.bat` or `src/pipeline.sh`.
