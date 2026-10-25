import serial
import csv
import math
import os
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# Configuration
# ============================================================

#IMU fields are stored as signed raw integer sensor counts.

PORT = "COM5"
BAUD_RATE = 115200
OUTPUT_FILE = "imu_two_hands_raw.csv"

# The gloves stream at ~100 Hz (one row per ~10 ms). Timing below is counted
# in rows read, so it follows the data rather than the PC clock.
ROWS_PER_SECOND = 100

# Every saved action is exactly this many rows.
SAMPLES_PER_ACTION = 32

# The buttons are not used. Each attempt counts down 3-2-1-0 in the terminal,
# one second per number, and the action must start within START_WINDOW_MS of
# 0 or the attempt is discarded.
COUNTDOWN_FROM = 3
START_WINDOW_MS = 640
START_WINDOW_ROWS = START_WINDOW_MS * ROWS_PER_SECOND // 1000

# Postures rather than gestures: after a single countdown, every
# SAMPLES_PER_ACTION rows recorded is one action.
CONTINUOUS_ACTIONS = ("idle", "block")

# Movement detection, in raw counts. The last REST_ROWS of the countdown are
# the resting pose, and an action starts on the first row where either hand's
# accel or gyro vector is further than its threshold from rest. In the
# existing data, idle noise stays under ~8500 counts 99% of the time and even
# weak punches peak above ~20000.
REST_ROWS = 20
ACCEL_THRESHOLD = 10000
GYRO_THRESHOLD = 10000

# The thresholds trip a few rows after the movement really begins, so each
# action also keeps this many rows from before that point.
LEAD_IN_ROWS = 3

LABEL_TO_ID = {
    "l_straight": 0,
    "r_straight": 1,
    "l_hook": 2,
    "r_hook": 3,
    "l_uppercut": 4,
    "r_uppercut": 5,
    "block": 6,
    "weave": 7,
    "pickup": 8,
    "use": 9,
    "idle": 10,
}

IMU_FIELDS = (
    "right_ax", "right_ay", "right_az",
    "right_gx", "right_gy", "right_gz",
    "left_ax", "left_ay", "left_az",
    "left_gx", "left_gy", "left_gz",
)

MOTION_VECTORS = (
    (("right_ax", "right_ay", "right_az"), ACCEL_THRESHOLD),
    (("right_gx", "right_gy", "right_gz"), GYRO_THRESHOLD),
    (("left_ax", "left_ay", "left_az"), ACCEL_THRESHOLD),
    (("left_gx", "left_gy", "left_gz"), GYRO_THRESHOLD),
)

SGT = ZoneInfo("Asia/Singapore")

# ============================================================
# User inputs
# ============================================================

print("Available labels:")
for label, label_id in LABEL_TO_ID.items():
    print(f"  {label_id:>2} -> {label}")

id_to_label = {v: k for k, v in LABEL_TO_ID.items()}

while True:
    label_input = input("\nEnter action label (name or ID): ").strip().lower()

    if label_input.isdigit():
        label_id = int(label_input)
        if label_id in id_to_label:
            action_label = label_id
            action_name = id_to_label[label_id]
            break
    elif label_input in LABEL_TO_ID:
        action_name = label_input
        action_label = LABEL_TO_ID[action_name]
        break

    print("Invalid label. Enter either the label name or ID.")

while True:
    try:
        user_id = int(input("Enter user ID: "))
        break
    except ValueError:
        print("User ID must be an integer.")

while True:
    try:
        total_required = int(input("Enter number of actions required: "))
        if total_required > 0:
            break
        print("Number of actions must be greater than 0.")
    except ValueError:
        print("Please enter an integer.")

print()
print("======================================")
print(f"Action:          {action_name} ({action_label})")
print(f"User ID:         {user_id}")
print(f"Target actions:  {total_required}")
print(f"Action length:   {SAMPLES_PER_ACTION} rows")
if action_name not in CONTINUOUS_ACTIONS:
    print(f"Start window:    {START_WINDOW_MS} ms after 0")
print("======================================")
print()

# ============================================================
# Helper functions
# ============================================================

def get_sgt_timestamp():
    return datetime.now(SGT).isoformat(timespec="milliseconds")


def format_row(action_count, row, final_label):
    return [
        action_count,
        row["timestamp"],
        user_id,
        row["right_ax"],
        row["right_ay"],
        row["right_az"],
        row["right_gx"],
        row["right_gy"],
        row["right_gz"],
        row["left_ax"],
        row["left_ay"],
        row["left_az"],
        row["left_gx"],
        row["left_gy"],
        row["left_gz"],
        final_label,
    ]


def read_row():
    """Block until the next valid DATA line arrives and return it as a row."""
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()

        if not line or not line.startswith("DATA,"):
            continue

        values = line.split(",")

        # DATA,index,
        # right_ax,right_ay,right_az,right_gx,right_gy,right_gz,
        # left_ax,left_ay,left_az,left_gx,left_gy,left_gz,
        # right_button,left_button
        #
        # The firmware still sends the buttons, but they are ignored.
        if len(values) != 16:
            continue

        try:
            imu_values = [int(value) for value in values[2:14]]
        except ValueError:
            continue

        row = dict(zip(IMU_FIELDS, imu_values))
        row["timestamp"] = get_sgt_timestamp()
        return row


