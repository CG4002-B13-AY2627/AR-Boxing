"""Central configuration for the board half of the AI subsystem.

The counterpart to train/config.py, and the same rule applies: nothing that
varies is written as a literal anywhere else. Every path, glob, register offset
and count the board code needs has its one home here.

Note what is deliberately *not* here: the window size, channel count, class
count and label order. Those belong to the build, not to the host, and are read
out of description_w<N>.json at run time. Restating them here is exactly how a
host ends up disagreeing with the bitstream it is driving.
"""

from pathlib import Path

# --- Paths ------------------------------------------------------------------

# transfer.sh lays a run out as ~/ai/<run>/bitstream/{*.bit,*.hwh,*.json} with
# this code in ~/ai/<run>/src/, so the run directory is always our parent.
RUN_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR_NAME = "bitstream"
BUILD_DIR = RUN_DIR / BUILD_DIR_NAME

# The run's artefacts, by pattern rather than by name: the width and build are
# in the filename, and re-exporting at another width must not need an edit
# here. Each pattern is expected to match exactly one file -- see one().
BITSTREAM_GLOB = "nn_w*_*.bit"
DESCRIPTION_GLOB = "description_w*.json"
GOLDEN_GLOB = "golden_w*.npz"

# Overlay() finds the hardware handoff from the bitstream by replacing the
# suffix, which is why the two are shipped side by side with the same stem.
HWH_SUFFIX = ".hwh"

# Per-channel standardisation, applied by the PS before every inference.
# Unused until preprocess.py (stage 7); named here so the run's fifth artefact
# is not the one thing the config does not know about.
NORM_STATS_NAME = "norm_stats.json"

SAMPLE_DIR_NAME = "sample"
SEGMENT_NAME = "segment.txt"
SEGMENT_FORMAT = "%.9g"
HARDWARE_TABLE_NAME = "hardware_logits.txt"
TABLE_DIGEST_CHARS = 16

# --- The accelerator --------------------------------------------------------

# block_design.tcl instantiates the HLS IP as nn_infer_0. Matched by prefix so
# a second instance would be a loud failure rather than a silent wrong pick.
IP_PREFIX = "nn_infer"

# The AXI4-Lite control block of any ap_ctrl_hs HLS IP. Fixed by the control
# protocol, not by our model, so these do not vary with width or build.
CTRL = 0x00
AP_START = 1 << 0
AP_DONE = 1 << 1

# The two m_axi offset-slave pointers take a 64-bit address as two 32-bit
# registers, in_r_1/in_r_2 and out_r_1/out_r_2. Confirmed against nn_w6_A.hwh
# on the board, 2026-09-17 -- there is no merged 64-bit form.
IN_PORT = "in_r"
OUT_PORT = "out_r"
PTR_LO = "_1"
PTR_HI = "_2"

# --- verify.py --------------------------------------------------------------

# How many mismatching vectors to print in full before summarising. A
# systematic error breaks every vector, and 440 dumps help nobody.
MAX_REPORTED = 5

# --- bench.py ---------------------------------------------------------------

# Timed inferences. Enough that the p99 means something -- at ~1.2 ms each this
# is a little over a second, so there is no reason to run fewer.
BENCH_ITERATIONS = 1000

# Discarded before timing starts. The first calls pay page faults, a cold cache
# and PYNQ's first MMIO; folding those into the mean would flatter the result
# and folding them into the p99 would libel it.
BENCH_WARMUP = 50

# Reported alongside mean/min/max. p99 is the one that matters: a latency
# commitment is a promise about the worst case, not the average.
BENCH_PERCENTILES = (50, 99)

# --- measure_power.py -------------------------------------------------------

# Seconds of settling before each regime is recorded. The rails lag the load,
# and a mean taken across the transition is a mean of neither state.
POWER_SETTLE_SECONDS = 3.0

# Seconds recorded per regime. Long, deliberately: the interesting delta is
# maybe a tenth of the total draw, and the PS dominates everything.
POWER_SECONDS = 20.0

# Regimes are measured in alternating blocks rather than one long run each, so
# that slow drift and bursts on the WiFi rail affect every regime equally
# instead of whichever happened to be running at the time. POWER_SECONDS is
# split across this many blocks per regime.
POWER_BLOCKS = 5

