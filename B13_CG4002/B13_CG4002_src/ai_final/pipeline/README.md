# Pipeline

Trains the gesture classifier and turns it into a bitstream for the Ultra96-V2. One command runs
all five stages, from the dataset to a `.bit`/`.hwh` pair that [`../ultra-96/`](../ultra-96/)
loads onto the board.

## Quick start

**Requirements**

| | |
|---|---|
| Python | 3.12 or 3.13. The first run creates `pipeline/.venv` and installs [`train/requirements.txt`](train/requirements.txt) into it. |
| Vitis HLS and Vivado | 2022.1, on `PATH` or in the default install location |
| Shell | bash (Git Bash on Windows), or use the `.bat` beside every `.sh` |

**Run**

```bash
./pipeline.sh --name my-run --build A --hls-mode synth-export
```

On Windows, `pipeline.bat` takes the same arguments. Any argument left out is prompted for during the run itself.

| Argument | Values | |
|---|---|---|
| `--name` | letters, digits, `.`, `-`, `_` | The name of the run's archive folder |
| `--build` | `A`–`E` | The HLS directive set. |
| `--hls-mode` | `full`, `synth-export` | `full` adds C simulation and co-simulation. |
| `--from` | `train`, `check`, `export`, `hls`, `vivado` | Resume from a stage, skipping the ones before it |

The generated files from any previous run are cleaned first. Then the stages run in order, and each
prints its log path:

| Stage | Does | Prints |
|---|---|---|
| 1 `train` | Trains the FP32 model, then quantization-aware training at 8, 7, 6, 5 and 4 bits. Selects the narrowest width within 2 pp of FP32. | Test accuracy of every model, the selected width |
| 2 `check` | Runs the exported integer model and the board's preprocessing against Brevitas | Match counts. The run stops on any mismatch. |
| 3 `export` | Writes the C++ headers and golden test vectors for the selected width | The generated files |
| 4 `hls` | Synthesizes the network into a packaged IP core | The Vitis HLS output. The estimates go to `reports/hls/`. |
| 5 `vivado` | Builds the block design and implements it | The bitstream written. The run fails if timing is not met. |

Everything is archived in
`../out/pipeline/<name>/`:

| Folder | Holds |
|---|---|
| `bitstream/` | `.bit`, `.hwh`, `norm_stats.json`, the model description and golden vectors. Everything the Ultra96 board needs. |
| `headers/` | The generated C++ headers |
| `model/` | The quantized checkpoint |
| `reports/` | Vivado timing, utilization and power, HLS reports, the loss curve and confusion matrices |
| `logs/` | The output of every stage |
| `manifest.txt` | Status, width, build, timings |

To put the run on the board, see [`../ultra-96/`](../ultra-96/).

## Structure

```
pipeline/
├── pipeline.sh / .bat      runs every stage below, in order
├── train/                  dataset, model definition, training
│   └── data/mike-tyson.csv
├── export/                 checkpoint -> integer description -> C++ headers
├── fpga/
│   ├── hls/                the network in C++, and the Vitis HLS flow
│   └── vivado/             the block design and implementation flow
├── scripts/                one script per stage, plus clean and shared helpers
└── test/                   live testing with the gloves on a laptop
```

Notably, the dataset we collected and used for our final product lives in [`/train/data/mike-tyson.csv`](./train/data/mike-tyson.csv) (Data is collected by four of us and *not* from Mike Tyson).

## Directories

| Directory | Function |
|---|---|
| [`train/`](train/train.md) | Loads the dataset, standardizes it and splits it. Trains the FP32 1D CNN and its quantized copies, and selects the width that goes to hardware. `config.py` holds the configuration of the model. |
| [`export/`](export/export.md) | Reads the quantized checkpoint's integer weights and scales, and writes them out as C++ headers with golden input/output vectors. Checks that the integer arithmetic reproduces Brevitas exactly before anything is synthesized. |
| [`fpga/`](fpga/fpga.md) | `hls/` holds the hand-written forward pass (`nn_infer.cpp`), its testbench, and the Tcl flow that synthesizes it into an IP core. `vivado/` wraps that core in a Zynq block design and produces the bitstream. |
| [`scripts/`](scripts/scripts.md) | The five stage scripts `pipeline.sh` calls, which can also be run one at a time. `clean`, which removes generated files and the shared build configuration. |
| [`test/`](test/test.md) | Streams both gloves into a laptop and classifies them live with a trained model, to test it on continuous motion before it goes to the board. Used mainly for feedback on model training.|

For more information, the documentation lives in their respective subdirectories.
