using System;
using CG4002.Visualizer.AR;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Models;
using CG4002.Visualizer.Presentation;
using CG4002.Visualizer.UI;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class PickupPlacementTests
    {
        [Test]
        public void FloorPose_ProjectsCameraAndAppliesBearing()
        {
            bool success = PickupPlacement.TryCreateFloorPose(
                new Vector3(0f, 1.6f, 0f),
                new Vector3(0f, -0.25f, 1f),
                Vector3.zero,
                Vector3.up,
                1f,
                30f,
                0.7f,
                1.25f,
                -65f,
                65f,
                out Pose pose);

            Assert.That(success, Is.True);
            Assert.That(pose.position.y, Is.EqualTo(0f).Within(0.0001f));
            Assert.That(pose.position.x, Is.EqualTo(0.5f).Within(0.0001f));
            Assert.That(pose.position.z, Is.EqualTo(Mathf.Sqrt(0.75f)).Within(0.0001f));
        }

        [TestCase(0.69f, 0f)]
        [TestCase(1.26f, 0f)]
        [TestCase(1f, -66f)]
        [TestCase(1f, 66f)]
        public void FloorPose_RejectsUnsafeRadiusOrBearing(float distance, float bearing)
        {
            Assert.That(PickupPlacement.TryCreateFloorPose(
                Vector3.up,
                Vector3.forward,
                Vector3.zero,
                Vector3.up,
                distance,
                bearing,
                0.7f,
                1.25f,
                -65f,
                65f,
                out _), Is.False);
        }

        [Test]
        public void FloorPose_RejectsNonFiniteAndVerticalHeading()
        {
            Assert.That(PickupPlacement.TryCreateFloorPose(
                Vector3.zero,
                Vector3.up,
                Vector3.zero,
                Vector3.up,
                1f,
                0f,
                0.7f,
                1.25f,
                -65f,
                65f,
                out _), Is.False);

            Assert.That(PickupPlacement.TryCreateFloorPose(
                new Vector3(float.NaN, 0f, 0f),
                Vector3.forward,
                Vector3.zero,
                Vector3.up,
                1f,
                0f,
                0.7f,
                1.25f,
                -65f,
                65f,
                out _), Is.False);
        }

        [Test]
        public void PolygonContainment_RespectsEdgeMargin()
        {
            Vector2[] square =
            {
                new(-1f, -1f), new(-1f, 1f), new(1f, 1f), new(1f, -1f)
            };

            Assert.That(PickupPlacement.IsPointInsidePolygon(square, Vector2.zero, 0.1f), Is.True);
            Assert.That(PickupPlacement.IsPointInsidePolygon(square, new Vector2(0.95f, 0f), 0.1f), Is.False);
            Assert.That(PickupPlacement.IsPointInsidePolygon(square, new Vector2(1.1f, 0f)), Is.False);
        }
    }

    public sealed class PickupSpawnPresenterTests
    {
        private GameObject testRoot;
        private Camera camera;
        private FloorPlaneProvider floor;
        private PickupSpawnPresenter presenter;
        private MatchStateStore store;
        private long sequence;

        [SetUp]
        public void SetUp()
        {
            testRoot = new GameObject("PickupTestRoot");
            var cameraObject = new GameObject("PickupTestCamera", typeof(Camera));
            cameraObject.transform.SetParent(testRoot.transform);
            cameraObject.transform.position = new Vector3(0f, 1.6f, 0f);
            cameraObject.transform.rotation = Quaternion.identity;
            camera = cameraObject.GetComponent<Camera>();

            floor = testRoot.AddComponent<FloorPlaneProvider>();
            floor.SetSyntheticFloorForTesting(
                new Pose(Vector3.zero, Quaternion.identity),
                new Vector2(4f, 4f),
                camera);

            var visuals = new GameObject("Visuals");
            visuals.transform.SetParent(testRoot.transform, false);
            presenter = testRoot.AddComponent<PickupSpawnPresenter>();
            presenter.ConfigureForTesting(floor, visuals.transform);
            store = new MatchStateStore();
        }

        [TearDown]
        public void TearDown()
        {
            if (testRoot != null)
            {
                UnityEngine.Object.DestroyImmediate(testRoot);
            }
        }

        [Test]
        public void RepeatedItemId_DoesNotDuplicateOrFollowCamera()
        {
            Apply(Item("health-fixed", 1, 1f, 0f));
            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(1));
            Assert.That(presenter.TryGetVisualPoseForTesting("health-fixed", out Pose first), Is.True);

            camera.transform.position = new Vector3(1.5f, 1.6f, 0f);
            Apply(Item("health-fixed", 1, 1.2f, 40f));

            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(1));
            Assert.That(presenter.TryGetVisualPoseForTesting("health-fixed", out Pose second), Is.True);
            Assert.That(second.position, Is.EqualTo(first.position));
        }

        [Test]
        public void MissingItem_RemovesVisual()
        {
            Apply(Item("health-remove", 1, 1f, 0f));
            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(1));

            Apply(Array.Empty<PickupStateMessage>());

            Assert.That(presenter.ActiveVisualCount, Is.Zero);
        }

        [Test]
        public void OtherPlayerItem_IsNotRendered()
        {
            Apply(Item("health-remote", 2, 1f, 0f));

            Assert.That(presenter.ActiveVisualCount, Is.Zero);
            Assert.That(presenter.PendingItemCount, Is.Zero);
        }

        [Test]
        public void ItemCap_IsAppliedAfterOwnerFiltering()
        {
            presenter.ConfigureForTesting(floor, testRoot.transform.Find("Visuals"), 1, 2);
            Apply(
                Item("remote", 2, 1f, 0f),
                Item("left", 1, 1f, -40f),
                Item("right", 1, 1f, 40f),
                Item("centre", 1, 1f, 0f));

            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(2));
        }

        [Test]
        public void MissingFloor_KeepsItemPendingAndRequestsGuidance()
        {
            var noFloorRoot = new GameObject("NoFloor");
            noFloorRoot.transform.SetParent(testRoot.transform);
            FloorPlaneProvider noFloor = noFloorRoot.AddComponent<FloorPlaneProvider>();
            var pendingPresenter = noFloorRoot.AddComponent<PickupSpawnPresenter>();
            pendingPresenter.ConfigureForTesting(noFloor, noFloorRoot.transform);

            ApplyTo(pendingPresenter, Item("health-pending", 1, 1f, 0f));

            Assert.That(pendingPresenter.ActiveVisualCount, Is.Zero);
            Assert.That(pendingPresenter.PendingItemCount, Is.EqualTo(1));
            Assert.That(noFloor.PlacementRequested, Is.True);
        }

        private void Apply(params PickupStateMessage[] items)
        {
            ApplyTo(presenter, items);
        }

        private void ApplyTo(PickupSpawnPresenter target, params PickupStateMessage[] items)
        {
            var state = new MatchStateMessage
            {
                type = "MatchState",
                seq = sequence++,
                timestamp = sequence,
                player_1 = new PlayerStateMessage { health = 100f, stamina = 100f },
                player_2 = new PlayerStateMessage { health = 100f, stamina = 100f },
                round_time = 90f,
                state = "FIGHTING",
                active_items = items
            };
            Assert.That(store.TryApply(state), Is.True);
            target.ApplySnapshotForTesting(store.Current);
        }

        private static PickupStateMessage Item(
            string id,
            int owner,
            float distance,
            float bearing)
        {
            return new PickupStateMessage
            {
                id = id,
                item_type = "HEALTH",
                owner_player = owner,
                distance_m = distance,
                bearing_degrees = bearing,
                magnitude = 25f,
                remaining_ms = 8000
            };
        }
    }

    public sealed class HudToastQueueTests
    {
        [Test]
        public void RepeatedItemId_IsOnlyQueuedOnce()
        {
            var queue = new HudToastQueue();

            Assert.That(queue.TryEnqueue("health-1", "HEALTH PICKUP SPAWNED"), Is.True);
            Assert.That(queue.TryEnqueue("health-1", "HEALTH PICKUP SPAWNED"), Is.False);
            Assert.That(queue.CurrentItemId, Is.EqualTo("health-1"));
            Assert.That(queue.PendingCount, Is.Zero);
            Assert.That(queue.SeenCount, Is.EqualTo(1));
        }

        [Test]
        public void PendingCap_DropsOldestPendingAndKeepsNewestInOrder()
        {
            var queue = new HudToastQueue(maximumPending: 2);
            queue.TryEnqueue("current", "CURRENT");
            queue.TryEnqueue("oldest-pending", "OLD");
            queue.TryEnqueue("next", "NEXT");
            queue.TryEnqueue("newest", "NEWEST");

            Assert.That(queue.CurrentItemId, Is.EqualTo("current"));
            Assert.That(queue.PendingCount, Is.EqualTo(2));

            queue.Advance(1f, 0f, 1f, 0f);
            Assert.That(queue.CurrentItemId, Is.EqualTo("next"));
            queue.Advance(1f, 0f, 1f, 0f);
            Assert.That(queue.CurrentItemId, Is.EqualTo("newest"));
        }

        [Test]
        public void Advance_UsesCallerTimeAndCompletesFadeSequence()
        {
            var queue = new HudToastQueue();
            queue.TryEnqueue("health-1", "HEALTH PICKUP SPAWNED");

            Assert.That(queue.Advance(0.1f, 0.2f, 0.4f, 0.2f), Is.EqualTo(0.5f).Within(0.001f));
            Assert.That(queue.Advance(0.3f, 0.2f, 0.4f, 0.2f), Is.EqualTo(1f).Within(0.001f));
            Assert.That(queue.Advance(0.3f, 0.2f, 0.4f, 0.2f), Is.EqualTo(0.5f).Within(0.001f));
            Assert.That(queue.Advance(0.1f, 0.2f, 0.4f, 0.2f), Is.Zero);
            Assert.That(queue.IsShowing, Is.False);
        }

        [Test]
        public void Presenter_FiltersRemoteAndRepeatedSnapshots()
        {
            var root = new GameObject("ToastTestRoot");
            try
            {
                HudToastPresenter presenter = root.AddComponent<HudToastPresenter>();
                presenter.ConfigureForTesting(null);
                var store = new MatchStateStore();
                var state = new MatchStateMessage
                {
                    type = "MatchState",
                    seq = 1,
                    timestamp = 1,
                    player_1 = new PlayerStateMessage { health = 100f, stamina = 100f },
                    player_2 = new PlayerStateMessage { health = 100f, stamina = 100f },
                    round_time = 90f,
                    state = "FIGHTING",
                    active_items = new[]
                    {
                        ToastItem("local", 1),
                        ToastItem("remote", 2)
                    }
                };
                Assert.That(store.TryApply(state), Is.True);

                presenter.ApplySnapshotForTesting(store.Current);
                presenter.ApplySnapshotForTesting(store.Current);

                Assert.That(presenter.CurrentItemId, Is.EqualTo("local"));
                Assert.That(presenter.SeenItemCountForTesting, Is.EqualTo(1));
                Assert.That(presenter.PendingNotificationCount, Is.Zero);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static PickupStateMessage ToastItem(string id, int owner)
        {
            return new PickupStateMessage
            {
                id = id,
                item_type = "HEALTH",
                owner_player = owner,
                distance_m = 1f,
                bearing_degrees = 0f,
                magnitude = 25f,
                remaining_ms = 8000
            };
        }
    }
}
