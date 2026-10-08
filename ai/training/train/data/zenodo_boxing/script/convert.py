import argparse

from pathlib import Path

import numpy as np

import zenodo_config as zc

from zenodo import assemble, frame


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Reformat Zenodo 14965635 into the training CSV layout."
    )
    parser.add_argument("--out", type=Path, default=zc.OUTPUT_PATH)
    parser.add_argument("--seed", type=int, default=zc.SEED)

    return parser.parse_args()


def main():
    arguments = parse_arguments()

    table = frame(assemble(np.random.default_rng(arguments.seed)))
    table.to_csv(arguments.out, index=False, float_format=f"%.{zc.PRECISION}f")

    labelled = table.dropna(subset=[zc.LABEL_COLUMN])
    print(f"{len(labelled)} windows, {len(table)} rows -> {arguments.out}")
    print(labelled.groupby([zc.LABEL_COLUMN, zc.PARTICIPANT_COLUMN]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
