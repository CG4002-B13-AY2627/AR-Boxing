# Windows development and Mac/iPhone deployment

For the latest reconciled state, read `docs/macbook-development-handoff.md` from `main` before using this procedural guide. The current implementation branch is `OpponentTracker`.

## Machine responsibilities

| Machine | Primary responsibility |
| --- | --- |
| Windows laptop | Unity scenes, C# code, UI, prefabs, animations, mock networking, edit-mode tests, and most iteration |
| MacBook Air M1 | Open the same committed Unity project, produce the Xcode project, sign it, deploy to iPhone, and profile ARKit/device behaviour |
| Physical iPhone | Camera, ARKit tracking, body-tracking feasibility, network permission, frame-time, heat, and end-to-end latency tests |

Use Git commits as the handoff unit. Both computers must use the Unity version in `VisualizerApp/ProjectSettings/ProjectVersion.txt`.

## Windows development setup

1. Install Unity Hub and Unity `6000.0.76f1` for Windows.
2. Install an editor such as Visual Studio or Rider with C# support.
3. Open `VisualizerApp`, allow packages to resolve, and commit the generated `.meta` and project-setting files.
4. Develop against `MockGameEventSource` or `tools/mock_server.py`.
5. Use Unity's AR simulation for basic scene/layout work where helpful, while treating it only as an approximation.
6. Commit and push a known-good revision before moving to the Mac.

The canonical Windows checkout is `C:\Dev\CG4002-Viz`. Avoid OneDrive or another live-synchronised folder; Unity's generated files change frequently and can make synced working copies slow or conflict-prone.

## Mac deployment setup

1. Update macOS Tahoe and install Xcode from the App Store.
2. Launch Xcode once, accept its licence, and allow it to install platform components. Install command-line tools with `xcode-select --install` if they are not already present.
3. In Xcode, sign in with the Apple ID used for device deployment. A free Personal Team is enough for short-lived development signing; App Store/TestFlight distribution needs the appropriate Apple Developer membership.
4. Install Unity Hub for Apple silicon.
5. Install Unity `6000.0.76f1` with the iOS Build Support module. If the team standardizes on another Unity 6.0 LTS patch, update `ProjectVersion.txt` for everyone in one commit.
6. Install Git. Install Git LFS before large binary assets are introduced.

An M1 Mac meets Unity 6's Apple-silicon requirement. Keep at least tens of GB free for Unity, Xcode, DerivedData, and iOS builds. Close memory-heavy apps during device profiling on an 8 GB model.

## Transfer revisions to macOS

Clone the same Git remote under a normal local path such as `~/Developer/CG4002-Viz`. Pull the Windows revision that you intend to test. Do not copy `Library`, `Temp`, `Logs`, `Builds`, or `UserSettings` between machines, and do not open the Unity project directly from a continuously synchronized directory.

```bash
cd ~/Developer/CG4002-Viz
git switch OpponentTracker
git pull --ff-only origin OpponentTracker
./tools/check_mac_setup.sh
./tools/bootstrap_python_env.sh
```

Open `VisualizerApp` from Unity Hub. The first Mac import can take several minutes because Unity builds a platform-specific `Library` locally. If Unity changes serialized project settings or generates missing `.meta` files, review and commit those changes so Windows receives them on the next pull.

## Unity project configuration

These steps are primarily completed on the Mac before the first iOS build. Settings stored in the Unity project are then committed and shared back to Windows:

1. Select the iOS build target in `File > Build Profiles`.
2. Open `Edit > Project Settings > XR Plug-in Management`, select iOS, and enable ARKit.
3. Run XR Plug-in Management's Project Validation fixes.
4. In iOS Player Settings set a unique bundle identifier such as `com.nus.cg4002.b13.arboxing`.
5. Set the camera usage description to: `Camera access is required to show the opponent and place augmented-reality game effects.`
6. Mark ARKit support as required because camera AR is a core feature.
7. Start with Metal, IL2CPP, ARM64, portrait or landscape orientation agreed with the headset, and no unnecessary camera/occlusion features.

The included iOS post-build step adds a local-network privacy explanation and permits local resources under App Transport Security. iOS will ask for local-network access the first time the app connects to the laptop. If access is denied, re-enable it under `Settings > Privacy & Security > Local Network`. The post-build step does not disable certificate validation or permit arbitrary internet traffic.

## Existing main scene

`Assets/Scenes/Main.unity` already contains the integrated AR, network, HUD, local-glove, AprilTag, simulation, and optional body-tracking objects. Inspect its serialized references after a fresh import; do not recreate the scene from this older checklist.

The intended module split remains:

- `AR Session`;
- `XR Origin (Mobile AR)` with `AR Camera Manager` and `AR Camera Background`;
- horizontal `AR Plane Manager` for floor experiments;
- `GameNetworkClient`;
- `MatchController`, linked to the network client;
- a Canvas with two health sliders, two stamina sliders, timer text, match-state text, and network-state text;
- `HudPresenter`, linked to the controller and UI fields;
- `MockGameEventSource` during offline development.

Keep the AR camera and network/state logic alive across scene transitions, or use only one gameplay scene until the vertical slice is stable.

The AprilTag package currently ships an x86-64 macOS editor binary in version `1.0.3`. If XR Simulation fails in the native Apple-silicon editor, confirm the binary-architecture issue before changing gameplay code or package versions. The iOS library is arm64 and must still be verified on a physical device.

## Run the mock server on Windows

From PowerShell on the Windows development laptop:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r tools/requirements.txt
python tools/mock_server.py --host 0.0.0.0 --port 8765
```

Find the Windows laptop's LAN IP and set `GameNetworkClient.serverUrl` to `ws://<WINDOWS-LAN-IP>:8765`. Windows Firewall must allow Python on the private network, and the Windows laptop and iPhone must be on the same LAN. The Mac is not part of the runtime data path unless you deliberately run the server there.

## First device build

1. Connect the iPhone by cable, trust the Mac, and enable Developer Mode on the iPhone if prompted.
2. On the Mac, open the exact Windows-tested Git revision in Unity and build the Xcode project into a disposable `Builds/iOS` folder.
3. Open the generated `.xcodeproj` or `.xcworkspace`, select the Unity-iPhone target, choose the signing team, and resolve the bundle identifier.
4. Select the physical iPhone and Run.
5. Grant camera permission and verify rear-camera passthrough before adding effects.

ARKit tracking is not meaningfully testable in the iOS Simulator. Three-dimensional body tracking should be gated by runtime support and tested on an A12-or-later iPhone.

Do not keep fixes only inside the generated Xcode project: Unity overwrites it on the next build. Express required changes in Unity Player Settings or an iOS post-build script, then commit them and verify that the project still opens on Windows.

## Bring-up checkpoints

- Device shows camera passthrough for ten minutes without crash or severe thermal throttling.
- Mock connection survives server restart and visibly changes to `RECONNECTING` and back to `CONNECTED`.
- State snapshots recover the HUD after intentionally dropping several transient events.
- A received punch event produces feedback without changing health locally.
- Measured frame time and event receipt-to-presentation latency are recorded with device/iOS/build details.
