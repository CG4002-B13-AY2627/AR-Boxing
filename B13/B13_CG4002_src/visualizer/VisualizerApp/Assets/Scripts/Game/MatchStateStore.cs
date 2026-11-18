using System;
using System.Collections.Generic;
using CG4002.Visualizer.Models;

namespace CG4002.Visualizer.Game
{
    public sealed class PickupSnapshot
    {
        public string Id { get; internal set; } = string.Empty;
        public string ItemType { get; internal set; } = string.Empty;
        public int OwnerPlayer { get; internal set; }
        public float DistanceMetres { get; internal set; }
        public float BearingDegrees { get; internal set; }
        public float Magnitude { get; internal set; }
        public int RemainingMilliseconds { get; internal set; }
    }

    public sealed class MatchSnapshot
    {
        public float PlayerOneHealth { get; internal set; } = 100f;
        public float PlayerOneStamina { get; internal set; } = 100f;
        public float PlayerTwoHealth { get; internal set; } = 100f;
        public float PlayerTwoStamina { get; internal set; } = 100f;
        public float RoundTime { get; internal set; }
        public string State { get; internal set; } = "LOBBY";
        public long ServerTimestamp { get; internal set; }
        public IReadOnlyList<PickupSnapshot> ActiveItems { get; internal set; } =
            Array.Empty<PickupSnapshot>();
    }

    public sealed class MatchStateStore
    {
        private long lastStateSequence = -1;
        private long lastEventSequence = -1;

        public MatchSnapshot Current { get; } = new();

        public bool TryApply(MatchStateMessage message)
        {
            if (message == null || message.seq <= lastStateSequence)
            {
                return false;
            }

            lastStateSequence = message.seq;
            Current.PlayerOneHealth = message.player_1.health;
            Current.PlayerOneStamina = message.player_1.stamina;
            Current.PlayerTwoHealth = message.player_2.health;
            Current.PlayerTwoStamina = message.player_2.stamina;
            Current.RoundTime = message.round_time;
            Current.State = message.state;
            Current.ServerTimestamp = message.timestamp;
            Current.ActiveItems = CopyItems(message.active_items);
            return true;
        }

        public bool TryAccept(GameEventMessage message)
        {
            if (message == null || message.seq <= lastEventSequence)
            {
                return false;
            }

            lastEventSequence = message.seq;
            return true;
        }

        private static IReadOnlyList<PickupSnapshot> CopyItems(PickupStateMessage[] items)
        {
            if (items == null || items.Length == 0)
            {
                return Array.Empty<PickupSnapshot>();
            }

            var copy = new PickupSnapshot[items.Length];
            for (int index = 0; index < items.Length; index++)
            {
                PickupStateMessage item = items[index];
                copy[index] = new PickupSnapshot
                {
                    Id = item.id,
                    ItemType = item.item_type,
                    OwnerPlayer = item.owner_player,
                    DistanceMetres = item.distance_m,
                    BearingDegrees = item.bearing_degrees,
                    Magnitude = item.magnitude,
                    RemainingMilliseconds = item.remaining_ms
                };
            }

            return copy;
        }
    }
}
