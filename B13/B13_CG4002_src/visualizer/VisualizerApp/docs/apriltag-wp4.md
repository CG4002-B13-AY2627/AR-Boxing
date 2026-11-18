# AprilTag WP4: refined punch animation

WP4 preserves WP3 target selection and tracking-loss safeguards while giving
each punch its own path and timing profile. This remains presentation code; it
does not determine hits.

## Motion definitions

- Jab: a direct straight line from the camera-relative rest position to the
  current WP2 left/right body target. It keeps the original short punch time.
- Hook: a cubic bowed arc. The added curvature lies in the camera's X-Y plane,
  while the base path still advances in depth to the WP2 head target.
- Uppercut: the existing rising curve to the head, with a longer duration and a
  progressive symmetric inward yaw so the gloves turn toward the player.

## Apply the recommended starting values

1. Open the scene containing `CameraRelativeGloves`.
2. Wait for Unity to compile.
3. Run `CG4002 > Visualizer > Apply WP4 Refined Punch Animation`.
4. Save the scene.

The command sets:

| Setting | Starting value |
| --- | ---: |
| Jab / Punch Duration | existing value, normally 0.34 s |
| Hook Duration | 0.46 s |
| Uppercut Duration | 0.48 s |
| Targeted Hook Arc Distance | 0.18 m |
| Targeted Hook Vertical Lift | 0.12 m |
| Targeted Uppercut Dip | 0.12 m |
| Uppercut Inward Yaw | 65 degrees |

## Physical tuning order

Use a rigid marker on a stand or mannequin and keep the phone approximately
0.75-1.0 m away.

1. Test both jabs. Their travel must remain on the direct line to the two body
   targets, without a visible upward bow.
2. Test both hooks. They should mirror each other: each fist first travels
   outward and upward, then sweeps into the head target.
3. Increase `Targeted Hook Arc Distance` for a wider swing, or reduce it if the
   fist leaves the camera view.
4. Increase `Targeted Hook Vertical Lift` for a rounder screen-space arc. Keep
   it lower than the head-target height so the path does not look like an
   overhand punch.
5. Test both uppercuts. The left and right glove yaw must be symmetric and turn
   inward as they rise.
6. If the imported glove mesh faces the wrong direction, adjust
   `Uppercut Inward Yaw Degrees`. A negative mesh pivot correction should be
   made on the glove model child, not by negatively scaling the motion root.
7. Cover the marker during every punch type and confirm the existing `ABORTED`
   return-to-rest behaviour still works.

Record the iPhone model, iOS version, FPS, thermal state, and observed
event-to-render latency after final tuning. Keep a visible stop/pause path and
do not test by physically striking a person.

## Acceptance checklist

- Jab positions are collinear with their start and target positions.
- Left and right hooks use mirrored X-Y arcs and take longer than jabs.
- Both uppercuts take longer than jabs and progressively rotate inward.
- All punch endpoints continue to follow their live WP2 targets.
- Target loss and invalid-target behaviour remain unchanged.
- No animation or collision code declares a hit.
