# Ultra-96

Runs a pipeline build on the Ultra96-V2. `transfer.sh` sends a run from the laptop to the board,
and the scripts on the board verify it, measure it and serve classifications to the game.

## Quick start

**Requirements**

| | |
|---|---|
| A run | `../out/pipeline/<name>/`, made by [`../pipeline/pipeline.sh`](../pipeline/README.md) |
| Laptop | `ssh` and `scp` (OpenSSH), and bash, or use `transfer.bat` on Windows |
| Board | Ultra96-V2 with PYNQ 3.0.1, reached through the NUS jump host |

**Transfer**

```bash
U96_JUMP=<nus-id>@stujump.comp.nus.edu.sg ./transfer.sh --name my-run
```

`transfer.bat` takes the same arguments. ssh asks for your NUS password at the jump host and the
`xilinx` password at the board. `--dry-run` lists what would be sent without sending it. The
connection is set by four variables:

| Variable | Default | |
|---|---|---|
| `U96_HOST` | `xilinx@makerslab-fpga-<>.ddns.comp.nus.edu.sg` | The board |
| `U96_JUMP` | `<nus-id>@stujump.comp.nus.edu.sg` | The jump host. Set your own NUS ID. |
| `U96_ROOT` | `ai` | Where runs land in the board's home directory |
| `U96_HOST_PASSWORD` | none | The board's password, so it is not asked for |

The run lands in `~/ai/<name>/`:

```
~/ai/<name>/
├── bitstream/               .bit, .hwh, norm_stats.json, description, golden vectors
├── src/                     the host code
├── verify.sh, latency.sh, power.sh, pmanagement.sh, test.sh
└── template.py
```

**On the board**

```bash
ssh -J <nus-id>@stujump.comp.nus.edu.sg xilinx@makerslab-fpga-12.ddns.comp.nus.edu.sg
cd ~/ai/my-run
bash verify.sh
```

Each script runs as root, since loading an overlay needs it.

| Script | Does | Prints |
|---|---|---|
| `verify.sh [n]` | Replays every golden window, or the first `n`, on the FPGA and compares the logits with the model's | How many windows match bit for bit, and how many are classified correctly |
| `latency.sh [n]` | Times the PS work and the accelerator round trip, and adds them up against each latency bound | Mean and p99 of every stage against its bound |
| `power.sh [regime]` | Reads the board's power rails at idle, inferring continuously, and at the real duty cycle | Watts per rail in each regime, and the die temperatures |
| `pmanagement.sh` | Sweeps every combination of CPU cores, CPU clock and PL clock, then the radios. Ranks the configurations that hold every latency bound and applies the one picked. `restore` puts the board back. | A table of every configuration, then asks which to apply. The report is saved to `pmanagement/<time>/report.md`. |
| `test.sh` | Streams samples through windowing, preprocessing, the FPGA and post-processing to events | The events produced |

## Structure

```
ultra-96/
├── transfer.sh / .bat       laptop to board
├── scripts/                 run on the board, from the run root
│   ├── verify.sh
│   ├── latency.sh
│   ├── power.sh
│   ├── pmanagement.sh
│   └── test.sh
└── src/                     the host code
    ├── u96_config.py        every setting
    ├── classifier.py        what the game calls
    ├── template.py          an example integration
    ├── window.py, preprocess.py, nn_driver.py, postprocess.py, description.py
    ├── verify.py, bench.py, budget.py, latency.py, commitment.py
    ├── test.py, segment.py, logit_table.py
    ├── power.py, thermal.py, measure_power.py
    └── pmanagement.py, pm_*.py
```

## Files

**Inference**

| File | Does |
|---|---|
| `classifier.py` | Samples in, events out, for both players. The one object the game server calls. |
| `window.py` | A ring buffer that emits a 32-sample window every 4 samples |
| `preprocess.py` | Standardizes a window with `norm_stats.json`, transposes it to channel-major and quantizes it to 8 bits |
| `nn_driver.py` | Loads the overlay, copies the window in, starts the accelerator and reads the 10 scores back. The only file that touches hardware. |
| `postprocess.py` | Turns scores into events, with the confidence threshold and the suppression rules |
| `description.py` | Reads `description_w<N>.json`, the class order, window and channels the build was made with |
| `template.py` | The four stages above wired together, for an integration to copy |
| `u96_config.py` | Every setting on the board side |

**Verification and timing**

| File | Does |
|---|---|
| `verify.py` | Behind `verify.sh` |
| `bench.py`, `budget.py` | Time the accelerator round trip and the PS work per window |
| `latency.py`, `commitment.py` | Behind `latency.sh`. Combine both halves into the latency table. |
| `test.py`, `segment.py`, `logit_table.py` | Behind `test.sh`. Random input, or a recorded segment in `sample/` printed as a table of logits. |

**Power**

| File | Does |
|---|---|
| `power.py`, `thermal.py` | Read the INA226 power rails and the die temperatures |
| `measure_power.py` | Behind `power.sh` |
| `pmanagement.py` | Behind `pmanagement.sh` |
| `pm_knobs.py`, `pm_radios.py` | The power settings the board exposes, and its radios |
| `pm_measure.py`, `pm_rank.py`, `pm_report.py` | Measure each configuration, rank them, write `pmanagement/<time>/report.md` |
| `pm_guard.py` | Records the starting state and writes the script that restores it |

## Integration

```python
from classifier import Classifier

classifier = Classifier()
for event in classifier.push(player, sample, t):
    print(event.action, event.confidence, event.intensity)
```

`player` is 0 or 1. `sample` is the 12 channel values at one instant, in the order of the
description. `t` is the time in seconds, stamped at the glove. Most calls return no events, and
every fourth sample runs one inference.
