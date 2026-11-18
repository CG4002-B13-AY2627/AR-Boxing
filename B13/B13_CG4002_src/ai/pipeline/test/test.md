# `test/`

Classifies live glove data on a laptop, window by window, with the same windowing and
post-processing the board runs. Used to test a trained model on continuous motion and to find what
to record next.

## Entry point

The right glove connects over USB serial. Run training first, since this uses `pipeline/.venv`.

```bash
./scripts/live.sh                     # live.bat on Windows
./scripts/live.sh --run my-run        # a built run in ../../out/pipeline/
./scripts/live.sh --checkpoint <path> # a checkpoint in Brevitas
./scripts/live.sh --port COM5
```

| Argument | |
|---|---|
| `--run` | Runs a pipeline run's exported model in integers, as the FPGA would |
| `--checkpoint` | Runs a quantized checkpoint in Brevitas. By default, the one in `../train/qmodel/`. |
| `--norm-stats` | The standardization statistics for `--checkpoint` |
| `--port` | The serial port. By default, the only USB serial device attached. |

It prints every sample, every window's top classes and every event, until Ctrl+C. The session is
saved to `logs/`.

## Structure

```
test/
├── live.py                  entry point
├── live_config.py           settings and arguments
├── glove.py                 serial reader
├── conversion.py            raw counts to the units the model trained on
├── build_model.py           a run's integer model
├── checkpoint_model.py      a checkpoint in Brevitas
├── lines.py                 console output
├── run_log.py               session log
├── requirements.txt
├── scripts/
│   └── live.sh / .bat
└── logs/                    generated
```

## Files

| File | Does |
|---|---|
| `live.py` | Reads the gloves, fills the window buffer, classifies each window and post-processes the results into events |
| `live_config.py` | Serial settings, log location and the arguments above |
| `glove.py` | Finds the serial port and parses each line from the glove |
| `conversion.py` | Converts raw sensor counts to m/s$^2$ and rad/s |
| `build_model.py` | Runs the integer model from a run's `bitstream/` |
| `checkpoint_model.py` | Runs a Brevitas checkpoint |
| `lines.py`, `run_log.py` | Format the console output and write the session log |

The window buffer and post-processing are imported from [`../../ultra-96/src/`](../../ultra-96/src/),
so the laptop and the board behave the same.

## Requirements

[`requirements.txt`](requirements.txt) adds `pyserial` to the training environment, installed on the
first run.
