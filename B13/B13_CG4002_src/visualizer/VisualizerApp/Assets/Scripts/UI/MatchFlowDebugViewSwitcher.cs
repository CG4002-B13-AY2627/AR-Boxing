using System;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Input;
using UnityEngine;
using UnityEngine.InputSystem;

namespace CG4002.Visualizer.UI
{
    public static class MatchFlowDebugPhaseCycle
    {
        private static readonly MatchFlowPhase[] PreviewOrder =
        {
            MatchFlowPhase.Connecting,
            MatchFlowPhase.Lobby,
            MatchFlowPhase.Calibrating,
            MatchFlowPhase.Countdown,
            MatchFlowPhase.Fighting,
            MatchFlowPhase.Paused,
            MatchFlowPhase.RoundEnd,
            MatchFlowPhase.MatchEnd,
            MatchFlowPhase.SafetyStop
        };

        public static MatchFlowPhase Step(MatchFlowPhase current, int direction)
        {
            int currentIndex = Array.IndexOf(PreviewOrder, current);
            if (currentIndex < 0)
            {
                currentIndex = 0;
            }

            int offset = direction < 0 ? -1 : 1;
            int nextIndex = (currentIndex + offset + PreviewOrder.Length) % PreviewOrder.Length;
            return PreviewOrder[nextIndex];
        }
    }

    /// <summary>
    /// Local-only view preview. It never writes MatchState or requests a server
    /// transition. Authoritative phase changes immediately replace the preview.
    /// </summary>
    public sealed class MatchFlowDebugViewSwitcher : MonoBehaviour
    {
        [SerializeField] private HeadsetInputRouter inputRouter;
        [SerializeField] private MatchFlowPlaceholderViews views;
        [SerializeField] private bool enableInEditor = true;
        [SerializeField] private bool enableInDevelopmentBuild;

        private bool DebugPreviewAvailable =>
            (Application.isEditor && enableInEditor) ||
            (!Application.isEditor && Debug.isDebugBuild && enableInDevelopmentBuild);

        private void OnEnable()
        {
            if (DebugPreviewAvailable && inputRouter != null)
            {
                inputRouter.ActionTriggered += HandleAction;
            }
        }

        private void OnDisable()
        {
            if (inputRouter != null)
            {
                inputRouter.ActionTriggered -= HandleAction;
            }
        }

        private void Update()
        {
            if (DebugPreviewAvailable && Application.isEditor && views != null &&
                Keyboard.current != null && Keyboard.current.rKey.wasPressedThisFrame)
            {
                ReturnToLiveState();
            }
        }

        private void HandleAction(HeadsetAction action)
        {
            if (views == null)
            {
                return;
            }

            MatchFlowPhase next = MatchFlowDebugPhaseCycle.Step(
                views.DisplayedPhase,
                action == HeadsetAction.Primary ? 1 : -1);
            views.Preview(next);
        }

        [ContextMenu("Preview Next Match Flow View")]
        public void PreviewNext()
        {
            if (DebugPreviewAvailable && views != null)
            {
                views.Preview(MatchFlowDebugPhaseCycle.Step(views.DisplayedPhase, 1));
            }
        }

        [ContextMenu("Preview Previous Match Flow View")]
        public void PreviewPrevious()
        {
            if (DebugPreviewAvailable && views != null)
            {
                views.Preview(MatchFlowDebugPhaseCycle.Step(views.DisplayedPhase, -1));
            }
        }

        [ContextMenu("Return To Live Match Flow View")]
        public void ReturnToLiveState()
        {
            if (DebugPreviewAvailable && views != null)
            {
                views.ReturnToLiveState();
            }
        }
    }
}
