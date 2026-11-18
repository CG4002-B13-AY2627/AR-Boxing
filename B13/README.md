# AR Boxing: CG4002 Group B13

A two-player, non-contact AR boxing game built for NUS CG4002 (AY26/27). Each player wears a pair of IMU gloves and looks through an iPhone. The gloves stream motion to an Ultra96-V2, where a quantized 1D CNN on the FPGA classifies punches, guards, weaves and pickups. A game engine on the board resolves every action and drives both players' AR views over secure WebSockets.

## System overview

```text
 left glove (ESP32 + IMU) --ESP-NOW--> right glove (ESP32 + IMU)        x2 players
                                              |
                                  TLS over the laptop hotspot  (port 8888)
                                              |
        laptop: hotspot + SSH tunnel to the Ultra96  (forwards 8888, 8889, 8890)
                                              |
 Ultra96-V2 (PYNQ 3.0.1)
   wrist alignment -> 32-sample windows -> FPGA 1D CNN (10 classes) -> post-processing
   -> GameEngine: hit/miss/block/dodge, damage, health, stamina, pickups, timer, phases
                                              |
                       protocol-v2 JSON over WSS  (port 8889)
                                              |
         iPhone visualizer P1 + iPhone visualizer P2   (Unity, ARKit, AprilTag)
```

- **The Ultra96 is the only authority.** It decides every hit, block, dodge, damage value, pickup and phase change. The laptop only forwards bytes.
- **The phones render and report evidence.** Each phone tells the server whether the opponent's AprilTag was in view when a punch was thrown and how far the player is from a pickup, then renders the authoritative `GameEvent` and `MatchState`.
- **Gesture classes:** left/right straight, left/right hook, left/right uppercut, block, weave, pickup and idle.
- **Dashboard:** the live server serves a status page on port 8890 (phone sessions, glove streams, aligned samples, FPGA activity).

## Directory structure of B13

```text
B13/
├── README.md                      this file
├── B13_CG4002_Design_Report.pdf   final design report
├── B13_CG4002_Poster.pdf          final project poster
├── B13_CG4002_Video.txt           YouTube link to the demo video
├── B13_CG4002_Training_Dataset/
│   └── mike-tyson.csv             team-recorded gesture dataset used for training
└── B13_CG4002_src/                all submitted source code
    ├── ai/
    │   ├── data-conversion/       turns raw glove recordings into a training CSV
    │   ├── pipeline/              train -> quantize -> check -> export -> HLS -> Vivado bitstream
    │   │   ├── train/             1D CNN model, data loading, training (data/ holds the CSV)
    │   │   ├── export/            integer model export and bit-exact checks against Brevitas
    │   │   ├── fpga/              HLS and Vivado projects for the accelerator
    │   │   ├── scripts/           per-stage .sh/.bat wrappers
    │   │   └── test/              offline and live model tests
    │   └── ultra-96/              board-side host code (src/), verify/latency/power scripts, transfer.sh
    ├── comms/
    │   ├── Ultra96/               game server: live dashboard, game_engine.py, visualizer_protocol.py, tests
    │   ├── esp/                   glove ESP32 firmware for P1 and P2 (left/right sketches)
    │   └── laptop/                TLS certificate generators for the gloves and phones
    └── hw/
        └── data collection code/  MPU6050 left/right sketches and datacollection.py labeller
```

