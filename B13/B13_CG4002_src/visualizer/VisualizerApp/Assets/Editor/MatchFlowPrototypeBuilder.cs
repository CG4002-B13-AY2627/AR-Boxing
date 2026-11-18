#if UNITY_EDITOR
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Input;
using CG4002.Visualizer.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace CG4002.Visualizer.Editor
{
    public static class MatchFlowPrototypeBuilder
    {
        [MenuItem("CG4002/Visualizer/Set Up Match Flow Prototype")]
        public static void SetUp()
        {
            MatchController controller = Object.FindFirstObjectByType<MatchController>();
            if (controller == null)
            {
                EditorUtility.DisplayDialog(
                    "Match flow prototype",
                    "No MatchController was found in the open scene.",
                    "OK");
                return;
            }

            int undoGroup = Undo.GetCurrentGroup();
            Undo.SetCurrentGroupName("Set up match flow prototype");

            GameObject host = controller.gameObject;
            MatchFlowPresenter presenter = host.GetComponent<MatchFlowPresenter>();
            if (presenter == null)
            {
                presenter = Undo.AddComponent<MatchFlowPresenter>(host);
            }

            SerializedObject serializedPresenter = new(presenter);
            serializedPresenter.FindProperty("controller").objectReferenceValue = controller;
            serializedPresenter.ApplyModifiedProperties();

            MatchFlowPlaceholderViews views = host.GetComponent<MatchFlowPlaceholderViews>();
            if (views == null)
            {
                views = Undo.AddComponent<MatchFlowPlaceholderViews>(host);
            }

            SerializedObject serializedViews = new(views);
            serializedViews.FindProperty("presenter").objectReferenceValue = presenter;
            serializedViews.FindProperty("buildAtRuntime").boolValue = true;
            serializedViews.ApplyModifiedProperties();

            HeadsetInputRouter inputRouter = host.GetComponent<HeadsetInputRouter>();
            if (inputRouter == null)
            {
                inputRouter = Undo.AddComponent<HeadsetInputRouter>(host);
            }

            MatchFlowDebugViewSwitcher debugSwitcher = host.GetComponent<MatchFlowDebugViewSwitcher>();
            if (debugSwitcher == null)
            {
                debugSwitcher = Undo.AddComponent<MatchFlowDebugViewSwitcher>(host);
            }

            SerializedObject serializedSwitcher = new(debugSwitcher);
            serializedSwitcher.FindProperty("inputRouter").objectReferenceValue = inputRouter;
            serializedSwitcher.FindProperty("views").objectReferenceValue = views;
            serializedSwitcher.FindProperty("enableInEditor").boolValue = true;
            serializedSwitcher.FindProperty("enableInDevelopmentBuild").boolValue = false;
            serializedSwitcher.ApplyModifiedProperties();

            Selection.activeGameObject = host;
            EditorSceneManager.MarkSceneDirty(host.scene);
            Undo.CollapseUndoOperations(undoGroup);
            Debug.Log("Match flow prototype is wired on " + host.name + ". Save the scene to keep the setup.");
        }
    }
}
#endif