# How often the rails are polled, in seconds. Each poll is a sysfs read per
# sensor, so this trades resolution against stealing time from the workload.
POWER_SAMPLE_INTERVAL = 0.1

# The realistic operating point. The PS windows at a stride of
# WINDOW_STRIDE_SAMPLES at SAMPLE_RATE_HZ, and classifies one window per
# player per stride. 100 Hz is the sampling rate the input contract specifies;
# it lives here because nothing in train/config.py holds it as a constant.
SAMPLE_RATE_HZ = 100
WINDOW_STRIDE_SAMPLES = 4
POWER_PLAYERS = 2

# Seconds between window boundaries. Derived, not written down.
STRIDE_SECONDS = WINDOW_STRIDE_SAMPLES / SAMPLE_RATE_HZ

# --- pm_*.py / pmanagement.py -----------------------------------------------

# Where the board's power knobs live. One root, because every knob under it is
# addressed the same way and naming each path separately would be four literals
# that must agree.
CPU_ROOT = Path("/sys/devices/system/cpu")

RFKILL_ROOT = Path("/sys/class/rfkill")
NET_ROOT = Path("/sys/class/net")
BLUETOOTH_ROOT = Path("/sys/class/bluetooth")
NET_FLAG_UP = 0x1

# Results land under the run directory, beside the bitstream they describe --
# the same principle as the run holding its own verify.sh. A sweep is named for
# when it ran, so re-running never destroys the measurement you are comparing
# against; restore.sh is not, because in an emergency you want the latest one
# without having to look up a name.
PM_DIR_NAME = "pmanagement"
RESTORE_NAME = "restore.sh"
REPORT_NAME = "report.md"
RESULTS_NAME = "results.json"
SNAPSHOT_NAME = "snapshot.json"
DEADMAN_NAME = "deadman.sh"
DEADMAN_ARMED_NAME = "deadman.armed"
DEADMAN_FIRED_NAME = "deadman.fired"
DEADMAN_MARGIN_SECONDS = 60.0

# PL clock settings, as divisors of whatever the bitstream was built for rather
# than as absolute megahertz. The nominal rate belongs to the block design, so
# writing 100/50/25 here would be restating it -- and it would silently mean
# something else the day pl_clk0 changes.
PL_CLOCK_DIVISORS = (1, 2, 4)

# Timed inferences per setting. Far fewer than BENCH_ITERATIONS because a sweep
# pays this at every point: enough for a stable mean and a usable p99, not
# enough to see the once-in-a-thousand scheduler outlier bench.py exists to
# catch. Quote bench.py for the latency commitment, not this.
PM_BENCH_ITERATIONS = 200

# Which of measure_power.py's regimes a sweep records. idle is what the board
# costs to have switched on and duty is what it costs in service; spin and
# continuous answer a question about the busy-wait that does not change with
# the knob being turned. Dropping them halves the time per setting.
PM_REGIMES = ("idle", "duty")

# Recording blocks per regime under --quick. POWER_BLOCKS exists to spread slow
# rail drift across every regime equally, so it cannot go to one without losing
# that property -- two is the least that still interleaves.
PM_QUICK_BLOCKS = 2

RADIO_SETTLE_SECONDS = 10.0
RAIL_RESOLUTION_W = 0.016
RADIO_RAIL = "3V3"

# The two rails a knob can actually move, and the only two quiet enough to
# read a tens-of-milliwatts change off. INT is the PL's own supply and PSINT_FP
# the application processor's; 3V3 wanders by ~170 mW because it carries the
# WiFi radio, and the rest do not respond to anything here.
#
# Both are needed, not either: lowering the PL clock shifts power *between*
# them -- the fabric draws less while the busy-wait polls for longer -- so a
# score on one rail alone credits or blames a knob for a transfer that did not
# change the total.
PL_RAIL = "INT"
PS_RAIL = "PSINT_FP"

# The AI lane's slice of the latency budget, in milliseconds. Every setting is
# checked against it, because a power saving that breaks the commitment is not
# a saving. See [[ai-subsystem]] for where the number comes from.
LATENCY_BUDGET_MS = 50.0

