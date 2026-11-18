# `export/`

Turns the selected quantized checkpoint into what the FPGA and the board need: an integer
description of every layer, C++ headers, and golden test vectors. Before any header is written, it
checks that the integer arithmetic reproduces Brevitas exactly.

## Entry point

Stages 2 and 3 of `pipeline.sh`, or on their own, in this order:

```bash
../scripts/check.sh            # check.bat on Windows
../scripts/export.sh           # export.bat on Windows
```

Both read the checkpoint in `../train/qmodel/` and share `pipeline/.venv` with training.

`check.sh` runs `check.py`. It exits non-zero if either check fails, which stops the pipeline:

| Check | Compares |
|---|---|
| Preprocessing | The board's [`preprocess.py`](../../ultra-96/src/preprocess.py) against Brevitas's input quantizer |
| Integer model | The exported description, run in NumPy integers, against every Brevitas quantizer |

`export.sh` runs `export.py` and writes:

| Output | Holds |
|---|---|
| `build/description_w<N>.json` | Every layer's integer weights, biases, shifts and clamps. The board loads it too. |
| `../fpga/hls/params_w<N>.hpp` | Types, dimensions, shifts and clamps |
| `../fpga/hls/weights_w<N>.hpp` | Weights and biases as constant arrays |
| `../fpga/hls/selected_width.hpp` | The selected width |
| `../fpga/hls/golden_w<N>.h` | Golden inputs and logits for C simulation and co-simulation |
| `../fpga/hls/golden_w<N>.npz` | The same vectors for the board to replay |

## Structure

```
export/
├── check.py                 entry point, stage 2
├── check_config.py          check settings
├── check_preprocess.py      preprocessing check
├── int_model.py             bit-exact integer model
├── export.py                entry point, stage 3
├── export_config.py         export settings
├── extract.py               checkpoint to description
├── emit.py                  description to headers
├── golden.py                golden vectors
└── build/                   generated
```

## Files

| File | Does |
|---|---|
| `check.py` | Entry point of stage 2. Runs one Brevitas pass and both checks against it. |
| `check_preprocess.py` | Compares the board's preprocessing with the input quantizer |
| `int_model.py` | The network in NumPy integers, layer by layer, compared against Brevitas |
| `export.py` | Entry point of stage 3. Runs extract, then emit, then golden. |
| `extract.py` | Reads the checkpoint's integer weights and scales, and derives each layer's shift, clamp bounds and accumulator width |
| `emit.py` | Writes the description out as C++ headers |
| `golden.py` | Runs test windows through Brevitas and saves inputs and logits as a header and an `.npz` |

## Configuration

| File | Holds |
|---|---|
| [`export_config.py`](export_config.py) | Which checkpoint is read, output paths and names, the layer topology the extractor walks, and how many golden vectors are written (200 for co-simulation) |
| [`check_config.py`](check_config.py) | How many windows the checks run over, and the rounding mode |

Model dimensions are not set here. They come from [`../train/config.py`](../train/config.py).
