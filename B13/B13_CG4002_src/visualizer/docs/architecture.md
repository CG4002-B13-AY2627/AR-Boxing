# Visualizer architecture

## System boundary

The end-to-end path is:

```text
Wearable IMUs -> torso ESP32 -> laptop relay -> Ultra96 inference
                                      |
                                      v
                           authoritative game engine
                                      |
                                  WebSocket
                               /             \
                         iPhone P1        iPhone P2
```

The Ultra96 returns classification fields such as player, punch, confidence, and intensity. The laptop combines these with game rules and range information, updates the match, and broadcasts to both phones. Each visualizer is a presentation client.

## Runtime modules

```text
GameNetworkClient (background async receive/reconnect)
        |
        v
Concurrent queue of raw payloads/status
        |
        v  Unity Update, capped per frame
MessageDecoder -> MatchController
                      |       |
                      |       +-> transient FX/audio/glove animation
                      +----------> persistent HUD/match state

AR Session / XR Origin
        |-> rear-camera background
        |-> horizontal plane detection and arena anchor
        +-> optional ARHumanBodyManager experiment
```

## Frames of reference

- Screen space: health, stamina, timer, network state, damage vignette.
- Camera relative: the local player's virtual gloves and immediate feedback.
- World space: floor-anchored boundary, start positions, optional pickups.
- Opponent relative: tracked hand/wrist glove meshes and hit particles if body tracking is reliable.

These layers must remain separate because their transforms and failure modes differ.

## State ownership

`MatchController` owns the visualizer's local copy. `MatchState` snapshots replace persistent fields when their sequence is newer. `GameEvent` messages trigger short-lived presentation only; they must not become an independent source of health truth.

When disconnected, keep the last state visible, display `RECONNECTING`, and stop implying that the match is live. The laptop determines whether match state is frozen.

## Latency instrumentation points

Record at least:

- server timestamp and phone receipt time;
- dequeue/apply time on the Unity main thread;
- first rendered frame after the event;
- sustained FPS and worst frame time during camera, HUD, particles, and body tracking tests.

Do not compare clocks directly until their offset is known. For initial integration, measure local receipt-to-render latency and use sequence numbers for ordering.

## Design risks to prove early

- Apple body tracking requires a compatible physical iPhone and may not track two fast, partially occluded hands well enough for boxing.
- A Cardboard-style enclosure can obstruct a rear camera, trap heat, distort the image, and reduce situational awareness.
- A self-signed WSS endpoint will fail on iOS unless its trust chain is installed/configured correctly.
- Camera passthrough plus stereo/Cardboard rendering may not behave like a conventional optical AR headset. Prototype the actual phone/headset arrangement before polishing content.
