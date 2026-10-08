# Boxing punch data — Zenodo 14965635

The six `.csv` files here are the dataset **exactly as published**, retrieved 2026-09-23. Their md5
sums match the record's. [`../zenodo_boxing.csv`](../zenodo_boxing.csv) is the same data
reformatted into our training layout.

> Manoharan, S. (2025). *Boxing punch data* [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.14965635 — licensed **CC BY 4.0**.

## What the source is

Elite boxers, one IMU on the **punching wrist**, 200 Hz. Columns are `gyrx gyry gyrz` (deg/s), then
`accx accy accz` (g). `Lead_hook.csv` has no header row, and the other five do. Each file holds
one punch type and runs as sets of about 10 punches.

## What `zenodo_boxing.csv` is

869 windows × 32 rows = 27,808 rows, in the same columns as `data.csv`.

| Class | Windows | From |
|---|---|---|
| `l_straight` / `r_straight` | 116 / 119 | `Lead_jab` / `Rear_jab` |
| `l_hook` / `r_hook` | 119 / 123 | `Lead_hook` / `Rear_hook` |
| `l_uppercut` / `r_uppercut` | 132 / 136 | `Lead_uppercut` / `Rear_uppercut` |
| `idle` | 124 | guard periods between punches, both hands |
| `block`, `weave`, `pickup`, `use` | 0 | not in the dataset |

## How it was made

1. **Resampled** 200 → 100 Hz with an anti-aliased zero-phase FIR decimation. **Converted** to
   m/s² and rad/s, and reordered to accel then gyro.
2. **Punches** are the peaks of `| |a| − 1 g |`, with these filters: prominence ≥ 0.8 g, ≥ 0.8 s
   apart (one per punch, not one each for extension and retraction), ≥ 300 °/s of wrist rotation
   within ±0.3 s, ≥ 35 % of the file's median spike, and another punch within 3 s. This yields
   one window per punch. The window's start is jittered so the peak lands in its central 160 ms,
   which is our labelling rule.
3. **Guard windows** have no punch within 0.4 s, wrist rotation under 150 °/s and `|a|` within
   1 ± 0.3 g.

## What is real and what was assigned

| | |
|---|---|
| **Real** | Every sample: the punch signals, their labels, and the guard periods. |
| **Lead = left, rear = right** | Assumes an orthodox stance, which the dataset does not record. |
| **The non-punching glove** | The dataset has only the punching wrist. The other glove's six channels are a guard window drawn at random from the *other* hand's recordings, for the same participant. Every window is therefore a composite of two real recordings made at different times. |
| **Participant IDs (0–2)** | Not in the dataset. Each file splits into three boxer blocks, at the set boundaries where strap orientation and punch amplitude change. That matches the protocol visible in the data: 4 sets × 10 punches per boxer. `Lead_uppercut` may hold four boxers, and its last two share a block. Merging boxers is the safe direction, because it never puts one boxer under two IDs. Each block was assigned to a participant **at random, once per file**, so no block is split across two IDs. Whether the same person appears in more than one file is unknown. |
| **`idle`** | A left and a right guard window from the same participant, paired at random. |

Each punch type was recorded as its own session, so strap orientation is partly confounded with
class. The sensor frame is also not our glove's frame. Treat accuracy on this data as evidence
that the model learns real punch dynamics, not as the accuracy our hardware will reach.
