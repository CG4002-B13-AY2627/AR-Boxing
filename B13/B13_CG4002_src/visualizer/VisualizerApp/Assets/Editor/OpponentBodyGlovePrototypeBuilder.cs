#if UNITY_EDITOR
using CG4002.Visualizer.Tracking;
using Unity.XR.CoreUtils;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.XR.ARFoundation;

namespace CG4002.Visualizer.Editor
{
    public static class OpponentBodyGlovePrototypeBuilder
    {
        [MenuItem("CG4002/Visualizer/Create Opponent Body Glove Prototype")]
        public static void CreatePrototype()
        {
            CreatePrototype(true);
        }

        // Used by automated project setup and verification. The normal Unity menu
        // command above deliberately leaves saving under the developer's control.
        public static void ConfigureMainSceneForBatch()
        {
            Scene scene = EditorSceneManager.OpenScene(
                "Assets/Scenes/Main.unity",
                OpenSceneMode.Single);
            if (!CreatePrototype(false))
            {
                throw new System.InvalidOperationException(
                    "Could not configure opponent body gloves in Main.unity.");
            }

            EditorSceneManager.SaveScene(scene);
        }

        private static bool CreatePrototype(bool showDialogs)
        {
            OpponentBodyGloveTracker existingTracker =
                Object.FindFirstObjectByType<OpponentBodyGloveTracker>();
            if (existingTracker != null)
            {
                Selection.activeGameObject = existingTracker.gameObject;
                if (showDialogs)
                {
                    EditorUtility.DisplayDialog(
                        "Opponent body gloves",
                        "This scene already contains an OpponentBodyGloveTracker. It has been selected.",
                        "OK");
                }

                return true;
            }

            Camera camera = FindTargetCamera();
            XROrigin xrOrigin = camera != null
                ? camera.GetComponentInParent<XROrigin>()
                : Object.FindFirstObjectByType<XROrigin>();
            if (camera == null || xrOrigin == null)
            {
                if (showDialogs)
                {
                    EditorUtility.DisplayDialog(
                        "Opponent body gloves",
                        "No AR Camera inside an XR Origin was found. Open the AR scene, select its AR Camera, and run this command again.",
                        "OK");
                }

                return false;
            }

            int undoGroup = Undo.GetCurrentGroup();
            Undo.SetCurrentGroupName("Create opponent body glove prototype");

            ARHumanBodyManager bodyManager = xrOrigin.GetComponent<ARHumanBodyManager>();
            if (bodyManager == null)
            {
                bodyManager = Undo.AddComponent<ARHumanBodyManager>(xrOrigin.gameObject);
            }

            Undo.RecordObject(bodyManager, "Configure 3D body tracking");
            bodyManager.pose2DRequested = false;
            bodyManager.pose3DRequested = true;
            bodyManager.pose3DScaleEstimationRequested = true;
            EditorUtility.SetDirty(bodyManager);

            GameObject trackerObject = new("OpponentBodyGloves");
            Undo.RegisterCreatedObjectUndo(trackerObject, "Create opponent body gloves");
            trackerObject.transform.SetParent(xrOrigin.transform, false);

            Transform leftGlove = CreatePlaceholderGlove(
                trackerObject.transform,
                "OpponentLeftGlove",
                new Vector3(-0.3f, 1.25f, 1.5f));
            Transform rightGlove = CreatePlaceholderGlove(
                trackerObject.transform,
                "OpponentRightGlove",
                new Vector3(0.3f, 1.25f, 1.5f));

            OpponentBodyGloveTracker tracker =
                Undo.AddComponent<OpponentBodyGloveTracker>(trackerObject);
            SerializedObject serializedTracker = new(tracker);
            serializedTracker.FindProperty("humanBodyManager").objectReferenceValue = bodyManager;
            serializedTracker.FindProperty("arCamera").objectReferenceValue = camera;
            serializedTracker.FindProperty("leftGlove").objectReferenceValue = leftGlove;
            serializedTracker.FindProperty("rightGlove").objectReferenceValue = rightGlove;
            serializedTracker.ApplyModifiedPropertiesWithoutUndo();

            Selection.activeGameObject = trackerObject;
            EditorSceneManager.MarkSceneDirty(trackerObject.scene);
            Undo.CollapseUndoOperations(undoGroup);

            if (showDialogs)
            {
                EditorUtility.DisplayDialog(
                    "Opponent body gloves created",
                    "The XR Origin now requests 3D human-body tracking. Save the scene, build on the Mac, and test with a full person visible to the iPhone's rear camera.",
                    "OK");
            }

            return true;
        }

        private static Camera FindTargetCamera()
        {
            if (Selection.activeGameObject != null)
            {
                Camera selectedCamera = Selection.activeGameObject.GetComponent<Camera>();
                if (selectedCamera != null)
                {
                    return selectedCamera;
                }

                selectedCamera = Selection.activeGameObject.GetComponentInChildren<Camera>();
                if (selectedCamera != null)
                {
                    return selectedCamera;
                }
            }

            return Camera.main != null ? Camera.main : Object.FindFirstObjectByType<Camera>();
        }

        private static Transform CreatePlaceholderGlove(
            Transform parent,
            string name,
            Vector3 previewPosition)
        {
            GameObject gloveRoot = new(name);
            Undo.RegisterCreatedObjectUndo(gloveRoot, "Create opponent glove");
            gloveRoot.transform.SetParent(parent, false);
            gloveRoot.transform.localPosition = previewPosition;

            GameObject fist = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            fist.name = "Fist";
            Undo.RegisterCreatedObjectUndo(fist, "Create glove fist");
            fist.transform.SetParent(gloveRoot.transform, false);
            fist.transform.localScale = new Vector3(0.20f, 0.16f, 0.22f);
            Object.DestroyImmediate(fist.GetComponent<Collider>());

            GameObject cuff = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cuff.name = "Cuff";
            Undo.RegisterCreatedObjectUndo(cuff, "Create glove cuff");
            cuff.transform.SetParent(gloveRoot.transform, false);
            cuff.transform.localPosition = new Vector3(0f, -0.12f, 0f);
            cuff.transform.localScale = new Vector3(0.15f, 0.12f, 0.16f);
            Object.DestroyImmediate(cuff.GetComponent<Collider>());

            return gloveRoot.transform;
        }
    }
}
#endif
