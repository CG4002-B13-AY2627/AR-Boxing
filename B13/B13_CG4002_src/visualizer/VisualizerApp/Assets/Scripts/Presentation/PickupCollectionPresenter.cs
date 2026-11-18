using System;
using System.Collections.Generic;
using CG4002.Visualizer.Development;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Models;
using CG4002.Visualizer.UI;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    /// <summary>
    /// Presents accepted ITEM_PICKUP events. The debug range gate is only a local
    /// stand-in for the future authority; accepted network events are always trusted.
    /// </summary>
    public sealed class PickupCollectionPresenter : MonoBehaviour
    {
        [SerializeField] private MatchController controller;
        [SerializeField] private PickupSpawnPresenter pickupPresenter;
        [SerializeField] private PickupReachPresenter reachPresenter;
        [SerializeField] private HudToastPresenter toastPresenter;
        [SerializeField] private MockGameEventSource debugEventSource;
        [SerializeField] private Camera arCamera;
        [SerializeField, Range(1, 2)] private int localPlayerId = 1;
        [SerializeField, Min(0.1f)] private float maximumDebugPickupDistanceMetres = 2f;
        [SerializeField, Range(8, 256)] private int maximumRememberedCollections = 128;

        private readonly HashSet<string> presentedItemIds = new(StringComparer.Ordinal);
        private readonly Queue<string> presentedOrder = new();
        private bool subscribed;

        public float MaximumDebugPickupDistanceMetres => maximumDebugPickupDistanceMetres;
        public int PresentedCollectionCount => presentedItemIds.Count;

        private void Awake()
        {
            if (arCamera == null)
            {
                arCamera = Camera.main;
            }
        }

        private void OnEnable()
        {
            Subscribe();
        }

        private void OnDisable()
        {
            Unsubscribe();
        }

        public void CollectNearestHealthForDebug()
        {
            TryCollectNearestHealthForDebug();
        }

        public bool TryCollectNearestHealthForDebug()
        {
            if (pickupPresenter == null || arCamera == null || debugEventSource == null ||
                !pickupPresenter.TryGetNearestVisual(
                    arCamera.transform.position,
                    out PickupVisual pickup))
            {
                ShowDebugRejection("NO HEALTH PICKUP TO COLLECT");
                return false;
            }

            if (!PickupCollectionRules.IsWithinCameraRange(
                    arCamera.transform.position,
                    pickup.ContactPosition,
                    maximumDebugPickupDistanceMetres))
            {
                ShowDebugRejection(
                    $"PICKUP TOO FAR  -  MAX {maximumDebugPickupDistanceMetres:0.0} M");
                return false;
            }

            Vector3 viewport = arCamera.WorldToViewportPoint(pickup.ContactPosition);
            string hand = PickupReachTargeting.ShouldUseLeftHand(viewport.x)
                ? "LEFT"
                : "RIGHT";
            return debugEventSource.TryCollectActiveHealthPickup(hand);
        }

        private void ObserveGameEvent(GameEventMessage gameEvent)
        {
            if (gameEvent == null || gameEvent.@event != "ITEM_PICKUP" ||
                gameEvent.item_type != "HEALTH" ||
                gameEvent.source_player != localPlayerId ||
                string.IsNullOrEmpty(gameEvent.item_id) ||
                !RememberCollection(gameEvent.item_id))
            {
                return;
            }

            if (pickupPresenter != null &&
                pickupPresenter.TryBeginCollection(gameEvent.item_id, out PickupVisual visual))
            {
                float magnitude = visual.Magnitude;
                Action contact = () => CompletePresentation(
                    gameEvent.item_id,
                    magnitude,
                    visual);
                if (reachPresenter == null ||
                    !reachPresenter.TryReachPickup(visual, gameEvent.hand, contact))
                {
                    contact();
                }

                return;
            }

            // The state may have converged before this transient event arrived.
            // Acknowledge it visually, but never invent an item or mutate health.
            toastPresenter?.ShowCollection(gameEvent.item_id, 0f);
        }

        private void CompletePresentation(
            string itemId,
            float magnitude,
            PickupVisual visual)
        {
            if (visual != null)
            {
                visual.PlayCollectionEffect();
            }

            toastPresenter?.ShowCollection(itemId, magnitude);
        }

        private bool RememberCollection(string itemId)
        {
            if (!presentedItemIds.Add(itemId))
            {
                return false;
            }

            presentedOrder.Enqueue(itemId);
            while (presentedOrder.Count > maximumRememberedCollections)
            {
                presentedItemIds.Remove(presentedOrder.Dequeue());
            }

            return true;
        }

        private void ShowDebugRejection(string message)
        {
            toastPresenter?.ShowMessage(
                $"debug-pickup-rejection:{Time.frameCount}",
                message);
        }

        private void Subscribe()
        {
            if (controller == null || subscribed)
            {
                return;
            }

            controller.GameEventReceived += ObserveGameEvent;
            subscribed = true;
        }

        private void Unsubscribe()
        {
            if (controller != null && subscribed)
            {
                controller.GameEventReceived -= ObserveGameEvent;
            }

            subscribed = false;
        }

#if UNITY_EDITOR
        public void ConfigureForTesting(
            MatchController matchController,
            PickupSpawnPresenter spawnPresenter,
            PickupReachPresenter pickupReachPresenter,
            HudToastPresenter toast,
            MockGameEventSource eventSource,
            Camera camera,
            float maximumDistance = 2f)
        {
            Unsubscribe();
            controller = matchController;
            pickupPresenter = spawnPresenter;
            reachPresenter = pickupReachPresenter;
            toastPresenter = toast;
            debugEventSource = eventSource;
            arCamera = camera;
            maximumDebugPickupDistanceMetres = maximumDistance;
            if (isActiveAndEnabled)
            {
                Subscribe();
            }
        }

        public void ApplyEventForTesting(GameEventMessage gameEvent)
        {
            ObserveGameEvent(gameEvent);
        }

        public void SetMaximumDistanceForTesting(float maximumDistance)
        {
            maximumDebugPickupDistanceMetres = Mathf.Max(0.1f, maximumDistance);
        }
#endif

        private void OnValidate()
        {
            localPlayerId = Mathf.Clamp(localPlayerId, 1, 2);
            maximumDebugPickupDistanceMetres = Mathf.Max(
                0.1f,
                maximumDebugPickupDistanceMetres);
            maximumRememberedCollections = Mathf.Clamp(
                maximumRememberedCollections,
                8,
                256);
        }
    }
}