def rest_pose(rows):
    return {field: sum(row[field] for row in rows) / len(rows) for field in IMU_FIELDS}


def is_moving(row, rest):
    return any(
        math.dist([row[f] for f in fields], [rest[f] for f in fields]) > threshold
        for fields, threshold in MOTION_VECTORS
    )


def countdown():
    """Print COUNTDOWN_FROM down to 0, one second apart.

    Rows are read throughout, so 0 appears in step with the live data.
    Returns the last REST_ROWS rows read before 0.
    """
    # Drop anything buffered before this attempt so 0 lines up with live data.
    ser.reset_input_buffer()

    recent = deque(maxlen=REST_ROWS)
    for number in range(COUNTDOWN_FROM, 0, -1):
        print(f"{number}... ", end="", flush=True)
        for _ in range(ROWS_PER_SECOND):
            recent.append(read_row())
    print("0  GO!", flush=True)
    return recent


def attempt_action():
    """Count down, then capture the action that starts after 0.

    Returns (rows, None), or (None, reason) when the attempt is discarded.
    """
    recent = countdown()
    rest = rest_pose(recent)

    if any(is_moving(row, rest) for row in recent):
        return None, "moved before 0"

    for _ in range(START_WINDOW_ROWS):
        row = read_row()
        if is_moving(row, rest):
            action_rows = list(recent)[len(recent) - LEAD_IN_ROWS:] + [row]
            while len(action_rows) < SAMPLES_PER_ACTION:
                action_rows.append(read_row())
            return action_rows, None
        recent.append(row)

    return None, f"no movement within {START_WINDOW_MS} ms of 0"


# ============================================================
# Serial connection
# ============================================================

ser = serial.Serial(PORT, BAUD_RATE, timeout=1)

# ============================================================
# Collection
# ============================================================

try:
    session_rows = []
    valid_action_count = 0
    attempt_count = 0

    print("\nCollecting two-hand RAW MPU6050 data...")
    if action_name in CONTINUOUS_ACTIONS:
        print(
            f"Get into the {action_name} pose during the countdown. "
            f"Collection starts at 0."
        )
        print(
            f"Each {action_name} action will contain exactly "
            f"{SAMPLES_PER_ACTION} samples."
        )
    else:
        print(
            "Hold still during each countdown, then start the action "
            "as soon as you see 0."
        )
        print(
            f"Attempts are discarded if you move before 0 or do not "
            f"start within {START_WINDOW_MS} ms."
        )
        print(
            f"Each action keeps {SAMPLES_PER_ACTION} samples from where "
            f"the movement starts."
        )
    print("Press Ctrl+C to stop.\n")

    if action_name in CONTINUOUS_ACTIONS:
        countdown()
        print(f"Continuous {action_name} collection started.")

    while valid_action_count < total_required:
        if action_name in CONTINUOUS_ACTIONS:
            action_rows = [read_row() for _ in range(SAMPLES_PER_ACTION)]
        else:
            attempt_count += 1
            action_rows, problem = attempt_action()
            if problem:
                print(
                    f"[WARNING] Attempt {attempt_count}: {problem}. "
                    f"Discarded."
                )
                continue

        valid_action_count += 1
        for action_row in action_rows:
            session_rows.append(
                format_row(valid_action_count, action_row, action_label)
            )
        print(
            f"[ACTION {valid_action_count}/{total_required}] "
            f"{action_name}: {SAMPLES_PER_ACTION} rows"
        )

    print("\n======================================")
    print("Collection complete")
    print(f"User:           {user_id}")
    print(f"Action:         {action_name}")
    print(f"Valid actions:  {valid_action_count}/{total_required}")
    print(f"Rows collected: {len(session_rows)}")
    print("======================================")

    while True:
        save_input = input(
            "Is the data OK to save? Enter 1 to SAVE or 0 to DISCARD: "
        ).strip()
        if save_input in ["0", "1"]:
            break
        print("Please enter only 1 or 0.")

    if save_input == "1":
        file_exists = os.path.exists(OUTPUT_FILE)
        file_empty = not file_exists or os.path.getsize(OUTPUT_FILE) == 0

        with open(OUTPUT_FILE, "a", newline="") as file:
            writer = csv.writer(file)
            if file_empty:
                writer.writerow([
                    "action_count", "timestamp", "user_id",
                    "right_ax", "right_ay", "right_az",
                    "right_gx", "right_gy", "right_gz",
                    "left_ax", "left_ay", "left_az",
                    "left_gx", "left_gy", "left_gz", "label",
                ])
            writer.writerows(session_rows)
        print(f"\nSaved {len(session_rows)} rows to {OUTPUT_FILE}.")
    else:
        print("\nData discarded.")
        print("No rows from this session were written to the CSV.")

except KeyboardInterrupt:
    print("\nCollection stopped by user. Nothing was saved.")
finally:
    ser.close()
