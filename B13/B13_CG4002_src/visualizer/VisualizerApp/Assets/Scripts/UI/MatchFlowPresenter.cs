using System;
using System.Collections.Generic;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Networking;
using UnityEngine;

namespace CG4002.Visualizer.UI
{
    /// <summary>
    /// Thin Unity adapter for the pure MatchFlowRouter. Concrete menu views subscribe
    /// to PhaseChanged in WP2; this component never mutates authoritative match data.
    /// </summary>
    public sealed class MatchFlowPresenter : MonoBehaviour
    {
        [SerializeField] private MatchController controller;

        private readonly MatchFlowRouter router = new();
        private readonly HashSet<string> warnedUnknownStates = new(StringComparer.OrdinalIgnoreCase);

        public MatchFlowPhase CurrentPhase => router.Current;

        public event Action<MatchFlowRoute> PhaseChanged;

        private void OnEnable()
        {
            if (controller == null)
            {
                return;
            }

            controller.StateChanged += RefreshState;
            controller.ConnectionStatusChanged += RefreshConnection;
            Publish(router.Route(controller.Current.State, controller.ConnectionStatus));
        }

        private void OnDisable()
        {
            if (controller == null)
            {
                return;
            }

            controller.StateChanged -= RefreshState;
            controller.ConnectionStatusChanged -= RefreshConnection;
        }

        private void RefreshState(MatchSnapshot snapshot)
        {
            Publish(router.Route(snapshot.State, controller.ConnectionStatus));
        }

        private void RefreshConnection(ConnectionStatus status)
        {
            // Re-route the latest snapshot when a connection returns. No new packet is
            // required for the presentation to converge on the stored authoritative state.
            Publish(router.Route(controller.Current.State, status));
        }

        private void Publish(MatchFlowRoute route)
        {
            if (!route.AuthoritativeStateRecognized &&
                controller.ConnectionStatus == ConnectionStatus.Connected)
            {
                string rawState = controller.Current.State ?? string.Empty;
                if (warnedUnknownStates.Add(rawState))
                {
                    Debug.LogWarning($"Unknown authoritative match state '{rawState}'. Showing safety stop.");
                }
            }

            if (route.Changed)
            {
                PhaseChanged?.Invoke(route);
            }
        }
    }
}
