using CG4002.Visualizer.Models;
using CG4002.Visualizer.Networking;
using UnityEngine;

namespace CG4002.Visualizer.Development
{
    public sealed class MockGameEventSource : MonoBehaviour
    {
        [SerializeField] private GameNetworkClient networkClient;
        [SerializeField, Min(0.25f)] private float eventIntervalSeconds = 1.5f;
        [SerializeField] private bool emitOnStart = true;

        [Header("Health pickup prototype")]
        [SerializeField, Range(1, 2)] private int localPlayerId = 1;
        [SerializeField] private string healthPickupId = "health-debug-001";
        [SerializeField, Range(0f, 100f)] private float healthPickupMagnitude = 25f;
        [SerializeField, Range(0.5f, 2f)] private float healthPickupDistanceMetres = 1f;
        [SerializeField, Range(-90f, 90f)] private float healthPickupBearingDegrees = -25f;
        [SerializeField, Range(0, 120000)] private int healthPickupRemainingMilliseconds = 8000;
        [SerializeField] private string healthPickupHand = "LEFT";
        [SerializeField, Range(0f, 100f)] private float playerOneHealth = 60f;
        [SerializeField, Range(0f, 100f)] private float playerTwoHealth = 100f;

        private long eventSequence;
        private long stateSequence;
        private float nextEventTime;
        private bool playerOneAttacks = true;
        private bool healthPickupActive;

        private void Start()
        {
            nextEventTime = Time.unscaledTime + (emitOnStart ? 0.1f : eventIntervalSeconds);
        }

        private void Update()
        {
            if (networkClient == null || Time.unscaledTime < nextEventTime)
            {
                return;
            }

            nextEventTime = Time.unscaledTime + eventIntervalSeconds;
            EmitExchange();
        }

        private void EmitExchange()
        {
            int source = playerOneAttacks ? 1 : 2;
            int target = playerOneAttacks ? 2 : 1;
            if (target == 1)
            {
                playerOneHealth = Mathf.Max(0f, playerOneHealth - 7f);
            }
            else
            {
                playerTwoHealth = Mathf.Max(0f, playerTwoHealth - 7f);
            }

            GameEventMessage gameEvent = new()
            {
                type = "GameEvent",
                seq = eventSequence++,
                timestamp = MillisecondsNow(),
                @event = "PUNCH",
                source_player = source,
                target_player = target,
                punch = playerOneAttacks ? "LEFT_HOOK" : "CROSS",
                confidence = 0.94f,
                intensity = 0.81f,
                outcome = "HIT"
            };

            networkClient.InjectForDevelopment(JsonUtility.ToJson(gameEvent));
            InjectState();
            playerOneAttacks = !playerOneAttacks;
        }

        [ContextMenu("Pickup Prototype/Emit Health Pickup State")]
        public void EmitHealthPickupState()
        {
            if (!CanInject())
            {
                return;
            }

            healthPickupActive = true;
            InjectState();
        }

        [ContextMenu("Pickup Prototype/Spawn Health Left")]
        public void EmitHealthPickupLeft()
        {
            ActivateHealthPickup("health-debug-left", -40f);
        }

        [ContextMenu("Pickup Prototype/Spawn Health Centre")]
        public void EmitHealthPickupCentre()
        {
            ActivateHealthPickup("health-debug-centre", 0f);
        }

        [ContextMenu("Pickup Prototype/Spawn Health Right")]
        public void EmitHealthPickupRight()
        {
            ActivateHealthPickup("health-debug-right", 40f);
        }

        [ContextMenu("Pickup Prototype/Clear Items")]
        public void ClearHealthPickups()
        {
            if (!CanInject())
            {
                return;
            }

            healthPickupActive = false;
            InjectState();
        }

        [ContextMenu("Pickup Prototype/Emit Accepted Health Pickup")]
        public void EmitAcceptedHealthPickup()
        {
            if (!CanInject() || !healthPickupActive)
            {
                if (!healthPickupActive)
                {
                    Debug.LogWarning("Cannot emit pickup acceptance before the debug pickup is active.");
                }

                return;
            }

            GameEventMessage pickup = new()
            {
                type = "GameEvent",
                seq = eventSequence++,
                timestamp = MillisecondsNow(),
                @event = "ITEM_PICKUP",
                source_player = localPlayerId,
                target_player = localPlayerId,
                punch = string.Empty,
                confidence = 1f,
                intensity = 0f,
                outcome = "NONE",
                item_id = healthPickupId,
                item_type = "HEALTH",
                hand = healthPickupHand
            };

            networkClient.InjectForDevelopment(JsonUtility.ToJson(pickup));
        }

