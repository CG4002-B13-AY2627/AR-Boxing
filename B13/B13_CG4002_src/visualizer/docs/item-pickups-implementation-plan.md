# Item pickups implementation plan

## Goal

Add floor-anchored health and attack-damage pickups to the AR visualizer. A pickup should:

- appear on a detected floor in a small, safe area in front of the local player;
- produce a short HUD notification when it first appears;
- remain visible across ordinary state updates;
- play a dedicated local-glove reach animation when the laptop confirms collection; and
- disappear without the phone deciding health, damage, or whether collection succeeded.

The production game-state authority is intentionally left undecided for this prototype. A local debug source and the Python mock server will temporarily act as the authority by emitting the same accepted item events and state snapshots that a future laptop or Ultra96 game engine would emit. The visualizer remains receive-only: Unity colliders may help with presentation or debugging, but they must not apply health, attack bonuses, or collection state directly.

## Recommended player experience

1. During calibration, the phone finds a horizontal floor and establishes one stable arena/floor origin.
2. A `MatchState` snapshot contains a new active pickup for the local player.
3. The visualizer chooses a valid point on the detected floor using the server-provided distance and bearing, creates the matching pickup prefab, and briefly shows a message such as `HEALTH PICKUP SPAWNED - FRONT LEFT`.
4. The prototype debug control or mock server confirms collection and emits an `ITEM_PICKUP` `GameEvent`.
5. The visualizer aims the requested local glove at the displayed pickup, plays a short reach-and-return animation, then fades the pickup out.
6. A subsequent `MatchState` omits the collected item and contains the authoritative health or attack-effect state. If the transient event was missed, the snapshot still removes the pickup and corrects the HUD.

```text
Prototype authority source -> MatchState.active_items
             |
             v
MatchController / MatchStateStore
        |                    |
        v                    v
PickupSpawnPresenter     HudToastPresenter
        |
        v
floor-anchored prefab
        ^
        |
ITEM_PICKUP GameEvent -> pickup reach animation + collection VFX
```

## Important decisions before coding

The following defaults are recommended for the first version. Confirm them with the game-engine and communications owners before changing the contract.

1. **Collection authority:** the prototype uses engine-recognised or debug-triggered collection. A local debug source and mock server simulate accepted collection; the iPhone never sends a local collider hit as proof of collection. The production authority can later move to the laptop or Ultra96 without changing the presentation components.
2. **Who sees an item:** each pickup has an `owner_player`; a phone renders pickups owned by its configured `localPlayerId` only. This avoids clutter and lets each player have a separate local floor frame.
3. **Placement meaning:** the laptop supplies a distance and bearing, but Unity resolves them against the player's floor-projected camera pose when that item is first seen. The object then stays world-anchored and is not kept at a fixed distance from the moving camera.
4. **Safe first-version area:** use a configurable annulus of approximately `0.70-1.25 m`, limited to a forward cone of approximately `-65 to +65 degrees`. Final values must be checked in the actual play area.
5. **No-floor fallback:** show the spawn notification and keep the item pending; do not place it at an invented height. Create it when a stable floor becomes available. Expired or already-collected pending items are discarded.
6. **Attack effect:** the eventual game engine owns the multiplier and duration. The client may display them but never uses them to calculate punch damage. The first working prototype implements health only; attack boost follows after the vertical slice is accepted.
7. **Physical movement:** the first version should make items look reachable but should not require the user to walk to, crouch over, or physically collide with them while wearing the phone/headset.

## Prototype delivery work packages

Each work package is intended to be requested, implemented, reviewed, and validated separately. Ask for them in order because later packages depend on the earlier ones. Work package 6 is the first complete working prototype; packages 7-8 prove integration and device behaviour.

### Work package 1: authority-neutral item data and debug messages

**Implementation status:** complete in the current working tree; automated validation passes. Unity-editor review by the project owner remains.

**Request to give Codex:** `Implement item-pickup work package 1 from docs/item-pickups-implementation-plan.md.`

**Outcome:** the normal decoder and match-state path understand one player-specific health pickup, but nothing is rendered yet.

Implementation:

- Extend `MatchState` with an optional, bounded `active_items` array.
- Extend `ITEM_PICKUP` with `item_id`, `item_type`, and optional `hand`.
- Implement health only. Keep `ATTACK_BOOST` reserved/documented but do not implement its gameplay effect yet.
- Add one development/debug source that can inject a state containing a health pickup, an accepted pickup event, and a later state with updated health. It must pass through `GameNetworkClient` and `MessageDecoder`, rather than calling presentation code directly.
- Keep the debug source disabled by default in `Main.unity`.
- Update schemas, examples, `tools/validate_contracts.py`, decoder/state tests, protocol documentation, and the communications change note together.

Codex validation:

- run every JSON example through its schema;
- run Unity edit-mode decoder and state-store tests;
- prove invalid types, duplicate IDs, excessive item counts, invalid owners, non-finite values, stale states, and duplicate events are rejected or ignored as designed; and
- run all existing edit-mode tests to catch protocol regressions.

Your validation:

1. Open `VisualizerApp` in Unity `6000.0.76f1` and allow compilation to finish.
2. Confirm there are no Console errors.
3. Open **Window > General > Test Runner > EditMode** and run all tests.
4. Inspect the example messages in `contracts/examples/` and confirm the field names and health-item semantics match the team vocabulary.
5. At this stage, expect no pickup to appear in the Game view.

Acceptance gate: schemas and all edit-mode tests pass, and the item message vocabulary is approved before any scene/prefab work relies on it.

### Work package 2: floor acquisition and the look-at-floor prompt

**Request to give Codex:** `Implement item-pickup work package 2 from docs/item-pickups-implementation-plan.md.`

**Outcome:** the app can establish one stable horizontal floor pose and clearly reports when it cannot.

Implementation:

- Add a focused `FloorPlaneProvider` under `Assets/Scripts/AR/`.
- Add/configure `ARPlaneManager`, `ARRaycastManager`, and, if stable in AR Foundation 6.0.6, one `ARAnchorManager`-managed arena origin on `XR Origin`.
- Prefer a classified floor, with a documented horizontal-plane fallback when classification is unavailable.
- Expose floor readiness and a pure placement method that converts distance/bearing to a candidate floor pose.
- Add a debounced, safe-area-aware message: `Floor not detected - pause and look down slowly.`
- Show the instruction only when placement is needed. Do not spam it every frame or every snapshot.
- Provide an idempotent editor setup command instead of hand-editing scene YAML.

Codex validation:

- add edit-mode tests for polar conversion, flattened camera heading, radius/bearing rejection, and finite-value checks;
- validate that the editor builder can be run twice without duplicate managers or objects;
- compile the Unity project and run all edit-mode tests; and
- use XR Simulation where possible to verify readiness changes and a stable origin.

Your validation on Windows:

1. Run the setup command that Codex documents.
2. Switch to the Windows build profile and enter Play Mode with XR Simulation.
3. Confirm the prompt is visible before a usable floor is available.
4. Aim the simulated camera at the floor and confirm the prompt clears once.
5. Move/rotate the simulated camera and confirm the accepted origin does not jump between planes.

Your later iPhone validation:

1. Begin while looking mostly forward: the prompt should appear.
2. While paused and standing still, look down slowly: the prompt should clear when the floor is found.
3. Test bright, dim, and low-texture flooring and record failures rather than treating simulation as proof.

Acceptance gate: floor readiness is stable, the error message is readable but not repetitive, and no item placement is attempted without a valid floor.

### Work package 3: render one health pickup in the safe spawn area

**Request to give Codex:** `Implement item-pickup work package 3 from docs/item-pickups-implementation-plan.md.`

**Outcome:** a debug state renders a health pickup on the floor for the local player.

Implementation:

- Create a simple `HealthPickup` prefab with a distinct shape/icon, ground marker, subtle bob/spin, and inexpensive material.
- Add `PickupSpawnPresenter` with a dictionary keyed by authoritative item ID.
- Render only items whose `owner_player` matches `localPlayerId`.
- Interpret server/debug distance and bearing relative to the floor-projected camera pose when the ID is first observed, then keep the resulting world pose fixed.
- Enforce an inspector-configurable annulus, initially `0.70-1.25 m`, and a forward cone, initially `-65 to +65 degrees`.
- Verify plane/boundary containment and minimum item separation. Keep invalid placements pending rather than floating them.
- Add development buttons/inspector actions for `Spawn Health Left`, `Spawn Health Centre`, `Spawn Health Right`, and `Clear Items`.

