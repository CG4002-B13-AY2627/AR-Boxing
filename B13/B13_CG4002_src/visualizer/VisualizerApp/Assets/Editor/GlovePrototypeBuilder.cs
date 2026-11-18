#if UNITY_EDITOR
using CG4002.Visualizer.Presentation;
using UnityEditor;
using UnityEditor.Events;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

namespace CG4002.Visualizer.Editor
{
    public static class GlovePrototypeBuilder
    {
        [MenuItem("CG4002/Visualizer/Create Camera Glove Prototype")]
        public static void CreatePrototype()
        {
            CameraRelativeGloveRig existingRig =
                Object.FindFirstObjectByType<CameraRelativeGloveRig>();
            if (existingRig != null)
            {
                Selection.activeGameObject = existingRig.gameObject;
                EditorUtility.DisplayDialog(
                    "Camera glove prototype",
                    "This scene already contains a CameraRelativeGloveRig. It has been selected.",
                    "OK");
                return;
            }

            Camera camera = FindTargetCamera();
            if (camera == null)
            {
                EditorUtility.DisplayDialog(
                    "Camera glove prototype",
                    "No Camera was found. Create the AR Session and XR Origin (Mobile AR), then run this command again.",
                    "OK");
                return;
            }

            int undoGroup = Undo.GetCurrentGroup();
            Undo.SetCurrentGroupName("Create camera glove prototype");

            GameObject rigObject = new("CameraRelativeGloves");
            Undo.RegisterCreatedObjectUndo(rigObject, "Create camera glove rig");
            rigObject.transform.SetParent(camera.transform, false);

            Transform leftGlove = CreatePlaceholderGlove(rigObject.transform, "LeftGlove", true);
            Transform rightGlove = CreatePlaceholderGlove(rigObject.transform, "RightGlove", false);
            CameraRelativeGloveRig rig = Undo.AddComponent<CameraRelativeGloveRig>(rigObject);

            SerializedObject serializedRig = new(rig);
            serializedRig.FindProperty("arCamera").objectReferenceValue = camera;
            serializedRig.FindProperty("leftGlove").objectReferenceValue = leftGlove;
            serializedRig.FindProperty("rightGlove").objectReferenceValue = rightGlove;
            serializedRig.ApplyModifiedPropertiesWithoutUndo();

            EnsureEventSystem();
            CreateDebugCanvas(rig);

            Selection.activeGameObject = rigObject;
            EditorSceneManager.MarkSceneDirty(rigObject.scene);
            Undo.CollapseUndoOperations(undoGroup);
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

        private static Transform CreatePlaceholderGlove(Transform parent, string name, bool isLeft)
        {
            GameObject gloveRoot = new(name);
            Undo.RegisterCreatedObjectUndo(gloveRoot, "Create placeholder glove");
            gloveRoot.transform.SetParent(parent, false);
            gloveRoot.transform.localPosition = new Vector3(isLeft ? -0.25f : 0.25f, -0.18f, 0.65f);

            GameObject fist = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            fist.name = "Fist";
            Undo.RegisterCreatedObjectUndo(fist, "Create placeholder fist");
            fist.transform.SetParent(gloveRoot.transform, false);
            fist.transform.localScale = new Vector3(0.18f, 0.13f, 0.22f);
            Object.DestroyImmediate(fist.GetComponent<Collider>());

            GameObject cuff = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cuff.name = "Cuff";
            Undo.RegisterCreatedObjectUndo(cuff, "Create placeholder cuff");
            cuff.transform.SetParent(gloveRoot.transform, false);
            cuff.transform.localPosition = new Vector3(0f, -0.10f, -0.05f);
            cuff.transform.localScale = new Vector3(0.15f, 0.10f, 0.14f);
            Object.DestroyImmediate(cuff.GetComponent<Collider>());

            return gloveRoot.transform;
        }

        private static void EnsureEventSystem()
        {
            if (Object.FindFirstObjectByType<EventSystem>() != null)
            {
                return;
            }

            GameObject eventSystemObject = new("EventSystem");
            Undo.RegisterCreatedObjectUndo(eventSystemObject, "Create EventSystem");
            Undo.AddComponent<EventSystem>(eventSystemObject);
            Undo.AddComponent<InputSystemUIInputModule>(eventSystemObject);
        }

        private static void CreateDebugCanvas(CameraRelativeGloveRig rig)
        {
            GameObject canvasObject = new("GloveDebugCanvas");
            Undo.RegisterCreatedObjectUndo(canvasObject, "Create glove debug canvas");

            Canvas canvas = Undo.AddComponent<Canvas>(canvasObject);
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            Undo.AddComponent<GraphicRaycaster>(canvasObject);
            CanvasScaler scaler = Undo.AddComponent<CanvasScaler>(canvasObject);
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.matchWidthOrHeight = 0.5f;

            CreateButton(canvas.transform, "LeftUppercutButton", "L Upper", -510f, rig.LeftUppercut);
            CreateButton(canvas.transform, "LeftHookButton", "L Hook", -340f, rig.LeftHook);
            CreateButton(canvas.transform, "LeftJabButton", "L Jab", -170f, rig.LeftJab);
            CreateButton(canvas.transform, "GuardButton", "Guard", 0f, rig.Guard);
            CreateButton(canvas.transform, "RightJabButton", "R Jab", 170f, rig.RightJab);
            CreateButton(canvas.transform, "RightHookButton", "R Hook", 340f, rig.RightHook);
            CreateButton(canvas.transform, "RightUppercutButton", "R Upper", 510f, rig.RightUppercut);
        }

        internal static void EnsureWp3DebugButtons(CameraRelativeGloveRig rig)
        {
            GameObject canvasObject = GameObject.Find("GloveDebugCanvas");
            if (canvasObject == null)
            {
                CreateDebugCanvas(rig);
                return;
            }

            SetButtonHorizontalPosition(canvasObject.transform, "LeftHookButton", -340f);
            SetButtonHorizontalPosition(canvasObject.transform, "LeftJabButton", -170f);
            SetButtonHorizontalPosition(canvasObject.transform, "GuardButton", 0f);
            SetButtonHorizontalPosition(canvasObject.transform, "RightJabButton", 170f);
            SetButtonHorizontalPosition(canvasObject.transform, "RightHookButton", 340f);

            if (canvasObject.transform.Find("LeftUppercutButton") == null)
            {
                CreateButton(
                    canvasObject.transform,
                    "LeftUppercutButton",
                    "L Upper",
                    -510f,
                    rig.LeftUppercut);
            }

            if (canvasObject.transform.Find("RightUppercutButton") == null)
            {
                CreateButton(
                    canvasObject.transform,
                    "RightUppercutButton",
                    "R Upper",
                    510f,
                    rig.RightUppercut);
            }
        }

        private static void SetButtonHorizontalPosition(
            Transform canvas,
            string buttonName,
            float horizontalPosition)
        {
            Transform button = canvas.Find(buttonName);
            if (button == null ||
                !button.TryGetComponent(out RectTransform buttonRect))
            {
                return;
            }

            Undo.RecordObject(buttonRect, "Arrange WP3 punch buttons");
            buttonRect.anchoredPosition = new Vector2(
                horizontalPosition,
                buttonRect.anchoredPosition.y);
        }

        private static void CreateButton(
            Transform parent,
            string objectName,
            string label,
            float horizontalPosition,
            UnityAction callback)
        {
            GameObject buttonObject = new(objectName, typeof(RectTransform), typeof(CanvasRenderer));
            Undo.RegisterCreatedObjectUndo(buttonObject, "Create glove debug button");
            buttonObject.transform.SetParent(parent, false);

            RectTransform buttonRect = buttonObject.GetComponent<RectTransform>();
            buttonRect.anchorMin = new Vector2(0.5f, 1f);
            buttonRect.anchorMax = new Vector2(0.5f, 1f);
            buttonRect.pivot = new Vector2(0.5f, 1f);
            buttonRect.anchoredPosition = new Vector2(horizontalPosition, -24f);
            buttonRect.sizeDelta = new Vector2(150f, 72f);

            Image image = Undo.AddComponent<Image>(buttonObject);
            image.color = new Color(0.92f, 0.92f, 0.92f, 0.88f);
            Button button = Undo.AddComponent<Button>(buttonObject);
            button.targetGraphic = image;
            UnityEventTools.AddPersistentListener(button.onClick, callback);

            GameObject textObject = new("Label", typeof(RectTransform), typeof(CanvasRenderer));
            Undo.RegisterCreatedObjectUndo(textObject, "Create glove debug label");
            textObject.transform.SetParent(buttonObject.transform, false);
            RectTransform textRect = textObject.GetComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero;
            textRect.anchorMax = Vector2.one;
            textRect.offsetMin = Vector2.zero;
            textRect.offsetMax = Vector2.zero;

            Text text = Undo.AddComponent<Text>(textObject);
            text.text = label;
            text.alignment = TextAnchor.MiddleCenter;
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = 28;
            text.color = Color.black;
        }
    }
}
#endif
