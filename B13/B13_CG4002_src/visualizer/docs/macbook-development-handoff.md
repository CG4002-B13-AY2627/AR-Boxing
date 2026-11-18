# CG4002 Visualizer: complete MacBook development handoff

> Snapshot date: 30 September 2026 (Asia/Singapore)  
> Repository: `https://github.com/zexueteh/CG4002-Viz.git`  
> Windows checkout audited: `C:\Dev\CG4002-Viz`  
> Unity project root: `VisualizerApp/`  
> Current branch at the time of writing: `OpponentTracker`  
> Current local commit: `8dc47c9` (`New guard animation movement and opacity change`)

This is the durable handoff for continuing NUS CG4002 Group B13's software visualizer work on the 2020 Apple-silicon MacBook Air as well as the ThinkPad T14. It consolidates the current repository, every Codex chat returned under the local `ZX CAPSTONE` project by the available app APIs, this handoff chat, two other clearly relevant repository chats, and the relevant archived-chat check.

It is deliberately more authoritative than any single old chat. When a chat, document, scene, and source file disagree, the reconciliation rules in this document explain which one currently wins.

## Read this first: the Mac cannot reproduce the current ThinkPad yet

At this snapshot, `OpponentTracker` is **three commits ahead** of `origin/OpponentTracker`:

| Commit | Meaning |
|---|---|
| `8dc47c9` | New guard movement and glove opacity/fade behaviour |
| `82f94e3` | Refined jab and uppercut paths |
| `8a2d1df` | Added a real AprilTag to XR Simulation for debugging |

The last-fetched `origin/OpponentTracker` tracking ref stops at `4105d6f` (`WP4 refined punch animations`). A fresh Mac clone therefore will not contain the three commits above until they are pushed. The last-fetched default `main` tracking ref is older still, at `c6af010`, and omits the AprilTag WP1-WP4 branch entirely.

This handoff document is also a new local file until it is committed. Before expecting parity on the Mac, review the current branch and then commit this document and push `OpponentTracker`:

```powershell
cd C:\Dev\CG4002-Viz
git fetch --prune origin
git status
git log --oneline origin/OpponentTracker..HEAD
git add docs/macbook-development-handoff.md
git commit -m "Add MacBook development handoff"
git push -u origin OpponentTracker
```

Do not switch the Mac to `main` and assume it is current. Work from `OpponentTracker` unless the branch is deliberately merged later.

There is also a **Windows-local Git stash**:

```text
stash@{0}: On main: codex camera relative gloves
```

It contains an older, large camera-relative glove implementation. Much of it appears superseded by committed code. Stashes do not transfer through Git hosting. Inspect it on the ThinkPad with `git stash show --stat 'stash@{0}'` and `git stash show -p 'stash@{0}'` before deciding whether anything remains useful; do not apply it blindly over the present scene and scripts. If anything is valuable, preserve it on a temporary branch or as an exported patch before retiring/replacing the ThinkPad; a local-only stash is not a cross-machine backup.

## 1. Project in one page

### Purpose and ownership

This is NUS CG4002 Group B13's Unity visualizer for an AR boxing system. Teh Ze Xue owns the software visualizer and supports communications as a secondary component.

The intended client is a Unity 6 LTS iOS application. The phone displays camera passthrough, player/opponent HUD state, glove feedback, and opponent-relative punch animation. Windows remains useful for ordinary Unity editing, pure logic tests, and XR Simulation. The Apple-silicon Mac is required for Xcode generation, signing, iPhone deployment, and physical-device proof.

### Non-negotiable architecture

The laptop Game Engine is authoritative for:

- whether a punch hits, misses, or is blocked;
- health and stamina;
- the round timer;
- match and round transitions.

The iPhone visualizer renders authoritative messages. It must **not** decide hits from local glove collision or AR tracking.

```text
Wearable IMUs -> torso ESP32 -> laptop relay -> Ultra96 inference
                                      |                |
                                      +<- result ------+
                                      |
                              laptop Game Engine
                                      |
                              GameEvent + MatchState
                                      v
                               iPhone visualizer(s)
```

The two phone-facing message roles are intentionally different:

- `GameEvent` is transient feedback, such as a punch, guard, weave, pickup, or round transition.
- `MatchState` is the periodic authoritative snapshot that lets a phone converge again after losing an event.

Sequence numbers for events and state snapshots are tracked independently. Network/background callbacks may enqueue raw strings only. Unity objects are decoded and updated on Unity's main thread, with a per-frame work cap.

### Safety and evidence rules

- AR body tracking is optional until it is proven stable on the actual iPhone.
- HUD, camera passthrough, connectivity status, and feedback must work without body tracking.
- Keep the centre of the camera view clear enough for the user to see the opponent and surroundings.
- Preserve an obvious pause/stop route and visible boundary guidance; these are not complete yet.
- Do not claim tracking quality, safety, latency, thermal stability, or frame rate without physical-device measurements.
- A Unity simulator or XR Simulation pass is useful engineering evidence, but not ARKit/device proof.

## 2. Sources of truth and how to resolve conflicts

Use this order, qualified by scope:

1. The current user request.
2. Repository-level `AGENTS.md` and the architectural invariants quoted above.
3. For phone message semantics, canonical protocol files under `contracts/` and `docs/protocol.md`.
4. For what the current build actually does, current code, `Main.unity`, package files, and project settings on the active branch.
5. This handoff, for reconciled history and setup context.
6. Other current docs.
7. Old chats, old reports, and proposal material.

Important nuances:

- For a value serialized in `Main.unity`, the scene value normally overrides a C# field initializer.
- For a newly added serialized field that has not yet been written to the scene YAML, the C# default is currently the only checked-in value and must be verified after Unity opens/resaves the scene.
- If runtime code disagrees with the canonical protocol, the implementation is the defect; code does not silently redefine the contract.
- Generated Xcode projects are disposable output. Put durable iOS settings in Unity project settings or `IOSPostProcess.cs`, not by hand-editing Xcode output.
- A ChatGPT conversation and a local checkout are separate things. Chat history may be available on another signed-in desktop, but the local repository does not upload with a conversation. Git plus checked-in `AGENTS.md`/docs is the portable source of context. See [Projects in ChatGPT](https://learn.chatgpt.com/docs/projects) and [Local environment](https://learn.chatgpt.com/docs/environments/local-environment).

## 3. Repository and branch map

### Current Git topology

```text
origin/main, main
  c6af010  Merge branch 'comms-integration'
      \
       636fc72  Initial testing Marker tracking
       ebaf9ed  WP2 Opponent Target Rig
       4f55e1b  WP3 dynamic punch trajectory
       4105d6f  WP4 refined punch animations       <- origin/OpponentTracker
       8a2d1df  add AprilTag to simulation for debug
       82f94e3  Refine Jab / Uppercut path
       8dc47c9  New guard animation movement and opacity change <- local HEAD
```

There are no repository tags at this snapshot. The repository is small (roughly a 6 MB Git pack), and Git LFS is not configured. The two glove FBX assets are each roughly 2.2 MB, so ordinary Git is still workable.

### Important folders

| Path | Role |
|---|---|
| `VisualizerApp/` | Unity project opened in Unity Hub |
| `VisualizerApp/Assets/Scenes/Main.unity` | Only enabled scene and current integration authority |
| `VisualizerApp/Assets/Scripts/Networking/` | WebSocket transport and thread-safe envelopes |
| `VisualizerApp/Assets/Scripts/Models/` | Message data classes and JSON decoder |
| `VisualizerApp/Assets/Scripts/Game/` | Main-thread draining, sequence gates, state store, diagnostics |
| `VisualizerApp/Assets/Scripts/UI/` | Runtime HUD and connection/debug presentation |
| `VisualizerApp/Assets/Scripts/AR/` | AprilTag tracking, pose filtering, semantic target provider |
| `VisualizerApp/Assets/Scripts/Presentation/` | Player glove rig, targeting/path logic, opacity |
| `VisualizerApp/Assets/Scripts/Tracking/` | Optional ARKit opponent body-glove tracking |
| `VisualizerApp/Assets/Editor/` | Scene/build helpers, simulation builder, iOS postprocess |
| `VisualizerApp/Assets/Tests/` | Edit-mode and play-mode tests |
| `contracts/` | Canonical schemas and valid examples |
| `tools/` | Schema validator, mock WebSocket server, smoke client |
| `docs/` | Architecture, protocol, setup, prototype notes, backlog, this handoff |

### Current code inventory

| File/component | Current responsibility |
|---|---|
| `Networking/GameNetworkClient.cs` | `ClientWebSocket` lifecycle, fragment assembly, connection status, reconnect backoff, raw queue |
| `Networking/NetworkEnvelope.cs` | Plain envelope for payloads and connection status crossing into the main thread |
| `Models/GameMessages.cs` | Serializable message models, discriminator probe, compatibility inference, decode validation |
| `Game/MatchController.cs` | Main-thread queue drain, decode/apply orchestration, public state/event/status/diagnostic events |
| `Game/MatchStateStore.cs` | Independent event/state sequence gates and authoritative snapshot storage |
| `Game/NetworkMessageDiagnostic.cs` | Compact accepted/rejected-message diagnostics for the HUD log |
| `Development/MockGameEventSource.cs` | Optional in-scene payload injection; present but disabled in `Main` |
| `UI/HudPresenter.cs` | Safe-area HUD, connection/freshness indicators, stats, timer/state, network log, runtime UI construction |
| `AR/AprilTagOpponentTracker.cs` | AR camera CPU-image acquisition/conversion, native AprilTag detection, raw target pose |
| `AR/OpponentTargetPoseFilter.cs` | Pure smoothing/snap/loss-state logic suitable for edit-mode testing |
| `AR/OpponentTargetProvider.cs` | Stable marker pose plus chest/head/left-body/right-body semantic targets |
| `Presentation/CameraRelativeGloveRig.cs` | Camera-resting player gloves and jab/hook/uppercut/guard animation control |
| `Presentation/PunchTargeting.cs` | Pure target selection, validity checks, contact compensation, and trajectory helpers |
| `Presentation/GloveOpacity.cs` | Per-renderer property-block opacity without shared-material mutation |
| `Tracking/OpponentBodyGloveTracker.cs` | Optional ARKit human-body hand/forearm-following opponent gloves |
| `Editor/AprilTagWp1Builder.cs` | WP1 scene construction/repair helper |
| `Editor/AprilTagWp2Builder.cs` | WP2 provider/target construction helper |
| `Editor/AprilTagWp3Builder.cs` | WP3 punch-target wiring helper |
| `Editor/AprilTagSimulationBuilder.cs` | Real detectable tag texture/environment generation and transformation repair helpers |
| `Editor/GlovePrototypeBuilder.cs` | Player glove/debug-control scene setup and upgrades |
| `Editor/OpponentBodyGlovePrototypeBuilder.cs` | Optional opponent body-glove scene setup |
| `Editor/IOSPostProcess.cs` | Durable generated-Xcode minimum-version and Info.plist network settings |
| `Tests/EditMode/MessageDecoderTests.cs` | Decoder, legacy compatibility, range/ordering-related message tests |
| `Tests/EditMode/OpponentTargetPoseFilterTests.cs` | Target filter state, smoothing, loss, reacquisition tests |
| `Tests/EditMode/PunchTargetingTests.cs` | Target selection/path/contact/invalid-target tests |
| `Tests/EditMode/GuardPresentationTests.cs` | Guard geometry, opacity, restoration, interruption, renderer/material tests |
| `Tests/PlayMode/AprilTagSimulationPlayModeTests.cs` | Main scene rendered simulation image -> real detector acquisition of tag ID 0 |
| `tools/validate_contracts.py` | Validate examples against both canonical JSON Schemas |
| `tools/mock_server.py` | Development WebSocket event/state broadcaster, optional WSS |
| `tools/smoke_test_server.py` | Minimal local WebSocket client smoke test |

Runtime code uses the `CG4002.Visualizer` namespace and child namespaces through `CG4002.Visualizer.asmdef`. Test assemblies are separated into edit-mode and simulation play-mode assembly definitions.

### Files that must not move between machines

The repository correctly ignores Unity and Apple build products. Do not copy these from Windows to macOS or vice versa:

```text
VisualizerApp/Library/
VisualizerApp/Temp/
VisualizerApp/Logs/
VisualizerApp/Builds/
VisualizerApp/UserSettings/
Xcode DerivedData/
generated Xcode projects
.venv/
tmp/
```

The Windows `VisualizerApp/Library` was about 1.26 GB during this audit. Let each machine regenerate its own `Library`.

## 4. Toolchain and Unity configuration

### Exact editor

Both machines must use:

```text
Unity 6000.0.76f1
revision 6f7f9e1c9e8a
```

Do not substitute an older chat's suggested Unity 6.5 build. Install the **iOS Build Support** module on the Mac.

### Direct package dependencies

| Package | Version |
|---|---:|
| AR Foundation | `6.0.6` |
| ARKit XR Plugin | `6.0.6` |
| XR Plug-in Management | `4.5.0` |
| XR Core Utilities | `2.4.0` |
| Input System | `1.11.2` |
| uGUI | `2.0.0` |
| AprilTag (`jp.keijiro.apriltag`) | `1.0.3` |
| Test Framework requested by manifest | `1.4.5` |
| Test Framework currently resolved in lockfile | `1.6.0` |

The AprilTag package comes from `https://registry.npmjs.com` under the `jp.keijiro` scope. It supports only `tagStandard41h12` in this version.

### Apple-silicon AprilTag warning

The cached package's own README lists its macOS native binary as **x86-64**, while its iOS library is arm64. The project will therefore need an explicit Mac check:

- Native Apple-silicon Unity Editor may fail to load the macOS AprilTag detector used by Standalone/XR Simulation.
- The generated iOS build has an arm64 AprilTag library and may still work on device.
- If native editor simulation fails, first confirm it is the binary architecture. Keeping AprilTag simulation on Windows is the simplest fallback. If evaluating an Intel Unity editor under Rosetta, use the exact same Unity version and preferably a separate checkout/`Library`; alternating ARM and Intel editors over one generated `Library` can trigger large reimports and muddy diagnosis. Do not change package versions casually; check Unity 6, AR Foundation, and iOS/IL2CPP compatibility first.

### Build and player facts

- Only `Assets/Scenes/Main.unity` is enabled.
- Standalone uses the XR Simulation loader.
- iPhone uses the ARKit loader.
- Rendering is the built-in pipeline, not URP.
- Product name: `ARBoxing`.
- Company: `NUSCG4002B13`.
- Bundle identifier: `com.NUSCG4002B13.ARBoxing`.
- Version: `1.0`.
- Near/far camera planes are approximately 0.1 m / 20 m.
- iPhone quality level is Medium.
- All four device orientations are currently allowed through auto-rotation.
- Apple development team is blank and Unity automatic signing is off; select the team in the generated Xcode project for local deployment.
- Serialized project settings say minimum iOS 13, but `IOSPostProcess.cs` forces iOS 15 on both generated Xcode targets. This should be made consistent.
- The camera permission description is currently `Augmented Reality requires the camera`.
- The postprocess adds a Local Network usage description and `NSAllowsLocalNetworking=true`.
- `iOSRequireARKit` is currently false, although `docs/mac-setup.md` describes ARKit as required. Decide and align code/docs/settings.
- The active Unity build profile is local editor state and should be reselected on the Mac; do not assume it transfers.

## 5. Runtime architecture

### End-to-end phone message path

```text
ClientWebSocket receive loop (background/async)
    -> ConcurrentQueue<NetworkEnvelope> containing raw JSON/status only
    -> MatchController.Update() on Unity main thread
       (maximum 64 envelopes per frame)
    -> MessageDecoder validates and classifies
    -> MatchStateStore applies independent sequence gates
       -> MatchState overwrites persistent display state
       -> GameEvent is emitted as transient accepted event
    -> HudPresenter and future feedback subscribers render it
```

This split is intentional. Never touch a `GameObject`, `Transform`, UI component, or other Unity object from the receive callback.

### Networking

`GameNetworkClient` uses `System.Net.WebSockets.ClientWebSocket`.

Current scene settings:

- URL: `ws://192.168.137.1:8889`
- connect timeout: 8 seconds;
- initial reconnect delay: 0.5 seconds;
- maximum reconnect delay: 5 seconds;
- connect on enable: true.

It handles fragmented WebSocket frames until `EndOfMessage`, enqueues connection statuses, and retries with exponential delay. Network exceptions are intentionally not thrown into Unity UI code, but this also means the current UI has little error detail.

Current limitations:

- the raw-message size is not capped and `GameNetworkClient` uses an unbounded `ConcurrentQueue`; a sender faster than the 64-per-frame drain can grow memory indefinitely;
- there is no application heartbeat or idle timeout;
- receive/decode/reconnect exceptions are mostly swallowed or hidden behind status changes, which makes diagnosis difficult;
- sequence gates never reset after a server restart/session change;
- no end-to-end TLS/reconnect/convergence test exists.

A future contract should add a session or match identifier, or explicitly guarantee lifetime-monotonic sequence numbers. Otherwise a restarted server beginning at sequence zero can be rejected forever by a still-running phone.

### Decode and validation

`MessageDecoder` uses Unity `JsonUtility` and probes message shape/type. Canonical messages require `type`, but the decoder temporarily accepts the old initial-report examples without the discriminator and infers `GameEvent` versus `MatchState` during integration.

Treat all incoming values as untrusted. The decoder checks sequence/timestamp, player IDs, finite/ranged numeric values, and that event/state strings are non-empty, but it **does not currently reject unknown event, punch, outcome, or match-state strings**. Schema validation is not running on-device. Do not assume JSON accepted by `JsonUtility` was complete: missing numeric fields can become zero and may pass when zero is within the permitted range. Enum allow-list validation and missing-field handling are current hardening gaps.

### Main-thread state handling

`MatchController` drains at most 64 queued envelopes in each `Update`. It exposes:

- `StateChanged`;
- `GameEventReceived`;
- `ConnectionStatusChanged`;
- message diagnostics.

`MatchStateStore` keeps **separate** last accepted event and state sequence numbers. A newer `MatchState` replaces health, stamina, time, state, and timestamp. An event is accepted/rejected for ordering but does not mutate authoritative health.

### Important missing integration

No current runtime subscriber connects `MatchController.GameEventReceived` to `CameraRelativeGloveRig`. The seven development buttons can trigger the punch/guard animations, but live network `GameEvent` messages do **not** yet trigger those gloves. This is one of the clearest next integration tasks.

When wiring it, map event/punch vocabulary carefully, keep the laptop's `outcome` authoritative, and treat the local animation as presentation only.

### HUD

`HudPresenter` can construct the missing UI at runtime because the serialized UI references in `Main.unity` are null. Current settings use local player 1, a one-second stale threshold, an eight-line debug limit, and a hidden-by-default network debug panel.

It shows player/opponent health and stamina, round timer/state, connection/reconnection condition, accepted packet counts, data freshness, and a `NET LOG`. It respects the iPhone safe area. Current freshness is based on any accepted payload rather than specifically the last authoritative `MatchState`, which is worth tightening.

The development scene currently contains several overlays and seven animation buttons as well as the runtime HUD. Before a demo, simplify it so the camera centre remains clear and the connection warning remains obvious.

## 6. Canonical phone protocol

The contract authority is:

- `contracts/game-event.schema.json`;
- `contracts/match-state.schema.json`;
- `contracts/examples/game-event.json`;
- `contracts/examples/match-state.json`;
- `docs/protocol.md`.

### `GameEvent`

Canonical required fields are:

```text
type, seq, timestamp, event, source_player, target_player,
confidence, intensity, outcome
```

Constraints:

- `type` is exactly `GameEvent`;
- `seq` and `timestamp` are non-negative integers;
- `event` is `PUNCH`, `GUARD`, `WEAVE`, `ITEM_PICKUP`, or `ROUND_TRANSITION`;
- player IDs are 1 or 2;
- `punch`, when present, is empty or one of `JAB`, `CROSS`, `LEFT_HOOK`, `RIGHT_HOOK`, `LEFT_UPPERCUT`, `RIGHT_UPPERCUT`;
- confidence and intensity are in `[0, 1]`;
- outcome is `HIT`, `BLOCK`, `MISS`, or `NONE`;
- additional properties are rejected by the schema.

The schema currently does **not** list `punch` as required even though punch events normally need it. Decide whether this is intentional for non-punch events or whether the schema needs conditional requirements.

### `MatchState`

Required fields are:

```text
type, seq, timestamp, player_1, player_2, round_time, state
```

Health and stamina are 0-100; round time is non-negative; state is one of `LOBBY`, `CALIBRATING`, `COUNTDOWN`, `FIGHTING`, `PAUSED`, `ROUND_END`, or `MATCH_END`; additional properties are rejected.

### Contract-change checklist

Every contract change must update all of these together:

1. both JSON Schemas and examples;
2. C# message models and decoder tests;
3. `tools/mock_server.py`;
4. `docs/protocol.md`;
5. a communications-owner-facing change note.

Development LAN traffic may use `ws://`. A demonstration/production `wss://` endpoint must use a certificate chain trusted by iOS. Never bypass certificate validation in app code, and never put credentials or certificate private keys in Git or message JSON.

## 7. Communications integration status

There are two distinct server contexts that should not be conflated.

### This repository's mock server

`tools/mock_server.py` is a WebSocket server, defaulting to port 8765. WP7 adds a deterministic health lifecycle (spawn at 2 s, accepted pickup at 6 s, expiry at 10 s, initial health 60), an immediate complete state on every connection, independent event/state sequences, and CLI timing/seed/duplicate/stale/burst options. Punches are disabled by default so the pickup demonstration converges cleanly from `60 -> 85`; pass a positive `--attack-interval-seconds` to restore alternating punch traffic. An optional reserved attack item can be emitted/expired, but it has no visualizer gameplay effect yet. Optional WSS still requires both certificate and key.

`tools/smoke_test_server.py` now accepts `--url` and uses a continuous observer plus reconnecting probes. It proves pre-collection item recreation, receipt of the transient pickup event, and post-collection convergence from a fresh state. `tools/test_mock_server.py` separately covers schema validity, clamping, expiry, duplicate/stale/burst delivery, and live WebSocket reconnect. TLS and two physical phones remain untested.

The current Unity scene points to `ws://127.0.0.1:8766`, while the mock server default remains 8765. The WP7 guide deliberately starts the server with `--port 8766`; the smoke client URL is configurable.

### Teammate communications repository

The companion checkout at `C:\Dev\cg4002-comms` currently documents/implements raw TCP with newline-delimited JSON on port 8889, not WebSockets. A Unity `ClientWebSocket` cannot connect to that server even if IP and port match.

Its sample payloads also differ from the canonical phone contract: the event can omit `type` and `outcome`, while state can omit `type`, `timestamp`, and both stamina values. Its simple server accepts one client, sends three messages, and closes. Treat it as a connectivity fixture, not final production behaviour.

The preferred reconciliation is a persistent multi-client WebSocket pusher on the laptop Game Engine side that emits the canonical schemas to one or two phones, supports reconnect, and periodically sends `MatchState`. If the team intentionally chooses raw TCP instead, that is a real architecture/implementation change and the Unity transport, tests, docs, and iOS network assumptions must change together.

Port meanings discussed with the communications work are:

- 8888: sensor data, ESP32 to Ultra96;
- 8889: laptop Game Engine to phone `GameEvent`/`MatchState` in the intended integrated arrangement.

An earlier document may contain plaintext credentials. Do not copy them into this handoff or another chat. Remove/rotate them before sharing if they are real.

## 8. Current scene and presentation

### Main scene contents

`Main.unity` contains, among other objects:

- AR Session;
- XR Origin / Camera Offset / Main Camera;
- red `CameraRelativeGloves` for the local player;
- blue opponent body gloves;
- AprilTag WP1 tracker;
- AprilTag WP2 target provider and smoothed semantic targets;
- `NetworkRuntime` with client/controller/HUD/mock source;
- EventSystem;
- `GloveDebugCanvas` with seven development buttons;
- an inactive legacy `TrackingDemo` object.

The buttons trigger left/right jab, hook, and uppercut plus two-hand guard.

### Current serialized player-glove values

These are the checked-in scene values and take precedence over older recommendations in chats/docs:

| Setting | Current value |
|---|---:|
| Left viewport position | `(0.18, 0.00)` |
| Right viewport position | `(0.82, 0.00)` |
| Distance from camera | `0.65 m` |
| General punch duration | `0.5 s` |
| Guard duration | `1.0 s` |
| Hook duration | `0.7 s` |
| Uppercut duration | `1.0 s` |
| Target standoff | `0.08 m` |
| Minimum target depth | `0.35 m` |
| Maximum target distance | `3.0 m` |
| Hook horizontal arc | `0.18 m` |
| Hook vertical lift | `0.12 m` |
| Uppercut dip | `0.12 m` |
| Target-loss return | `0.12 s` |
| Uppercut inward yaw | `-53 degrees` |
| Uppercut pitch | `0 degrees` |
| Jab turn completion | `65%` of extension |
| Left jab local-Y yaw | `-60 degrees` |
| Right jab local-Y yaw | `+60 degrees` |
| Tracked targets | enabled |
| Local fallback if target unavailable | enabled |

The optional jab contact transforms are null, so fallback contact offsets `(0, 0.12, 0)` and local `+Y` strike axes are in use.

### Guard and opacity commit

Commit `8dc47c9` adds:

- a higher/inward guard pose;
- a 0.12 m pull toward the camera;
- a 0.25 m minimum camera-depth clamp;
- local-Y guard twist defaults of left `+55` and right `-55` degrees;
- opacity interpolation to 0.65 at full guard;
- restoration on completion, reset, disable, or punch interruption;
- per-renderer `MaterialPropertyBlock` use so shared materials are not mutated at runtime;
- player glove materials configured for Standard/Fade rendering;
- extensive guard/opacity edit-mode tests.

The new guard fields do not yet appear as explicit YAML entries in `Main.unity`; the checked-in C# initializers are therefore the present defaults. Open the scene on one editor, visually verify both hands, then save so intended values are explicit.

Note the sign difference: current scene jab yaw is left negative/right positive, while the new guard defaults are left positive/right negative. That may be correct because guard palms and extended knuckles need different orientations, but it needs visual and device verification rather than assumption.

### Assets and licensing

The current player gloves are imported red FBX models; opponent gloves are blue versions. Old rounded primitive placeholders remain in some history/docs but are no longer the main visual target. The right red material filename has the existing typo `M_PlayeGlove_Right_Red.mat`.

The glove source is by Gohar.Munir on Sketchfab under CC BY 4.0. Keep `VisualizerApp/Assets/Art/Gloves/README.md` and its attribution with any distributed build/material.

`docs/glove-prototype.md` still talks substantially about the earlier placeholder fist/cuff and is stale.

## 9. AprilTag opponent targeting

The implemented punch-target path is AprilTag-based, not AR tracked-image based.

### WP1: raw marker pose

`AprilTagOpponentTracker` obtains `XRCpuImage` frames from `ARCameraManager`, requests asynchronous conversion/downsampling, runs the native detector, and publishes the selected tag pose on the main thread. It records the camera transform and FOV associated with the captured image and correctly disposes images, conversions, and detector resources.

Current scene values:

- family: `tagStandard41h12`;
- tag ID: 0;
- detector tag size: `0.10 m`, meaning the inner black-square width;
- intended print total width: about 180 mm;
- image downsample: 2;
- detector decimation: 1;
- detection rate: 10 Hz;
- tracking timeout: 0.35 s;
- world axes and status overlay: enabled.

Use a rigid, matte print and measure the **actual** inner black square. Avoid glossy flexing paper for final measurement.

### Critical camera-transformation mismatch

Code/docs intend a rear-camera transformation of `XRCpuImage.Transformation.None`, but `Main.unity` currently serializes:

```text
imageTransformation: 2
```

This is `MirrorY`. It can reflect the image, reverse apparent left/right, and even reflect the tag payload enough to make decoding intermittent. The XR Simulation texture was generated while this mirrored setting was present, so the simulated marker is precompensated and can pass while the physical rear camera is wrong.

Recommended correction:

1. Change the WP1 tracker transformation to `None` in `Main.unity`.
2. Run the editor helper labelled for fixing rear-camera left/right mirroring, if appropriate.
3. Regenerate the AprilTag XR Simulation environment/texture.
4. Save the scene.
5. Re-run edit-mode and play-mode tests.
6. Re-test the printed tag on the physical iPhone and confirm real left/right motion.

Do not treat a simulation-only pass as confirmation of this fix.

### WP2: stable semantic targets

`OpponentTargetProvider` and `OpponentTargetPoseFilter` convert the raw tag pose into stable target transforms. States are `MissingSource`, `Searching`, `Tracking`, and `Lost`. Position/rotation smoothing values are about 12/10; reacquisition snaps after large changes (about 0.75 m or 70 degrees); loss hides/invalidates targets rather than returning the origin or a stale pose.

Current marker-relative semantic points are approximately:

| Target | Offset |
|---|---|
| Chest | `(0, 0, 0)` |
| Head | `(0, 0.35, 0)` |
| Left body | `(-0.18, -0.10, 0)` |
| Right body | `(0.18, -0.10, 0)` |

### WP3: tracked punch endpoints

- Left/right jabs use separate left/right body targets.
- Hooks and uppercuts use the head target.
- The endpoint is resampled throughout the animation so it follows the moving target.
- Invalid, behind-camera, too-near, or farther-than-3 m targets are rejected.
- Loss during a punch aborts and returns in about 0.12 s.
- A prototype local fallback remains enabled for development.

### WP4 and later path refinement

- Jab is straight and knuckle/contact-point compensated.
- Hook is a mirrored cubic curve with horizontal bow and lift.
- Uppercut is a rising quadratic path with separately controlled local-X pitch and local-Y twist.
- Commit `82f94e3` contains the latest jab/uppercut refinements.
- Current scene tuning, listed earlier, supersedes old WP4 recommendations of roughly 0.46/0.48 seconds and +65 degrees.

None of this decides hit/miss. It is a debug-driven presentation prototype designed to visualize a laptop-authoritative event once live `GameEventReceived` wiring is added; today its motions are triggered by the development controls.

### XR Simulation

The simulation contains a rendered, detectable tag; it does not inject a fake pose into the tracker. It is valuable for pipeline integration, trajectory, target-loss, and deterministic play-mode checks.

On Windows, select the Standalone profile before Play Mode so XR Simulation loads. Return to iOS before generating an Xcode build. Rebuild simulation assets after changing the camera image transformation.

Simulation cannot establish camera exposure/motion-blur robustness, actual ARKit quality, motion-to-render latency, thermals, or physical-device frame rate.

## 10. Optional ARKit body gloves

`OpponentBodyGloveTracker` is a separate, optional visual path. It uses `ARHumanBodyManager` with 3D pose/scale and follows hard-coded left/right forearm/hand joint indices (21/22 and 65/66), with forearm fallback, centred-body selection, smoothing, and a short hide timeout around 0.2 s.

It drives blue opponent glove models. It is currently enabled in the scene but is not the target source for the player punch animations; the AprilTag provider is.

There are no dedicated automated tests or recorded physical boxing-motion results for this body tracker. Keep it optional and be prepared to disable it if it hurts performance, thermal behaviour, stability, or visibility. A full-body pose in ideal lighting is not evidence that fast, partially occluded boxing arms will work.

The legacy `TrackingDemoScript` is outside the main namespace/assembly and sits on an inactive scene object; it only created a simple cube after session tracking. Treat it as old scaffolding.

## 11. Verification evidence and what it proves

### Checks performed during this handoff

`py -3 tools/validate_contracts.py` passed both current examples:

```text
valid: game-event.json
valid: match-state.json
```

The repository mock WebSocket server and smoke client were also exercised during the repository audit and the client received three sequential `MatchState` objects.

There are Unity-generated trailing spaces in some simulation YAML/meta files when comparing the local branch with the remote. They are formatting noise from Unity assets, not a contract failure, but explain why a branch-wide `git diff --check` is not entirely silent.

### Unity test history from the implementation chats

The implementation work reported these progressive edit-mode totals as features were added:

```text
4 -> 9 -> 17 -> 23 -> 28 -> 32 -> 41 -> 55 passing tests
```

The latest ignored local Unity XML report found on the ThinkPad records 55/55 passing tests on 30 September 2026. Because it lives under ignored `tmp/`, it will not transfer to the Mac. A chat also reported the AprilTag XR Simulation play-mode test passing 1/1.

These results are useful, but re-run them after the Mac import and after any scene transformation fix. Do not present chat-reported or local ignored reports as a CI record.

### Missing physical evidence

The chats contain a user report that WP1 was fully functional in testing, but the device/build/environment details were not recorded. It was likely part of the iPhone workflow, but that is an inference rather than durable evidence. The repository has no test sheet containing all of:

- device model;
- exact iOS version;
- Unity/Xcode build identity;
- FPS;
- thermal state over time;
- loss/reacquisition rate;
- pose jitter/drift;
- motion-to-render latency;
- network event-to-render latency.

Collect these before making performance or readiness claims.

## 12. MacBook Air setup and transfer workflow

### Before leaving the ThinkPad

1. Confirm no intentional edits are missing: `git status`.
2. Review local commits: `git log --oneline origin/OpponentTracker..HEAD`.
3. Commit this handoff file.
4. Push `OpponentTracker`.
5. Inspect the local stash separately; retain it on the ThinkPad until deliberately resolved.
6. If the correct Group B13 source report is needed on the Mac, transfer it deliberately or add it under a clear repository filename after checking sharing/copyright expectations. The tracked file with a similar B13 name is the wrong project; see the reference section below.

### Install on the M1 MacBook Air

1. Install an Xcode version mutually supported by macOS Tahoe, the attached iPhone/iOS version, and Unity `6000.0.76f1`. The App Store release is a convenient starting point, but do not assume the newest release is automatically compatible. Open full Xcode once, accept the licence, and let it install platform components.
2. Install/select command-line tools if needed, then verify the selected developer directory and version:

   ```bash
   xcode-select --install
   xcode-select -p
   xcodebuild -version
   ```

3. Install the Apple-silicon build of Unity Hub.
4. Through Unity Hub, install **Unity 6000.0.76f1** plus **iOS Build Support**.
5. Avoid putting the checkout inside iCloud Drive, OneDrive, Dropbox, or another live-synchronised folder.

Use a normal local path:

```bash
mkdir -p ~/Developer
cd ~/Developer
git clone https://github.com/zexueteh/CG4002-Viz.git
cd CG4002-Viz
git switch -c OpponentTracker --track origin/OpponentTracker
git status
```

If the branch already exists locally:

```bash
git switch OpponentTracker
git pull --ff-only origin OpponentTracker
```

Open this exact folder in Unity Hub:

```text
~/Developer/CG4002-Viz/VisualizerApp
```

The first import will take time and requires internet access for Unity packages and the scoped AprilTag npm registry. Let Unity generate a fresh macOS `Library`.

After the import completes and before making edits, run `git status`. This separates any unexpected package, project-setting, scene-serialization, or line-ending churn from intentional work. The repository already has `.gitattributes` line-ending/Unity YAML rules; investigate rather than casually committing a whole-project rewrite.

### First Mac validation

1. Confirm Unity reports no compile errors.
2. Open `Assets/Scenes/Main.unity`.
3. Confirm the enabled scene and serialized objects/references survived.
4. Run all edit-mode tests.
5. Switch to the macOS/Standalone build profile before trying play-mode AprilTag XR Simulation; it will not load while the active target is iOS. If the detector native plugin fails under Apple silicon, investigate the x86-only macOS package warning rather than changing gameplay code.
6. Switch back to iOS before generating Xcode.
7. Run contract validation with Python.

Python setup:

```bash
cd ~/Developer/CG4002-Viz
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
python tools/validate_contracts.py
```

Mock server and smoke client:

```bash
python tools/mock_server.py --host 127.0.0.1 --port 8765
```

In another terminal:

```bash
cd ~/Developer/CG4002-Viz
source .venv/bin/activate
python tools/smoke_test_server.py
```

The loopback binding above is safer for a same-Mac smoke test. Bind `--host 0.0.0.0` only when an iPhone must reach the server over a trusted LAN, restrict the firewall exposure as practical, and stop the plaintext unauthenticated test server afterward.

### iPhone build

1. Select the iOS build profile in Unity.
2. Confirm ARKit is the active iPhone loader and run XR project validation.
3. For the first Mac/device validation, build cleanly to a fresh ignored path such as `VisualizerApp/Builds/iOS-first-mac` rather than reusing an old generated Xcode tree.
4. Open the generated Xcode project/workspace.
5. Select `Unity-iPhone`, the connected physical iPhone, and the user's Apple development team.
6. Resolve bundle-signing ownership through Xcode; do not commit personal signing identifiers unless the team deliberately wants them.
7. On the iPhone, enable Developer Mode, trust the Mac, and grant camera/local-network permissions.
8. Run on the device.
9. Move any durable fix back into Unity project settings or the post-build script, then regenerate Xcode. Never preserve the only copy of a fix in generated Xcode output.

Use an Xcode release compatible with the Mac's current macOS and the iPhone's current iOS. Old chats contained time-sensitive Xcode/macOS version advice; verify current compatibility on the Mac rather than following those numbers literally.

### LAN testing details

- `127.0.0.1` on the iPhone means the iPhone, not the Mac or ThinkPad.
- If the Mac runs the server, point Unity at the Mac's LAN address.
- If the ThinkPad runs the server, point Unity at the ThinkPad's LAN address.
- Put both devices on the same reachable network, permit the server through the host firewall, and accept iOS Local Network permission.
- Decide explicitly whether the integration endpoint uses port 8765 or 8889.
- The endpoint is serialized in `Main.unity`; do not casually commit a one-machine DHCP address that breaks the other computer. Prefer a stable DHCP reservation, a small runtime configuration mechanism, or an intentionally documented development value.
- A personal hotspot/isolated campus network can block peer-to-peer traffic; verify basic reachability before debugging JSON.

### Normal two-machine routine

On the machine finishing work:

```bash
git status
git add -- path/to/intentional-file path/to/another-file  # replace these placeholders
git commit -m "Describe the change"
git push
```

On the machine starting work:

```bash
git status
git pull --ff-only
```

Do not begin with uncommitted work on both machines. Close or let Unity finish serialising before switching computers, and inspect every scene/prefab diff because Unity YAML conflicts are difficult to merge safely.

## 13. Complete chat audit

### Coverage

The audit enumerated 27 chats visible through the available desktop-app APIs (limit 50, with no unavailable source reported) and checked archives. It then read every turn, through pagination/EOF, for:

- all seven Codex-kind chats returned under the local project ID/label `ZX CAPSTONE`; no ChatGPT-kind chat was returned under that ID;
- this current repository handoff chat, which the app reported without the project ID;
- two clearly relevant repository-working chats that also lacked that project assignment;
- archived Codex and ChatGPT lists for relevant omissions.

The seven project chats contained 42 turn records, with 39 unique records because `Basic AR Boxing Gloves Animation + Body tracking` inherited/repeated the three initial setup turns. There was one archived Codex chat and no archived ChatGPT conversations; the archived item was unrelated. Within the chats and archives returned by the available APIs, no relevant project chat was omitted. Unrelated chats that happened to start from the same working directory, such as parcel tracking, were not treated as project development context.

### 1. Install Xcode on Sequoia 15.7.9 (7-15 September 2026)

This chat explored Apple hardware/tooling before the M1 Mac was available. Conclusions were that an AMD VMware path was unreliable for Xcode/iOS deployment, a 2018 Intel Air was undesirable, and a 2020 M1 Air was the oldest sensible choice. It discussed 16 GB/512 GB as preferable and 8 GB/256 GB as workable with tighter storage/memory discipline.

No repository changes came from it. Exact Xcode/macOS compatibility numbers in it are historical and should be rechecked now.

### 2. Set up NUS capstone project (16 September 2026)

This created the initial repository foundation from the design material: exact Unity pinning, modular networking/state/HUD code, message schemas/examples, mock server, protocol/architecture/setup docs, tests, `.gitignore`, and `AGENTS.md` guidance. It established the Windows-development -> Git -> Mac-Xcode/iPhone workflow and rejected using Unity `6000.5.10f1` in favour of the project's exact `6000.0.76f1`.

Its three turns recur at the beginning of the later Basic AR chat due to conversation ancestry; they are the same context, not separate work.

### 3. Update CG4002 development folder (17 September 2026)

This established `C:\Dev\CG4002-Viz` as the canonical Windows checkout. An earlier OneDrive-based path is obsolete. Continue avoiding synced folders on both Windows and macOS.

### 4. Review Unity networking stack (18 September 2026)

This review found the WebSocket-versus-raw-TCP mismatch and schema omissions in communications samples. It reinforced laptop authority, periodic state convergence, independent event/state sequence handling, two-phone/reconnect/TLS concerns, and credential hygiene.

It implemented/finished the scene `NetworkRuntime`, diagnostics, runtime HUD, and `NET LOG`, and documented injected mock testing. Seeing `OFFLINE` without a server was expected, not proof that the UI was broken.

Still-open findings from this chat remain relevant: session/sequence reset semantics, persistent multi-client WebSocket server, full reconnect/convergence tests, and safe WSS.

### 5. Review AR glove tracking brief (19 September 2026)

This implemented an early temporary rounded blue glove prototype and an approval gate. That placeholder design was later superseded by imported red local-player and blue opponent glove assets plus the current AprilTag/punch branch. Some old generated prefab/doc expectations from this chat are no longer present or authoritative.

### 6. Explain AR Foundation basics (26-29 September 2026)

This was mostly educational. It explained AR Session, XR Origin, AR camera, why a normal desktop Play view can be black without simulation, CPU camera image access, provider setup, and the difference between editor simulation and device proof.

It also developed the intended safety/arena direction: detect a floor plane, let the user confirm one arena anchor, parent boundary/start/pickup objects to it, then disable plane visualisation/scanning; use two player zones and a neutral gap; warn on marker distance/tracking loss; keep a clear pause/stop path. Those arena/boundary features are plans, not current implementation.

### 7. Basic AR Boxing Gloves Animation + Body tracking (16-30 September 2026)

This is the large implementation history. In order, it covered:

- the initial repository setup context repeated from chat 2;
- an iOS build error, leading to iOS 15 being forced on both Xcode targets by postprocess;
- camera-relative player gloves and seven debug controls;
- optional ARKit body-tracked opponent gloves; the whole project edit-mode suite was 4/4 at that point, but there was no dedicated body-tracker test or physical proof;
- a merge around commit `de929b9`;
- model/licensing decisions and imported glove assets;
- AprilTag WP1 CPU-camera detection, later reported fully functional by the user, without a recorded device/build/environment;
- WP2 semantic target rig and 9/9 tests;
- intended `MirrorY` -> `None` rear-camera correction and a 9/9 whole-suite pass, which did not physically prove camera orientation;
- WP3 live targeted trajectories and 17/17 tests;
- WP4 path refinement and 23/23 tests;
- real-tag XR Simulation, 1/1 play-mode plus 23/23 edit-mode;
- jab contact-point compensation, 28/28;
- jab local-Y rotation, 32/32;
- uppercut local-Y refinement, 41/41;
- guard pose/transparency, 55/55, plus contract validation.

The important reconciliation is that the chat said the mirror fix was made, but the current scene still serializes `MirrorY`. Likewise several values discussed in prose were later retuned. Current scene/source values win.

### 8. Summarize project for Mac handoff (30 September 2026)

This chat requested the full cross-machine context package. It audited the repository, current and archived chat inventory, relevant out-of-project repository chats, current Git state, Unity scene/configuration, the companion communications checkout, local test reports, and official product guidance on local-folder/chat portability. This document is its durable output.

### Relevant repo chat outside the project: Resolve Main.unity merge conflict (29 September 2026)

This preserved the local AR/glove scene while incorporating the remote WebSocket URL, then merged the communications integration into `main` as `c6af010`. It specifically preserved `NetworkRuntime` and glove work. Tests could not be run during part of that chat because Unity held the project lock.

### Relevant repo chat outside the project: Enable iPhone SE developer mode (29 September 2026)

This covered an iPhone SE 2020 with a broken Home button: AssistiveTouch, Back Tap, and command-line developer-mode possibilities, including the need to temporarily remove a passcode for some recovery flows. Later it diagnosed Finder showing the device contents as unreadable after an update. The safe advice was: do not Restore before a backup, reset trust/pairing, verify current Xcode/device support, and try cable/port basics.

The exact OS/version claims in the chat were inconsistent and time-sensitive. Treat the general recovery logic as context, not the literal version numbers. Earlier project discussion also referenced an iPhone 13 mini on iOS 18.6.2; record the actual device used for each future test.

## 14. Reconciled and superseded decisions

This section prevents old context from silently overriding current work.

| Old/conflicting context | Current decision/evidence |
|---|---|
| OneDrive development path | Obsolete; use `C:\Dev\CG4002-Viz` and `~/Developer/CG4002-Viz` |
| Unity 6.5 or an arbitrary latest Unity | Use exactly `6000.0.76f1` on both computers |
| AMD VMware as iOS build host | Superseded by physical M1 MacBook Air |
| Direct Ultra96-to-phone path as final architecture | Connectivity test only; final authority remains laptop Game Engine -> phone |
| Raw TCP server on 8889 works with Unity | False with current client; Unity expects WebSocket |
| Messages without `type` are canonical | Only decoder compatibility; canonical outgoing JSON requires `type` |
| Body tracking or tracked-image plan drives punches | AprilTag CPU-image tracker currently drives semantic punch targets; body gloves are optional parallel presentation |
| `MirrorY` rear-camera transform is correct/fixed | Intended answer is `None`, but current scene still serializes `MirrorY`; fix and test |
| Existing simulation proves physical transform | No; it was generated to match the mirrored scene and can hide the defect |
| Old WP4 defaults (`0.46` hook, `0.48` uppercut, `+65` yaw) and a later chat claim that uppercut remained `0.7 s / 90 degrees` | Current scene uses hook `0.7`, uppercut `1.0`, uppercut yaw `-53`; current serialized values win pending visual proof |
| Conflicting jab sign advice in chats | Current scene is left `-60`, right `+60` |
| Temporary rounded blue gloves are the deliverable | Superseded by imported red player and blue opponent FBX gloves |
| `docs/glove-prototype.md` fully describes current scene | Stale; use current code/scene and this handoff |
| Backlog marks many foundations unstarted | Stale; decoder, scene, tests, HUD, AprilTag WP1-WP4, and simulation now exist |
| Project minimum iOS is clearly set | Inconsistent: serialized 13, generated Xcode forced to 15 |
| ARKit is clearly required | Inconsistent: docs say required, serialized setting says optional |
| Main scene button animations are network-driven | Not yet; `GameEventReceived` has no glove subscriber |
| A merged/passing branch is remotely available | Not yet; local branch is three commits ahead until pushed |

## 15. Known gaps and recommended priority order

### P0: make the work portable

1. Commit this handoff.
2. Push all three local commits plus the handoff to `origin/OpponentTracker`.
3. Clone/pull that branch on the Mac and confirm identical HEAD.

### P1: fix/verify the real camera path

1. Change AprilTag transformation from serialized `MirrorY` to `None`.
2. Rebuild the simulation marker/environment.
3. Run all tests.
4. Physically confirm left/right pose and tag decoding on the iPhone.
5. Check whether the M1 editor can load the x86-only macOS detector plugin.

### P1: close the live gameplay loop

1. Wire `GameEventReceived` to presentation animations.
2. Define exact mapping for `JAB` versus `CROSS` and left/right identity.
3. Show hit/block/miss feedback without deriving outcome locally.
4. Ensure missed events are visually corrected by later `MatchState`.

### P1: reconcile the actual server

1. Agree with communications owner on WebSocket framing and canonical JSON.
2. Choose/configure the integration IP/port.
3. Support persistent multi-client connections and reconnect.
4. Resolve sequence reset with session/match identity or monotonic guarantee.
5. Add two-client and reconnect/convergence tests.

### P1: physical-device quality and safety

1. Add/verify an obvious pause/stop path.
2. Add visible boundary/tracking-loss warnings without cluttering the centre.
3. Test real orientation/headset layout and camera obstruction.
4. Record FPS, thermals, loss/reacquisition, and latency with device/OS identity.

### P2: configuration/document cleanup

1. Align minimum iOS between project settings and postprocess.
2. Decide whether ARKit is required and align setting/docs.
3. Improve camera and local-network permission text.
4. Resolve mock port 8765 versus scene port 8889.
5. Update `docs/glove-prototype.md` and `docs/visualizer-backlog.md`.
6. Make HUD freshness depend on authoritative state as appropriate.
7. Add payload/queue size limits, heartbeat/idle detection, and useful network error diagnostics.

### P2: optional tracking

Run body-glove tracking under actual fast boxing motion. Keep it only if it remains stable and does not compromise frame rate, heat, visibility, or the core HUD/network path.

## 16. Reference-material provenance

The correct current Group B13 boxing report was found outside the repository at:

```text
C:\Users\zexue\Downloads\B13_CG4002_Initial_Design_Report.pdf
```

It is a 34-page report naming Teh Ze Xue as Software Visualizer owner/Comms secondary and matches this architecture: three ESP32 nodes per player, torso aggregation, Ultra96 classification, laptop-authoritative Game Engine, phone-facing events plus 100 ms state snapshots, and fiducial support.

The tracked file named `Past Reports/B13_CG4002_Initial_Design_Report (1).pdf` is actually a different **Furniture Layout Designer** project with different members. README text implying it is the current B13 report is wrong. Rename/relabel it as historical material, and add the correct report under an unambiguous name only if distribution is permitted.

Other tracked prior-team reports are examples, not authority:

- B01: AR maze game;
- B017: AR magic/spell game.

B017 may have influenced the queue/module separation, and B01 illustrates camera/world/HUD layers, but neither defines the present system.

`Past Reports/pitch.html` is an older `Split Ring` proposal involving separated rooms, a synthetic opponent, continuous phone-to-phone pose streaming, and optional arm-chain purchase. That conflicts with the currently implemented physically visible, chest-marker AprilTag approach and the current message contract. Treat it as design history unless the team explicitly re-adopts it.

Five references listed in `docs/references/README.md` exist only in the ThinkPad Downloads folder and will not transfer through Git: the correct B13 report, `VizPehslides.pdf`, `Comms.pdf`, `CG4002 - Hardware Sensors.pdf`, and `AIPehslides.pdf`.

## 17. Paste this into the first Mac Codex chat

```text
Work in ~/Developer/CG4002-Viz on branch OpponentTracker. Read AGENTS.md and docs/macbook-development-handoff.md completely before changing anything. Use Unity 6000.0.76f1 and open ~/Developer/CG4002-Viz/VisualizerApp. The laptop Game Engine is authoritative; the iPhone only renders GameEvent and MatchState, and network callbacks must enqueue raw messages for main-thread handling. Preserve independent event/state sequence gates and never infer hits from AR/collisions.

First perform a read-only parity check: show git status, HEAD, upstream divergence, Unity editor version, package resolution, and any compile/import errors. Confirm HEAD includes at least commits 8a2d1df, 82f94e3, 8dc47c9 and the handoff commit. Then run contract validation and all Unity edit-mode tests. Try the AprilTag simulation, but be alert that jp.keijiro.apriltag 1.0.3 ships an x86-64 macOS binary while the Mac is Apple silicon. Do not change packages or generated Xcode files without explaining the reason.

The highest-priority known camera-path defect is that Main.unity still serializes AprilTag imageTransformation=MirrorY even though the chat/code review's intended correction is None; this still needs physical confirmation, and the simulation was generated to compensate for MirrorY. Inspect and propose the smallest safe fix, regenerate simulation assets, and verify tests before asking for an iPhone build. Also remember the scene URL ws://192.168.137.1:8889 does not match the mock server's default ws://127.0.0.1:8765, and the teammate comms server is currently raw TCP rather than WebSocket.
```

## 18. Final working rules

- Git, not chat sync or copied Unity caches, is the bridge between machines.
- Pull before starting; commit and push before switching computers.
- Keep scene, prefab, `.meta`, package, source, and project-setting changes in the Unity repository.
- Never copy `Library`, `Temp`, `Logs`, builds, generated Xcode, or DerivedData.
- Keep networking, authoritative state, presentation, and AR tracking separated.
- Validate both schemas/examples whenever the contract changes.
- Use physical iPhone results as evidence for ARKit, signing, camera behaviour, performance, latency, and thermals.
- Keep body tracking optional and the central view usable without it.
- Do not bypass TLS validation or commit credentials.
- When a chat and the checked-in scene disagree, inspect current code/scene and document the reconciliation rather than repeating the chat as fact.

## 19. Post-handoff update: item pickups WP2-WP7 (2026-10-08)

`main` now contains the WP1 pickup contract foundation plus the WP2/WP3 floor and rendering prototype. The detailed Windows procedure is in `docs/item-pickups-wp2-wp3-simulation-guide.md`.

Implemented state:

- `FloorPlaneProvider` selects and locks a suitable upward-facing plane, preferring the `Floor` classification and supporting unclassified XR Simulation planes.
- Pickup polar placement is pure/tested and rejects non-finite values, unsafe radius/bearing, plane-boundary overflow, and insufficient separation.
- Missing floor data keeps an item pending and produces a debounced safe-area prompt; there is no runtime guessed-height fallback.
- `PickupSpawnPresenter` renders only local-player `HEALTH` items, keys visuals by authoritative ID, fixes the initial world pose, and removes items missing from later state.
- `HealthPickup.prefab`, editor-only left/centre/right/clear controls, and an idempotent `ItemPickupPrototypeBuilder` are checked in.
- `HudToastPresenter` independently observes accepted state snapshots and shows one safe-area spawn notice per local-player item ID. Its bounded queue favours recent notices, repeated snapshots are de-duplicated, and timing uses unscaled time.
- `PickupReachPresenter` and the existing camera-relative glove rig provide explicit left/right and automatic pickup reaches. The target is captured in world space, path geometry is clamped above the floor, and per-hand interruption cleanup prevents guard, punch, or disappearing-item cases from leaving a glove displaced or transparent.
- `PickupCollectionPresenter` presents accepted local-player `ITEM_PICKUP/HEALTH` events. It reaches to the retained target, plays the contact/removal effect, and displays the collection toast. Duplicate item IDs are ignored and a short visual-removal grace handles state-before-event ordering.
- The editor-only **COLLECT NEAREST** command uses an adjustable camera-to-item gate with a serialized `2.0 m` default. It emits an accepted event followed by a newer state through the normal client queue. The mock authority clamps health to `100`; only `MatchState` updates client health. Accepted external events are not re-litigated against local AR distance.
- The external Python WebSocket authority now schedules the same pickup lifecycle, sends an immediate convergence snapshot on reconnect, and exposes deterministic timing plus duplicate/stale/burst fault modes. Its ordinary restart sequence base is wall-clock-derived so a still-running client accepts the new process; an explicitly repeated `--sequence-start` remains stale by design.
- The teammate communications prototype is raw TCP with newline-delimited JSON on port `8889`; Unity uses WebSocket framing. They require an explicit WebSocket endpoint or gateway decision and cannot connect directly as-is.
- `XR Origin` was corrected from approximately `(0, 0.86, -9.93)` to the standard zero pose. The old translation put the simulated camera outside the room and contributed to the apparent movement problem.
- The official XR Simulation controls remain: focus Game view, hold right mouse, use WASD, Q/E, and Shift. An editor-only HUD hint now displays them.

Validation at implementation time:

- the setup builder compiled and produced one runtime root when run twice;
- 131/131 Unity Edit Mode tests passed, including the 64-message per-frame drain cap against a 70-message reconnect burst;
- the single-session XR Simulation Play Mode test passed, including production-queue pickup collection, adjustable distance rejection, glove reach/contact, health `60 -> 85`, full-health clamp `90 -> 100`, repeated-collection rejection, both event/state orderings, WP5 interruption/return-to-rest, and disabled-presenter unsubscription;
- 6/6 Python mock-authority tests and the real process-to-client reconnect smoke test passed, with duplicate/stale/70-message burst faults enabled for the latter; and
- real plane acquisition still requires the documented interactive Game-view check, because the command-line runner does not reliably emit simulation planes.

The prototype now implements debug-confirmed and externally scheduled collection, collection VFX/removal, mock-authority expiry, and an authoritative-looking health state update. It does not yet implement real laptop recognition/acknowledgement, attack-damage effects, or physical-iPhone validation. Do not treat the editor-only collection gate or deterministic test floor as production authority/fallback; both are excluded from the gameplay decision.