The Unity visualizer is not in this folder; it lives in the [CG4002-Viz](https://github.com/zexueteh/CG4002-Viz) repository.

## Repository layout

| Path | What it is |
|---|---|
| [`B13_CG4002_src/`](B13_CG4002_src/) | **Final submission code.** Start here. |
| &nbsp;&nbsp;[`ai/`](B13_CG4002_src/ai/README.md) | Dataset, training, quantization, HLS/Vivado bitstream pipeline, and the Ultra96 host code |
| &nbsp;&nbsp;[`comms/`](B13_CG4002_src/comms/README.md) | Ultra96 game server and phone hub, glove (ESP32) firmware for P1/P2, certificate tools |
| &nbsp;&nbsp;[`hw/`](B13_CG4002_src/hw/) | Two-hand MPU6050 data-collection firmware and the labelling collector |
| [`B13_CG4002_Training_Dataset/`](B13_CG4002_Training_Dataset/) | The team-recorded training CSV (`mike-tyson.csv`) |
| [`B13_CG4002_Poster.pdf`](B13_CG4002_Poster.pdf) | Final project poster |
| [`CG4002-Viz/`](https://github.com/zexueteh/CG4002-Viz) | **Git submodule:** the Unity iOS AR visualizer and the protocol-v2 contracts (`contracts/`, `docs/protocol.md`) |
| `ai/`, `ai-comms-integration/`, `comms/`, `hw/` | Development history from before the final submission folder; kept for reference |
| `poster-assets/` | Project poster sources and exports |
| `viz/` | Placeholder; the visualizer lives in the `CG4002-Viz` submodule |

## Getting the code

```bash
git clone --recurse-submodules https://github.com/CG4002-B13-AY2627/AR-Boxing.git
cd AR-Boxing
```

For an existing clone, run `git submodule update --init CG4002-Viz` after every pull, so your checkout of the visualizer matches the commit `main` pins. If you skip this, `git add -A` or `git commit -a` can quietly commit your old submodule commit and undo someone else's update.

## Subsystems

### AI: gesture classifier on the FPGA

Requirements: Python 3.12 or 3.13, Vitis HLS and Vivado 2022.1, bash (or the `.bat` beside every script on Windows).

```bash
cd B13_CG4002_src/ai
./pipeline/pipeline.sh --name my-run --build A --hls-mode synth-export          # train -> check -> export -> HLS -> Vivado
U96_JUMP=<nus-id>@stujump.comp.nus.edu.sg ./ultra-96/transfer.sh --name my-run  # copy the run to ~/ai/my-run on the board
```

The pipeline trains an FP32 model, then quantization-aware models at 8 down to 4 bits, keeps the narrowest width within 2 percentage points of FP32, checks the integer model bit for bit against Brevitas, and builds the bitstream into `out/pipeline/<name>/`. On the board, `verify.sh`, `latency.sh`, `power.sh`, `pmanagement.sh` and `test.sh` verify, time, measure and tune the build. The training data is `pipeline/train/data/mike-tyson.csv`, recorded by the team; [`data-conversion/`](B13_CG4002_src/ai/data-conversion/README.md) turns new recordings into a training CSV. Details: [ai/README.md](B13_CG4002_src/ai/README.md), [pipeline](B13_CG4002_src/ai/pipeline/README.md), [ultra-96](B13_CG4002_src/ai/ultra-96/README.md).

### Communications and game server

- **Gloves:** each player's left ESP32 sends IMU samples to their right ESP32 over ESP-NOW; the right ESP32 forwards both wrists over TLS. Flash the matching left/right sketches from `comms/esp/ESP_HW_16G_2000DPS/P1/` or `P2/` (±16 g, ±2000 °/s), after checking peer MACs, hotspot settings and the embedded server certificate.
- **Laptop:** runs the hotspot and an SSH tunnel to the Ultra96 forwarding ports 8888 (gloves), 8889 (phones) and 8890 (dashboard).
- **Ultra96:** `esp_ai_live_dashboard_16g.py` aligns both wrists, runs FPGA inference, resolves actions in `game_engine.py` and serves the phones through `visualizer_protocol.py`.

```sh
cd B13_CG4002_src/comms/Ultra96
sudo -E python3 esp_ai_live_dashboard_16g.py --mode fpga \
  --ai-dir /home/xilinx/ai/<run> \
  --cert <esp-server.crt> --key <esp-server.key> \
  --phone-cert <phone-server.crt> --phone-key <phone-server.key> \
  --wait-players 2 --spawn-seconds 20
```

`--wait-players 1` allows single-phone testing, `--spawn-seconds N` turns on automatic item spawns, and `--god-mode` keeps both players above 1 HP with the round clock frozen for guided demos. Without gloves or a board, `ai_to_visualizer_demo.py` runs the same game engine and phone hub from the keyboard or synthetic actions. Details and certificate generation: [comms/README.md](B13_CG4002_src/comms/README.md); match flow, tutorial and god mode: [AI_VISUALIZER_DEMO.md](B13_CG4002_src/comms/Ultra96/AI_VISUALIZER_DEMO.md).

### Hardware: data collection

The left and right ESP32 sketches read an MPU6050 each at about 100 Hz; the right glove prints combined rows over USB serial, and `datacollection.py` prompts for a label, user and repetition count, keeps exactly 32 samples per action and writes a dated CSV. Wiring, labels and CSV format: [hw/data collection code/README.md](<B13_CG4002_src/hw/data collection code/README.md>).

### Visualizer: iPhone AR client

The `CG4002-Viz` submodule is a Unity 6 (6000.0.76f1) iOS app using AR Foundation/ARKit. It handles the WebSocket handshake and P1/P2 slots, menus and match flow, HUD, camera-relative gloves, AprilTag tracking of the opponent's belt tag, incoming-punch effects, floor-placed pickups, a tutorial and an optional Cardboard headset view. Build and deployment need a Mac with Xcode. Its README covers setup, tests and the protocol; the submodule is pinned, so develop in the [CG4002-Viz repository](https://github.com/zexueteh/CG4002-Viz), not inside this folder. To move the pin to the visualizer's latest `main`:

```bash
git -C CG4002-Viz fetch origin && git -C CG4002-Viz checkout origin/main
git add CG4002-Viz && git commit -m "Update CG4002-Viz submodule"
```

## Protocol between the Ultra96 and the phones

Protocol v2: JSON messages over a full-duplex WebSocket, each carrying `type` and `protocol_version: 2`. The canonical schemas, golden examples and semantics live in the visualizer repository (`CG4002-Viz/contracts/` and `CG4002-Viz/docs/protocol.md`), and the server's tests validate its output against them.

| Message | Direction | Purpose |
|---|---|---|
| `ClientHello` / `ServerWelcome` | phone <-> server | join, requested and assigned player slot |
| `PlayerCommand` | phone -> server | ready, calibrated, pause/resume, restart, tutorial |
| `PunchAttempt` / `PunchObservation` | server <-> attacking phone | was the opponent's tag in view for this punch |
| `PickupCheck` / `PickupObservation` / `PickupResult` | server <-> phone | pickup distance evidence and the verdict |
| `GameEvent` | server -> phones | final punch, guard, weave and pickup outcomes |
| `MatchState` | server -> phones | full health/stamina/timer/phase/items snapshot, about every 0.1 s |

A contract change is made in CG4002-Viz first (schemas, examples, C# models, mock server, docs), then mirrored in `comms/Ultra96/visualizer_protocol.py` and its tests.

## Testing

```bash
# Game server and phone hub (final comms package); point at the contracts for schema checks
cd B13_CG4002_src/comms
CG4002_CONTRACTS_DIR=../../../CG4002-Viz/contracts python -m unittest discover -s Ultra96
```

The visualizer's own checks (contract validation, mock server, Unity Edit/Play Mode tests) are described in `CG4002-Viz/README.md`. The AI pipeline checks itself during the `check` stage and on the board with `verify.sh`.

## Security

TLS secures both the glove link and the phone link. Generate fresh certificates with `B13_CG4002_src/comms/laptop/make_cert.py` (gloves) and `make_phone_cert.py` (phones), keep private keys on the Ultra96 or the laptop, and install only the public CA certificate on the phones. Never commit private keys: any key that has been committed to this repository's history must be treated as compromised and replaced.

## Team

CG4002 Group B13, AY26/27: hardware sensors, AI on the FPGA, communications, and the software visualizer. See each subsystem's README for its owners' notes.
