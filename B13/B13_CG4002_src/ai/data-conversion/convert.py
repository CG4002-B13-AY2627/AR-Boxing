import argparse

from pathlib import Path

import numpy as np

import convert_config as cc

from assemble import assemble
from merge import merged
from tables import frame, provenance


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Format, mirror, splice and resample collector recordings into the training CSV layout."
    )
    parser.add_argument("recordings", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, default=cc.OUTPUT_PATH)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--seed", type=int, default=cc.SEED)
    parser.add_argument("--target", type=int, default=cc.TARGET)

    return parser.parse_args()


def report(matrix, skipped, absent):
    if matrix is None:
        print("No participant recorded an action with both hands, so nothing is mirrored")
    else:
        print(f"Mirror, left accel -> right accel: {matrix.astype(int).tolist()}; gyro takes its negative")

    for reason, count in skipped.items():
        print(f"skipped {count} repetitions {reason}")

    if absent:
        print(f"no windows for {len(absent)} participant and class pairs: {absent}")


def main():
    arguments = parse_arguments()
    out = arguments.out
    origin_path = arguments.provenance or out.with_name(f"{out.stem}{cc.PROVENANCE_SUFFIX}{out.suffix}")

    raw = merged(arguments.recordings)

    rng = np.random.default_rng(arguments.seed)
    matrix, windows, skipped, absent = assemble(raw, rng, arguments.target)

    out.parent.mkdir(parents=True, exist_ok=True)
    table = frame(windows)
    table.to_csv(out, index=False, float_format=f"%.{cc.PRECISION}f")

    origin = provenance(windows)
    origin.to_csv(origin_path, index=False)

    report(matrix, skipped, absent)
    print(f"{len(windows)} windows, {len(table)} rows -> {out}")
    print(f"provenance -> {origin_path}")
    print(origin.groupby([cc.LABEL_COLUMN, cc.PARTICIPANT_COLUMN, "source"]).size().unstack([1, 2], fill_value=0).sort_index(axis=1).to_string())


if __name__ == "__main__":
    main()