Codex validation:

- test owner filtering, repeated-state deduplication, fixed pose retention, radius/cone constraints, pending placement, item removal, and item-count caps;
- verify repeated snapshots do not instantiate duplicates;
- run the existing Unity test suite; and
- inspect the scene/prefab references after the idempotent builder runs.

Your validation:

1. Detect the simulated floor, then trigger left, centre, and right health spawns individually.
2. Confirm each object sits on the floor between approximately `0.70` and `1.25 m` from the spawn-time camera projection.
3. Walk the simulated camera sideways: the item must stay anchored instead of following the camera.
4. Trigger the same item ID repeatedly: only one visual should exist.
5. Change the test item owner to the other player: it must not render.
6. Lose the floor before spawning: no object should float; the floor prompt should appear.

Acceptance gate: one stable, readable health item can be placed safely from normal state data without duplication.

### Work package 4: momentary spawn notification

**Request to give Codex:** `Implement item-pickup work package 4 from docs/item-pickups-implementation-plan.md.`

**Outcome:** a newly observed pickup produces one short HUD notification.

Implementation:

- Add a separate `HudToastPresenter`; do not overload the persistent/network HUD update loop.
- Show an icon plus `HEALTH PICKUP SPAWNED` near the safe-area edge without covering the centre view.
- Use a short unscaled-time fade/hold/fade sequence.
- Deduplicate by item ID and cap the queue.
- Do not repeat the spawn toast for every `MatchState` snapshot.
- Keep the floor error prompt visually distinct from ordinary pickup notifications.

Codex validation:

- test notification deduplication, queue cap, ordering, and completion while time scale is zero;
- verify event subscriptions are removed in `OnDisable`; and
- run all edit-mode tests and a play-mode timing check where practical.

Your validation:

1. Spawn one item and confirm exactly one notification appears.
2. Let the debug source repeat the same state for several seconds; confirm there are no repeated notifications.
3. Spawn several new IDs quickly and confirm the queue remains readable.
4. Pause the match/time scale during a notification and confirm it still disappears.
5. Check portrait/landscape orientation used by the prototype and confirm the banner remains inside the iOS safe area.

Acceptance gate: the notification is momentary, deduplicated, readable, and does not obscure the opponent or connection status.

### Work package 5: dedicated pickup glove reach animation

**Request to give Codex:** `Implement item-pickup work package 5 from docs/item-pickups-implementation-plan.md.`

**Outcome:** either local glove can visibly reach toward an existing pickup and return to rest, without collecting it yet.

Implementation:

- Add a pickup-specific targeted motion to `CameraRelativeGloveRig` or a tightly coupled presentation helper.
- Use a tested curved path from the selected glove rest pose toward a safe contact pose above the item.
- Stop short of the floor and clamp excessive target distances.
- Support explicit left/right hand and automatic nearest-screen-side selection.
- Follow the rig's existing interruption rules so guard, punch, and pickup do not leave a hand displaced or transparent.
- Add debug controls for left reach, right reach, and automatic reach. These controls animate only; they do not award health or remove the item.

Codex validation:

- add pure edit-mode tests for hand selection, path endpoints, standoff, distance clamping, and return-to-rest;
- run all existing punch, uppercut, hook, targeting, and guard tests;
- add interruption tests for guard-to-pickup and pickup-to-punch; and
- use Play Mode to verify the coroutine completes when the target disappears mid-motion.

Your validation:

1. Spawn pickups on the left and right and test explicit and automatic hands.
2. Confirm the glove approaches the item, does not pass through the floor, and returns to exactly its normal rest pose.
3. Trigger guard, then pickup; trigger pickup, then jab. Neither glove should remain displaced or semi-transparent.
4. Clear the item during the reach and confirm the glove returns safely.
5. Confirm existing punch buttons and AprilTag-targeted punches still behave normally.

Acceptance gate: the new motion is readable and robust without changing item or health state.

### Work package 6: debug-confirmed collection and health effect

**Request to give Codex:** `Implement item-pickup work package 6 from docs/item-pickups-implementation-plan.md.`

**Outcome:** this is the first complete working prototype: spawn, notification, reach, collection effect, item removal, and authoritative-looking health update.

Implementation:

- Add a debug action `Collect Nearest Health` that makes the debug authority source emit an accepted `ITEM_PICKUP` event followed by a newer `MatchState` with the item removed and health increased.
- Gate only that local debug action by an adjustable camera-to-item distance, defaulting to `2.0 m`. The future authoritative engine must enforce its own equivalent rule; never discard an already accepted network event using a second client-side distance decision.
- Route both messages through the normal queue, decoder, sequence checks, store, and presenter.
- Trigger the reach animation from the accepted event, retain the item target until contact, then play a burst/fade and remove it.
- Update health only from the later `MatchState`; clamp in the debug authority to `100`.
- Show a short `+25 HEALTH` collection message, clearly treated as presentation of accepted state rather than a local calculation.
- Make repeated collection of the same ID idempotent.
- Resolve event/state races: the target visual survives long enough to finish the reach even if the removal snapshot is processed in the same frame.

Codex validation:

- add an integration test for the full message sequence;
- test full-health collection, duplicate events, stale removal state, state-before-event ordering, event-before-state ordering, and missing target visual;
- prove that the collider/debug visual itself never writes `MatchSnapshot` health; and
- run all contract, edit-mode, and relevant play-mode tests.

Your validation:

1. Set the debug player health to `60` and spawn one health item.
2. Trigger `Collect Nearest Health` and observe, in order: reach, contact VFX, item fade/removal, `+25 HEALTH`, and HUD health becoming `85`.
3. Trigger collection again for the same ID; health must remain `85`.
4. Repeat from `90`; health must finish at `100`, not `115`.
5. Spawn without a floor and try collection; it should fail safely or produce a controlled debug rejection, never invisible health gain.
6. Test collection while paused and during another glove motion.

Acceptance gate: the entire prototype works through production-shaped messages with no phone-originated gameplay mutation.

### Work package 7: external mock server and reconnect behaviour

**Request to give Codex:** `Implement item-pickup work package 7 from docs/item-pickups-implementation-plan.md.`

**Outcome:** the same prototype works from a separate process rather than only from in-app debug controls.

Implementation:

- Extend `tools/mock_server.py` to schedule health spawn, accepted pickup, item removal, and health update.
- Add deterministic seed/timing options.
- Keep the current WebSocket development path; do not decide the production laptop-versus-Ultra96 authority in this package.
- Confirm reconnect convergence from `MatchState`, including active item recreation and already-collected item absence.
- Document the existing difference between the visualizer WebSocket transport and the communications repository's raw TCP prototype as a separate integration decision.

Codex validation:

- run schema validation and the Python smoke test;
- exercise mock-server connection, disconnect, restart, duplicate messages, stale messages, and burst delivery;
- confirm Unity's per-frame queue cap remains effective; and
- record any test that still requires a human-operated Unity editor or phone.

Your validation:

1. Start the documented mock-server command on Windows.
2. Disable the in-app debug authority and connect `Main.unity` through the normal network client.
3. Confirm the same spawn-to-collection sequence works.
4. Disconnect after spawn and reconnect before collection: the item should return from state.
5. Disconnect across collection and reconnect: the item should be absent and health should be correct.
6. Confirm the visible connection/reconnecting indicator remains usable throughout.

Acceptance gate: the prototype survives reconnects and does not depend on direct presentation calls from the debug UI.

### Work package 8: physical-iPhone acceptance pass

**Request to give Codex:** `Prepare and document item-pickup work package 8 from docs/item-pickups-implementation-plan.md.`

**Outcome:** the prototype is assessed on the real target device, with limitations recorded rather than inferred from Windows simulation.

Codex preparation and validation:

- produce a concise device checklist and results template;
- verify the project remains pinned to Unity `6000.0.76f1`;
- verify no generated Xcode project, `Library`, `Temp`, `Logs`, `Builds`, or `DerivedData` is staged; and
- review the supplied measurements/screenshots/logs and fix reproducible Unity-side issues in a follow-up task.

Your validation on the Mac/iPhone:

1. Pull the same Git revision on the Mac and open it in Unity `6000.0.76f1`.
2. Build/sign through Xcode and deploy to the physical iPhone.
3. Record iPhone model and iOS version.
4. Run floor acquisition and pickup placement on bright, dim, glossy, and low-texture floors.
5. Confirm the item remains anchored during head translation and rotation.
6. Confirm the spawn toast, floor error, health HUD, and reconnect indicator remain readable.
7. Exercise pickup reach with both hands and confirm it never encourages stepping beyond the visible boundary.
8. Record FPS, thermal state, obvious jitter/drift, and event-receipt-to-first-render latency where measurable.
9. Capture a short video of one successful end-to-end collection and one no-floor recovery.