        [ContextMenu("Pickup Prototype/Emit Applied Health State")]
        public void EmitAppliedHealthState()
        {
            if (!CanInject() || !healthPickupActive)
            {
                if (!healthPickupActive)
                {
                    Debug.LogWarning("Cannot apply the debug pickup before it is active.");
                }

                return;
            }

            if (localPlayerId == 1)
            {
                playerOneHealth = Mathf.Min(100f, playerOneHealth + healthPickupMagnitude);
            }
            else
            {
                playerTwoHealth = Mathf.Min(100f, playerTwoHealth + healthPickupMagnitude);
            }

            healthPickupActive = false;
            InjectState();
        }

        [ContextMenu("Pickup Prototype/Emit Complete Health Lifecycle")]
        public void EmitCompleteHealthPickupLifecycle()
        {
            EmitHealthPickupState();
            if (!healthPickupActive)
            {
                return;
            }

            EmitAcceptedHealthPickup();
            EmitAppliedHealthState();
        }

        public bool TryCollectActiveHealthPickup(string hand)
        {
            if (!CanInject() || !healthPickupActive)
            {
                if (!healthPickupActive)
                {
                    Debug.LogWarning("Cannot collect before the debug pickup is active.");
                }

                return false;
            }

            healthPickupHand = hand == "RIGHT" ? "RIGHT" : "LEFT";
            EmitAcceptedHealthPickup();
            EmitAppliedHealthState();
            return true;
        }

        private void InjectState()
        {
            PickupStateMessage[] activeItems = healthPickupActive
                ? new[] { BuildHealthPickup() }
                : System.Array.Empty<PickupStateMessage>();

            MatchStateMessage state = new()
            {
                type = "MatchState",
                seq = stateSequence++,
                timestamp = MillisecondsNow(),
                player_1 = new PlayerStateMessage { health = playerOneHealth, stamina = 75f },
                player_2 = new PlayerStateMessage { health = playerTwoHealth, stamina = 68f },
                round_time = Mathf.Max(0f, 90f - Time.unscaledTime),
                state = "FIGHTING",
                active_items = activeItems
            };

            networkClient.InjectForDevelopment(JsonUtility.ToJson(state));
        }

        private PickupStateMessage BuildHealthPickup()
        {
            return new PickupStateMessage
            {
                id = healthPickupId,
                item_type = "HEALTH",
                owner_player = localPlayerId,
                distance_m = healthPickupDistanceMetres,
                bearing_degrees = healthPickupBearingDegrees,
                magnitude = healthPickupMagnitude,
                remaining_ms = healthPickupRemainingMilliseconds
            };
        }

        private void ActivateHealthPickup(string itemId, float bearingDegrees)
        {
            if (!CanInject())
            {
                return;
            }

            healthPickupId = itemId;
            healthPickupBearingDegrees = bearingDegrees;
            healthPickupActive = true;
            InjectState();
        }

        private bool CanInject()
        {
            if (networkClient != null)
            {
                return true;
            }

            Debug.LogWarning("MockGameEventSource needs a GameNetworkClient reference.");
            return false;
        }

        private void OnValidate()
        {
            localPlayerId = Mathf.Clamp(localPlayerId, 1, 2);
            healthPickupMagnitude = Mathf.Clamp(healthPickupMagnitude, 0f, 100f);
            healthPickupDistanceMetres = Mathf.Clamp(healthPickupDistanceMetres, 0.5f, 2f);
            healthPickupBearingDegrees = Mathf.Clamp(healthPickupBearingDegrees, -90f, 90f);
            healthPickupRemainingMilliseconds = Mathf.Clamp(
                healthPickupRemainingMilliseconds, 0, 120000);
            playerOneHealth = Mathf.Clamp(playerOneHealth, 0f, 100f);
            playerTwoHealth = Mathf.Clamp(playerTwoHealth, 0f, 100f);
            if (healthPickupHand != "LEFT" && healthPickupHand != "RIGHT")
            {
                healthPickupHand = "LEFT";
            }
        }

        private static long MillisecondsNow()
        {
            return (long)(Time.realtimeSinceStartupAsDouble * 1000.0);
        }

#if UNITY_EDITOR
        public void SetPlayerHealthForTesting(float health)
        {
            if (localPlayerId == 1)
            {
                playerOneHealth = Mathf.Clamp(health, 0f, 100f);
            }
            else
            {
                playerTwoHealth = Mathf.Clamp(health, 0f, 100f);
            }
        }
#endif
    }
}
