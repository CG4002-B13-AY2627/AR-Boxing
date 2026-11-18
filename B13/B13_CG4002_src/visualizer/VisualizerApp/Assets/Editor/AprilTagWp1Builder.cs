using CG4002.Visualizer.AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace CG4002.Visualizer.Editor
{
    public static class AprilTagWp1Builder
    {
        [MenuItem("CG4002/Visualizer/Set Up AprilTag WP1")]
        public static void SetUpAprilTagWp1()
        {
            ARCameraManager cameraManager =
                Object.FindFirstObjectByType<ARCameraManager>();
            if (cameraManager == null)
            {
                EditorUtility.DisplayDialog(
                    "AprilTag WP1",
                    "No AR Camera Manager was found. Open the AR scene containing the XR Origin and AR Camera, then try again.",
                    "OK");
                return;
            }

            AprilTagOpponentTracker tracker =
                Object.FindFirstObjectByType<AprilTagOpponentTracker>();
            if (tracker == null)
            {
                var gameObject = new GameObject("AprilTag WP1 Tracker");
                Undo.RegisterCreatedObjectUndo(gameObject, "Create AprilTag WP1 Tracker");
                tracker = Undo.AddComponent<AprilTagOpponentTracker>(gameObject);
            }

            var serializedTracker = new SerializedObject(tracker);
            serializedTracker.FindProperty("cameraManager").objectReferenceValue = cameraManager;
            serializedTracker.FindProperty("arCamera").objectReferenceValue =
                cameraManager.GetComponent<Camera>();
            serializedTracker.ApplyModifiedPropertiesWithoutUndo();

            Selection.activeGameObject = tracker.gameObject;
            EditorSceneManager.MarkSceneDirty(tracker.gameObject.scene);
            UnityEngine.Debug.Log(
                "AprilTag WP1 is set up. Configure tag ID and inner black-square size on the selected component, then save the scene.",
                tracker);
        }

        [MenuItem("CG4002/Visualizer/AprilTag/Fix Rear-Camera Left-Right Mirroring")]
        public static void FixRearCameraLeftRightMirroring()
        {
            AprilTagOpponentTracker tracker =
                Object.FindFirstObjectByType<AprilTagOpponentTracker>();
            if (tracker == null)
            {
                EditorUtility.DisplayDialog(
                    "AprilTag orientation",
                    "No AprilTag WP1 Tracker was found in the open scene.",
                    "OK");
                return;
            }

            var serializedTracker = new SerializedObject(tracker);
            serializedTracker.FindProperty("imageTransformation").intValue =
                (int)XRCpuImage.Transformation.None;
            serializedTracker.ApplyModifiedProperties();

            Selection.activeGameObject = tracker.gameObject;
            EditorSceneManager.MarkSceneDirty(tracker.gameObject.scene);
            UnityEngine.Debug.Log(
                "AprilTag input is now unmirrored (Transformation.None). Save the scene and rebuild the iOS app.",
                tracker);
        }
    }
}
