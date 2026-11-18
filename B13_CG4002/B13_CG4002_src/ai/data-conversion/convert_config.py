import sys

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
TRAIN_DIR = ROOT_DIR / "pipeline" / "train"
U96_SRC_DIR = ROOT_DIR / "ultra-96" / "src"

for path in (TRAIN_DIR, U96_SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config as train_config  # noqa: E402
import u96_config  # noqa: E402

OUTPUT_PATH = train_config.DATA_DIR / "converted.csv"
PROVENANCE_SUFFIX = "_provenance"
SEED = train_config.RANDOM_SEED

WINDOW = train_config.WINDOW_SIZE
FEATURE_COLUMNS = train_config.FEATURE_COLUMNS
PARTICIPANT_COLUMN = train_config.PARTICIPANT_COLUMN
LABEL_COLUMN = train_config.LABEL_COLUMN
LABEL_TO_ID = train_config.LABEL_TO_ID
PRECISION = 4

GRAVITY = u96_config.GRAVITY_MS2

RAW_FILE = "file"
RAW_USER = "user_id"
RAW_LABEL = "label"
RAW_REP = "action_count"
RAW_NODE = {"l": "left", "r": "right"}
RAW_ID_TO_LABEL = dict(enumerate([
    "l_straight", "r_straight", "l_hook", "r_hook", "l_uppercut", "r_uppercut",
    "block", "weave", "pickup", "use", "idle",
]))

ACCEL = "a"
GYRO = "g"
ACCEL_LSB_PER_G = 2048
GYRO_LSB_PER_DPS = 16.4
RAW_MIN = -32768
RAW_MAX = 32767

REAL = "real"
MIRRORED = "mirrored"
RESAMPLED = "resampled"
SPLICED = "spliced"

TARGET = 110
SELF_MIRRORED = ("weave",)
REAL_ONLY = ("l_hook", "r_hook")
GLOVE_SPLICED = ("block",)
