# AprilTag WP3: tracked-target punch trajectories

WP3 makes the camera-relative glove animations travel toward the smoothed WP2
target points. This is presentation only. It does not use collision detection
or decide whether a punch hit; the laptop game engine remains authoritative.

## Target mapping

| Punch button | WP2 target |
| --- | --- |
| Left jab | Left Body Target |
| Right jab | Right Body Target |
| Left hook | Head Target |
| Right hook | Head Target |
| Left uppercut | Head Target |
| Right uppercut | Head Target |

The endpoint is sampled throughout the punch, so the trajectory follows the
smoothed marker rig when the opponent moves. A small standoff stops the rendered
glove just before the target point.

## Unity setup

1. Open the scene containing the camera glove rig and WP2 target provider.
2. Confirm WP1 uses `Image Transformation = None` and WP2 says `Tracking` when
   the marker is visible.
3. Run `CG4002 > Visualizer > Set Up AprilTag WP3 Targeted Punches`.
4. Select `CameraRelativeGloves` and confirm `Target Provider` references
   `AprilTag WP2 Target Provider`.
5. Save the scene.

The setup command adds missing left/right uppercut buttons and arranges seven
debug buttons: left uppercut, left hook, left jab, guard, right jab, right hook,
and right uppercut.

## Important Inspector settings

- `Use Tracked Targets`: enables WP3 world-space trajectories.
- `Fallback To Prototype When Target Unavailable`: plays the older local punch
  when tracking is unavailable. Disable it when testing target validity alone.
- `Target Standoff Metres`: initial value 0.08 m.
- `Minimum Target Depth Metres`: rejects a target too close to or behind the
  camera. Initial value 0.35 m.
- `Maximum Target Distance Metres`: initial value 3.0 m.
- Jab, hook, and uppercut arc settings alter only the visual path.
- `Target Loss Return Duration`: controls the safe return when tracking is lost
  during a punch.

## Physical test

Use a rigid marker on a chair, stand, or mannequin. Do not punch a person during
trajectory tuning.

1. Hold the phone still with the marker 0.75-1.0 m away.
2. Wait for WP1 and WP2 to report valid tracking.
3. Press Left Jab and verify the glove approaches the magenta left-body point.
4. Press Right Jab and verify it approaches the orange right-body point.
5. Press both hook buttons and both uppercut buttons; all four must approach the
   cyan head point but use visibly different arcs.
6. Start a punch and cover the marker. The status should say `ABORTED`, and the
   glove should return instead of remaining at the stale target.
7. Disable `Fallback To Prototype When Target Unavailable`, hide the marker,
   and press each punch button. The status should say `BLOCKED` and no targeted
   punch should launch.
8. Re-enable the fallback if the non-AR demo path is required.
9. Move the marker slowly during a punch and confirm the endpoint follows WP2
   without sudden origin jumps.

If left and right body targets are visually reversed, first verify the WP1 red
axis and WP2 child offsets. Correct or swap the two WP2 body-target local X
positions rather than mirroring the camera image.

Record the iPhone model, iOS version, approximate FPS, thermal state, tracking
loss behaviour, and event-to-render latency. Windows testing verifies scripts,
buttons, and layout; the Mac-to-iPhone build is the evidence for AR behaviour.

## Acceptance checklist

- Jabs select separate left/right body targets.
- Hooks and uppercuts select the head target.
- Punches follow the smoothed WP2 target rather than a fixed camera offset.
- Invalid, behind-camera, too-close, and too-distant targets are rejected.
- Losing tracking returns the glove and never targets the world origin.
- No WP3 collision or trajectory code declares a hit.