Acceptance gate: a physical-device result is recorded, critical safety/UI failures are fixed, and simulation-only assumptions are labelled as such.

## Proposed authority-neutral contract extension

Do not add a third message type. Keep the existing roles:

- `MatchState` is the recoverable source of active pickups and active attack effects.
- `GameEvent` remains the transient cue for the collection animation.

Add an optional `active_items` array to `MatchState` during integration. Treat a missing array as empty for backward compatibility. Each active item should contain:

```json
{
  "id": "item-0042",
  "item_type": "HEALTH",
  "owner_player": 1,
  "distance_m": 1.0,
  "bearing_degrees": -25.0,
  "magnitude": 25.0,
  "remaining_ms": 8000
}
```

Recommended validation:

- `id`: non-empty, bounded length, unique within a snapshot;
- `item_type`: initially `HEALTH` or `ATTACK_BOOST`;
- `owner_player`: `1` or `2`;
- `distance_m`: finite and within the agreed protocol bounds, proposed `0.5-2.0`;
- `bearing_degrees`: finite and within `-90 to +90` for the first version;
- `magnitude`: finite, non-negative, and capped by an agreed gameplay maximum;
- `remaining_ms`: integer from `0` to an agreed maximum lifetime; and
- `active_items`: capped, proposed maximum eight, so an untrusted payload cannot create unlimited objects.

Extend an `ITEM_PICKUP` `GameEvent` with `item_id`, `item_type`, and optional `hand` (`LEFT` or `RIGHT`). `source_player` is the collecting player. If `hand` is absent, Unity chooses the hand whose rest position is closest on screen. Health and attack values still come from the following `MatchState`, not from locally applying `magnitude`. These semantics do not depend on whether the eventual sender runs on the laptop or Ultra96.

For an attack boost, add authoritative display state to each player snapshot, for example `attack_multiplier` and `attack_boost_remaining_ms`. Missing fields should temporarily decode as `1.0` and `0` while the senders are upgraded.

Because this changes the contract, the implementation must update all of the following in the same change:

- `contracts/game-event.schema.json` and `contracts/match-state.schema.json`;
- existing examples plus item-spawn-state and item-pickup examples;
- `VisualizerApp/Assets/Scripts/Models/GameMessages.cs`;
- decoder and state-store tests;
- `tools/mock_server.py` and `tools/validate_contracts.py`;
- `docs/protocol.md`; and
- a communications owner-facing change note, proposed as `docs/communications-item-pickups-change-note.md`.

## Executable implementation steps

### Step 1: agree the gameplay and wire contract

**Purpose:** prevent the phone and laptop from implementing different meanings for item position, ownership, lifetime, and collection.

Work:

- Confirm the defaults in “Important decisions before coding.”
- Add the proposed fields and conditional JSON Schema rules. Item fields should be required when `event` is `ITEM_PICKUP` and rejected when malformed.
- Add separate valid examples for a state containing active items and an item-pickup event. Keep a punch example too.
- Change `tools/validate_contracts.py` so every checked-in example is validated, rather than maintaining only one fixed example per schema.
- Write the concise communications change note with field meanings and example payloads.

Done when:

- every JSON example passes `tools/validate_contracts.py`;
- old payloads without `active_items` still decode during integration; and
- both owners agree that the eventual engine, wherever it runs, owns collection and effects while the visualizer remains a receiver/presenter.

### Step 2: add typed item data and snapshot reconciliation

**Purpose:** make item state recoverable after packet loss or reconnects.

Files:

- `VisualizerApp/Assets/Scripts/Models/GameMessages.cs`
- `VisualizerApp/Assets/Scripts/Game/MatchStateStore.cs`
- `VisualizerApp/Assets/Scripts/Game/MatchController.cs`
- `VisualizerApp/Assets/Tests/EditMode/MessageDecoderTests.cs`

Work:

- Add serializable item-state fields/arrays and the pickup-event fields.
- Validate IDs, enum-like strings, finite numeric ranges, array size, and duplicate IDs before accepting a message.
- Copy the accepted active-item set into `MatchSnapshot`; do not store Unity `GameObject` or `Transform` references in game state.
- Preserve the existing independent event and snapshot sequence filters.
- Continue emitting `StateChanged` for a new snapshot and `GameEventReceived` for accepted pickup events. Presentation components will subscribe to these on the Unity main thread.

Done when edit-mode tests prove:

- a valid pickup state and pickup event decode;
- unknown item types, duplicate IDs, invalid players, non-finite values, excessive distances, and oversized arrays are rejected;
- an older snapshot cannot resurrect a removed item; and
- a newer snapshot restores the full active-item set after a missed event.

### Step 3: build one stable floor/arena provider

**Purpose:** give all world-space features a single, dependable placement frame rather than letting each pickup query AR independently.

New component proposed:

- `VisualizerApp/Assets/Scripts/AR/FloorPlaneProvider.cs`

Scene work on `XR Origin`:

- add `ARPlaneManager`, requesting horizontal planes only;
- add `ARRaycastManager` for floor hit testing;
- optionally add `ARAnchorManager` and attach one arena origin after a suitable floor has stabilised; and
- keep plane meshes hidden in the normal game, with an optional development visualisation.

Selection policy:

- prefer a plane classified as floor when the provider supplies classification;
- otherwise choose a horizontal-up plane below the camera with sufficient area;
- wait for a short stability period before locking the arena origin;
- do not jump the origin between planes after it has been accepted; and
- expose `IsReady` and a method such as `TryResolveFloorPose(distance, bearing, out Pose)`.

Placement policy:

- project the camera position onto the chosen floor;
- flatten the camera forward direction onto the floor so head tilt does not change the bearing;
- generate the requested polar point, then verify it is on/within the detected plane and inside the configured arena boundary;
- enforce minimum/maximum radius, forward cone, minimum item separation, and a small height offset above the plane; and
- search nearby candidate angles toward the player if the requested point is just outside the plane. If no safe point exists, return false and leave the item pending.

Done when XR Simulation can establish one floor origin and produce repeatable poses inside the configured radius without visible repositioning every frame.

### Step 4: create data-driven pickup prefabs

**Purpose:** keep item appearance separate from spawn/state logic.

Assets proposed:

- `Assets/Prefabs/Pickups/HealthPickup.prefab`
- `Assets/Prefabs/Pickups/AttackBoostPickup.prefab`
- `Assets/Scripts/Presentation/Pickups/PickupVisual.cs`
- a small `PickupVisualDefinition` configuration, either serializable in the presenter or as ScriptableObject assets if designers need to add more item types later.

Each prefab should have:

- a low-cost mesh and material with distinct shape as well as colour;
- a ground ring or soft marker so its floor location is readable;
- a subtle bob/spin animation using unscaled or normal time as agreed;
- a collection burst/fade that can finish even after the authoritative state removes the item; and
- an optional trigger collider marked presentation/debug only.

Use green plus a cross/heart silhouette for health and orange plus a fist/bolt silhouette for attack. Do not rely on colour alone.

Done when both prefabs are legible against camera passthrough, cast no distracting large shadow, and remain inexpensive on the target iPhone.

### Step 5: reconcile snapshots into spawned visuals

**Purpose:** create, retain, and remove visuals by authoritative item ID.

New component proposed:

- `Assets/Scripts/Presentation/Pickups/PickupSpawnPresenter.cs`

Work:

- subscribe to `MatchController.StateChanged` in `OnEnable` and unsubscribe in `OnDisable`;
- keep a dictionary keyed by item ID for presentation objects only;
- filter to `localPlayerId`;
- create newly observed IDs through `FloorPlaneProvider`, or keep them in a bounded pending list until a floor exists;
- retain an existing object's world pose when the same ID appears in later snapshots;
- remove IDs absent from a newer snapshot, using a short fade;
- discard items whose authoritative lifetime reaches zero; and
- avoid instantiate/destroy churn. With at most eight items, a tiny per-type pool is sufficient but can be deferred until profiling shows it helps.

Race handling:

- when an `ITEM_PICKUP` event arrives, mark that visual as collecting and keep its target transform alive until the glove reach finishes;
- if the next snapshot removes it during the animation, finish the animation/fade rather than destroying immediately;
- if the event is missed, the next snapshot still fades the stale visual; and
- if the event references an unknown ID, play a generic pickup gesture/notification but do not invent an item effect.

