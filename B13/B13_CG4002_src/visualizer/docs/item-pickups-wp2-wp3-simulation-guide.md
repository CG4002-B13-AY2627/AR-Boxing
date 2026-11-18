# Item pickups WP2-WP7: Windows simulation guide

This prototype renders a local-player health pickup from authoritative `MatchState.active_items` and presents an accepted `ITEM_PICKUP` event. The local **COLLECT NEAREST** button simulates the future authority for testing, but collection and health are still expressed as production-shaped messages: the event starts presentation and a newer `MatchState` changes health/removes the item. The visualizer does not infer collection from collision.

## What is implemented

- `FloorPlaneProvider` selects one stable upward-facing AR plane. A classified floor is preferred; when classification is unavailable (including XR Simulation), it selects the largest suitable horizontal plane below the camera.
- Placement is rejected unless distance is `0.70-1.25 m`, bearing is `-65 to +65 degrees`, values are finite, the point is inside the detected boundary with a margin, and it is separated from existing items.
- A missing floor leaves the item pending and shows `FLOOR NOT DETECTED - Pause and look down slowly.` It never places the item at a guessed height.
- `PickupSpawnPresenter` keeps one visual per authoritative item ID, filters for the local player and `HEALTH`, fixes the first valid pose in world space, and reconciles visuals against later snapshots. A short removal grace handles state-before-event ordering.
- `HealthPickup.prefab` provides the green health visual, ground marker, and low-cost bob/spin animation.
- `HudToastPresenter` shows one short green `HEALTH PICKUP SPAWNED` notice for each newly observed local-player item ID. Repeated state snapshots are de-duplicated, bursts are bounded, and the fade uses unscaled time so it completes while gameplay is paused.
- `PickupReachPresenter` resolves the nearest rendered pickup and asks the existing camera-relative glove rig to perform a dedicated reach. Explicit left/right and automatic screen-side selection are available.
- The reach follows a curved world-space path, stops above the floor, clamps excessive distances, captures its target position, and returns to the live camera-relative rest pose even if the item disappears. Punches, guard, and reaches share the same per-hand interruption cleanup.
- `PickupCollectionPresenter` listens for accepted local-player `ITEM_PICKUP/HEALTH` events, starts the requested glove reach, plays the contact burst/removal effect, and queues `+25 HEALTH`. It never writes health.
- **COLLECT NEAREST** is editor-only. It rejects a pickup whose contact point is farther than `Maximum Debug Pickup Distance Metres` from the camera; the serialized default is `2.0`. Change that field on `ItemPickupRuntime > PickupCollectionPresenter` to tune the simulation gate.
- An accepted laptop event is never rejected again using the phone's local distance estimate. Production authority must enforce its own collection distance; the visualizer only presents the accepted event.
- Editor-only buttons inject ordinary JSON through `GameNetworkClient`, so the decoder, independent event/state sequence gates, state store, and presenter are all exercised.

## First run after pulling these changes

1. Exit Play Mode.
2. Let Unity finish compiling. If Unity reports that `Main.unity` changed on disk, reload it rather than saving the older in-memory scene over it.
3. Open `Assets/Scenes/Main.unity`.
4. Use the Windows/Standalone build profile. XR Simulation must be enabled for Standalone.
5. The setup is already serialized. If references were lost during a merge, run **CG4002 > Visualizer > Set Up Item Pickup WP2-WP6** once. The command is idempotent.

The scene should contain:

- `ARPlaneManager` and `ARRaycastManager` on `XR Origin`;
- a zero-position, identity-rotation `XR Origin`; and
- one `ItemPickupRuntime` with the floor provider, spawn presenter, floor prompt, toast presenter, pickup-reach presenter, collection presenter, and debug controls.

## Camera movement in XR Simulation

XR Simulation deliberately locks navigation until the right mouse button is held.

1. Enter Play Mode and click inside the **Game** view once to give it keyboard focus.
2. Move the pointer away from the bottom-left pickup buttons.
3. Hold the **right mouse button continuously**.
4. While holding it, use **W/A/S/D** to move, move the mouse to look, **Q/E** to move vertically, and **Shift** to move faster.

