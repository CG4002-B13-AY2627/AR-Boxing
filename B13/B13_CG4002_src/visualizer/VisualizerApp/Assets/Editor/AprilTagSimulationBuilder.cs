using System;
using System.IO;
using System.Linq;
using AprilTag;
using CG4002.Visualizer.AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.XR.ARSubsystems;
using UnityEngine.XR.Simulation;

namespace CG4002.Visualizer.Editor
{
    /// <summary>
    /// Creates an XR Simulation environment whose camera view contains a real
    /// tagStandard41h12 ID 0 image. The normal WP1 detector still performs the
    /// detection; this does not inject a pose into the target provider.
    /// </summary>
    public static class AprilTagSimulationBuilder
    {
        private const string RootFolder = "Assets/Simulation/AprilTag";
        private const string TextureFolder = RootFolder + "/Textures";
        private const string EnvironmentFolder = RootFolder + "/Environments";
        private const string TextureAssetPath =
            TextureFolder + "/tagStandard41h12-0-simulation.png";
        private const string EnvironmentAssetPath =
            EnvironmentFolder + "/AprilTagPunchEnvironment.prefab";
        private const string PreferencesAssetPath =
            "Assets/XR/UserSimulationSettings/Resources/XRSimulationPreferences.asset";

        // The 9 x 9 tagStandard41h12 ID 0 pattern from the supplied SVG.
        // 1 is black. The generated texture adds a two-cell white quiet zone.
        private static readonly string[] TagRows =
        {
            "001000011",
            "111111111",
            "010000011",
            "110000010",
            "110110011",
            "110101010",
            "010000011",
            "111111111",
            "001011011"
        };

        private const int QuietZoneCells = 2;
        private const int PixelsPerCell = 40;
        private const float DetectionSquareSizeMetres = 0.10f;
        private const float MarkerDistanceMetres = 0.80f;

        [MenuItem("CG4002/Visualizer/Set Up AprilTag Punch Simulation")]
        public static void SetUpAprilTagSimulation()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorUtility.DisplayDialog(
                    "AprilTag Simulation",
                    "Exit Play Mode before creating the simulation environment.",
                    "OK");
                return;
            }