Done when reconnecting while an item is active recreates it from a fresh snapshot, and reconnecting after collection does not resurrect it.

### Step 6: add the momentary HUD notification

**Purpose:** announce a spawn without blocking the centre of the camera view.

New component proposed:

- `Assets/Scripts/UI/HudToastPresenter.cs`

Work:

- let `PickupSpawnPresenter` publish an `ItemFirstObserved` presentation event after it accepts a new item ID;
- show a compact icon-plus-text banner near an edge of the safe area, preferably immediately below the existing top-centre round panel;
- use a `CanvasGroup` and coroutine for approximately `0.15 s` fade-in, `1.2 s` hold, and `0.25 s` fade-out;
- use `Time.unscaledDeltaTime` so the message completes even if the match is paused;
- queue a small number of messages, deduplicate by item ID, and cap the queue so a burst cannot cover the screen; and
- provide an inspector/debug method that previews health and attack messages without a server.

Do not put notification timing into `HudPresenter.Update`; keep the existing network/match HUD focused on persistent state.

Done when repeated snapshots do not repeat the toast, a reconnect can announce genuinely new IDs once, and the banner does not cover the opponent or connection indicator.

### Step 7: add a dedicated pickup glove animation

**Purpose:** make collection readable while preserving the existing punch, uppercut, hook, and guard motions.

Recommended approach:

- extend `CameraRelativeGloveRig` with a `PickupReach` motion and a public method such as `PlayPickupReach(Transform target, PickupHand hand, Action onContact)`;
- keep the existing camera-relative rest pose, but calculate a world-space quadratic Bezier from the selected glove's rest point toward a point just above the pickup;
- move down/forward, briefly close/tilt the glove over the item, invoke the presentation-only contact callback, and return to rest;
- clamp target distance and stop short of the floor so the glove cannot clip deeply through it;
- cancel or serialise conflicting motions using the rig's existing per-hand coroutine rules; and
- factor pure path/hand-selection maths into `PickupReachPath.cs` so it can be edit-mode tested without a scene.

Trigger it only from an accepted `ITEM_PICKUP` event emitted by the debug/mock authority or eventual game engine. The collider must not call it as authoritative collection. If `hand` is missing, select left/right from the target's viewport side.

Done when both hands can collect left/right items, interrupted animations return cleanly to rest, losing the target uses a safe return path, and existing guard/punch tests still pass.

### Step 8: update the mock server for a full lifecycle

**Purpose:** test the same path the integrated laptop will use.

Work in `tools/mock_server.py`:

- add one health and one attack item on a deterministic schedule;
- include all active items in every state snapshot;
- emit `ITEM_PICKUP` before removing the item from the next snapshot;
- increase health or set the authoritative attack multiplier in server state;
- expire an uncollected item; and
- add command-line timing/seed options if useful for repeatable tests.

Do not make the Unity development source bypass the decoder. If `MockGameEventSource` is retained, update it only as a small no-server convenience and keep it disabled in `Main.unity` for live networking.

Done when the visual sequence is: spawn toast, floor item, pickup reach/fade, then converged HUD/state.

### Step 9: wire the scene through a repeatable editor builder

**Purpose:** avoid fragile hand-edited scene YAML and make setup repeatable in another scene.

Add an editor menu command such as:

- `CG4002 > Visualizer > Set Up Item Pickup Prototype`

The builder should idempotently:

- add/configure the floor managers on `XR Origin`;
- create `PickupRuntime` with `FloorPlaneProvider` and `PickupSpawnPresenter`;
- connect `MatchController`, camera, glove rig, and the two prefabs;
- add/wire `HudToastPresenter` to the current runtime HUD setup; and
- mark the scene dirty without duplicating objects on a second run.

Run it against `Assets/Scenes/Main.unity`, inspect the serialized references in Unity, and save the scene and all `.meta` files.

Done when running the command twice produces the same hierarchy and no duplicate managers, canvases, or event subscriptions.

### Step 10: verify in layers

Automated checks:

- JSON Schema validation for every example;
- Unity edit-mode tests for decoder validation, snapshot reconciliation, polar placement, safe clamping, hand selection, and animation paths;
- existing punch/guard/targeting tests remain green; and
- a play-mode XR Simulation test proves a horizontal plane can host a pickup and that a pickup event completes the visual lifecycle.