# ...and how that slice is divided between the two halves we measure, from the
# same latency table. The third row, window completion, is not written down
# here because it is not a budget at all: it is STRIDE_SECONDS, and deriving it
# is what stops the two from ever disagreeing.
PS_BUDGET_MS = 8.0
PL_BUDGET_MS = 2.0

# --- thermal.py -------------------------------------------------------------

# Where the kernel publishes its IIO devices. The ZynqMP AMS block lands here
# as iio:device0 named `ams`, confirmed on the board 2026-09-21, beside two
# irps5401 regulators and an iio_hwmon bridge under /sys/class/hwmon. One root
# rather than a device path, because the numbering is a probe-order accident
# and thermal.py finds the device by name.
IIO_ROOT = Path("/sys/bus/iio/devices")

# --- preprocess.py ----------------------------------------------------------

# MPU-6050 full-scale sensitivity the node firmware configures: ACCEL_CONFIG
# (0x1C) = 0x18 is +/-16 g, GYRO_CONFIG (0x1B) = 0x18 is +/-2000 deg/s. The nodes send
# raw int16 counts; training saw m/s^2 and rad/s. If the firmware changes
# either range these change with it, or every sample is mis-scaled.
ACCEL_LSB_PER_G = 2048.0
GYRO_LSB_PER_DPS = 16.4

# --- postprocess.py ---------------------------------------------------------

# Softmax probability a window must reach before it is allowed to emit an
# event. Below it the window is treated as "no action", not as its argmax:
# with eleven classes and a continuous stream, most windows fall between two
# actions and the argmax of a flat distribution is noise.
#
# Provisional, exactly like the selected bit width: it is set against synthetic
# data, and the value that matters comes off the real confusion matrix. Too
# high drops real punches, too low fires on guard adjustments.
CONFIDENCE_MIN = 0.60

# Seconds an action is suppressed after it fires, so one punch produces one
# event rather than one per overlapping window. A punch spans ~150-250 ms, so
# at a 40 ms stride it classifies over four to six consecutive windows; combos
# arrive at 3-5 punches/s, which is 200-330 ms apart. The refractory has to sit
# between those two numbers, and there is not much room: longer and the second
# punch of a fast combo is swallowed, shorter and one punch fires twice.
REFRACTORY_SECONDS = 0.15

# Classes that are postures rather than events. A sustained class fires on
# every window for as long as it is held, so it is reported as an edge -- a
# start when it takes hold, an end when it lets go -- instead of as a stream of
# identical events. This is why `unblock` is not a class: it is this falling
# edge, and asking the network to recognise a transition it sees a fraction of
# a window of would cost a class and its collection time.
SUSTAINED_ACTIONS = ("block",)

# Classes that never emit. `idle` exists so the model has somewhere to put
# guard adjustments and footwork instead of false-firing a punch; it is not a
# game action and the game has nothing to do with it.
IGNORED_ACTIONS = ("idle",)

# Consecutive windows without a sustained class before its falling edge fires.
# One is too eager -- a single window misreading a held block would end it and
# immediately restart it. Every window of hysteresis costs a stride of latency
# on the release, which is why this is not larger.
SUSTAINED_RELEASE_WINDOWS = 2

# Standard gravity, m/s^2. Subtracted from the accelerometer magnitude so that
# a stationary arm reads zero intensity rather than 9.8: the raw magnitude
# never falls below g, so an intensity built on it would be an offset, not a
# measure of how hard the punch was thrown.
GRAVITY_MS2 = 9.80665

# --- Helpers ----------------------------------------------------------------


def one(pattern, where=BUILD_DIR):
    """The single file in `where` matching `pattern`, or a loud failure.

    A run directory holds exactly one build. Two matches means two builds got
    mixed into one directory, which is worse than none: the code would pick one
    arbitrarily and every number after that would be attributed to the wrong
    bitstream.
    """
    hits = sorted(Path(where).glob(pattern))
    if len(hits) != 1:
        raise SystemExit(
            f"{where}: expected exactly one {pattern}, found {len(hits)}. "
            "A run directory holds one build."
        )
    return hits[0]
