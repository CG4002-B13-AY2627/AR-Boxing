# AR Boxing Communications

This package contains the communications code for the two-player AR Boxing demo. Each left glove sends IMU data to the corresponding right glove over ESP-NOW. The right glove forwards both wrists over TLS to the Ultra96 through the laptop. The Ultra96 aligns the samples, runs FPGA inference, resolves game actions and exchanges JSON messages with the iOS visualizers over secure WebSockets.

## Package layout

| Folder | Contents |
| --- | --- |
| `Ultra96/` | Live dashboard server, 16 g / 2000 °/s launcher, wrist alignment, wearable protocol, phone hub, game engine, haptic feedback, keyboard demo, tests and integration notes |
| `laptop/` | Certificate generation tools and the laptop-side binary protocol helper |
| `esp/ESP_HW_16G_2000DPS/P1/` | Left and right Arduino sketch folders configured for Player 1 |
| `esp/ESP_HW_16G_2000DPS/P2/` | Left and right Arduino sketch folders configured for Player 2 |

The server and utility files come from the project's `comms` branch. The P1 and P2 sketch folders come from the matching preconfigured firmware copies. `live_alignment.py` comes from the earlier ESP live deployment folder and is required by the dashboard server.

## Setup and launch

1. Open each glove's sketch folder in Arduino IDE with the ESP32 board support installed. Use the left and right sketches from the same player folder. Both player folders are configured for real IMU input at ±16 g and ±2000 °/s. Before flashing to different hardware or deploying on a different hotspot, check the peer MACs, hotspot settings, gateway endpoint and certificate configuration.
2. On the laptop, start the demo hotspot and forward TCP ports 8888 and 8889 to the Ultra96 over SSH. Forward port 8890 for local dashboard access. With a campus jump host, use the lab's SSH jump configuration and keep the forwarding session open. The phones and gloves use the laptop's hotspot address.
3. On the Ultra96, use a Python environment with `websockets`, NumPy and the AI build's dependencies. The FPGA model and board environment come from the AI subsystem. Provision the server certificate and its matching private key on the board. The ESP firmware and phones need the appropriate trust configuration. The certificate tools in `laptop/` use the `cryptography` package.
4. From the packaged `Ultra96/` directory, start the live server. Replace the AI and certificate paths with the deployed paths as needed.

```sh
sudo -E python3 esp_ai_live_dashboard_16g.py \
  --mode fpga \
  --ai-dir /home/xilinx/ai/mike-tyson \
  --cert /home/xilinx/comms/server.crt \
  --key /home/xilinx/comms/server.key \
  --phone-cert /home/xilinx/comms/server.crt \
  --phone-key /home/xilinx/comms/server.key \
  --wait-players 2 \
  --spawn-seconds 20
```

5. Connect each phone to `wss://<laptop-hotspot-address>:8889` using its player slot. On the laptop, open `http://127.0.0.1:8890` to check phone sessions, gateway sessions, both wrist streams, aligned samples and FPGA activity.

## Launch options

| Option | Default | When to use it |
| --- | --- | --- |
| `--wait-players 1` or `--wait-players 2` | `2` | Use `1` to test with one phone, or `2` for a two-player match. This sets the minimum number of connected phones for a normal match. The connected players still complete the readiness and calibration steps in the app. |
| `--spawn-seconds N` | `0` | Use a positive value to enable automatic item spawning during regular play. Each player gets a separately scheduled item after a delay with ±20% variation on the fight clock. For example, `20` gives a delay of 16–24 seconds when that player has no active item. Use `0` to turn off automatic spawning. Tutorial pickups are triggered separately by the tutorial. |
| `--god-mode` | Off | Add this flag for a guided match. Both players stay at or above 1 HP and the regular round timer is frozen. Leave the flag out for normal match rules. |

Edit the values in the launch command above. To enable God mode, append `--god-mode` to the last line, for example `--spawn-seconds 20 --god-mode`. Restart the server to apply changed launch options.

## Testing

Run `python -m unittest discover -s Ultra96` from this package's root. Some tests use local loopback sockets. Schema validation tests also require `jsonschema` and the visualizer team's contracts, which can be located with `CG4002_CONTRACTS_DIR`.

Run `python Ultra96/ai_to_visualizer_demo.py --help` for the keyboard and synthetic action entry point. With the live server, `--haptic-test` enables keyboard-triggered vibration and `--wait-players 1` permits single-player testing. For more integration notes, see `Ultra96/AI_VISUALIZER_DEMO.md`.

## TLS certificates and private keys

The demo server launch above uses `/home/xilinx/comms/server.crt` and `/home/xilinx/comms/server.key` on the Ultra96. The two files must be a matching pair. The private key stays on the Ultra96.

To generate fresh credentials, run these PowerShell commands from the `comms_final` folder on the laptop. Set `$hotspot` to the address the gloves and phones use to reach the laptop's forwarded ports.

```powershell
python -m pip install cryptography
$hotspot = '192.168.137.1'
New-Item -ItemType Directory -Path .\tls-esp
python .\laptop\make_cert.py --host $hotspot --out .\tls-esp --ino .\tls-esp\unused-sketch.ino
python .\laptop\make_phone_cert.py --host $hotspot --out .\tls-phone
```

Use fresh output directories when regenerating. The ESP utility also supports embedding the certificate in an older sketch format. The `--ino` path above deliberately points to a nonexistent file so it only generates the certificate and key.

- **ESP gateway:** Copy `tls-esp/server.crt` and `tls-esp/server.key` to a dedicated directory on the Ultra96. Set `--cert` and `--key` to those files. Replace the PEM inside `SERVER_CERT` in each player's right-gateway `server_cert.h` with the contents of the new ESP `server.crt`, then rebuild and flash both right gateways.
- **Phone WSS:** Copy `tls-phone/server.crt` and `tls-phone/server.key` to a separate directory on the Ultra96. Set `--phone-cert` and `--phone-key` to those files. Install `tls-phone/ca.crt` on each iPhone and enable full trust for that CA. Keep `ca.key` on the laptop for certificate issuance.

Restart the server after updating the paths, then check the ESP gateway and phone connections in the dashboard.
