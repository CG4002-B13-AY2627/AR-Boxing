# Data conversion

Converts the recordings made by the glove data collector (`datacollection.py`, in the hardware
source) into the training CSV that [`../pipeline/train/`](../pipeline/train/train.md) reads. It
converts units, then balances every participant's classes with the augmentation described in the
report.

## Quick start

Run training once first, since this uses `pipeline/.venv`.

```bash
./convert.sh 18-11-26.csv --out ../pipeline/train/data/my-data.csv
```

`convert.bat` on Windows, same arguments. Then set `CSV_NAME = "my-data.csv"` in
[`../pipeline/train/config.py`](../pipeline/train/config.py) and run the pipeline.

| Argument | |
|---|---|
| recordings | One or more collector CSVs. The collector writes one per session date, so a dataset recorded over several days is several files, merged in the order given. |
| `--out` | The training CSV. By default `../pipeline/train/data/converted.csv`. |
| `--provenance` | Where each window came from. By default beside `--out`, as `<name>_provenance.csv`. |
| `--target` | Windows per participant per class. By default 110. |
| `--seed` | The random seed. By default the one in `train/config.py`. |

It prints the mirror it fitted, anything it skipped, any participant and class with no windows,
and the number of windows per participant, class and source. The same recordings and seed always
give the same CSV.

## What it does

| Step | Does |
|---|---|
| Read | Splits each recording into 32-sample repetitions by participant, label and count |
| Units | Converts raw counts to m/s$^2$ and rad/s, at the IMU's $\pm 16$ g and $\pm 2000^\circ$/sec ranges |
| Mirroring | For straights and uppercuts, adds the opposite hand's repetitions mirrored. Weave is mirrored onto itself. The mirror is fitted from the actions each participant recorded with both hands. |
| Real only | Hooks are never mirrored, since a mirrored hook lands between hook and uppercut |
| Glove splicing | For block, a new window takes its left glove from one repetition and its right glove from another |
| Resampling | For pickup and idle, each of the 12 channels comes from a random real repetition of the same participant and class |
| Top-up | Any class still below the target, such as hooks with fewer than 110 real repetitions, is filled the same way by resampling its real and mirrored windows |
| Shuffle | Shuffles the windows with the seed |

Every participant and class with at least one repetition comes out with at least the target number
of windows. Classes with more real and mirrored windows than the target keep all of them.

It works on any collector CSV, and skips what it cannot use:

| Case | What happens |
|---|---|
| A repetition is not 32 samples long | Skipped, and counted in the output |
| A label the model has no class for, such as `use` | Skipped, and counted in the output |
| A participant never recorded a class, in either hand | That participant has no windows of it. Listed in the output. |
| No participant recorded an action with both hands | Nothing is mirrored, and the top-up fills those classes instead |

The more real repetitions per class, the fewer windows are synthesized. Recording at least 55 of
each action per participant, with both hands for the one-handed punches, keeps resampling to the
classes the report applies it to.

The output has one row per sample, with columns `index`, `participant`, the 12 channels and
`label`. The label sits on the last row of each window.

## Structure

```
data-conversion/
├── convert.sh / .bat        entry point
├── convert.py               reads, assembles and writes
├── convert_config.py        every setting
├── merge.py                 reads and merges the recordings
├── recording.py             repetitions, channels and units
├── assemble.py              which strategy each class gets
├── mirror.py                fits and applies the mirror
├── splice.py                glove splicing
├── resample.py              per-channel resampling
└── tables.py                the training CSV and the provenance table
```

## Configuration

[`convert_config.py`](convert_config.py) holds the settings. Window size, channels and labels come
from [`../pipeline/train/config.py`](../pipeline/train/config.py).

| Setting | |
|---|---|
| `TARGET` | Windows per participant per class, unless `--target` is given |
| `REAL_ONLY`, `SELF_MIRRORED`, `GLOVE_SPLICED` | The classes that get each strategy. Every other one-handed class is mirrored, and every other two-handed class is resampled. |
| `ACCEL_LSB_PER_G`, `GYRO_LSB_PER_DPS` | The IMU's scale at its configured range |
| `RAW_ID_TO_LABEL` | The collector's label IDs. Repetitions of `use` are skipped, since the model has no class for it. |
