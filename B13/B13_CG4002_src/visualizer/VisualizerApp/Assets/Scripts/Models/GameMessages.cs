using System;
using System.Collections.Generic;
using UnityEngine;

namespace CG4002.Visualizer.Models
{
    public enum MessageKind
    {
        Unknown,
        GameEvent,
        MatchState
    }

    [Serializable]
    public sealed class PlayerStateMessage
    {
        public float health;
        public float stamina;
    }

    [Serializable]
    public sealed class PickupStateMessage
    {
        public string id;
        public string item_type;
        public int owner_player;
        public float distance_m;
        public float bearing_degrees;
        public float magnitude;
        public int remaining_ms;
    }

    [Serializable]
    public sealed class GameEventMessage
    {
        public string type;
        public long seq;
        public long timestamp;
        public string @event;
        public int source_player;
        public int target_player;
        public string punch;
        public float confidence;
        public float intensity;
        public string outcome;
        public string item_id;
        public string item_type;
        public string hand;
    }

    [Serializable]
    public sealed class MatchStateMessage
    {
        public string type;
        public long seq;
        public long timestamp;
        public PlayerStateMessage player_1;
        public PlayerStateMessage player_2;
        public float round_time;
        public string state;
        public PickupStateMessage[] active_items;
    }

    [Serializable]
    internal sealed class MessageProbe
    {
        public string type;
        public string @event;
        public PlayerStateMessage player_1;
    }

    public sealed class DecodedMessage
    {
        public MessageKind Kind { get; private set; }
        public GameEventMessage GameEvent { get; private set; }
        public MatchStateMessage MatchState { get; private set; }

        public static DecodedMessage FromGameEvent(GameEventMessage value)
        {
            return new DecodedMessage { Kind = MessageKind.GameEvent, GameEvent = value };
        }

        public static DecodedMessage FromMatchState(MatchStateMessage value)
        {
            return new DecodedMessage { Kind = MessageKind.MatchState, MatchState = value };
        }
    }

    public static class MessageDecoder
    {
        private const int MaximumActiveItems = 8;
        private const int MaximumItemIdLength = 64;
        private const int MaximumItemLifetimeMilliseconds = 120000;

        public static bool TryDecode(string json, out DecodedMessage decoded, out string error)
        {
            decoded = null;
            error = string.Empty;

            if (string.IsNullOrWhiteSpace(json))
            {
                error = "Message is empty.";
                return false;
            }

            try
            {
                MessageProbe probe = JsonUtility.FromJson<MessageProbe>(json);
                if (probe == null)
                {
                    error = "Message is not a JSON object.";
                    return false;
                }

                MessageKind kind = ResolveKind(probe);
                switch (kind)
                {
                    case MessageKind.GameEvent:
                    {
                        GameEventMessage value = JsonUtility.FromJson<GameEventMessage>(json);
                        if (!Validate(value, out error))
                        {
                            return false;
                        }

                        decoded = DecodedMessage.FromGameEvent(value);
                        return true;
                    }
                    case MessageKind.MatchState:
                    {
                        MatchStateMessage value = JsonUtility.FromJson<MatchStateMessage>(json);
                        if (!Validate(value, out error))
                        {
                            return false;
                        }

                        decoded = DecodedMessage.FromMatchState(value);
                        return true;
                    }
                    default:
                        error = "Unknown message type.";
                        return false;
                }
            }
            catch (ArgumentException exception)
            {
                error = "Invalid JSON: " + exception.Message;
                return false;
            }
        }

        private static MessageKind ResolveKind(MessageProbe probe)
        {
            if (string.Equals(probe.type, "GameEvent", StringComparison.OrdinalIgnoreCase))
            {
                return MessageKind.GameEvent;
            }

            if (string.Equals(probe.type, "MatchState", StringComparison.OrdinalIgnoreCase))
            {
                return MessageKind.MatchState;
            }

            // Backward compatibility for the discriminator-free examples in the initial report.
            if (!string.IsNullOrWhiteSpace(probe.@event))
            {
                return MessageKind.GameEvent;
            }

            return probe.player_1 != null ? MessageKind.MatchState : MessageKind.Unknown;
        }

