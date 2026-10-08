"""Generate the placeholder IMU dataset until real collection happens."""

import csv

import numpy as np

from config import (
    DATA_DIR,
    CSV_NAME,
    WINDOW_SIZE,
    RANDOM_SEED,
    PARTICIPANT_COLUMN,
    FEATURE_COLUMNS,
    LABEL_TO_ID,
)

# This is stand in data, not recorded data. It exists so the pipeline can be
# built and tested end to end before anybody straps a Beetle on. Every time the
# class list in config.py changes, run this file again rather than editing the
# csv by hand.
#
# What it does try to get right is the structure the model has to learn:
#
#   - Left and right actions differ in *which glove moves*, which is the whole
#     point of splitting straight/hook/uppercut into l_ and r_ variants. The
#     idle glove only carries gravity and noise.
#   - Punch types differ in which axes move. A straight pushes forward, a hook
#     swings sideways and yaws, an uppercut lifts and pitches.
#   - Defensive and utility actions are slower and involve both arms.
#   - Participants differ in amplitude, timing and mounting angle, so holding a
#     participant out for testing is a real test rather than a formality.

NUMBER_OF_PARTICIPANTS = 4
REPETITIONS_PER_CLASS = 40

GRAVITY = 9.81

ACCELEROMETER_NOISE = 0.05
GYROSCOPE_NOISE = 0.02

# Per action: which arm moves, how wide the motion is in samples, and the
# amplitude on each of the six channels of a moving glove.
#
#   arm:   "l", "r" or "both"
#   width: standard deviation of the bump, in samples. Punches are brief,
#          blocks and pickups are long.
#   axes:  (ax, ay, az, gx, gy, gz)
ACTION_PROFILES = {
    "l_straight": {"arm": "l", "width": 3.0, "axes": (12.0, 1.5, 2.0, 0.5, 2.0, 0.8)},
    "r_straight": {"arm": "r", "width": 3.0, "axes": (12.0, 1.5, 2.0, 0.5, 2.0, 0.8)},
    "l_hook": {"arm": "l", "width": 4.0, "axes": (3.0, 11.0, 2.0, 0.8, 1.0, 6.5)},
    "r_hook": {"arm": "r", "width": 4.0, "axes": (3.0, -11.0, 2.0, 0.8, 1.0, -6.5)},
    "l_uppercut": {"arm": "l", "width": 4.0, "axes": (4.0, 2.0, -10.0, 6.0, 1.5, 1.0)},
    "r_uppercut": {"arm": "r", "width": 4.0, "axes": (4.0, 2.0, -10.0, 6.0, 1.5, 1.0)},
    "block": {"arm": "both", "width": 9.0, "axes": (1.0, 1.5, -4.5, 1.2, 0.8, 0.5)},
    "weave": {"arm": "both", "width": 8.0, "axes": (2.5, 3.5, 2.0, 1.5, 2.5, 1.5)},
    "pickup": {"arm": "both", "width": 11.0, "axes": (2.0, 2.5, -5.5, 2.0, 1.0, 1.0)},
    "use": {"arm": "both", "width": 5.0, "axes": (2.0, 2.0, 1.5, 1.0, 1.0, 3.0)},
    "idle": {"arm": "none", "width": 12.0, "axes": (0.3, 0.3, 0.3, 0.2, 0.2, 0.2)},
}


def participant_traits(rng):
    """How one person differs from another, held constant across their session."""
    return {
        # Reach and power vary between people.
        "gain": rng.normal(1.0, 0.15),
        # The straps never sit at quite the same angle twice.
        "tilt": rng.normal(0.0, 0.35, size=3),
        # Every gyroscope has its own resting offset.
        "gyro_bias": rng.normal(0.0, 0.05, size=6),
    }


def bump(width, centre, length):
    """A smooth single-peaked envelope, the shape of one action."""
    time = np.arange(length)

    return np.exp(-0.5 * ((time - centre) / width) ** 2)


def make_window(label, traits, rng):
    """One (window_size, channels) window of a single action."""
    profile = ACTION_PROFILES[label]

    window = np.zeros((WINDOW_SIZE, len(FEATURE_COLUMNS)), dtype=np.float64)

    # Gravity sits on z while the glove is roughly level, shifted a little by
    # however this participant's straps happen to sit.
    for glove in (0, 1):
        window[:, glove * 6 + 0] += traits["tilt"][0]
        window[:, glove * 6 + 1] += traits["tilt"][1]
        window[:, glove * 6 + 2] += GRAVITY + traits["tilt"][2]

    # The action does not start at the same instant every repetition.
    centre = rng.uniform(0.35, 0.65) * WINDOW_SIZE
    envelope = bump(profile["width"], centre, WINDOW_SIZE)

    if profile["arm"] == "l":
        moving_gloves = [0]
    elif profile["arm"] == "r":
        moving_gloves = [1]
    elif profile["arm"] == "both":
        moving_gloves = [0, 1]
    else:
        moving_gloves = []

    for glove in moving_gloves:
        for axis, amplitude in enumerate(profile["axes"]):
            # Each repetition is a little stronger or weaker than the last.
            scale = traits["gain"] * rng.normal(1.0, 0.12)
            window[:, glove * 6 + axis] += amplitude * scale * envelope

    # Sensor noise and the resting gyroscope offset.
    for glove in (0, 1):
        accelerometer = slice(glove * 6, glove * 6 + 3)
        gyroscope = slice(glove * 6 + 3, glove * 6 + 6)

        window[:, accelerometer] += rng.normal(0.0, ACCELEROMETER_NOISE, (WINDOW_SIZE, 3))
        window[:, gyroscope] += rng.normal(0.0, GYROSCOPE_NOISE, (WINDOW_SIZE, 3))
        window[:, gyroscope] += traits["gyro_bias"][glove * 3:glove * 3 + 3]

    return window


def generate():
    """Build the whole csv: every participant, every class, every repetition."""
    rng = np.random.default_rng(RANDOM_SEED)

    windows = []

    for participant in range(NUMBER_OF_PARTICIPANTS):
        traits = participant_traits(rng)

        for label in LABEL_TO_ID:
            for _ in range(REPETITIONS_PER_CLASS):
                windows.append((participant, label, make_window(label, traits, rng)))

    # Shuffle so a participant's session is not ordered by class, which would
    # otherwise let the split accidentally correlate with recording order.
    rng.shuffle(windows)

    return windows


def write(windows, path):
    header = ["index", PARTICIPANT_COLUMN] + FEATURE_COLUMNS + ["label"]

    path.parent.mkdir(exist_ok=True)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        row_index = 0

        for participant, label, window in windows:
            for offset, sample in enumerate(window):
                # Only the final row of a window carries the label.
                is_last = offset == WINDOW_SIZE - 1

                writer.writerow(
                    [row_index, participant]
                    + [f"{value:.4f}" for value in sample]
                    + [label if is_last else ""]
                )

                row_index += 1

    return row_index


if __name__ == "__main__":
    windows = generate()
    path = DATA_DIR / CSV_NAME
    rows = write(windows, path)

    print(f"Wrote {rows} rows ({len(windows)} windows) to {path}")
    print(f"{NUMBER_OF_PARTICIPANTS} participants, {len(LABEL_TO_ID)} classes, "
          f"{REPETITIONS_PER_CLASS} repetitions each")
