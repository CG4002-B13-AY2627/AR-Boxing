import serial
import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# Configuration
# ============================================================

#IMU fields are stored as signed raw integer sensor counts.

PORT = "COM5"
BAUD_RATE = 115200
OUTPUT_FILE = "imu_two_hands_raw.csv" 

MIN_ACTION_ROWS = 32
MAX_ACTION_ROWS = 64
IDLE_SAMPLES_PER_ACTION = 32

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
print(f"Minimum length:  {MIN_ACTION_ROWS} rows")
print(f"Maximum length:  {MAX_ACTION_ROWS} rows")
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


# ============================================================
# Serial connection
# ============================================================

ser = serial.Serial(PORT, BAUD_RATE, timeout=1)

# ============================================================
# Collection and save batches
# ============================================================

try:
    while True:
        action_buffer = []
        session_rows = []
        valid_action_count = 0
        attempt_count = 0
        idle_collection_started = False

        print("\nCollecting two-hand RAW MPU6050 data...")
        if action_name == "idle":
            print("Press either button once to start continuous idle collection.")
            print(
                f"Each idle action will contain exactly "
                f"{IDLE_SAMPLES_PER_ACTION} samples."
            )
        else:
            print("Hold either button to start and continue an action.")
        print("Press Ctrl+C to stop.\n")

        while valid_action_count < total_required:
            line = ser.readline().decode("utf-8", errors="ignore").strip()

            if not line or not line.startswith("DATA,"):
                continue

            values = line.split(",")

            # DATA,index,
            # right_ax,right_ay,right_az,right_gx,right_gy,right_gz,
            # left_ax,left_ay,left_az,left_gx,left_gy,left_gz,
            # right_button,left_button
            if len(values) != 16:
                continue

            try:
                right_ax = int(values[2])
                right_ay = int(values[3])
                right_az = int(values[4])
                right_gx = int(values[5])
                right_gy = int(values[6])
                right_gz = int(values[7])

                left_ax = int(values[8])
                left_ay = int(values[9])
                left_az = int(values[10])
                left_gx = int(values[11])
                left_gy = int(values[12])
                left_gz = int(values[13])

                right_button = int(values[14])
                left_button = int(values[15])
            except ValueError:
                continue

            row = {
                "timestamp": get_sgt_timestamp(),
                "right_ax": right_ax,
                "right_ay": right_ay,
                "right_az": right_az,
                "right_gx": right_gx,
                "right_gy": right_gy,
                "right_gz": right_gz,
                "left_ax": left_ax,
                "left_ay": left_ay,
                "left_az": left_az,
                "left_gx": left_gx,
                "left_gy": left_gy,
                "left_gz": left_gz,
            }

            raw_label = 1 if (left_button == 1 or right_button == 1) else 0

            if action_name == "idle":
                if not idle_collection_started:
                    if raw_label == 1:
                        idle_collection_started = True
                        print("Idle collection started.")
                    else:
                        continue

                action_buffer.append(row)

                if len(action_buffer) == IDLE_SAMPLES_PER_ACTION:
                    valid_action_count += 1
                    for action_row in action_buffer:
                        session_rows.append(
                            format_row(valid_action_count, action_row, action_label)
                        )
                    print(
                        f"[ACTION {valid_action_count}/{total_required}] "
                        f"{action_name}: {IDLE_SAMPLES_PER_ACTION} rows"
                    )
                    action_buffer.clear()
                continue

            if raw_label == 1:
                action_buffer.append(row)
            elif action_buffer:
                attempt_count += 1
                action_length = len(action_buffer)

                if MIN_ACTION_ROWS <= action_length <= MAX_ACTION_ROWS:
                    valid_action_count += 1
                    for action_row in action_buffer:
                        session_rows.append(
                            format_row(valid_action_count, action_row, action_label)
                        )
                    print(
                        f"[ACTION {valid_action_count}/{total_required}] "
                        f"{action_name}: {action_length} rows"
                    )
                else:
                    print(
                        f"[WARNING] Attempt {attempt_count}: {action_length} rows "
                        f"(must be between {MIN_ACTION_ROWS} and "
                        f"{MAX_ACTION_ROWS}). Discarded."
                    )
                action_buffer.clear()

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

        print("\nStarting a new set of actions...")

except KeyboardInterrupt:
    print("\nCollection stopped by user.")
finally:
    ser.close()
