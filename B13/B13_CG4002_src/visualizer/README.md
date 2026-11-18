# CG4002 AR Boxing Visualizer

This repository is the working home for Teh Ze Xue's CG4002 software visualizer: a Unity iOS AR client for the two-player, non-contact boxing game described in Group B13's initial design report.

The visualizer receives authoritative gameplay updates from the laptop relay, maintains a local read-only match model, and renders the rear-camera AR view, HUD, effects, audio, and connection state. It does not classify IMU data or decide whether a punch landed.

## What is already set up

- `VisualizerApp/`: Unity 6.0 LTS project pinned to editor `6000.0.76f1`, with the integrated `Main.unity` scene.
- `VisualizerApp/Assets/Scripts/`: message decoding, WebSocket receive/reconnect logic, a main-thread queue, authoritative match-state handling, a basic HUD presenter, and a mock event source.
- `VisualizerApp/Assets/Scripts/AR/` and `Presentation/`: AprilTag opponent targeting, pose filtering, semantic punch targets, player-glove animation, and optional ARKit body-glove tracking.
- `VisualizerApp/Assets/Tests/`: edit-mode decoder, pose-filter, targeting, and guard tests plus an XR Simulation play-mode test.
- `contracts/`: JSON Schemas and examples for `GameEvent` and `MatchState`.
- `tools/mock_server.py`: a laptop-side WebSocket authority that produces deterministic pickup, state, punch, reconnect, and optional fault-injection traffic.
- `docs/`: architecture, interface, Windows-to-Mac workflow, and an actionable visualizer backlog.
- `AGENTS.md`: persistent project context and engineering rules for future Codex sessions.

## Start on this Mac

The current implementation is on `OpponentTracker`. The full reconciled handoff is tracked on `main` at commit `ca4576c` until the team deliberately reconciles the branch history.

```bash
git switch OpponentTracker
git pull --ff-only origin OpponentTracker
./tools/check_mac_setup.sh
./tools/bootstrap_python_env.sh
```

Then open `VisualizerApp` in Unity Hub with editor `6000.0.76f1`, open `Assets/Scenes/Main.unity`, let Unity build a fresh Mac-local `Library`, and run the edit-mode tests. Use the macOS/Standalone profile for XR Simulation and return to the iOS profile before generating Xcode.

Do not copy Unity caches or generated Xcode projects between computers. Commit and push a known-good revision on the machine finishing work, then pull it on the machine starting work.

For the WP7 pickup integration, follow [docs/item-pickups-wp7-mock-server-guide.md](docs/item-pickups-wp7-mock-server-guide.md). The server default remains `127.0.0.1:8765`; the current scene uses `ws://127.0.0.1:8766`, so pass `--port 8766` for Unity or deliberately change the scene endpoint while out of Play Mode.

The full workflow is in [docs/mac-setup.md](docs/mac-setup.md), the reconciled state is in `docs/macbook-development-handoff.md` on `main`, and the phone protocol is in [docs/protocol.md](docs/protocol.md).

## Current scope

The first vertical slice is deliberately small:

1. rear-camera AR passthrough on a physical iPhone;
2. stable health, stamina, timer, and network HUD;
3. mock and live WebSocket messages through the same decoder and queue;
4. hit/block audiovisual feedback driven by `GameEvent`;
5. floor detection and a safe arena boundary;
6. performance and latency measurements on-device.

Opponent body tracking and hand-attached glove meshes are a later experiment. The core demo must remain useful if body tracking is unstable.

## Repository workflow

- Keep generated Unity folders (`Library`, `Temp`, `Logs`, `Builds`) out of Git.
- Keep separate local Git clones on Windows and macOS. Avoid opening the Unity project from a live cross-machine OneDrive sync.
- Commit Unity `.meta` files alongside their assets.
- Update the schemas, examples, decoder, mock server, and tests together when the laptop-to-phone contract changes.
- Record measured latency and tracking results; do not replace measurements with assumptions.

## Source material

The five supplied PDFs were used as reference material. Their key decisions have been distilled into the repository documentation. See [docs/references/README.md](docs/references/README.md).