The bottom-left panel repeats these controls. The previous scene had `XR Origin` displaced about 10 metres from the simulated room; WP2-WP3 resets it to the standard zero pose, which removes the apparent no-movement/empty-environment problem.

## Interactive acceptance check

1. Enter Play Mode and confirm the AprilTag simulation environment is visible.
2. Click **HEALTH CENTRE** before a floor is ready. No pickup may float; the amber floor prompt should appear.
3. Confirm one green `HEALTH PICKUP SPAWNED` toast appears near the upper-left safe-area edge. The centre view must remain clear.
4. Focus the Game view, hold right mouse, and look down slowly while moving a short distance. The prompt should clear after a stable horizontal plane is acquired, and the pending health pickup should appear on the floor.
5. Walk sideways. The pickup must remain fixed in world space rather than following the camera.
6. Click **HEALTH CENTRE** again. It replays the same ID and must not create a duplicate visual or notification.
7. Click **HEALTH LEFT**, **HEALTH CENTRE**, and **HEALTH RIGHT** individually. Each new ID should show one queued toast, replace the prior debug item, and place it inside the configured forward safe area.
8. With a pickup visible, click **REACH LEFT**, **REACH RIGHT**, and **REACH AUTO**. The selected glove should curve down to the health pack, stop above the floor, and return exactly to its normal camera-relative position. Automatic reach should use the glove on the pickup's screen side.
9. Start a reach and immediately click the matching jab button. Then trigger guard followed by a reach. The glove must return normally and must not remain displaced or transparent.
10. Start a reach and click **CLEAR ITEMS** before contact. The item should disappear, while the captured reach finishes and returns safely. No health value should change.
11. Spawn a fresh item and click **COLLECT NEAREST**. The screen-side glove should reach toward it, the item should burst/shrink away at contact, a `+25 HEALTH` toast should queue, and the HUD health should change only when the following state is processed.
12. Click **COLLECT NEAREST** again. It should show a controlled rejection and must not add health again.
13. On `ItemPickupRuntime > PickupCollectionPresenter`, temporarily set **Maximum Debug Pickup Distance Metres** below the current camera-to-item distance (for example `0.5`). Collection must be rejected and the item/health must remain unchanged. Restore it to `2.0` and retry successfully.
14. While a toast or reach is visible, set **Time Scale** to `0` in the editor. Both must still complete because momentary presentation uses unscaled time.
15. Resize the Game view between a tall phone aspect and landscape. The toast must remain within the safe area and must not cover the central target region.
16. While no floor is available, verify the centre of the camera remains clear and the error message appears only after a pickup needs placement.

If movement still appears stuck, verify that the Game view—not Scene or Inspector—has focus and that right mouse remains held while pressing movement keys. Stop and re-enter Play Mode after switching build profiles or XR providers.

## What automated tests prove

- Edit Mode covers placement conversion, flattened camera heading, finite/radius/bearing rejection, boundary margin, owner filtering, item cap, pending placement, fixed pose, toast filtering/de-duplication, queue order/cap, pickup hand selection, curved path endpoints, standoff, reach clamp, floor clearance, interruption cleanup, timing, adjustable collection range, duplicate accepted events, missing visuals, and proof that a pickup event does not write authoritative health.
- Play Mode loads the real Main scene, confirms AprilTag ID 0, exercises the production queue/decoder/store/presenter path, validates the adjustable range rejection, event-before-state collection, health `60 -> 85`, full-health clamping `90 -> 100`, removal, repeated-collection rejection, and delayed event after removal state. It also retains the WP2-WP5 spawn, toast, reach, interruption, unscaled-time, and unsubscription checks.
- The Play Mode command-line runner uses an editor-only deterministic floor because it has no interactive Game view and does not reliably return XR Simulation plane discoveries. This hook is not compiled into iOS and is not a runtime floor fallback.

Interactive Windows testing is evidence for prototype behavior only. A physical iPhone remains required to validate ARKit plane acquisition, scale, tracking stability, performance, thermal behavior, and safe real-world placement.

For the separate-process WebSocket lifecycle and reconnect procedure, continue with `docs/item-pickups-wp7-mock-server-guide.md`.
