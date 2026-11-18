from pathlib import Path

import numpy as np

from u96_config import RUN_DIR, SAMPLE_DIR_NAME, SEGMENT_FORMAT, SEGMENT_NAME


def find(run_dir=RUN_DIR):
    where = Path(run_dir) / SAMPLE_DIR_NAME
    if not where.is_dir():
        return None

    path = where / SEGMENT_NAME
    if not path.is_file():
        raise SystemExit(
            f"{where}: exists but holds no {SEGMENT_NAME}. "
            "Send the sample from the laptop again."
        )

    return path


def save(path, segment):
    np.savetxt(path, segment, fmt=SEGMENT_FORMAT)


def load(path, window, channels):
    segment = np.loadtxt(path, dtype=np.float32, ndmin=2)

    if segment.shape[1] != channels:
        raise SystemExit(
            f"{path}: {segment.shape[1]} columns, but the build takes {channels} channels."
        )
    if len(segment) < window:
        raise SystemExit(
            f"{path}: {len(segment)} samples, fewer than one {window}-sample window."
        )

    return segment
