# Camera-relative glove prototype

This prototype creates two local-player gloves that stay near the lower-left and lower-right camera viewport positions. Five temporary screen buttons trigger procedural jab, hook, and guard motions. It is intended to prove placement and event triggering before final models and authored animation clips are available.

## Add it to the AR scene

1. Open the scene containing `AR Session` and `XR Origin (Mobile AR)`.
2. Select the AR Camera in the Hierarchy. This makes the intended camera unambiguous if the scene contains more than one.
3. Run `CG4002 > Visualizer > Create Camera Glove Prototype` from the Unity menu.
4. Save the scene.
5. Enter Play Mode. Use the five buttons along the top of the Game view: `L Hook`, `L Jab`, `Guard`, `R Jab`, and `R Hook`.
6. Deploy to the iPhone and repeat the test while moving the phone. The gloves should remain camera-relative rather than staying at a world anchor.

The command creates:

```text
AR Camera
└── CameraRelativeGloves
    ├── LeftGlove
    │   ├── Fist
    │   └── Cuff
    └── RightGlove
        ├── Fist
        └── Cuff

GloveDebugCanvas
EventSystem (only if the scene did not already have one)
```

## Tune the composition

Select `CameraRelativeGloves` and adjust `CameraRelativeGloveRig`:

- Left Viewport Position: defaults to `(0.18, 0.20)`.
- Right Viewport Position: defaults to `(0.82, 0.20)`.
- Distance From Camera: defaults to `0.65 m`; increase it if the gloves dominate the view.
- Rest Euler values: rotate each glove model into a natural first-person pose.
- Punch Duration: start around `0.30-0.40 s`.
- Distances and heights: keep motions readable without covering the opponent in the centre.

Viewport coordinates range from `(0, 0)` at bottom-left to `(1, 1)` at top-right. Because the rig calculates positions through the AR Camera, placement remains visually similar across editor and phone aspect ratios.

## Replace placeholders with real glove models

1. Import each model and its textures under `Assets/Art/Gloves/`.
2. Place the model beneath `LeftGlove` or `RightGlove`.
3. Reset the model child's local position and tune its local rotation/scale.
4. Disable or delete the placeholder `Fist` and `Cuff` children.
5. Keep `LeftGlove` and `RightGlove` as the motion roots referenced by the rig.

The current motion is procedural and requires no Animator Controller. Once authored clips exist, keep the button-facing public methods but replace the procedural offsets with Animator triggers. This avoids changing UI and later network event bindings.

## Connect game events later

The same methods used by the buttons can be called from the presentation layer after a validated `GameEvent` arrives:

- local `JAB` or `CROSS` -> `LeftJab()` / `RightJab()` according to the agreed punch-side mapping;
- local `LEFT_HOOK` / `RIGHT_HOOK` -> matching hook method;
- local `GUARD` -> `Guard()`.

Do not trigger local health or hit resolution from these animations. The laptop remains authoritative and the gloves only present the event.

## Device acceptance check

- Gloves remain in the lower side regions while the phone rotates and translates.
- Neither resting glove blocks the centre of the opponent view.
- Repeated taps restart cleanly without leaving a glove displaced.
- Both hands return to their resting poses after Guard.
- Frame rate remains stable with both gloves visible.
- Debug buttons are removed or hidden before the integrated match demo.
