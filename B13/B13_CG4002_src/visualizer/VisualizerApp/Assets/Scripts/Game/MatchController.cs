using System;
using CG4002.Visualizer.Models;
using CG4002.Visualizer.Networking;
using UnityEngine;

namespace CG4002.Visualizer.Game
{
    public sealed class MatchController : MonoBehaviour
    {
        [SerializeField] private GameNetworkClient networkClient;
        [SerializeField, Min(1)] private int maximumMessagesPerFrame = 64;

        private readonly MatchStateStore store = new();

        public MatchSnapshot Current => store.Current;
        public ConnectionStatus ConnectionStatus { get; private set; } = ConnectionStatus.Disconnected;
        public int ReceivedPayloadCount { get; private set; }
        public int AcceptedPayloadCount { get; private set; }
        public float LastAcceptedMessageRealtime { get; private set; } = -1f;

        public event Action<MatchSnapshot> StateChanged;
        public event Action<GameEventMessage> GameEventReceived;
        public event Action<ConnectionStatus> ConnectionStatusChanged;
        public event Action<NetworkMessageDiagnostic> NetworkMessageObserved;

        private void Update()
        {
            DrainQueue();
        }

        private int DrainQueue()
        {
            if (networkClient == null)
            {
                return 0;
            }

            int processed = 0;
            while (processed < maximumMessagesPerFrame && networkClient.TryDequeue(out NetworkEnvelope item))
            {
                processed++;
                if (item.Kind == NetworkItemKind.Status)
                {
                    ApplyConnectionStatus(item.Status);
                    continue;
                }

                ReceivedPayloadCount++;
                if (!MessageDecoder.TryDecode(item.Payload, out DecodedMessage decoded, out string error))
                {
                    PublishDiagnostic(false, MessageKind.Unknown, -1, "Rejected: " + error);
                    Debug.LogWarning("Dropped visualizer message: " + error);
                    continue;
                }

                if (decoded.Kind == MessageKind.MatchState && store.TryApply(decoded.MatchState))
                {
                    MatchStateMessage state = decoded.MatchState;
                    MarkAccepted(
                        MessageKind.MatchState,
                        state.seq,
                        $"{state.state}  P1 {state.player_1.health:0}%  P2 {state.player_2.health:0}%  " +
                        $"{state.round_time:0.0}s  Items {state.active_items?.Length ?? 0}");
                    StateChanged?.Invoke(store.Current);
                }
                else if (decoded.Kind == MessageKind.GameEvent && store.TryAccept(decoded.GameEvent))
                {
                    GameEventMessage gameEvent = decoded.GameEvent;
                    MarkAccepted(
                        MessageKind.GameEvent,
                        gameEvent.seq,
                        BuildEventSummary(gameEvent));
                    GameEventReceived?.Invoke(decoded.GameEvent);
                }
                else
                {
                    long sequence = decoded.Kind == MessageKind.MatchState
                        ? decoded.MatchState.seq
                        : decoded.GameEvent.seq;
                    PublishDiagnostic(false, decoded.Kind, sequence, "Ignored stale or duplicate message.");
                }
            }

            return processed;
        }

        private void MarkAccepted(MessageKind kind, long sequence, string summary)
        {
            AcceptedPayloadCount++;
            LastAcceptedMessageRealtime = Time.realtimeSinceStartup;
            PublishDiagnostic(true, kind, sequence, summary);
        }

        private static string BuildEventSummary(GameEventMessage gameEvent)
        {
            if (gameEvent.@event == "ITEM_PICKUP")
            {
                return $"ITEM_PICKUP/{gameEvent.item_type}  P{gameEvent.source_player}  " +
                       $"{gameEvent.item_id}  {gameEvent.hand}";
            }

            return $"{gameEvent.@event}/{gameEvent.punch}  " +
                   $"P{gameEvent.source_player}>P{gameEvent.target_player}  {gameEvent.outcome}";
        }

        private void PublishDiagnostic(bool accepted, MessageKind kind, long sequence, string summary)
        {
            NetworkMessageObserved?.Invoke(new NetworkMessageDiagnostic(
                accepted,
                kind,
                sequence,
                ReceivedPayloadCount,
                AcceptedPayloadCount,
                summary));
        }

        private void ApplyConnectionStatus(ConnectionStatus value)
        {
            if (ConnectionStatus == value)
            {
                return;
            }

            ConnectionStatus = value;
            ConnectionStatusChanged?.Invoke(value);
        }

#if UNITY_EDITOR
        public void ConfigureForTesting(GameNetworkClient client, int messageCap = 64)
        {
            networkClient = client;
            maximumMessagesPerFrame = Mathf.Max(1, messageCap);
        }

        public int ProcessQueuedMessagesForTesting()
        {
            return DrainQueue();
        }
#endif
    }
}
