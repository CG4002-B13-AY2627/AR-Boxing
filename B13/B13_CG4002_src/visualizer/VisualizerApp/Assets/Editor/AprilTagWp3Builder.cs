using CG4002.Visualizer.AR;
using CG4002.Visualizer.Presentation;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace CG4002.Visualizer.Editor
{
    public static class AprilTagWp3Builder
    {
        [MenuItem("CG4002/Visualizer/Set Up AprilTag WP3 Targeted Punches")]
        public static void SetUpAprilTagWp3()
        {
            CameraRelativeGloveRig gloveRig =
                Object.FindFirstObjectByType<CameraRelativeGloveRig>();
            OpponentTargetProvider targetProvider =
                Object.FindFirstObjectByType<OpponentTargetProvider>();

            if (gloveRig == null || targetProvider == null)
            {
                EditorUtility.DisplayDialog(
                    "AprilTag WP3",
                    "WP3 needs both CameraRelativeGloveRig and AprilTag WP2 Target Provider in the open scene.",
                    "OK");
                return;
            }

            var serializedRig = new SerializedObject(gloveRig);
            serializedRig.FindProperty("targetProvider").objectReferenceValue =
                targetProvider;
            serializedRig.FindProperty("useTrackedTargets").boolValue = true;
            serializedRig.ApplyModifiedProperties();

            GlovePrototypeBuilder.EnsureWp3DebugButtons(gloveRig);
            Selection.activeGameObject = gloveRig.gameObject;
            EditorSceneManager.MarkSceneDirty(gloveRig.gameObject.scene);
            UnityEngine.Debug.Log(
                "AprilTag WP3 is ready. Save the scene, then test the six punch buttons with a valid WP2 marker target.",
                gloveRig);
        }

        [MenuItem("CG4002/Visualizer/Apply WP4 Refined Punch Animation")]
        public static void ApplyWp4AnimationDefaults()
        {
            CameraRelativeGloveRig gloveRig =
                Object.FindFirstObjectByType<CameraRelativeGloveRig>();
            if (gloveRig == null)
            {
                EditorUtility.DisplayDialog(
                    "AprilTag WP4",
                    "No CameraRelativeGloveRig was found in the open scene.",
                    "OK");
                return;
            }

            var serializedRig = new SerializedObject(gloveRig);
            serializedRig.FindProperty("targetedHookArcDistance").floatValue = 0.18f;
            serializedRig.FindProperty("targetedHookVerticalLift").floatValue = 0.12f;
            serializedRig.FindProperty("targetedUppercutDip").floatValue = 0.12f;
            serializedRig.FindProperty("hookDuration").floatValue = 0.46f;
            serializedRig.FindProperty("uppercutDuration").floatValue = 0.48f;
            serializedRig.FindProperty("uppercutInwardYawDegrees").floatValue = 65f;
            serializedRig.FindProperty("uppercutPitchDegrees").floatValue = 0f;
            serializedRig.ApplyModifiedProperties();

            Selection.activeGameObject = gloveRig.gameObject;
            EditorSceneManager.MarkSceneDirty(gloveRig.gameObject.scene);
            UnityEngine.Debug.Log(
                "WP4 punch defaults applied. Save the scene, then tune the hook arc and uppercut yaw on the physical iPhone build.",
                gloveRig);
        }
    }
}
