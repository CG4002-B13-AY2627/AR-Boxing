# CG4002 B13: Software/Hardware AI

Source code for the action classifier of our AR boxing game, from training to inference on the
Ultra96-V2.

## Quick start

```bash
./pipeline/pipeline.sh --name my-run --build A --hls-mode synth-export
U96_JUMP=<nus-id>@stujump.comp.nus.edu.sg ./ultra-96/transfer.sh --name my-run
```

The first command trains the model and builds the bitstream into `out/pipeline/my-run/`. The second
sends it to `~/ai/my-run/` on the board, where `bash verify.sh` checks it. On Windows, use the
`.bat` beside each script. See [`pipeline/`](pipeline/README.md) and [`ultra-96/`](ultra-96/README.md)
for the details.

## Dataset

[`pipeline/train/data/mike-tyson.csv`](pipeline/train/data/mike-tyson.csv), recorded by the four of
us with both gloves.

## Structure

```
final-src-code/
├── pipeline/        dataset, training, export, HLS and Vivado, to a bitstream
├── ultra-96/        transfer to the board, and the code that runs on it
└── out/             generated, one folder per pipeline run
```
