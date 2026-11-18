# Visualizer backlog

This orders work by dependency and demo risk. Weeks refer to the initial design report's schedule and should be updated as the team calendar changes.

## Now: foundation and vertical slice

- [ ] Open the project in Unity 6.0 LTS on Windows and commit generated project settings/meta files.
- [ ] Clone the same Git revision on the Mac, verify a clean Unity import, and complete the first iOS build/signing pass.
- [ ] Create the baseline AR scene and prove rear-camera passthrough on the physical iPhone.
- [ ] Wire the provided network client, controller, mock source, and HUD.
- [ ] Agree the explicit `type`, `outcome`, stamina, timestamp, and sequence semantics with communications.
- [ ] Run the Python mock server from another machine and test disconnect/reconnect.
- [ ] Add edit-mode decoder/state tests inside Unity and one device smoke-test checklist.
- [ ] Record headset/camera obstruction, image distortion, heat, comfort, and safe field-of-view findings.

## Core gameplay presentation

- [ ] Implement match FSM views: lobby, calibration, countdown, fighting, paused, round end, match end.
- [ ] Implement local glove presentation states: idle, jab, cross, hook, uppercut, guard.
- [ ] Implement distinct hit, block, and miss feedback with restrained particles/audio/vignette.
- [ ] Add a persistent but unobtrusive connection indicator and reconnect overlay.
- [ ] Confirm all HUD state is restored by a fresh `MatchState` snapshot.

## World-space AR

- [ ] Detect a horizontal floor and place one arena origin.
- [ ] Render boundary and start-position guides with a clear pause/exit affordance.
- [ ] Test drift under quick head motion, low texture, partial occlusion, and lighting changes.
- [ ] Measure performance before enabling optional occlusion or environment features.

## Opponent tracking experiment

- [ ] Confirm the actual iPhone model supports 3D body tracking.
- [ ] Prototype `ARHumanBodyManager` with one standing opponent.
- [ ] Locate and document left/right hand or wrist joint indices for the selected AR Foundation version.
- [ ] Quantify jitter, loss rate, reacquisition time, and latency during boxing motion.
- [ ] Add smoothing and lost-tracking fallback only if the raw experiment passes agreed thresholds.
- [ ] Keep screen-space/opponent-centre effects as a fallback for the final demo.

## Integration and evaluation

- [ ] Replace mock messages with the communications WSS endpoint using a trusted certificate.
- [ ] Validate two-phone state synchronization and sequence handling.
- [ ] Measure receipt-to-render median, p95, and p99 latency.
- [ ] Profile FPS, CPU, GPU, memory, and thermals in a representative match.
- [ ] Stress packet bursts, malformed JSON, duplicates, stale snapshots, server restart, and Wi-Fi loss.
- [ ] Freeze functionality before final UI polish; archive screenshots, videos, profiler captures, and experiment notes for the report.

## Decisions still needed from the team

- Actual iPhone model(s) and iOS version(s).
- Phone orientation and whether the Cardboard-style headset truly requires stereo split rendering.
- Authoritative range source and whether range appears in phone messages.
- Final action vocabulary and damage/outcome event names.
- WSS certificate/provisioning approach for the demo network.
- Measurable acceptance targets for FPS, tracking loss, drift, and event-to-render latency.
