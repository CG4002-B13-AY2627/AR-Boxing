# `scripts/`

One script per pipeline stage, each with a `.sh` and a `.bat` that take the same arguments.
`pipeline.sh` calls them in order. Each can also be run on its own.

## Entry point

```bash
./train.sh  [--reinstall]
./check.sh  [--reinstall] [--rounding <mode>] [--vectors <n>]
./export.sh [--reinstall]
./hls.sh    [width] [build] [cosim vectors] [mode]
./vivado.sh [width] [build] [bd]
./clean.sh  [--dry-run] [train] [export] [hls] [vivado]
```

Each exits non-zero on failure. The Python stages share one virtual environment, `pipeline/.venv`,
which the first of them to run creates. `clean.sh` deletes what the named stages generated, or
every stage's output when none is named. `--dry-run` lists the files without deleting them.

## Structure

```
scripts/
├── train.sh / .bat          stage 1, see ../train/train.md
├── check.sh / .bat          stage 2, see ../export/export.md
├── export.sh / .bat         stage 3, see ../export/export.md
├── hls.sh / .bat            stage 4, see ../fpga/fpga.md
├── vivado.sh / .bat         stage 5, see ../fpga/fpga.md
├── clean.sh / .bat          deletes generated files
├── build_support.sh / .bat
├── build_support.py         locking, checked cleanup, build list
└── build_config.py          paths and generated names
```

## Files

| File | Does |
|---|---|
| `train`, `check`, `export` | Create the virtual environment if needed, install the requirements when they change, and run the stage's Python entry point |
| `hls`, `vivado` | Find Vitis HLS or Vivado and run the stage's Tcl entry point |
| `clean` | Deletes generated files, stage by stage |
| `build_support.py` | Holds a lock so that two builds never run in the same tree at once. Refuses to clean while a Xilinx tool is running. Lists and validates the build letters. |
| `build_config.py` | Every path, generated name and environment variable the scripts use |
