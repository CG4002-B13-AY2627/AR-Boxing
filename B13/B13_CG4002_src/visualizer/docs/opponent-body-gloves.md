# Opponent body-tracked gloves

This prototype renders glove models on the opponent detected by ARKit 3D human-body tracking. It is a presentation feature only. It does not decide whether a punch hits; the laptop game engine remains authoritative for hit and match state.

## Scene setup

`VisualizerApp/Assets/Scenes/Main.unity` is already configured. Open it in Unity `6000.0.76f1`, expand `XR Origin`, and inspect `OpponentBodyGloves`.

To add the same setup to a different AR scene:

1. Open the AR scene and wait for Unity to finish compiling.
2. Select its AR Camera under the XR Origin in the Hierarchy.
3. Run **CG4002 > Visualizer > Create Opponent Body Glove Prototype** from Unity's top menu.
4. Save the scene.

The menu command:

- adds an `AR Human Body Manager` to the XR Origin if one is missing;
- requests **Pose 3D** and **Pose 3D Scale Estimation**;
- creates `OpponentBodyGloves` with left and right sphere-and-cube placeholders; and
- connects those placeholders to `OpponentBodyGloveTracker`.

Do not use **Create Camera Glove Prototype** for this feature. That older prototype is camera-relative and represents the local player's gloves, not the tracked opponent.

## Runtime behaviour

The tracker follows ARKit's left and right hand joints. If a hand joint briefly becomes unavailable, it falls back to the matching forearm joint. The cuff is aligned along the forearm-to-hand direction, motion is lightly smoothed, and a glove is hidden after tracking has been absent for 0.2 seconds.

The glove models keep their authored materials and textures by default. `Override Material Color` exists only for deliberately tintable prototype materials. Enabling it multiplies the texture by the selected color, so a red tint on a blue texture can make the model appear nearly black.

Left and right are the opponent's anatomical sides. When the opponent faces the camera, their left glove normally appears on the right side of the phone screen.

If more than one body is ever supplied by the provider, the component selects the body whose root is closest to the centre of the camera view. The current ARKit provider normally supplies one 3D body anchor.

## Physical-device test

Body tracking must be judged on the iPhone, not in the Windows Game view or simulator.

1. Commit the Unity source changes and scene; do not commit `Library`, `Builds`, or generated Xcode files.
2. Pull the same commit on the Mac and open it with Unity `6000.0.76f1`.
3. Build the Unity project for iOS, open the generated Xcode workspace/project, select the development team, and deploy to the iPhone.
4. Use the rear camera in a well-lit, open area. Keep the opponent's full body visible at first so ARKit can establish the skeleton.
5. Confirm that both gloves remain attached while the opponent raises, lowers, and crosses their arms.
6. Record iPhone model, iOS version, approximate FPS, thermal state, and any visible tracking latency or jitter.

Apple's 3D body-tracking sample requires an iOS device with an A12 chip or later. The app should keep working without opponent gloves when body tracking is unsupported or temporarily lost.

## Tuning

Select `OpponentBodyGloves` and adjust these Inspector fields:

- **Position Smooth Time**: raise it to reduce jitter; lower it to reduce visual lag.
- **Rotation Sharpness**: raise it for faster rotation response.
- **Lost Tracking Grace Period**: raise it slightly if the gloves flicker during short occlusions.
- **Left/Right Position Offset**: fine-tune placement in each glove's local axes.
- **Left/Right Rotation Offset**: rotate a replacement glove model without changing tracking code.
- **Align Cuff To Forearm**: disable this if a future glove model is already rigged to ARKit joint orientation.
- **Show Tracking Diagnostics**: temporarily display the current subsystem/body/joint state at the bottom of the device screen.
- **Override Material Color**: leave disabled for the textured blue glove models.

## Troubleshooting

- **The menu item is missing:** wait for Unity compilation to finish and fix any red Console errors first.
- **No gloves appear on iPhone:** verify the `AR Human Body Manager` has Pose 3D requested, the device supports body tracking, the rear camera is active, and most of the opponent is visible.
- **Dark or black replacement gloves:** disable `Override Material Color`; material tint multiplies the texture rather than replacing its color.
- **Gloves appear on the wrong screen sides:** remember that the joint names use the opponent's anatomical left and right.
- **The app works but gloves flicker:** improve lighting and framing first, then increase the grace period or position smoothing slightly.
- **Status says no subsystem:** Windows/Editor cannot prove ARKit body tracking. On an iPhone, verify the ARKit loader and device support.
- **Status says 3D active but no person:** begin with the opponent's full body visible, standing upright in good light.
- **Status says joints unavailable:** keep hands and forearms inside the camera view and uncrossed until tracking stabilises.
