import argparse
import sys

from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent
REPO_DIR = SRC_DIR.parent

EXPORT_DIR = SRC_DIR / "export"
U96_SRC_DIR = REPO_DIR / "ultra-96" / "src"

for path in (EXPORT_DIR, U96_SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import export_config  # noqa: E402

from u96_config import BUILD_DIR_NAME  # noqa: E402

train_config = export_config.train_config
build_config = export_config.build_config

DATASET_SCRIPT_DIR = REPO_DIR / "data-conversion"
DATASET_CONFIG_NAME = "convert_config.py"

if str(DATASET_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_SCRIPT_DIR))

RUNS_DIR = REPO_DIR / build_config.OUT_NAME / build_config.OUT_KIND_PIPELINE
NORM_STATS_PATH = train_config.CHECKPOINT_DIR / train_config.NORM_STATS_NAME

LOG_DIR = TEST_DIR / "logs"
LOG_NAME_FORMAT = "%Y-%m-%d_%H-%M-%S"
LOG_SUFFIX = ".log"
STARTED_FORMAT = "%Y-%m-%d %H:%M:%S"

BAUD_RATE = 115200
SERIAL_TIMEOUT_S = 1

LINE_PREFIX = "DATA"
INDEX_FIELD = "index"
LINE_FIELDS = (
    INDEX_FIELD,
    "right_ax", "right_ay", "right_az",
    "right_gx", "right_gy", "right_gz",
    "left_ax", "left_ay", "left_az",
    "left_gx", "left_gy", "left_gz",
    "right_button", "left_button",
)

TOP_K = 3
SAMPLE_PRECISION = 4


def log_path(started):
    return LOG_DIR / f"{started.strftime(LOG_NAME_FORMAT)}{LOG_SUFFIX}"


def run_build_dir(run):
    path = RUNS_DIR / run / BUILD_DIR_NAME

    if not path.is_dir():
        raise SystemExit(f"{path}: no such build. Runs live in {RUNS_DIR}.")

    return path


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Classify live glove IMU data on this machine, window by window.",
    )

    parser.add_argument(
        "--port",
        help="serial port of the right glove (default: the one USB serial device attached)",
    )

    model = parser.add_mutually_exclusive_group()
    model.add_argument(
        "--run",
        help=f"an archived run in {RUNS_DIR.relative_to(REPO_DIR)}, executed as the "
             "integer model the bitstream was built from",
    )
    model.add_argument(
        "--checkpoint",
        type=Path,
        help=f"a {export_config.CHECKPOINT_GLOB} checkpoint, run in Brevitas "
             f"(default: the one in {train_config.QMODEL_DIR.relative_to(REPO_DIR)})",
    )

    parser.add_argument(
        "--norm-stats",
        type=Path,
        default=NORM_STATS_PATH,
        help=f"the checkpoint's normalisation statistics "
             f"(default: {NORM_STATS_PATH.relative_to(REPO_DIR)})",
    )

    arguments = parser.parse_args(argv)

    if arguments.run is not None and arguments.norm_stats != NORM_STATS_PATH:
        parser.error("--norm-stats is for a checkpoint; a run carries its own")

    return arguments
