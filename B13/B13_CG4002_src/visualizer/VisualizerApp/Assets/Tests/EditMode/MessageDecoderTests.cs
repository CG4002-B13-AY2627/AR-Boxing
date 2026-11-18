using CG4002.Visualizer.Game;
using CG4002.Visualizer.Models;
using CG4002.Visualizer.Networking;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class MessageDecoderTests
    {
        [Test]
        public void DecodesExplicitGameEvent()
        {
            const string json =
                "{\"type\":\"GameEvent\",\"seq\":573,\"timestamp\":12345678," +
                "\"event\":\"PUNCH\",\"source_player\":1,\"target_player\":2," +
                "\"punch\":\"LEFT_HOOK\",\"confidence\":0.94,\"intensity\":0.81," +
                "\"outcome\":\"HIT\"}";

            bool success = MessageDecoder.TryDecode(json, out DecodedMessage decoded, out string error);

            Assert.That(success, Is.True, error);
            Assert.That(decoded.Kind, Is.EqualTo(MessageKind.GameEvent));
            Assert.That(decoded.GameEvent.punch, Is.EqualTo("LEFT_HOOK"));
        }

        [Test]
        public void DecodesInitialReportPayloadWithoutType()
        {
            const string json =
                "{\"seq\":574,\"player_1\":{\"health\":75}," +
                "\"player_2\":{\"health\":39},\"round_time\":75,\"state\":\"FIGHTING\"}";

            bool success = MessageDecoder.TryDecode(json, out DecodedMessage decoded, out string error);

            Assert.That(success, Is.True, error);
            Assert.That(decoded.Kind, Is.EqualTo(MessageKind.MatchState));
            Assert.That(decoded.MatchState.player_1.health, Is.EqualTo(75f));
            Assert.That(decoded.MatchState.active_items, Is.Null);
        }

        [Test]
        public void DecodesHealthPickupEvent()
        {
            const string json =
                "{\"type\":\"GameEvent\",\"seq\":575,\"timestamp\":12345800," +
                "\"event\":\"ITEM_PICKUP\",\"source_player\":1,\"target_player\":1," +
                "\"punch\":\"\",\"confidence\":1.0,\"intensity\":0.0," +
                "\"outcome\":\"NONE\",\"item_id\":\"health-0042\"," +
                "\"item_type\":\"HEALTH\",\"hand\":\"LEFT\"}";

            bool success = MessageDecoder.TryDecode(json, out DecodedMessage decoded, out string error);

            Assert.That(success, Is.True, error);
            Assert.That(decoded.GameEvent.item_id, Is.EqualTo("health-0042"));
            Assert.That(decoded.GameEvent.item_type, Is.EqualTo("HEALTH"));
            Assert.That(decoded.GameEvent.hand, Is.EqualTo("LEFT"));
        }

        [Test]
        public void DecodesMatchStateWithHealthPickup()
        {
            MatchStateMessage message = State(12, 60f, Item("health-0042"));

            bool success = MessageDecoder.TryDecode(
                JsonUtility.ToJson(message), out DecodedMessage decoded, out string error);

            Assert.That(success, Is.True, error);
            Assert.That(decoded.MatchState.active_items, Has.Length.EqualTo(1));
            Assert.That(decoded.MatchState.active_items[0].owner_player, Is.EqualTo(1));
        }

        [Test]
        public void RejectsOutOfRangeConfidence()
        {
            const string json =
                "{\"type\":\"GameEvent\",\"seq\":1,\"timestamp\":2," +
                "\"event\":\"PUNCH\",\"source_player\":1,\"target_player\":2," +
                "\"confidence\":1.4,\"intensity\":0.5}";

            Assert.That(MessageDecoder.TryDecode(json, out _, out _), Is.False);
        }

        [Test]
        public void RejectsUnknownGameEvent()
        {
            const string json =
                "{\"type\":\"GameEvent\",\"seq\":1,\"timestamp\":2," +
                "\"event\":\"TELEPORT\",\"source_player\":1,\"target_player\":2," +
                "\"confidence\":1.0,\"intensity\":0.5}";

            Assert.That(MessageDecoder.TryDecode(json, out _, out _), Is.False);
        }

        [Test]
        public void RejectsPickupEventWithoutItemIdentity()
        {
            const string json =
                "{\"type\":\"GameEvent\",\"seq\":1,\"timestamp\":2," +
                "\"event\":\"ITEM_PICKUP\",\"source_player\":1,\"target_player\":1," +
                "\"confidence\":1.0,\"intensity\":0.0}";

            Assert.That(MessageDecoder.TryDecode(json, out _, out _), Is.False);
        }

        [Test]
        public void RejectsPickupEventWithInvalidHand()
        {
            const string json =
                "{\"type\":\"GameEvent\",\"seq\":1,\"timestamp\":2," +
                "\"event\":\"ITEM_PICKUP\",\"source_player\":1,\"target_player\":1," +
                "\"confidence\":1.0,\"intensity\":0.0," +
                "\"item_id\":\"health-1\",\"item_type\":\"HEALTH\",\"hand\":\"BOTH\"}";

            Assert.That(MessageDecoder.TryDecode(json, out _, out _), Is.False);
        }

        [Test]
        public void RejectsUnknownItemType()
        {
            MatchStateMessage message = State(1, 60f, Item("item-1", "MYSTERY"));

            Assert.That(MessageDecoder.TryDecode(JsonUtility.ToJson(message), out _, out _), Is.False);
        }

        [Test]
        public void RejectsInvalidItemId()
        {
            MatchStateMessage message = State(1, 60f, Item(".hidden-item"));

            Assert.That(MessageDecoder.TryDecode(JsonUtility.ToJson(message), out _, out _), Is.False);
        }

        [Test]
        public void RejectsDuplicateItemIds()
        {
            MatchStateMessage message = State(1, 60f, Item("item-1"), Item("item-1"));

            Assert.That(MessageDecoder.TryDecode(JsonUtility.ToJson(message), out _, out _), Is.False);
        }

        [Test]
        public void RejectsInvalidItemOwner()
        {
            PickupStateMessage item = Item("item-1");
            item.owner_player = 3;

            Assert.That(
                MessageDecoder.TryDecode(JsonUtility.ToJson(State(1, 60f, item)), out _, out _),
                Is.False);
        }

        [Test]
        public void RejectsExcessiveItemDistance()
        {
            PickupStateMessage item = Item("item-1");
            item.distance_m = 2.1f;

            Assert.That(
                MessageDecoder.TryDecode(JsonUtility.ToJson(State(1, 60f, item)), out _, out _),
                Is.False);
        }

        [Test]
        public void RejectsNonFiniteItemDistance()
        {
            PickupStateMessage item = Item("item-1");
            item.distance_m = float.PositiveInfinity;

            Assert.That(
                MessageDecoder.TryDecode(JsonUtility.ToJson(State(1, 60f, item)), out _, out _),
                Is.False);
        }

        [Test]
        public void RejectsMoreThanEightActiveItems()
        {
            var items = new PickupStateMessage[9];
            for (int index = 0; index < items.Length; index++)
            {
                items[index] = Item($"item-{index}");
            }

            Assert.That(
                MessageDecoder.TryDecode(JsonUtility.ToJson(State(1, 60f, items)), out _, out _),
                Is.False);
        }

        [Test]
        public void StateStoreIgnoresOlderSnapshot()
        {
            MatchStateStore store = new();
            MatchStateMessage newer = State(10, 70f);
            MatchStateMessage older = State(9, 99f);

            Assert.That(store.TryApply(newer), Is.True);
            Assert.That(store.TryApply(older), Is.False);
            Assert.That(store.Current.PlayerOneHealth, Is.EqualTo(70f));
        }

        [Test]
        public void OlderSnapshotCannotResurrectRemovedItem()
        {
            MatchStateStore store = new();

            Assert.That(store.TryApply(State(10, 70f)), Is.True);
            Assert.That(store.TryApply(State(9, 70f, Item("old-item"))), Is.False);
            Assert.That(store.Current.ActiveItems, Is.Empty);
        }

        [Test]
        public void StateStoreCopiesActiveItems()
        {
            MatchStateStore store = new();
            PickupStateMessage item = Item("health-1");
            MatchStateMessage message = State(1, 60f, item);

            Assert.That(store.TryApply(message), Is.True);
            item.id = "mutated-after-apply";

            Assert.That(store.Current.ActiveItems.Count, Is.EqualTo(1));
            Assert.That(store.Current.ActiveItems[0].Id, Is.EqualTo("health-1"));
        }

        [Test]
        public void EventAndStateSequencesAreIndependent()
        {
            MatchStateStore store = new();
            GameEventMessage gameEvent = PickupEvent(5);

            Assert.That(store.TryApply(State(5, 60f)), Is.True);
            Assert.That(store.TryAccept(gameEvent), Is.True);
            Assert.That(store.TryApply(State(5, 70f)), Is.False);
            Assert.That(store.TryAccept(gameEvent), Is.False);
        }

        [Test]
        public void MatchController_CapsReconnectBurstWorkPerFrame()
        {
            var root = new GameObject("QueueCapTest");
            root.SetActive(false);
            try
            {
                GameNetworkClient network = root.AddComponent<GameNetworkClient>();
                MatchController controller = root.AddComponent<MatchController>();
                controller.ConfigureForTesting(network, 64);
                for (int sequence = 0; sequence < 70; sequence++)
                {
                    network.InjectForDevelopment(JsonUtility.ToJson(
                        State(sequence, 60f)));
                }

                Assert.That(controller.ProcessQueuedMessagesForTesting(), Is.EqualTo(64));
                Assert.That(controller.AcceptedPayloadCount, Is.EqualTo(64));
                Assert.That(controller.ProcessQueuedMessagesForTesting(), Is.EqualTo(6));
                Assert.That(controller.AcceptedPayloadCount, Is.EqualTo(70));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        private static MatchStateMessage State(
            long sequence,
            float health,
            params PickupStateMessage[] activeItems)
        {
            return new MatchStateMessage
            {
                type = "MatchState",
                seq = sequence,
                timestamp = 100,
                player_1 = new PlayerStateMessage { health = health, stamina = 50f },
                player_2 = new PlayerStateMessage { health = 100f, stamina = 50f },
                round_time = 60f,
                state = "FIGHTING",
                active_items = activeItems
            };
        }

        private static PickupStateMessage Item(string id, string itemType = "HEALTH")
        {
            return new PickupStateMessage
            {
                id = id,
                item_type = itemType,
                owner_player = 1,
                distance_m = 1f,
                bearing_degrees = -25f,
                magnitude = 25f,
                remaining_ms = 8000
            };
        }

        private static GameEventMessage PickupEvent(long sequence)
        {
            return new GameEventMessage
            {
                type = "GameEvent",
                seq = sequence,
                timestamp = 100,
                @event = "ITEM_PICKUP",
                source_player = 1,
                target_player = 1,
                confidence = 1f,
                intensity = 0f,
                outcome = "NONE",
                item_id = "health-1",
                item_type = "HEALTH",
                hand = "LEFT"
            };
        }
    }
}
