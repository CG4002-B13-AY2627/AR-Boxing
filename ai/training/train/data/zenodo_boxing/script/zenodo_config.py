import sys

from collections import namedtuple
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = SCRIPT_DIR.parent
TRAIN_DIR = SOURCE_DIR.parents[1]
U96_SRC_DIR = TRAIN_DIR.parents[1] / "ultra-96" / "src"

for path in (TRAIN_DIR, U96_SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config as train_config  # noqa: E402
import u96_config  # noqa: E402

OUTPUT_PATH = train_config.DATA_DIR / "zenodo_boxing.csv"
SEED = train_config.RANDOM_SEED

WINDOW = train_config.WINDOW_SIZE
FEATURE_COLUMNS = train_config.FEATURE_COLUMNS
PARTICIPANT_COLUMN = train_config.PARTICIPANT_COLUMN
LABEL_COLUMN = train_config.LABEL_COLUMN
IDLE_LABEL = "idle"
PRECISION = 4

SOURCE_RATE_HZ = 200
TARGET_RATE_HZ = u96_config.SAMPLE_RATE_HZ
GRAVITY = 9.80665

Source = namedtuple("Source", ["label", "cuts_s", "participants"])

SOURCES = {
    "Lead_jab": Source("l_straight", (51.1, 124.4), (2, 1, 0)),
    "Rear_jab": Source("r_straight", (48.3, 115.2), (1, 0, 2)),
    "Lead_hook": Source("l_hook", (80.5, 150.0), (0, 1, 2)),
    "Rear_hook": Source("r_hook", (57.9, 120.1), (1, 0, 2)),
    "Lead_uppercut": Source("l_uppercut", (65.7, 111.3), (2, 0, 1)),
    "Rear_uppercut": Source("r_uppercut", (69.1, 124.2), (2, 0, 1)),
}

PEAK_PROMINENCE_G = 0.8
PEAK_SPACING_S = 0.8
ROTATION_MIN_DPS = 300
ROTATION_REACH_S = 0.3
SPIKE_FRACTION = 0.35
NEIGHBOUR_S = 3.0
CENTRAL_S = 0.16

GUARD_CLEAR_S = 0.4
GUARD_ROTATION_MAX_DPS = 150
GUARD_TOLERANCE_G = 0.3
