# `train/`

Trains the FP32 1D CNN on [`data/mike-tyson.csv`](data/mike-tyson.csv), then a quantized copy at every
width in the sweep, and selects the width that goes to hardware.

## Entry point

Stage 1 of `pipeline.sh`, or on its own:

```bash
../scripts/train.sh            # train.bat on Windows
../scripts/train.sh --reinstall
```

The first run creates `pipeline/.venv` and installs the requirements. `--reinstall` installs them
again. Training runs `train.py` and writes:

| Output | Holds |
|---|---|
| `checkpoints/` | `cnn.pt` (FP32), `qacnn_w8.pt` to `qacnn_w4.pt`, and `norm_stats.json`, the per-channel mean and standard deviation the board standardizes with |
| `qmodel/` | The selected width's checkpoint, which `export/` reads |
| `plots/` | The loss curves and a confusion matrix per model |

## Structure

```
train/
├── train.py                 entry point
├── config.py                every setting
├── dataload.py              dataset, windows, split and folds
├── normalize.py             per-channel standardization
├── cnn.py                   FP32 network
├── qacnn.py                 quantized network
├── evaluate.py              accuracy and per-class results
├── selection.py             width selection
├── checkpoint.py            saving checkpoints
├── confusion.py             confusion matrix plot
├── loss_curve.py            loss curve plot
├── requirements.txt
├── requirements-macos.txt
├── data/
│   └── mike-tyson.csv
├── checkpoints/             generated
├── qmodel/                  generated
└── plots/                   generated
```

## Files

| File | Does |
|---|---|
| `train.py` | Entry point. Splits the data, fits the standardization, trains FP32, trains each quantized width from it, and selects one. |
| `config.py` | Every setting, below |
| `dataload.py` | Reads the CSV into 32-sample windows and makes the train/test split and the folds |
| `normalize.py` | Fits the per-channel statistics on the training set and saves them |
| `cnn.py` | The FP32 network |
| `qacnn.py` | The same network in Brevitas, quantized, initialized from the FP32 weights |
| `evaluate.py` | Test accuracy and per-class results |
| `selection.py` | Compares each width against FP32 and picks the narrowest within budget |
| `checkpoint.py` | Saves checkpoints and copies the selected one to `qmodel/` |
| `confusion.py`, `loss_curve.py` | The plots |

## Configuration

[`config.py`](config.py) owns every dimension of the model, and everything downstream (export, HLS,
the board) derives from it.

| Group | Settings |
|---|---|
| Data | `CSV_NAME`, `FEATURE_COLUMNS` (12 channels), `LABEL_TO_ID` (10 classes), `WINDOW_SIZE` 32, `TEST_SIZE` 0.2, `K_FOLDS` 3, `RANDOM_SEED` |
| Network | `CONV1_FILTERS`/`KERNEL`, `POOL_KERNEL`/`STRIDE`, `CONV2_FILTERS`/`KERNEL`, `HIDDEN_UNITS` |
| Quantization | `BIT_WIDTH_SWEEP` [8, 7, 6, 5, 4], `MAX_QUANT_LOSS_PP` 2.0 |
| FP32 training | `NUM_EPOCHS`, `LEARNING_RATE`, `WEIGHT_DECAY`, early stopping and learning-rate plateau |
| QAT | `QAT_NUM_EPOCHS`, `QAT_LEARNING_RATE` |

To train on another dataset, put the CSV in `data/` and change `CSV_NAME`.

## Requirements

| File | For |
|---|---|
| [`requirements.txt`](requirements.txt) | Windows and Linux. PyTorch, Brevitas for quantization-aware training, pandas and scikit-learn for loading and splitting, matplotlib, torchsummary and tqdm for reporting. |
| [`requirements-macos.txt`](requirements-macos.txt) | macOS. The same packages, held at PyTorch 2.2.2 and NumPy 1.26, the last versions with Intel Mac wheels. |

`train.sh` picks the file by platform.
