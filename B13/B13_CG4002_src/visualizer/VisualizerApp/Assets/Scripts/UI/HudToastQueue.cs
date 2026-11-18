using System;
using System.Collections.Generic;
using UnityEngine;

namespace CG4002.Visualizer.UI
{
    /// <summary>
    /// Pure notification queue with bounded pending and de-duplication history.
    /// The caller supplies unscaled delta time so animation is independent of game pause.
    /// </summary>
    public sealed class HudToastQueue
    {
        private sealed class Entry
        {
            public Entry(string itemId, string message)
            {
                ItemId = itemId;
                Message = message;
            }

            public string ItemId { get; }
            public string Message { get; }
        }

        private readonly Queue<Entry> pending = new();
        private readonly HashSet<string> seenIds = new(StringComparer.Ordinal);
        private readonly Queue<string> seenOrder = new();
        private readonly int maximumPending;
        private readonly int maximumRememberedIds;

        private Entry current;
        private float elapsed;

        public HudToastQueue(int maximumPending = 4, int maximumRememberedIds = 64)
        {
            this.maximumPending = Mathf.Max(1, maximumPending);
            this.maximumRememberedIds = Mathf.Max(
                this.maximumPending + 1,
                maximumRememberedIds);
        }

        public bool IsShowing => current != null;
        public string CurrentItemId => current?.ItemId ?? string.Empty;
        public string CurrentMessage => current?.Message ?? string.Empty;
        public int PendingCount => pending.Count;
        public int SeenCount => seenIds.Count;

        public bool TryEnqueue(string itemId, string message)
        {
            if (string.IsNullOrEmpty(itemId) || string.IsNullOrEmpty(message) ||
                !seenIds.Add(itemId))
            {
                return false;
            }

            seenOrder.Enqueue(itemId);
            TrimSeenHistory();

            if (pending.Count >= maximumPending)
            {
                // Preserve the toast already on screen, but favour the newest pending state.
                pending.Dequeue();
            }

            pending.Enqueue(new Entry(itemId, message));
            StartNextIfIdle();
            return true;
        }

        public float Advance(
            float unscaledDeltaTime,
            float fadeInSeconds,
            float holdSeconds,
            float fadeOutSeconds)
        {
            StartNextIfIdle();
            if (current == null)
            {
                return 0f;
            }

            float fadeIn = Mathf.Max(0f, fadeInSeconds);
            float hold = Mathf.Max(0f, holdSeconds);
            float fadeOut = Mathf.Max(0f, fadeOutSeconds);
            float duration = fadeIn + hold + fadeOut;
            float remainingDelta = Mathf.Max(0f, unscaledDeltaTime);

            while (current != null && (duration <= 0f || elapsed + remainingDelta >= duration))
            {
                remainingDelta = duration > 0f
                    ? Mathf.Max(0f, elapsed + remainingDelta - duration)
                    : 0f;
                current = null;
                elapsed = 0f;
                StartNextIfIdle();

                if (current == null)
                {
                    return 0f;
                }

                if (duration <= 0f)
                {
                    continue;
                }
            }

            elapsed += remainingDelta;
            if (fadeIn > 0f && elapsed < fadeIn)
            {
                return Mathf.Clamp01(elapsed / fadeIn);
            }

            if (elapsed < fadeIn + hold || fadeOut <= 0f)
            {
                return 1f;
            }

            return Mathf.Clamp01(1f - ((elapsed - fadeIn - hold) / fadeOut));
        }

        private void StartNextIfIdle()
        {
            if (current == null && pending.Count > 0)
            {
                current = pending.Dequeue();
                elapsed = 0f;
            }
        }

        private void TrimSeenHistory()
        {
            while (seenOrder.Count > maximumRememberedIds)
            {
                seenIds.Remove(seenOrder.Dequeue());
            }
        }
    }
}
