# Multiplayer server

The CPU GameEngine is authoritative. Both phones use one full-duplex WebSocket each through a byte-forwarding laptop hotspot/SSH tunnel. Use `visualizer_server.py`; do not run another phone listener on the same port.

Install Python 3.10+ and `python -m pip install -r comms/requirements.txt` from the AR-Boxing root. The deployable schema mirror is bundled in `comms/contracts` and found automatically. It is copied from the canonical CG4002-Viz contracts; deploy it together with the Python files. `--contracts-dir` or `CG4002_CONTRACTS_DIR` can explicitly select another matching export. An explicit incomplete path fails with the resolved directory and missing filenames.

For the board layout `~/comms/esp_ai_live/*.py`, copy the **whole** bundled `comms/contracts` directory to `~/comms/contracts`, then use `--contracts-dir /home/xilinx/comms/contracts`. This avoids depending on a Unity checkout or its submodule being present on the board. In Bash, end each continued command line with `\`; otherwise the options on the next line are separate shell commands.

Local development:

```powershell
python -B comms/Ultra96/visualizer_server.py --source keyboard --insecure-ws --host 127.0.0.1
```

Phones choose P1/P2, press Start, then Ready. Both READY -> CALIBRATING; both CALIBRATED -> 3-second COUNTDOWN -> FIGHTING. Any pause/drop pauses the fight; both connected players must RESUME. Joining never starts/resumes automatically. Single-client development is explicit with `--wait-players 1`. Default round 90 fighting seconds, then ROUND_END for 2 seconds and an authoritative winner/draw. Restart the server for another match.

Keyboard: 1/2 player; j/c jab/cross; h/b left/right hook; u/n left/right uppercut; g/x guard start/end; k pickup classification; p operator pause; s state; r retry stable action; q quit. Phones supply visibility/proximity evidence. The keyboard never chooses a hit or grants healing.

HEALTH packs spawn every 30 fighting seconds for each owner lacking a pack, first at 30. Expire before respawning; no catch-up bursts. Lifetime 30 fighting seconds, heal 25, radius 1 m, bearing +/-65 degrees, maximum one/player. Collect at <=0.5 m following a server PickupCheck with 750 ms real-time deadline. Full-health collection consumes with zero gain. Pause/countdown freeze gameplay clocks; pending checks fail without consumption. Stable classified action IDs are mandatory for deduplication.

Generate a fresh phone CA and leaf (OpenSSL required):

```powershell
python -B comms/Ultra96/make_phone_cert.py --output comms/.local-certs --host 192.168.137.1 --host 127.0.0.1 --host localhost
python -B comms/Ultra96/visualizer_server.py --source keyboard
```

Default WSS port is 8889 and default leaf/key are under comms/.local-certs. Copy the matching server pair securely to Ultra96; install only ca.crt and enable full trust on each phone. Use `wss://<laptop-hotspot-address>:8889`, covered by the leaf SAN, with the laptop forwarding that port to Ultra96. No TLS bypass. Previously committed demo private keys are published and must not be reused. New credentials are ignored and the generator refuses nonempty output directories. Phone trust is separate from ESP gateway trust.

Automated tests and full encrypted scenario:

```powershell
python -B -m unittest discover -s comms/Ultra96 -p 'test_*.py'
python -B comms/Ultra96/visualizer_server.py --source scripted --script comms/Ultra96/integration-scenario.json --spawn-seconds 3 --round-seconds 12 --start-delay 0
# Another terminal:
python -B comms/Ultra96/smoke_test_multiplayer.py --url wss://127.0.0.1:8889 --ca comms/.local-certs/ca.crt
```

The accelerated spawn/round are test-only overrides. The script exercises all six punches, guard and both pickups. The probe supplies menu commands/evidence, pauses/resumes and compares final states. Restart the server afterward: probes reserve the player slots until restart. `smoke_test_visualizer_wss.py` remains the focused strict-TLS handshake/occupied-slot/reconnect probe.

`classified_actions.py` maps real server-originated events to the same hub entry points, including pickup. FPGA-noise is labelled diagnostic input, never live wearable proof. `esp_ai_live.py` is gated on missing live_alignment.py and reviewed expected_norm_stats.json; their communications/AI owner must restore and validate them. It uses separate --phone-cert/--phone-key for phone WSS and --cert/--key for ESP TLS. Assessment TCP/file/ESP fixtures remain separate; do not silently replace their trust or claim their dummy traffic proves gameplay.

The matching visualizer's `docs/multiplayer-integration.md` contains detailed Unity, two-client, Ultra96/tunnel and Mac-mini-to-two-iPhone verification, plus FPS/thermal/latency evidence requirements. Simulation results are not physical-device evidence.

## Live dashboard entry point

`esp_ai_live_dashboard.py` uses the same authority, classified-action adapter and phone listener. It supports `--contracts-dir`, `--phone-cert`, `--phone-key`, `--countdown-seconds` and `--spawn-seconds`. Existing `--cert`/`--key` still belong to ESP TLS; they do not silently become the phone certificate. The dashboard stays read-only on loopback port 8890; forward that port through SSH.

The dashboard shows phase/round timing, readiness, result, guard state, health packs and pending observations alongside sensor/model diagnostics. Joining phones must still Ready/calibrate; reconnect requires explicit Resume. Its normalization comes from the selected AI build and is checked against the preprocessor's loaded values; it does not require expected_norm_stats.json. The alignment module is loaded only when starting live input, with a clear missing-dependency error; `--help` and hardware-free dashboard tests remain available without it.
