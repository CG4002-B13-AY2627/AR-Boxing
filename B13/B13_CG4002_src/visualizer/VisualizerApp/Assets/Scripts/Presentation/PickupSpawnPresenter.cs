using System;
using System.Collections.Generic;
using CG4002.Visualizer.AR;
using CG4002.Visualizer.Game;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    /// <summary>
    /// Reconciles authoritative active item IDs with fixed world-space visuals.
    /// It does not decide collection or modify player stats.
    /// </summary>
    public sealed class PickupSpawnPresenter : MonoBehaviour
    {
        [SerializeField] private MatchController controller;
        [SerializeField] private FloorPlaneProvider floorProvider;
        [SerializeField] private PickupVisual healthPickupPrefab;
        [SerializeField] private Transform visualRoot;
        [SerializeField, Range(1, 2)] private int localPlayerId = 1;
        [SerializeField, Range(1, 8)] private int maximumVisibleItems = 8;
        [SerializeField, Min(0f)] private float minimumSpawnDistanceMetres = 0.70f;
        [SerializeField, Min(0f)] private float maximumSpawnDistanceMetres = 1.25f;
        [SerializeField, Range(-90f, 0f)] private float minimumBearingDegrees = -65f;
        [SerializeField, Range(0f, 90f)] private float maximumBearingDegrees = 65f;
        [SerializeField, Min(0f)] private float minimumItemSeparationMetres = 0.35f;
        [SerializeField, Min(0f)] private float unmatchedRemovalGraceSeconds = 0.25f;

        private readonly Dictionary<string, PickupVisual> activeVisuals =
            new(StringComparer.Ordinal);
        private readonly Dictionary<string, PickupSnapshot> pendingItems =
            new(StringComparer.Ordinal);
        private readonly HashSet<string> incomingIds = new(StringComparer.Ordinal);
        private readonly List<string> removalScratch = new(8);

        public int ActiveVisualCount => activeVisuals.Count;
        public int PendingItemCount => pendingItems.Count;

        public bool TryGetNearestVisual(Vector3 origin, out PickupVisual nearest)
        {
            nearest = null;
            float nearestSquared = float.PositiveInfinity;
            foreach (PickupVisual visual in activeVisuals.Values)
            {
                if (visual == null || visual.IsCollecting || visual.IsRetiring)
                {
                    continue;
                }

                float squared = (visual.ContactPosition - origin).sqrMagnitude;
                if (squared < nearestSquared)
                {
                    nearest = visual;
                    nearestSquared = squared;
                }
            }

            return nearest != null;
        }

        public bool TryGetVisual(string itemId, out PickupVisual visual)
        {
            visual = null;
            return !string.IsNullOrEmpty(itemId) &&
                   activeVisuals.TryGetValue(itemId, out visual) &&
                   visual != null;
        }

        public bool TryBeginCollection(string itemId, out PickupVisual visual)
        {
            if (!TryGetVisual(itemId, out visual))
            {
                return false;
            }

            visual.BeginCollection();
            return true;
        }

        private void Awake()
        {
            if (visualRoot == null)
            {
                var root = new GameObject("PickupVisuals");
                root.transform.SetParent(transform, false);
                visualRoot = root.transform;
            }
        }

        private void OnEnable()
        {
            if (controller == null)
            {
                return;
            }

            controller.StateChanged += Reconcile;
            Reconcile(controller.Current);
        }

        private void OnDisable()
        {
            if (controller != null)
            {
                controller.StateChanged -= Reconcile;
            }

            if (floorProvider != null)
            {
                floorProvider.SetPlacementRequested(false);
            }
        }

        private void Update()
        {
            if (floorProvider == null || !floorProvider.IsReady || pendingItems.Count == 0)
            {
                UpdateFloorRequest();
                return;
            }

            removalScratch.Clear();
            foreach (KeyValuePair<string, PickupSnapshot> pair in pendingItems)
            {
                if (activeVisuals.Count >= maximumVisibleItems)
                {
                    break;
                }

                if (TrySpawn(pair.Value))
                {
                    removalScratch.Add(pair.Key);
                }
            }

            foreach (string id in removalScratch)
            {
                pendingItems.Remove(id);
            }

            UpdateFloorRequest();
        }

        private void Reconcile(MatchSnapshot snapshot)
        {
            incomingIds.Clear();
            IReadOnlyList<PickupSnapshot> items = snapshot?.ActiveItems;
            if (items != null)
            {
                for (int index = 0; index < items.Count &&
                    incomingIds.Count < maximumVisibleItems; index++)
                {
                    PickupSnapshot item = items[index];
                    if (!ShouldRender(item, localPlayerId))
                    {
                        continue;
                    }

                    incomingIds.Add(item.Id);
                    if (activeVisuals.TryGetValue(item.Id, out PickupVisual existing))
                    {
                        if (existing != null && !existing.IsCollecting)
                        {
                            existing.CancelAuthoritativeRemoval();
                        }

                        continue;
                    }

                    if (pendingItems.ContainsKey(item.Id))
                    {
                        continue;
                    }

                    if (!TrySpawn(item))
                    {
                        pendingItems[item.Id] = item;
                    }
                }
            }

            RemoveMissingVisuals();
            RemoveMissingPendingItems();
            UpdateFloorRequest();
        }

        public static bool ShouldRender(PickupSnapshot item, int localPlayerId)
        {
            return item != null && item.OwnerPlayer == localPlayerId &&
                   item.ItemType == "HEALTH" && item.RemainingMilliseconds > 0 &&
                   !string.IsNullOrEmpty(item.Id);
        }

        private bool TrySpawn(PickupSnapshot item)
        {
            if (floorProvider == null || !floorProvider.TryCreatePlacementPose(
                    item.DistanceMetres,
                    item.BearingDegrees,
                    minimumSpawnDistanceMetres,
                    maximumSpawnDistanceMetres,
                    minimumBearingDegrees,
                    maximumBearingDegrees,
                    out Pose pose) || !HasMinimumSeparation(pose.position))
            {
                return false;
            }

            PickupVisual visual = healthPickupPrefab != null
                ? Instantiate(healthPickupPrefab, visualRoot)
                : PickupVisual.CreateFallback(visualRoot);
            visual.transform.SetPositionAndRotation(pose.position, pose.rotation);
            visual.Initialize(item.Id, item.Magnitude);
            visual.PresentationFinished += HandleVisualPresentationFinished;
            activeVisuals.Add(item.Id, visual);
            return true;
        }

        private bool HasMinimumSeparation(Vector3 candidate)
        {
            float minimumSquared = minimumItemSeparationMetres * minimumItemSeparationMetres;
            foreach (PickupVisual visual in activeVisuals.Values)
            {
                if (visual != null &&
                    (visual.transform.position - candidate).sqrMagnitude < minimumSquared)
                {
                    return false;
                }
            }

            return true;
        }

        private void RemoveMissingVisuals()
        {
            removalScratch.Clear();
            foreach (KeyValuePair<string, PickupVisual> pair in activeVisuals)
            {
                if (!incomingIds.Contains(pair.Key))
                {
                    if (pair.Value != null)
                    {
                        if (Application.isPlaying)
                        {
                            pair.Value.BeginAuthoritativeRemoval(unmatchedRemovalGraceSeconds);
                        }
                        else
                        {
                            pair.Value.PresentationFinished -= HandleVisualPresentationFinished;
                            DestroyRuntimeObject(pair.Value.gameObject);
                            removalScratch.Add(pair.Key);
                        }
                    }
                }
            }

            foreach (string id in removalScratch)
            {
                activeVisuals.Remove(id);
            }
        }

        private void HandleVisualPresentationFinished(PickupVisual visual)
        {
            if (visual == null || string.IsNullOrEmpty(visual.ItemId) ||
                !activeVisuals.TryGetValue(visual.ItemId, out PickupVisual current) ||
                current != visual)
            {
                return;
            }

            visual.PresentationFinished -= HandleVisualPresentationFinished;
            activeVisuals.Remove(visual.ItemId);
            DestroyRuntimeObject(visual.gameObject);
        }

        private void RemoveMissingPendingItems()
        {
            removalScratch.Clear();
            foreach (string id in pendingItems.Keys)
            {
                if (!incomingIds.Contains(id))
                {
                    removalScratch.Add(id);
                }
            }

            foreach (string id in removalScratch)
            {
                pendingItems.Remove(id);
            }
        }

        private void UpdateFloorRequest()
        {
            if (floorProvider != null)
            {
                floorProvider.SetPlacementRequested(
                    pendingItems.Count > 0 && !floorProvider.IsReady);
            }
        }

        private static void DestroyRuntimeObject(UnityEngine.Object value)
        {
            if (Application.isPlaying)
            {
                Destroy(value);
            }
            else
            {
                DestroyImmediate(value);
            }
        }

#if UNITY_EDITOR
        public void ConfigureForTesting(
            FloorPlaneProvider provider,
            Transform root,
            int playerId = 1,
            int itemCap = 8)
        {
            floorProvider = provider;
            visualRoot = root;
            localPlayerId = playerId;
            maximumVisibleItems = itemCap;
        }

        public void ApplySnapshotForTesting(MatchSnapshot snapshot)
        {
            Reconcile(snapshot);
        }

        public bool TryGetVisualPoseForTesting(string id, out Pose pose)
        {
            if (activeVisuals.TryGetValue(id, out PickupVisual visual) && visual != null)
            {
                pose = new Pose(visual.transform.position, visual.transform.rotation);
                return true;
            }

            pose = default;
            return false;
        }
#endif

        private void OnValidate()
        {
            localPlayerId = Mathf.Clamp(localPlayerId, 1, 2);
            maximumVisibleItems = Mathf.Clamp(maximumVisibleItems, 1, 8);
            minimumSpawnDistanceMetres = Mathf.Max(0f, minimumSpawnDistanceMetres);
            maximumSpawnDistanceMetres = Mathf.Max(
                minimumSpawnDistanceMetres,
                maximumSpawnDistanceMetres);
            minimumBearingDegrees = Mathf.Clamp(minimumBearingDegrees, -90f, 0f);
            maximumBearingDegrees = Mathf.Clamp(maximumBearingDegrees, 0f, 90f);
            minimumItemSeparationMetres = Mathf.Max(0f, minimumItemSeparationMetres);
            unmatchedRemovalGraceSeconds = Mathf.Max(0f, unmatchedRemovalGraceSeconds);
        }
    }
}
