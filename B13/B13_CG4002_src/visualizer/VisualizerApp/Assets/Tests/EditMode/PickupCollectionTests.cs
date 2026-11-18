using CG4002.Visualizer.Game;
using CG4002.Visualizer.Models;
using CG4002.Visualizer.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class PickupCollectionTests
    {
        [TestCase(1.99f, 2f, true)]
        [TestCase(2f, 2f, true)]
        [TestCase(2.01f, 2f, false)]
        [TestCase(2.49f, 2.5f, true)]
        public void RangeGate_UsesAdjustableCameraDistance(
            float pickupDistance,
            float maximumDistance,
            bool expected)
        {
            Assert.That(PickupCollectionRules.IsWithinCameraRange(
                Vector3.zero,
                Vector3.forward * pickupDistance,
                maximumDistance), Is.EqualTo(expected));
        }

        [Test]
        public void RangeGate_RejectsInvalidInputs()
        {
            Assert.That(PickupCollectionRules.IsWithinCameraRange(
                Vector3.zero, Vector3.forward, 0f), Is.False);
            Assert.That(PickupCollectionRules.IsWithinCameraRange(
                Vector3.zero, Vector3.forward, float.NaN), Is.False);
            Assert.That(PickupCollectionRules.IsWithinCameraRange(
                new Vector3(float.PositiveInfinity, 0f, 0f),
                Vector3.forward,
                2f), Is.False);
        }

        [Test]
        public void RangeGate_MeasuresFullThreeDimensionalCameraDistance()
        {
            Assert.That(PickupCollectionRules.IsWithinCameraRange(
                Vector3.zero,
                new Vector3(1.2f, 1.6f, 0f),
                2f), Is.True);
            Assert.That(PickupCollectionRules.IsWithinCameraRange(
                Vector3.zero,
                new Vector3(1.21f, 1.6f, 0f),
                2f), Is.False);
        }

        [Test]
        public void PickupEvent_DoesNotMutateAuthoritativeHealth()
        {
            var store = new MatchStateStore();
            Assert.That(store.TryApply(State(10, 60f)), Is.True);

            Assert.That(store.TryAccept(PickupEvent(5, "health-authority")), Is.True);
            Assert.That(store.Current.PlayerOneHealth, Is.EqualTo(60f));

            Assert.That(store.TryApply(State(11, 85f)), Is.True);
            Assert.That(store.Current.PlayerOneHealth, Is.EqualTo(85f));
        }

        [Test]
        public void CollectionPresenter_DeduplicatesAcceptedItemAndToleratesMissingVisual()
        {
            var root = new GameObject("PickupCollectionTest");
            try
            {
                PickupCollectionPresenter presenter =
                    root.AddComponent<PickupCollectionPresenter>();
                GameEventMessage pickup = PickupEvent(1, "missing-visual");

                presenter.ApplyEventForTesting(pickup);
                presenter.ApplyEventForTesting(pickup);

                Assert.That(presenter.PresentedCollectionCount, Is.EqualTo(1));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        private static MatchStateMessage State(long sequence, float health)
        {
            return new MatchStateMessage
            {
                type = "MatchState",
                seq = sequence,
                timestamp = 100,
                player_1 = new PlayerStateMessage { health = health, stamina = 75f },
                player_2 = new PlayerStateMessage { health = 100f, stamina = 75f },
                round_time = 60f,
                state = "FIGHTING",
                active_items = System.Array.Empty<PickupStateMessage>()
            };
        }

        private static GameEventMessage PickupEvent(long sequence, string itemId)
        {
            return new GameEventMessage
            {
                type = "GameEvent",
                seq = sequence,
                timestamp = 100,
                @event = "ITEM_PICKUP",
                source_player = 1,
                target_player = 1,
                punch = string.Empty,
                confidence = 1f,
                intensity = 0f,
                outcome = "NONE",
                item_id = itemId,
                item_type = "HEALTH",
                hand = "LEFT"
            };
        }
    }
}
