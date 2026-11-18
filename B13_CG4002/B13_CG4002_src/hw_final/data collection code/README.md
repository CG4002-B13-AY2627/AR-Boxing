# Data Collection Code

This folder contains the firmware and Python program used to collect two-hand
MPU6050 motion data for the project. The system uses two ESP32 boards:

1. The **left-hand ESP32** reads the left-hand MPU6050 and sends its readings
   to the right-hand ESP32 using ESP-NOW.
2. The **right-hand ESP32** reads the right-hand MPU6050, receives the
   left-hand readings, and sends combined data over USB serial.
3. `datacollection.py` reads the combined serial data, guides the operator
   through labelled actions, and saves accepted samples to a CSV file.

## Files

### `left_hand_data_collection.cpp`

Upload this Arduino sketch to the **left-hand ESP32**.

It:

- Reads the left MPU6050 directly through I2C at approximately 100 Hz.
- Uses raw signed MPU6050 accelerometer and gyroscope values.
- Reads the left button on GPIO 26 and buzzer on GPIO 25.
- Sends an `ImuPacket` to the right-hand ESP32 through ESP-NOW.

The `RIGHT_HAND_MAC` array must contain the Wi-Fi MAC address of the
right-hand ESP32. The packet structure must remain identical to the
`ImuPacket` structure in `right_hand_data_collection.cpp`.

### `right_hand_data_collection.cpp`

Upload this Arduino sketch to the **right-hand ESP32**.

It:

- Reads the right MPU6050 directly through I2C at approximately 100 Hz.
- Receives the left-hand `ImuPacket` through ESP-NOW.
- Reads the right button on GPIO 26 and buzzer on GPIO 25.
- Prints a combined row over USB serial whenever recent left-hand data is
  available.

Rows are printed in this format:

```text
DATA,index,right_ax,right_ay,right_az,right_gx,right_gy,right_gz,left_ax,left_ay,left_az,left_gx,left_gy,left_gz,right_button,left_button
```

The Python collector uses the 12 IMU values and ignores the two button values.
The serial baud rate is **115200**.

### `datacollection.py`

Run this script on the computer connected to the **right-hand ESP32**.

It:

- Opens the configured serial port at 115200 baud.
- Prompts for an action label, user ID, and number of repetitions.
- Waits for the countdown and detects when movement starts.
- Keeps exactly 32 samples for each valid action.
- Discards attempts where movement starts before `0`, starts too late, or
  contains missing serial samples.
- Adds a Singapore-time timestamp and writes the results to a date-named CSV
  file such as `18-11-26.csv`.
- Asks for confirmation before saving.

The available labels and numeric IDs are:

| ID | Label |
|---:|---|
| 0 | `l_straight` |
| 1 | `r_straight` |
| 2 | `l_hook` |
| 3 | `r_hook` |
| 4 | `l_uppercut` |
| 5 | `r_uppercut` |
| 6 | `block` |
| 7 | `weave` |
| 8 | `pickup` |
| 9 | `use` |
| 10 | `idle` |

The CSV columns are:

```text
action_count,timestamp,user_id,
right_ax,right_ay,right_az,right_gx,right_gy,right_gz,
left_ax,left_ay,left_az,left_gx,left_gy,left_gz,label
```

The script also creates a matching `.window` file. This prevents recordings
made with different capture-window settings from being appended to the same
CSV accidentally.

## Hardware connections

Both ESP32 boards use the typical ESP32 I2C pins:

| MPU6050 pin | ESP32 pin |
|---|---:|
| SDA | GPIO 21 |
| SCL | GPIO 22 |

Also connect:

- MPU6050 `VCC` and `GND` to the appropriate ESP32 power and ground pins.
- The action button between GPIO 26 and GND. The firmware uses
  `INPUT_PULLUP`, so a pressed button reads `LOW`.
- The buzzer to GPIO 25 and GND if the buzzer is being used.

The MPU6050 address is expected to be `0x68`. Verify the address and wiring
before collecting data.

## Software requirements

Install:

