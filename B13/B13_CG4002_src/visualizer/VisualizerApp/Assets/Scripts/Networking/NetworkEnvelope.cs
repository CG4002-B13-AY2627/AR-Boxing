namespace CG4002.Visualizer.Networking
{
    public enum NetworkItemKind
    {
        Payload,
        Status
    }

    public enum ConnectionStatus
    {
        Disconnected,
        Connecting,
        Connected,
        Reconnecting
    }

    public readonly struct NetworkEnvelope
    {
        private NetworkEnvelope(NetworkItemKind kind, string payload, ConnectionStatus status)
        {
            Kind = kind;
            Payload = payload;
            Status = status;
        }

        public NetworkItemKind Kind { get; }
        public string Payload { get; }
        public ConnectionStatus Status { get; }

        public static NetworkEnvelope FromPayload(string payload)
        {
            return new NetworkEnvelope(NetworkItemKind.Payload, payload, default);
        }

        public static NetworkEnvelope FromStatus(ConnectionStatus status)
        {
            return new NetworkEnvelope(NetworkItemKind.Status, string.Empty, status);
        }
    }
}
