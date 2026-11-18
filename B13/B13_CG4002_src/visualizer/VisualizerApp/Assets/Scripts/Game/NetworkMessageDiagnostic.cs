using CG4002.Visualizer.Models;

namespace CG4002.Visualizer.Game
{
    public readonly struct NetworkMessageDiagnostic
    {
        public NetworkMessageDiagnostic(
            bool accepted,
            MessageKind kind,
            long sequence,
            int receivedCount,
            int acceptedCount,
            string summary)
        {
            Accepted = accepted;
            Kind = kind;
            Sequence = sequence;
            ReceivedCount = receivedCount;
            AcceptedCount = acceptedCount;
            Summary = summary;
        }

        public bool Accepted { get; }
        public MessageKind Kind { get; }
        public long Sequence { get; }
        public int ReceivedCount { get; }
        public int AcceptedCount { get; }
        public string Summary { get; }
    }
}