- Arduino IDE with ESP32 board support.
- A Python version with `pyserial` available.

Install the Python dependency with:

```bash
python -m pip install pyserial
```

The Arduino sketches use ESP32/Arduino core functionality, `Wire`, Wi-Fi, and
ESP-NOW. No third-party Arduino library is required by these sketches.

## Upload and collection procedure

### 1. Prepare the right-hand ESP32

1. Open `right_hand_data_collection.cpp` in Arduino IDE.
2. Select the correct ESP32 board and the right-hand ESP32 COM port.
3. Compile and upload the sketch.
4. Open Serial Monitor at **115200 baud**.
5. Copy the MAC address printed after:

   ```text
   RIGHT ESP32 MAC:
   ```

6. Close Serial Monitor before using the Python script, because only one
   program can normally access the serial port at a time.

### 2. Configure and upload the left-hand ESP32

1. Open `left_hand_data_collection.cpp`.
2. Replace the six values in `RIGHT_HAND_MAC` with the MAC address printed by
   the right-hand ESP32. For example:

   ```cpp
   uint8_t RIGHT_HAND_MAC[] = {0x70, 0x4B, 0xCA, 0xE5, 0x18, 0xC4};
   ```

3. Select the left-hand ESP32 board and its COM port.
4. Upload the sketch.
5. Open its Serial Monitor briefly to confirm that the MPU6050 initializes and
   note the left ESP32 MAC if troubleshooting is needed.
6. Close Serial Monitor.

Keep both ESP32 boards powered while collecting data. The boards communicate
directly through ESP-NOW, so they do not need to join a normal Wi-Fi network.

### 3. Configure and run the Python collector

1. Connect the right-hand ESP32 to the computer by USB.
2. Find its serial port:
   - Windows: check **Device Manager > Ports (COM & LPT)**.
   - macOS/Linux: identify the `/dev/...` serial device.
3. Open `datacollection.py` and update `PORT`. The checked-in value is a
   macOS-style example:

   ```python
   PORT = "/dev/cu.wchusbserial1410"
   ```

   On Windows, use the assigned COM port, for example:

   ```python
   PORT = "COM5"
   ```

4. From this folder, run:

   ```bash
   python datacollection.py
   ```

5. Enter the label (name or numeric ID), user ID, and required number of
   actions.
6. Keep the gloves still during the countdown. Start the action immediately
   after `0 GO!`.
7. Repeat discarded attempts when prompted.
8. At the end, enter `1` to save or `0` to discard the session.

The script saves data in the current working directory. Run it from this
folder if the CSV files should be stored here.

## Collection behaviour and important settings

The default settings in `datacollection.py` are:

- Sampling rate: approximately 100 rows per second.
- Saved samples per action: 32 rows.
- Start delay: 8 rows, approximately 80 ms after movement detection.
- Start window: movement must begin within 640 ms after `0`.
- Movement thresholds: 1250 raw counts for both acceleration and gyroscope
  vectors.
- Lead-in: 3 rows before the detected movement are retained.

If these values are changed, use a new output CSV or update the associated
window marker rather than mixing incompatible recordings.

## Troubleshooting

- **No Python data is received:** confirm that the right-hand ESP32 is
  connected, `PORT` is correct, Serial Monitor is closed, and the baud rate is
  115200.
- **Left-hand data is missing:** confirm that the MAC address in
  `left_hand_data_collection.cpp` is the current MAC of the right-hand board,
  both boards are powered, and the left MPU6050 is wired correctly.
- **`MPU6050 initialization failed`:** check power, ground, SDA, SCL, and the
  `0x68` I2C address.
- **The script rejects attempts:** remain still during the countdown and start
  the action immediately after `0`. A serial index gap also causes the attempt
  to be discarded.
- **The script refuses to append to a CSV:** the existing CSV was created with
  a different capture window or has no matching `.window` file. Move the old
  CSV and marker elsewhere, or configure a new output filename.

The `__pycache__` directory, if present, is generated by Python and is not
needed for replication.
