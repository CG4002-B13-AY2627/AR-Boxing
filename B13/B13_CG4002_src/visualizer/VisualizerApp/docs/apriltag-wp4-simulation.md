# AprilTag punch testing with XR Simulation

This setup renders a virtual `tagStandard41h12` ID 0 marker into AR
Foundation's XR Simulation camera. `AprilTagOpponentTracker` then reads the
simulated CPU camera image and performs normal AprilTag detection. It does not
inject a fake pose into WP2 or the glove rig.

## Create or refresh the environment

1. Open `Main.unity` and wait for Unity to finish compiling.
2. Exit Play Mode if it is active.
3. Select `CG4002 > Visualizer > Set Up AprilTag Punch Simulation`.
4. Wait for the confirmation dialog.

The command:

- creates a crisp ID 0 texture with the necessary white quiet zone;
- validates that the native detector decodes the generated pattern as ID 0;
- creates `Assets/Simulation/AprilTag/Environments/AprilTagPunchEnvironment.prefab`;
- positions the marker 0.8 metres in front of the XR Simulation camera;
- makes that prefab the active XR Simulation environment;
- compensates the displayed texture for the open scene's current
  `Image Transformation` setting.

Rerun the setup command after changing `AprilTagOpponentTracker > Image
Transformation`, because a mirrored CPU conversion requires a correspondingly
pre-mirrored simulation texture.

## Test the punches

1. Open `File > Build Profiles`, select **Windows**, and click **Switch
   Platform**. The XR Simulation loader is configured for the Standalone
   profile; Play Mode cannot use it while iOS is the active build target.
2. Open the Game view and enter Play Mode.
3. Wait for the WP1 overlay to show `TRACKING tag 0 (VALID)`.
4. Confirm that the WP2 coloured target points appear around the marker.
5. Trigger left and right jab, hook, and uppercut using the existing debug
   buttons.
6. Verify that jabs target the body points and hooks/uppercuts target the head.
7. Move the simulated camera while holding the right mouse button:
   - mouse: look around;
   - `WASD`: move horizontally;
   - `Q` / `E`: move down/up;
   - `Shift`: move faster.
8. Look away from the marker during a punch and confirm the existing `ABORTED`
   return-to-rest path still runs.

Switch the active Build Profile back to **iOS** before producing the Xcode
project for the MacBook deployment workflow.

If the tag starts outside the Game view, rerun the setup command. The builder
uses the camera starting pose from the currently installed AR Foundation
fallback environment, so rebuilding also repairs the initial marker placement.

## Scope of this test

XR Simulation is useful for checking detector integration, target selection,
animation paths, target loss, and basic camera-relative movement on Windows. It
does not validate iPhone camera exposure, ARKit tracking quality, real-world
motion blur, performance, thermals, or latency. Repeat the final checks on the
physical iPhone before accepting WP4.
