# AprilTag WP2: smoothed opponent targets

WP2 converts the working WP1 AprilTag pose into a stable presentation target
for later glove trajectories. It does not determine whether a punch hit. The
laptop game engine remains authoritative for hit/miss and game state.

## What WP2 adds

- Exponential position and rotation smoothing over new WP1 detections.
- Explicit `Searching`, `Tracking`, `Lost`, and `MissingSource` states.
- Safe loss behaviour: target visuals disappear and target queries fail rather
  than returning the world origin or a stale opponent position.
- Reacquisition behaviour: the filter snaps to the newly detected pose, so an
  old opponent location is not animated through after an occlusion.
- Four editable target points below `Smoothed Marker Pose`: chest, head, left
  body, and right body.

## One-time Unity setup

1. Open the AR scene in Unity 6000.0.76f1.
2. Confirm the working `AprilTag WP1 Tracker` is present in the Hierarchy.
3. Run `CG4002 > Visualizer > Set Up AprilTag WP2 Target Provider`.
4. Select `AprilTag WP2 Target Provider` and inspect the assigned references.
5. Save the scene. The setup command is idempotent and can be run again.

The default offsets assume the tag is mounted flat at the centre of the
opponent's chest and its green local Y axis points toward the head. In the Scene
view, adjust only the local positions of the four target children. If the WP1
red X axis points opposite the expected opponent-left direction, swap the left
and right target local X values.

Suggested starting values in marker-local metres:

| Target | Local position |
| --- | --- |
| Chest | `(0.00, 0.00, 0.00)` |
| Head | `(0.00, 0.35, 0.00)` |
| Left body | `(-0.18, -0.10, 0.00)` |
| Right body | `(0.18, -0.10, 0.00)` |

## Marker used by this project

The reproducible marker is `docs/markers/tagStandard41h12-0.svg`: family
`tagStandard41h12`, ID 0, 180 mm total width. Print at 100% / Actual Size with
no fit-to-page scaling. The detector's `Tag Size Metres` remains `0.100`, which
is the inner detection-square width for this generated marker, not the full
180 mm paper width. Measure the print before testing.

Mount it flat and rigidly. Avoid folds, glossy lamination, strong glare, and a
hand covering the black border. For initial tests, attach it to a stationary
stand or chair rather than asking someone to receive physical punches.

## Physical iPhone test

1. Commit the Unity source changes on Windows; do not commit `Library`, `Temp`,
   `Logs`, `Builds`, an Xcode project, or Xcode `DerivedData`.
2. Pull on the M1 Mac and open the project with Unity 6000.0.76f1.
3. Create a fresh iOS build folder, open the generated Xcode workspace/project,
   select the development team and connected iPhone, then Run.
4. Hold the iPhone 1.0 m from the stationary marker. The WP1 RGB axes should
   show the raw pose. WP2 should show a yellow chest sphere, cyan head sphere,
   magenta left-body sphere, and orange right-body sphere with less jitter.
5. Move the marker slowly left/right and toward/away from the camera. All four
   targets must remain rigidly arranged relative to it.
6. Cover the tag. Within the WP1 timeout (about 0.35 s), the WP2 overlay must
   say `Lost`, all target spheres must disappear, and `TryGetTargetPose` must
   return false.
7. Move the covered marker, then uncover it. The targets must reappear at the
   new location without travelling through the stale location.
8. Repeat at 0.5, 1.0, 1.5, and 2.0 m and with moderate yaw/pitch. Tune
   `Position Sharpness` and `Rotation Sharpness` on-device; larger values reduce
   lag but expose more detector jitter.

Record the iPhone model, iOS version, approximate FPS, thermal state, usable
distance/angle range, reacquisition behaviour, and observed motion-to-render
latency. These measurements are the WP2 evidence; Windows Play mode is useful
for compilation and layout only, not ARKit tracking quality.

## WP2 acceptance checklist

- No target is returned before the first valid detection.
- A tracked marker produces stable target points without visible origin jumps.
- Loss hides targets and invalidates target queries.
- Reacquisition uses the new pose rather than a stale pose.
- Offsets remain editable without changing detector code.
- No local collision or target provider code declares a hit.
