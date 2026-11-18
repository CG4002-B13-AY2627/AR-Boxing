#if UNITY_EDITOR
using System;
using CG4002.Visualizer.AR;
using CG4002.Visualizer.Development;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Presentation;
using CG4002.Visualizer.UI;
using Unity.XR.CoreUtils;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace CG4002.Visualizer.Editor
{
    public static class ItemPickupPrototypeBuilder
    {
        private const string MainScenePath = "Assets/Scenes/Main.unity";
        private const string PrefabFolder = "Assets/Prefabs/Pickups";
        private const string MaterialFolder = "Assets/Materials/Pickups";
        private const string HealthPrefabPath = PrefabFolder + "/HealthPickup.prefab";

        [MenuItem("CG4002/Visualizer/Set Up Item Pickup WP2-WP6")]
        public static void SetUpCurrentScene()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorUtility.DisplayDialog(
                    "Item pickup setup",
                    "Exit Play Mode, then run this command again.",
                    "OK");
                return;
            }

            if (SceneManager.GetActiveScene().path != MainScenePath)
            {
                EditorUtility.DisplayDialog(
                    "Item pickup setup",
                    "Open Assets/Scenes/Main.unity, then run this command again.",
                    "OK");
                return;
            }

            BuildAssetsAndUpgradeOpenScene();
        }

        /// <summary>Batch-mode entry point used for reproducible scene and prefab generation.</summary>
        public static void BuildAssetsAndUpgradeMainScene()
        {
            EditorSceneManager.OpenScene(MainScenePath, OpenSceneMode.Single);
            BuildAssetsAndUpgradeOpenScene();
        }

        private static void BuildAssetsAndUpgradeOpenScene()
        {
            EnsureFolder(PrefabFolder);
            EnsureFolder(MaterialFolder);
            PickupVisual prefab = CreateOrReplaceHealthPickupPrefab();

            XROrigin origin = UnityEngine.Object.FindFirstObjectByType<XROrigin>();
            Camera camera = Camera.main != null
                ? Camera.main
                : UnityEngine.Object.FindFirstObjectByType<Camera>();
            MatchController controller =
                UnityEngine.Object.FindFirstObjectByType<MatchController>();
            MockGameEventSource eventSource =
                UnityEngine.Object.FindFirstObjectByType<MockGameEventSource>(FindObjectsInactive.Include);
            CameraRelativeGloveRig gloveRig =
                UnityEngine.Object.FindFirstObjectByType<CameraRelativeGloveRig>(FindObjectsInactive.Include);

            if (origin == null || camera == null || controller == null ||
                eventSource == null || gloveRig == null)
            {
                throw new InvalidOperationException(
                    "Main needs an XR Origin, Main Camera, MatchController, MockGameEventSource, and CameraRelativeGloveRig before pickup setup.");
            }

            // AR Foundation tracking poses are relative to XR Origin. Keeping the root
            // translated placed the simulated camera about ten metres outside the room.
            Undo.RecordObject(origin.transform, "Reset XR Origin for AR tracking");
            origin.transform.SetLocalPositionAndRotation(Vector3.zero, Quaternion.identity);
            origin.transform.localScale = Vector3.one;

            ARPlaneManager planeManager = EnsureComponent<ARPlaneManager>(origin.gameObject);
            planeManager.requestedDetectionMode = PlaneDetectionMode.Horizontal;
            EnsureComponent<ARRaycastManager>(origin.gameObject);

            GameObject runtime = GameObject.Find("ItemPickupRuntime");
            if (runtime == null)
            {
                runtime = new GameObject("ItemPickupRuntime");
                Undo.RegisterCreatedObjectUndo(runtime, "Create item pickup runtime");
            }

            FloorPlaneProvider floor = EnsureComponent<FloorPlaneProvider>(runtime);
            PickupSpawnPresenter presenter = EnsureComponent<PickupSpawnPresenter>(runtime);
            FloorStatusPresenter status = EnsureComponent<FloorStatusPresenter>(runtime);
            HudToastPresenter toast = EnsureComponent<HudToastPresenter>(runtime);
            PickupReachPresenter reach = EnsureComponent<PickupReachPresenter>(runtime);
            PickupCollectionPresenter collection =
                EnsureComponent<PickupCollectionPresenter>(runtime);
            PickupDebugControls controls = EnsureComponent<PickupDebugControls>(runtime);

            Transform visualRoot = runtime.transform.Find("PickupVisuals");
            if (visualRoot == null)
            {
                var visualObject = new GameObject("PickupVisuals");
                Undo.RegisterCreatedObjectUndo(visualObject, "Create pickup visual root");
                visualObject.transform.SetParent(runtime.transform, false);
                visualRoot = visualObject.transform;
            }

            SetObjectReference(floor, "planeManager", planeManager);
            SetObjectReference(floor, "arCamera", camera);
            SetObjectReference(presenter, "controller", controller);
            SetObjectReference(presenter, "floorProvider", floor);
            SetObjectReference(presenter, "healthPickupPrefab", prefab);
            SetObjectReference(presenter, "visualRoot", visualRoot);
            SetObjectReference(status, "floorProvider", floor);
            SetObjectReference(toast, "controller", controller);
            SetObjectReference(reach, "pickupPresenter", presenter);
            SetObjectReference(reach, "gloveRig", gloveRig);
            SetObjectReference(reach, "arCamera", camera);
            SetObjectReference(collection, "controller", controller);
            SetObjectReference(collection, "pickupPresenter", presenter);
            SetObjectReference(collection, "reachPresenter", reach);
            SetObjectReference(collection, "toastPresenter", toast);
            SetObjectReference(collection, "debugEventSource", eventSource);
            SetObjectReference(collection, "arCamera", camera);
            SetObjectReference(controls, "eventSource", eventSource);
            SetObjectReference(controls, "reachPresenter", reach);
            SetObjectReference(controls, "collectionPresenter", collection);

            EditorSceneManager.MarkSceneDirty(runtime.scene);
            EditorSceneManager.SaveScene(runtime.scene);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Selection.activeGameObject = runtime;

            const string message =
                "Item pickup WP2-WP6 is ready. Spawn a health item, then use Collect Nearest. " +
                "The debug distance gate defaults to 2 metres and is adjustable on ItemPickupRuntime.";
            Debug.Log(message, runtime);
            if (!Application.isBatchMode)
            {
                EditorUtility.DisplayDialog("Item pickup setup", message, "OK");
            }
        }

        private static PickupVisual CreateOrReplaceHealthPickupPrefab()
        {
            Material healthMaterial = GetOrCreateMaterial(
                MaterialFolder + "/HealthPickupGreen.mat",
                new Color(0.08f, 0.82f, 0.30f, 1f));
            Material crossMaterial = GetOrCreateMaterial(
                MaterialFolder + "/HealthPickupCross.mat",
                new Color(0.95f, 1f, 0.96f, 1f));
            Material markerMaterial = GetOrCreateMaterial(
                MaterialFolder + "/HealthPickupMarker.mat",
                new Color(0.04f, 0.34f, 0.12f, 1f));

            var root = new GameObject("HealthPickup");
            try
            {
                GameObject marker = CreatePrimitive(
                    PrimitiveType.Cylinder,
                    "GroundMarker",
                    root.transform,
                    new Vector3(0f, 0.006f, 0f),
                    new Vector3(0.27f, 0.006f, 0.27f),
                    markerMaterial);
                marker.transform.localRotation = Quaternion.identity;

                var floating = new GameObject("FloatingVisual");
                floating.transform.SetParent(root.transform, false);
                floating.transform.localPosition = new Vector3(0f, 0.24f, 0f);

                CreatePrimitive(
                    PrimitiveType.Sphere,
                    "HealthOrb",
                    floating.transform,
                    Vector3.zero,
                    Vector3.one * 0.23f,
                    healthMaterial);
                CreatePrimitive(
                    PrimitiveType.Cube,
                    "CrossHorizontal",
                    floating.transform,
                    new Vector3(0f, 0f, -0.121f),
                    new Vector3(0.18f, 0.055f, 0.025f),
                    crossMaterial);
                CreatePrimitive(
                    PrimitiveType.Cube,
                    "CrossVertical",
                    floating.transform,
                    new Vector3(0f, 0f, -0.121f),
                    new Vector3(0.055f, 0.18f, 0.025f),
                    crossMaterial);

                PickupVisual visual = root.AddComponent<PickupVisual>();
                SetObjectReference(visual, "floatingRoot", floating.transform);
                GameObject saved = PrefabUtility.SaveAsPrefabAsset(root, HealthPrefabPath);
                if (saved == null)
                {
                    throw new InvalidOperationException("Unity could not save the HealthPickup prefab.");
                }

                return saved.GetComponent<PickupVisual>();
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static GameObject CreatePrimitive(
            PrimitiveType type,
            string name,
            Transform parent,
            Vector3 localPosition,
            Vector3 localScale,
            Material material)
        {
            GameObject value = GameObject.CreatePrimitive(type);
            value.name = name;
            value.transform.SetParent(parent, false);
            value.transform.localPosition = localPosition;
            value.transform.localScale = localScale;
            UnityEngine.Object.DestroyImmediate(value.GetComponent<Collider>());
            value.GetComponent<Renderer>().sharedMaterial = material;
            return value;
        }

        private static Material GetOrCreateMaterial(string path, Color color)
        {
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                Shader shader = Shader.Find("Standard");
                if (shader == null)
                {
                    throw new InvalidOperationException("The built-in Standard shader is unavailable.");
                }

                material = new Material(shader);
                AssetDatabase.CreateAsset(material, path);
            }

            material.color = color;
            EditorUtility.SetDirty(material);
            return material;
        }

        private static T EnsureComponent<T>(GameObject owner) where T : Component
        {
            T existing = owner.GetComponent<T>();
            return existing != null ? existing : Undo.AddComponent<T>(owner);
        }

        private static void SetObjectReference(
            UnityEngine.Object target,
            string propertyName,
            UnityEngine.Object value)
        {
            var serialized = new SerializedObject(target);
            SerializedProperty property = serialized.FindProperty(propertyName);
            if (property == null)
            {
                throw new InvalidOperationException(
                    $"{target.GetType().Name} has no serialized field named {propertyName}.");
            }

            property.objectReferenceValue = value;
            serialized.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(target);
        }

        private static void EnsureFolder(string assetFolder)
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
    }
}
#endif