            try
            {
                EnsureAssetFolder(TextureFolder);
                EnsureAssetFolder(EnvironmentFolder);

                XRCpuImage.Transformation transformation =
                    GetActiveTrackerTransformation();
                Texture2D tagTexture = CreateOrReplaceTagTexture(transformation);
                ValidateCanonicalTagPattern();
                GameObject environmentPrefab = CreateOrReplaceEnvironment(tagTexture);
                ActivateEnvironment(environmentPrefab);

                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh();
                Selection.activeObject = environmentPrefab;

                string message =
                    "AprilTag ID 0 XR Simulation is ready. Open Main, enter Play Mode, " +
                    "and wait for the WP1 overlay to show TRACKING before pressing the punch buttons. " +
                    $"The displayed tag was prepared for image transformation: {transformation}.";
                if (BuildPipeline.GetBuildTargetGroup(
                        EditorUserBuildSettings.activeBuildTarget) !=
                    BuildTargetGroup.Standalone)
                {
                    message +=
                        " Switch the active Build Profile to Windows before Play Mode so Unity uses the XR Simulation loader.";
                }

                Debug.Log(message, environmentPrefab);
                if (!Application.isBatchMode)
                {
                    EditorUtility.DisplayDialog("AprilTag Simulation", message, "OK");
                }
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                if (!Application.isBatchMode)
                {
                    EditorUtility.DisplayDialog(
                        "AprilTag Simulation setup failed",
                        exception.Message,
                        "OK");
                }

                throw;
            }
        }

        /// <summary>
        /// Batch-mode entry point used to reproduce the checked-in environment.
        /// </summary>
        public static void SetUpAprilTagSimulationFromMainScene()
        {
            EditorSceneManager.OpenScene("Assets/Scenes/Main.unity", OpenSceneMode.Single);
            SetUpAprilTagSimulation();
        }

        [MenuItem("CG4002/Visualizer/Set Up AprilTag Punch Simulation", true)]
        private static bool ValidateSetUpAprilTagSimulation()
        {
            return !EditorApplication.isPlayingOrWillChangePlaymode;
        }

        private static Texture2D CreateOrReplaceTagTexture(
            XRCpuImage.Transformation transformation)
        {
            Color32[] canonicalPixels = CreateCanonicalTagPixels(
                out int width,
                out int height);
            Color32[] displayPixels = PrecompensateForImageTransformation(
                canonicalPixels,
                width,
                height,
                transformation);

            var texture = new Texture2D(width, height, TextureFormat.RGBA32, false, true)
            {
                name = "tagStandard41h12-0-simulation",
                filterMode = FilterMode.Point,
                wrapMode = TextureWrapMode.Clamp
            };
            texture.SetPixels32(displayPixels);
            texture.Apply(false, false);

            string absolutePath = AssetPathToAbsolutePath(TextureAssetPath);
            Directory.CreateDirectory(Path.GetDirectoryName(absolutePath));
            File.WriteAllBytes(absolutePath, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);

            AssetDatabase.ImportAsset(
                TextureAssetPath,
                ImportAssetOptions.ForceSynchronousImport |
                ImportAssetOptions.ForceUpdate);

            var importer = AssetImporter.GetAtPath(TextureAssetPath) as TextureImporter;
            if (importer == null)
            {
                throw new InvalidOperationException(
                    $"Unity did not import {TextureAssetPath} as a texture.");
            }

            importer.textureType = TextureImporterType.Default;
            importer.alphaSource = TextureImporterAlphaSource.None;
            importer.sRGBTexture = false;
            importer.mipmapEnabled = false;
            importer.isReadable = true;
            importer.filterMode = FilterMode.Point;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.maxTextureSize = 1024;
            importer.SaveAndReimport();

            return AssetDatabase.LoadAssetAtPath<Texture2D>(TextureAssetPath);
        }

        private static Color32[] CreateCanonicalTagPixels(
            out int width,
            out int height)
        {
            int cellCount = TagRows.Length + QuietZoneCells * 2;
            width = cellCount * PixelsPerCell;
            height = width;

            var white = new Color32(255, 255, 255, 255);
            var black = new Color32(0, 0, 0, 255);
            var pixels = Enumerable.Repeat(white, width * height).ToArray();

            for (int row = 0; row < TagRows.Length; row++)
            {
                for (int column = 0; column < TagRows[row].Length; column++)
                {
                    if (TagRows[row][column] != '1')
                    {
                        continue;
                    }

                    int startX = (column + QuietZoneCells) * PixelsPerCell;
                    int startY =
                        (TagRows.Length - 1 - row + QuietZoneCells) * PixelsPerCell;
                    for (int y = startY; y < startY + PixelsPerCell; y++)
                    {
                        int rowOffset = y * width;
                        for (int x = startX; x < startX + PixelsPerCell; x++)
                        {
                            pixels[rowOffset + x] = black;
                        }
                    }
                }
            }

            return pixels;
        }

        private static Color32[] PrecompensateForImageTransformation(
            Color32[] canonicalPixels,
            int width,
            int height,
            XRCpuImage.Transformation transformation)
        {
            bool flipVertically =
                (transformation & XRCpuImage.Transformation.MirrorX) != 0;
            bool flipHorizontally =
                (transformation & XRCpuImage.Transformation.MirrorY) != 0;

            if (!flipHorizontally && !flipVertically)
            {
                return canonicalPixels;
            }

            var compensated = new Color32[canonicalPixels.Length];
            for (int y = 0; y < height; y++)
            {
                int sourceY = flipVertically ? height - 1 - y : y;
                for (int x = 0; x < width; x++)
                {
                    int sourceX = flipHorizontally ? width - 1 - x : x;
                    compensated[y * width + x] =
                        canonicalPixels[sourceY * width + sourceX];
                }
            }

            return compensated;
        }

        private static void ValidateCanonicalTagPattern()
        {
            Color32[] pixels = CreateCanonicalTagPixels(out int width, out int height);
            using var detector = new TagDetector(width, height, 1);
            detector.ProcessImage(
                pixels.AsSpan(),
                60f * Mathf.Deg2Rad,
                DetectionSquareSizeMetres);

            if (!detector.DetectedTags.Any(tag => tag.ID == 0))
            {
                throw new InvalidOperationException(
                    "The generated simulation texture did not decode as tagStandard41h12 ID 0.");
            }
        }

        private static GameObject CreateOrReplaceEnvironment(Texture2D tagTexture)
        {
            ScriptableObject preferences =
                AssetDatabase.LoadAssetAtPath<ScriptableObject>(PreferencesAssetPath);
            if (preferences == null)
            {
                throw new InvalidOperationException(
                    "XR Simulation preferences are missing. Enable XR Simulation for the Standalone platform first.");
            }

            var serializedPreferences = new SerializedObject(preferences);
            SerializedProperty fallbackProperty =
                serializedPreferences.FindProperty("m_FallbackEnvironmentPrefab");
            GameObject template = fallbackProperty?.objectReferenceValue as GameObject;
            if (template == null)
            {
                throw new InvalidOperationException(
                    "The default XR Simulation environment prefab could not be found.");
            }

            var root = PrefabUtility.InstantiatePrefab(template) as GameObject;
            if (root == null)
            {
                throw new InvalidOperationException(
                    "The default XR Simulation environment could not be instantiated.");
            }

            try
            {
                root.name = "AprilTag Punch Environment";
                foreach (SimulatedTrackedImage existing in
                    root.GetComponentsInChildren<SimulatedTrackedImage>(true))
                {
                    UnityEngine.Object.DestroyImmediate(existing.gameObject);
                }

                Pose cameraPose = GetEnvironmentCameraStartingPose(root);
                Vector3 cameraForward = cameraPose.rotation * Vector3.forward;
                Vector3 cameraUp = cameraPose.rotation * Vector3.up;

                var marker = new GameObject("AprilTag ID 0 (WP4 punch target)");
                marker.transform.SetParent(root.transform, true);
                marker.transform.SetPositionAndRotation(
                    cameraPose.position + cameraForward * MarkerDistanceMetres,
                    Quaternion.LookRotation(cameraUp, -cameraForward));

                SimulatedTrackedImage simulatedImage =
                    marker.AddComponent<SimulatedTrackedImage>();
                var serializedImage = new SerializedObject(simulatedImage);
                serializedImage.FindProperty("m_Image").objectReferenceValue = tagTexture;

                float fullTextureSize = DetectionSquareSizeMetres *
                    (TagRows.Length + QuietZoneCells * 2) / TagRows.Length;
                serializedImage.FindProperty("m_ImagePhysicalSizeMeters").vector2Value =
                    Vector2.one * fullTextureSize;
                serializedImage.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(simulatedImage);

                GameObject saved = PrefabUtility.SaveAsPrefabAsset(
                    root,
                    EnvironmentAssetPath);
                if (saved == null)
                {
                    throw new InvalidOperationException(
                        $"Unity could not save {EnvironmentAssetPath}.");
                }

                return saved;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static Pose GetEnvironmentCameraStartingPose(GameObject root)
        {
            Component environment = root.GetComponents<Component>().FirstOrDefault(
                component => component != null &&
                    component.GetType().FullName ==
                    "UnityEngine.XR.Simulation.SimulationEnvironment");
            if (environment == null)
            {
                throw new InvalidOperationException(
                    "The environment prefab has no Simulation Environment component.");
            }

            var serializedEnvironment = new SerializedObject(environment);
            SerializedProperty poseProperty =
                serializedEnvironment.FindProperty("m_CameraStartingPose");
            SerializedProperty positionProperty =
                poseProperty?.FindPropertyRelative("position");
            SerializedProperty rotationProperty =
                poseProperty?.FindPropertyRelative("rotation");
            if (positionProperty == null || rotationProperty == null)
            {
                throw new InvalidOperationException(
                    "The XR Simulation camera starting pose could not be read.");
            }

            return new Pose(
                positionProperty.vector3Value,
                rotationProperty.quaternionValue);
        }

        private static void ActivateEnvironment(GameObject environmentPrefab)
        {
            ScriptableObject preferences =
                AssetDatabase.LoadAssetAtPath<ScriptableObject>(PreferencesAssetPath);
            var serializedPreferences = new SerializedObject(preferences);
            SerializedProperty environmentProperty =
                serializedPreferences.FindProperty("m_EnvironmentPrefab");
            if (environmentProperty == null)
            {
                throw new InvalidOperationException(
                    "The active XR Simulation environment setting could not be found.");
            }

            environmentProperty.objectReferenceValue = environmentPrefab;
            serializedPreferences.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(preferences);
        }

        private static XRCpuImage.Transformation GetActiveTrackerTransformation()
        {
            AprilTagOpponentTracker tracker =
                UnityEngine.Object.FindFirstObjectByType<AprilTagOpponentTracker>();
            if (tracker == null)
            {
                Debug.LogWarning(
                    "No AprilTagOpponentTracker is open in the active scene. " +
                    "The simulation texture will assume image transformation None.");
                return XRCpuImage.Transformation.None;
            }

            var serializedTracker = new SerializedObject(tracker);
            SerializedProperty property =
                serializedTracker.FindProperty("imageTransformation");
            return property == null
                ? XRCpuImage.Transformation.None
                : (XRCpuImage.Transformation)property.intValue;
        }

        private static void EnsureAssetFolder(string assetFolder)
        {
            string[] parts = assetFolder.Split('/');
            string current = parts[0];
            for (int index = 1; index < parts.Length; index++)
            {
                string next = current + "/" + parts[index];
                if (!AssetDatabase.IsValidFolder(next))
                {
                    AssetDatabase.CreateFolder(current, parts[index]);
                }

                current = next;
            }
        }

        private static string AssetPathToAbsolutePath(string assetPath)
        {
            string projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
            if (string.IsNullOrEmpty(projectRoot))
            {
                throw new InvalidOperationException("The Unity project root is unavailable.");
            }

            return Path.Combine(
                projectRoot,
                assetPath.Replace('/', Path.DirectorySeparatorChar));
        }
    }
}
