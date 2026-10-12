import sys
from pathlib import Path

HOME_DIR = Path(__file__).resolve().parents[2]

AI_ROOT = HOME_DIR / "ai"
AI_RUN_NAME = "demo"
AI_RUN_DIR = AI_ROOT / AI_RUN_NAME
AI_SRC_DIR = AI_RUN_DIR / "src"
AI_BUILD_DIR = AI_RUN_DIR / "bitstream"

COMMS_DIR = HOME_DIR / "comms"

PLAYERS = (1, 2)
LEFT_NODE = 0x01
RIGHT_NODE = 0x02

MS_PER_S = 1000
SAMPLE_PERIOD_MS = 10
PAIR_TOLERANCE_MS = SAMPLE_PERIOD_MS / 2
PAIR_BUFFER_SAMPLES = 50

MP_START_METHOD = "spawn"
IN_QUEUE_MAXSIZE = 2000
OUT_QUEUE_MAXSIZE = 200
QUEUE_GET_TIMEOUT_S = 1.0
MONITOR_INTERVAL_S = 1.0

sys.path.insert(0, str(AI_SRC_DIR))
sys.path.insert(0, str(COMMS_DIR))

from nn_driver import NNDriver
from postprocess import Postprocess
from preprocess import Preprocess
from window import WindowBuffer

def load_model():
    return NNDriver(AI_RUN_DIR)

def load_preprocess(nn):
    return Preprocess(AI_BUILD_DIR, desc=nn.desc)

def load_buffer(nn):
    return WindowBuffer(nn.desc.window, nn.desc.channels)

def load_postprocess(nn, pre):
    return Postprocess(nn.desc, pre.channel_names)

def load_comms_server():
    import comms_server
    return comms_server

def load_ai_events():
    import ai_events
    return ai_events