        private static bool Validate(GameEventMessage value, out string error)
        {
            if (value == null || value.seq < 0 || value.timestamp < 0)
            {
                error = "GameEvent has an invalid sequence or timestamp.";
                return false;
            }

            if (value.source_player < 1 || value.source_player > 2 ||
                value.target_player < 1 || value.target_player > 2)
            {
                error = "GameEvent contains an invalid player ID.";
                return false;
            }

            if (!IsSupportedGameEvent(value.@event) ||
                !InUnitRange(value.confidence) || !InUnitRange(value.intensity))
            {
                error = "GameEvent contains an invalid event, confidence, or intensity.";
                return false;
            }

            if (string.Equals(value.@event, "ITEM_PICKUP", StringComparison.Ordinal))
            {
                if (!IsValidItemId(value.item_id) ||
                    !IsSupportedItemType(value.item_type) ||
                    !IsOptionalHand(value.hand))
                {
                    error = "ITEM_PICKUP contains invalid item or hand fields.";
                    return false;
                }
            }

            error = string.Empty;
            return true;
        }

        private static bool Validate(MatchStateMessage value, out string error)
        {
            if (value == null || value.seq < 0 || value.timestamp < 0 ||
                value.player_1 == null || value.player_2 == null)
            {
                error = "MatchState is missing required fields.";
                return false;
            }

            if (!InPercentRange(value.player_1.health) || !InPercentRange(value.player_1.stamina) ||
                !InPercentRange(value.player_2.health) || !InPercentRange(value.player_2.stamina) ||
                !IsFinite(value.round_time) || value.round_time < 0f || string.IsNullOrWhiteSpace(value.state))
            {
                error = "MatchState contains an out-of-range value.";
                return false;
            }

            PickupStateMessage[] items = value.active_items;
            if (items == null)
            {
                error = string.Empty;
                return true;
            }

            if (items.Length > MaximumActiveItems)
            {
                error = $"MatchState contains more than {MaximumActiveItems} active items.";
                return false;
            }

            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (PickupStateMessage item in items)
            {
                if (item == null || !IsValidItemId(item.id) ||
                    !IsSupportedItemType(item.item_type) ||
                    item.owner_player < 1 || item.owner_player > 2 ||
                    !IsFinite(item.distance_m) || item.distance_m < 0.5f || item.distance_m > 2f ||
                    !IsFinite(item.bearing_degrees) || item.bearing_degrees < -90f || item.bearing_degrees > 90f ||
                    !IsFinite(item.magnitude) || item.magnitude < 0f || item.magnitude > 100f ||
                    item.remaining_ms < 0 || item.remaining_ms > MaximumItemLifetimeMilliseconds)
                {
                    error = "MatchState contains an invalid active item.";
                    return false;
                }

                if (!ids.Add(item.id))
                {
                    error = "MatchState contains duplicate active item IDs.";
                    return false;
                }
            }

            error = string.Empty;
            return true;
        }

        private static bool IsSupportedGameEvent(string value)
        {
            return value == "PUNCH" || value == "GUARD" || value == "WEAVE" ||
                   value == "ITEM_PICKUP" || value == "ROUND_TRANSITION";
        }

        private static bool IsSupportedItemType(string value)
        {
            return value == "HEALTH" || value == "ATTACK_BOOST";
        }

        private static bool IsOptionalHand(string value)
        {
            return string.IsNullOrEmpty(value) || value == "LEFT" || value == "RIGHT";
        }

        private static bool IsValidItemId(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > MaximumItemIdLength)
            {
                return false;
            }

            char first = value[0];
            bool firstIsLetter = (first >= 'A' && first <= 'Z') ||
                                 (first >= 'a' && first <= 'z');
            bool firstIsDigit = first >= '0' && first <= '9';
            if (!firstIsLetter && !firstIsDigit)
            {
                return false;
            }

            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                bool isAsciiLetter = (character >= 'A' && character <= 'Z') ||
                                     (character >= 'a' && character <= 'z');
                bool isDigit = character >= '0' && character <= '9';
                bool valid = isAsciiLetter || isDigit || character == '-' ||
                             character == '_' || character == '.' || character == ':';
                if (!valid)
                {
                    return false;
                }
            }

            return true;
        }

        private static bool InUnitRange(float value)
        {
            return IsFinite(value) && value >= 0f && value <= 1f;
        }

        private static bool InPercentRange(float value)
        {
            return IsFinite(value) && value >= 0f && value <= 100f;
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }
    }
}
