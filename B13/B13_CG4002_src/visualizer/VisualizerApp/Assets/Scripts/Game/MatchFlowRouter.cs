using System;
using CG4002.Visualizer.Networking;

namespace CG4002.Visualizer.Game
{
    public enum MatchFlowPhase
    {
        Connecting,
        Lobby,
        Calibrating,
        Countdown,
        Fighting,
        Paused,
        RoundEnd,
        MatchEnd,
        SafetyStop
    }

    public readonly struct MatchFlowRoute
    {
        public MatchFlowRoute(
            MatchFlowPhase previous,
            MatchFlowPhase current,
            bool authoritativeStateRecognized)
        {
            Previous = previous;
            Current = current;
            AuthoritativeStateRecognized = authoritativeStateRecognized;
        }

        public MatchFlowPhase Previous { get; }
        public MatchFlowPhase Current { get; }
        public bool AuthoritativeStateRecognized { get; }
        public bool Changed => Previous != Current;
    }

    /// <summary>
    /// Resolves network and authoritative match state into a presentation-only phase.
    /// It deliberately accepts any known server phase from any previous phase so a
    /// reconnecting client can converge immediately on the latest MatchState.
    /// </summary>
    public sealed class MatchFlowRouter
    {
        private bool hasReceivedAuthoritativeState;

        public MatchFlowPhase Current { get; private set; } = MatchFlowPhase.Connecting;

        public MatchFlowRoute Route(string authoritativeState, ConnectionStatus connectionStatus)
        {
            MatchFlowPhase previous = Current;
            bool recognized = true;

            switch (connectionStatus)
            {
                case ConnectionStatus.Connected:
                    if (TryParseAuthoritativeState(authoritativeState, out MatchFlowPhase phase))
                    {
                        Current = phase;
                        hasReceivedAuthoritativeState = true;
                    }
                    else
                    {
                        Current = MatchFlowPhase.SafetyStop;
                        recognized = false;
                    }

                    break;

                case ConnectionStatus.Connecting:
                case ConnectionStatus.Reconnecting:
                    Current = IsActivePlayPhase(previous)
                        ? MatchFlowPhase.SafetyStop
                        : MatchFlowPhase.Connecting;
                    break;

                case ConnectionStatus.Disconnected:
                    Current = hasReceivedAuthoritativeState
                        ? MatchFlowPhase.SafetyStop
                        : MatchFlowPhase.Connecting;
                    break;

                default:
                    Current = MatchFlowPhase.SafetyStop;
                    recognized = false;
                    break;
            }

            return new MatchFlowRoute(previous, Current, recognized);
        }

        public static bool TryParseAuthoritativeState(string value, out MatchFlowPhase phase)
        {
            switch (value?.Trim().ToUpperInvariant())
            {
                case "LOBBY":
                    phase = MatchFlowPhase.Lobby;
                    return true;
                case "CALIBRATING":
                    phase = MatchFlowPhase.Calibrating;
                    return true;
                case "COUNTDOWN":
                    phase = MatchFlowPhase.Countdown;
                    return true;
                case "FIGHTING":
                    phase = MatchFlowPhase.Fighting;
                    return true;
                case "PAUSED":
                    phase = MatchFlowPhase.Paused;
                    return true;
                case "ROUND_END":
                    phase = MatchFlowPhase.RoundEnd;
                    return true;
                case "MATCH_END":
                    phase = MatchFlowPhase.MatchEnd;
                    return true;
                default:
                    phase = MatchFlowPhase.SafetyStop;
                    return false;
            }
        }

        private static bool IsActivePlayPhase(MatchFlowPhase phase)
        {
            return phase == MatchFlowPhase.Countdown || phase == MatchFlowPhase.Fighting;
        }
    }
}
