# AprilTag WP1 diagnostic

## Purpose

This spike detects one moving AprilTag from AR Foundation's CPU camera feed and
renders RGB world axes at the estimated pose. It does not change glove animation,
decide hit/miss, or apply game state.

## Dependency decision

The project uses `jp.keijiro.apriltag` 1.0.3 (BSD-2-Clause) because it packages
native AprilTag binaries for Windows x86-64 and iOS arm64. The upstream package
declares Unity 2021.3 and supports only `tagStandard41h12`; Unity 6.0 and the
project's IL2CPP iOS build must therefore be validated by this spike before the
package is accepted for later work packages.

## Unity setup

1. Open `Assets/Scenes/Main.unity`.
2. Wait until Package Manager finishes installing `jp.keijiro.apriltag`.
3. Run `CG4002 > Visualizer > Set Up AprilTag WP1`.
4. Select `AprilTag WP1 Tracker`.
5. Set `Target Tag Id` to the printed ID (default 0).
6. Set `Tag Size Metres` to the inner black detection-square width, not the full
   paper width. A tagStandard41h12 marker with 180 mm total width uses 0.100 m.
7. Leave Image Downsample 2, Detector Decimation 1, and Detection Rate 10 Hz for
   the first device test.
8. Save the scene.

## Marker preparation

Use the AprilTag generator with family `tagStandard41h12`, ID 0, and total size
180 mm. The detector tag size is 100 mm. Export PDF, print at 100% / Actual Size,
verify the inner black square with a ruler, and mount the page flat on rigid matte
backing. Do not laminate it with glossy film.

## Device test

Build for iOS on the Mac, open the generated Xcode project, select the development
team and connected iPhone, then Run. Start with the marker stationary,
front-facing, evenly lit, and 0.75-1.0 m from the camera.

Expected result:

- Overlay changes from Searching to TRACKING tag 0.
- VALID is shown while detections remain recent.
- RGB axes appear at the marker.
- Reported distance is approximately the measured phone-to-marker distance.
- Removing the marker makes the axes disappear after about 0.35 seconds.

Repeat at 0.5, 1.0, 1.5, and 2.0 m; yaw and pitch the marker; move it slowly;
partially cover it; leave and re-enter view; and test bright and dim indoor light.
Record iPhone model, iOS version, detection range, detector milliseconds, FPS,
thermal state, pose jitter, loss time, and reacquisition time.

If position follows correctly but the axes are rolled by 90 degrees, try Camera
Image Roll Correction Degrees = 90 or -90. If distance is consistently wrong,
re-measure the inner black detection square and correct Tag Size Metres first.

## Left/right inversion and intermittent detection

For the rear camera, `Image Transformation` should be `None`. `MirrorY` flips
the converted CPU image horizontally: motion appears in the opposite direction
and the reflected AprilTag payload can fail to decode consistently.

For an existing scene, run
`CG4002 > Visualizer > AprilTag > Fix Rear-Camera Left-Right Mirroring`, save the
scene, rebuild, and test again. The WP1 overlay must report `None`, not
`MirrorY (LEFT/RIGHT REVERSED)`.

If detection still drops during motion after fixing mirroring, first test in
bright, even lighting and move the rigidly mounted marker slowly. Then A/B test
`Image Downsample = 1` and `Detection Rate Hz = 15`. Watch the displayed
detector time, device FPS, and thermal state; do not hide genuine detection loss
by increasing the timeout before measuring it.

## Performance and lifecycle notes

CPU camera access is throttled. Every `XRCpuImage` and asynchronous conversion is
disposed. If detector cost is excessive, first reduce Detection Rate to 5 Hz;
then increase Detector Decimation to 2. Do not tune glove movement until this
diagnostic is stable.
