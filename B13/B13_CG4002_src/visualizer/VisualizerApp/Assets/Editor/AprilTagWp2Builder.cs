using CG4002.Visualizer.AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace CG4002.Visualizer.Editor
{
    public static class AprilTagWp2Builder
    {
        [MenuItem("CG4002/Visualizer/Set Up AprilTag WP2 Target Provider")]
        public static void SetUpAprilTagWp2()
        {
            AprilTagOpponentTracker tracker =
                Object.FindFirstObjectByType<AprilTagOpponentTracker>();
            if (tracker == null)
            {
                EditorUtility.DisplayDialog(
                    "AprilTag WP2",
                    "No AprilTag WP1 Tracker was found. Run CG4002 > Visualizer > Set Up AprilTag WP1 in the working AR scene first.",
                    "OK");
                return;
            }

            OpponentTargetProvider provider =
                Object.FindFirstObjectByType<OpponentTargetProvider>();
            if (provider == null)
            {
                var providerObject = new GameObject("AprilTag WP2 Target Provider");
                Undo.RegisterCreatedObjectUndo(
                    providerObject,
                    "Create AprilTag WP2 Target Provider");
                provider = Undo.AddComponent<OpponentTargetProvider>(providerObject);
            }

            Transform smoothedRoot = GetOrCreateChild(
                provider.transform,
                "Smoothed Marker Pose",
                Vector3.zero);
            Transform chest = GetOrCreateChild(
                smoothedRoot,
                "Chest Target",
                Vector3.zero);
            Transform head = GetOrCreateChild(
                smoothedRoot,
                "Head Target",
                new Vector3(0f, 0.35f, 0f));
            Transform leftBody = GetOrCreateChild(
                smoothedRoot,
                "Left Body Target",
                new Vector3(-0.18f, -0.10f, 0f));
            Transform rightBody = GetOrCreateChild(
                smoothedRoot,
                "Right Body Target",
                new Vector3(0.18f, -0.10f, 0f));

            var serializedProvider = new SerializedObject(provider);
            serializedProvider.FindProperty("source").objectReferenceValue = tracker;
            serializedProvider.FindProperty("smoothedPoseRoot").objectReferenceValue = smoothedRoot;
            serializedProvider.FindProperty("chestTarget").objectReferenceValue = chest;
            serializedProvider.FindProperty("headTarget").objectReferenceValue = head;
            serializedProvider.FindProperty("leftBodyTarget").objectReferenceValue = leftBody;
            serializedProvider.FindProperty("rightBodyTarget").objectReferenceValue = rightBody;
            serializedProvider.ApplyModifiedProperties();

            Selection.activeGameObject = provider.gameObject;
            EditorSceneManager.MarkSceneDirty(provider.gameObject.scene);
            UnityEngine.Debug.Log(
                "AprilTag WP2 target provider is ready. Save the scene, then deploy to an iPhone to tune smoothing and target offsets.",
                provider);
        }

        private static Transform GetOrCreateChild(
            Transform parent,
            string objectName,
            Vector3 defaultLocalPosition)
        {
            Transform existing = parent.Find(objectName);
            if (existing != null)
            {
                return existing;
            }

            var child = new GameObject(objectName);
            Undo.RegisterCreatedObjectUndo(child, $"Create {objectName}");
            child.transform.SetParent(parent, false);
            child.transform.localPosition = defaultLocalPosition;
            return child.transform;
        }
    }
}
