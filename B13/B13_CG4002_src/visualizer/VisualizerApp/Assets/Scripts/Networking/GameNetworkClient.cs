using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace CG4002.Visualizer.Networking
{
    public sealed class GameNetworkClient : MonoBehaviour
    {
        [Header("Laptop relay")]
        [SerializeField] private string serverUrl = "ws://192.168.137.1:8889";
        [SerializeField, Min(1f)] private float connectTimeoutSeconds = 8f;
        [SerializeField, Min(0.1f)] private float initialReconnectDelaySeconds = 0.5f;
        [SerializeField, Min(0.5f)] private float maximumReconnectDelaySeconds = 5f;
        [SerializeField] private bool connectOnEnable = true;

        private readonly ConcurrentQueue<NetworkEnvelope> incoming = new();
        private CancellationTokenSource lifetime;

        public bool TryDequeue(out NetworkEnvelope item)
        {
            return incoming.TryDequeue(out item);
        }

        public void InjectForDevelopment(string json)
        {
            incoming.Enqueue(NetworkEnvelope.FromPayload(json));
        }

        private void OnEnable()
        {
            lifetime = new CancellationTokenSource();
            if (connectOnEnable)
            {
                RunConnectionLoopAsync(lifetime.Token);
            }
            else
            {
                incoming.Enqueue(NetworkEnvelope.FromStatus(ConnectionStatus.Disconnected));
            }
        }

        private void OnDisable()
        {
            lifetime?.Cancel();
            lifetime?.Dispose();
            lifetime = null;
        }

        private async void RunConnectionLoopAsync(CancellationToken cancellationToken)
        {
            float delaySeconds = initialReconnectDelaySeconds;
            bool hasConnected = false;

            while (!cancellationToken.IsCancellationRequested)
            {
                incoming.Enqueue(NetworkEnvelope.FromStatus(
                    hasConnected ? ConnectionStatus.Reconnecting : ConnectionStatus.Connecting));

                try
                {
                    using ClientWebSocket socket = new();
                    using CancellationTokenSource connectTimeout =
                        CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                    connectTimeout.CancelAfter(TimeSpan.FromSeconds(connectTimeoutSeconds));

                    await socket.ConnectAsync(new Uri(serverUrl), connectTimeout.Token);
                    hasConnected = true;
                    delaySeconds = initialReconnectDelaySeconds;
                    incoming.Enqueue(NetworkEnvelope.FromStatus(ConnectionStatus.Connected));

                    await ReceiveUntilClosedAsync(socket, cancellationToken);
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    break;
                }
                catch (Exception)
                {
                    // Status is queued so background networking never touches scene objects.
                }

                if (cancellationToken.IsCancellationRequested)
                {
                    break;
                }

                incoming.Enqueue(NetworkEnvelope.FromStatus(ConnectionStatus.Reconnecting));
                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(delaySeconds), cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    break;
                }

                delaySeconds = Mathf.Min(delaySeconds * 2f, maximumReconnectDelaySeconds);
            }

            incoming.Enqueue(NetworkEnvelope.FromStatus(ConnectionStatus.Disconnected));
        }

        private async Task ReceiveUntilClosedAsync(ClientWebSocket socket, CancellationToken cancellationToken)
        {
            byte[] buffer = new byte[4096];

            while (socket.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
            {
                using MemoryStream message = new();
                WebSocketReceiveResult result;

                do
                {
                    result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), cancellationToken);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        if (socket.State == WebSocketState.Open || socket.State == WebSocketState.CloseReceived)
                        {
                            await socket.CloseOutputAsync(
                                WebSocketCloseStatus.NormalClosure,
                                "Closing",
                                cancellationToken);
                        }

                        return;
                    }

                    message.Write(buffer, 0, result.Count);
                }
                while (!result.EndOfMessage);

                if (result.MessageType == WebSocketMessageType.Text)
                {
                    string payload = Encoding.UTF8.GetString(message.GetBuffer(), 0, checked((int)message.Length));
                    incoming.Enqueue(NetworkEnvelope.FromPayload(payload));
                }
            }
        }
    }
}