Network checks:

- run the mock server and connect through the normal WebSocket queue;
- disconnect after spawn and reconnect before collection: the item returns from `MatchState`;
- disconnect across collection and reconnect: the item is absent and health/attack state is correct;
- inject stale/duplicate events and snapshots: no duplicate toast, object, or animation; and
- burst several valid and invalid item records without exceeding the per-frame message cap or object cap.

Physical iPhone checks:

- test on the exact Unity editor version in `ProjectVersion.txt` (`6000.0.76f1`);
- record iPhone model, iOS version, FPS, thermal state, and event-receipt-to-first-render latency;
- test floor detection in bright/dim light, low-texture flooring, fast head motion, and partial plane visibility;
- verify pickups stay floor-anchored and within the visible safe boundary;
- verify the HUD and network/reconnecting indicator remain visible;
- verify pause/stop remains obvious and no item encourages movement beyond the safe area; and
- repeat after an AR tracking reset or relocalisation.

## Suggested implementation slices

To keep each change reviewable:

1. **Contract and pure state:** Step 1-2, with schemas/examples/tests and no scene change.
2. **Floor and item visuals:** Step 3-5, initially driven by a debug snapshot.
3. **HUD and glove collection:** Step 6-7, including interruption tests.
4. **Integration and device proof:** Step 8-10, including the mock server, builder, scene, reconnect test, and iPhone measurements.

## Unity concepts used here

- **GameObject and Component:** a GameObject is a scene object; components such as `ARPlaneManager`, `PickupSpawnPresenter`, and renderers give it behaviour. Prefer several focused components over one large pickup script.
- **Prefab:** a saved reusable GameObject hierarchy. Each pickup type should be a prefab so appearance can change without changing spawn logic.
- **Transform and coordinate spaces:** screen-space HUD follows the display; camera-relative gloves follow the camera; world-space pickups stay at a floor pose. Mixing these spaces is the main source of AR placement bugs.
- **AR plane:** AR Foundation's evolving estimate of a real flat surface. A detected plane is not a physics floor and may resize or merge, so placement needs validation and a stable origin.
- **AR anchor/origin:** a tracked pose used to keep virtual content stable in the physical world. One arena origin should be shared by boundary and pickup presentation.
- **Raycast:** a query from a screen/world ray into AR trackables. Here it helps confirm a floor location; it does not prove that a gameplay pickup was collected.
- **Collider and trigger:** physics volumes that can report overlap. They are useful for debug or visual proximity, but must not award health/damage in this architecture.
- **MonoBehaviour lifecycle:** `OnEnable`/`OnDisable` are the right places to subscribe/unsubscribe to controller events. `Update` runs every frame; avoid doing scene searches, allocations, or network parsing there.
- **Coroutine and AnimationCurve:** a coroutine spreads an animation across frames; an AnimationCurve shapes reach and return motion. Use unscaled time for momentary HUD messages that should finish during pause.
- **ScriptableObject:** an asset containing reusable configuration. It is useful for a growing item catalogue, but two initial types can stay as serialized prefab definitions if the extra abstraction is not yet needed.
- **Edit Mode versus Play Mode tests:** edit-mode tests suit pure validation and geometry maths; play-mode tests cover components, coroutines, prefabs, and XR Simulation. Neither replaces testing ARKit floor stability on a physical iPhone.

## Main risks and mitigations

- **No reliable floor:** keep items pending and retain a HUD cue; never float them at an arbitrary height.
- **AR drift or plane refinement:** lock a single arena origin after stability, do not continuously re-place active items.
- **Missed transient event:** reconcile all active items and effects from `MatchState`.
- **Snapshot/event race:** retain a collecting visual until its animation finishes, even if state removes the ID in the same frame.
- **Duplicate messages:** keep the current independent sequence filters and also deduplicate spawn notifications by item ID.
- **Conflicting glove motions:** use the rig's per-hand cancellation/return-to-rest rules and test guard/pickup interruption both ways.
- **Unsafe movement:** keep items in a tested forward annulus and inside the visible boundary; gameplay collection comes from the laptop, not physical collision.
- **Camera-view clutter:** cap active item count, keep meshes near the floor, and make the notification short and edge-aligned.
