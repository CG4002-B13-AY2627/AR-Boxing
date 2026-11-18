using System.Collections.Generic;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Presentation;
using UnityEngine;
using UnityEngine.UI;

namespace CG4002.Visualizer.UI
{
    /// <summary>Displays short, safe-area-aware notices for new local-player pickups.</summary>
    public sealed class HudToastPresenter : MonoBehaviour
    {
        private const string HealthSpawnMessage = "HEALTH PICKUP SPAWNED";

        [SerializeField] private MatchController controller;
        [SerializeField, Range(1, 2)] private int localPlayerId = 1;
        [SerializeField, Range(1, 8)] private int maximumPendingNotifications = 4;
        [SerializeField, Range(8, 256)] private int maximumRememberedItemIds = 64;
        [SerializeField, Min(0f)] private float fadeInSeconds = 0.18f;
        [SerializeField, Min(0f)] private float holdSeconds = 1.35f;
        [SerializeField, Min(0f)] private float fadeOutSeconds = 0.30f;

        private HudToastQueue queue;
        private CanvasGroup toastGroup;
        private Text messageText;
        private string renderedMessage = string.Empty;
        private bool subscribed;

        public bool IsVisible => toastGroup != null && toastGroup.alpha > 0.001f;
        public string CurrentItemId => queue?.CurrentItemId ?? string.Empty;
        public int PendingNotificationCount => queue?.PendingCount ?? 0;

        public void ShowCollection(string itemId, float magnitude)
        {
            string message = magnitude > 0f
                ? $"+{Mathf.RoundToInt(magnitude)} HEALTH"
                : "HEALTH PICKED UP";
            ShowMessage("collection:" + (itemId ?? string.Empty), message);
        }

        public void ShowMessage(string notificationId, string message)
        {
            EnsureQueue();
            queue.TryEnqueue(notificationId, message);
            RenderCurrentMessage();
        }

        private void Awake()
        {
            EnsureQueue();
            BuildRuntimeToast();
            SetVisualAlpha(0f);
        }

        private void OnEnable()
        {
            Subscribe();
            if (controller != null)
            {
                ObserveState(controller.Current);
            }
        }

        private void OnDisable()
        {
            Unsubscribe();
            SetVisualAlpha(0f);
        }

        private void Update()
        {
            Tick(Time.unscaledDeltaTime);
        }

        private void ObserveState(MatchSnapshot snapshot)
        {
            EnsureQueue();
            IReadOnlyList<PickupSnapshot> items = snapshot?.ActiveItems;
            if (items == null)
            {
                return;
            }

            for (int index = 0; index < items.Count; index++)
            {
                PickupSnapshot item = items[index];
                if (PickupSpawnPresenter.ShouldRender(item, localPlayerId))
                {
                    queue.TryEnqueue(item.Id, HealthSpawnMessage);
                }
            }

            RenderCurrentMessage();
        }

        private void Tick(float unscaledDeltaTime)
        {
            EnsureQueue();
            float alpha = queue.Advance(
                unscaledDeltaTime,
                fadeInSeconds,
                holdSeconds,
                fadeOutSeconds);
            RenderCurrentMessage();
            SetVisualAlpha(alpha);
        }

        private void Subscribe()
        {
            if (controller == null || subscribed)
            {
                return;
            }

            controller.StateChanged += ObserveState;
            subscribed = true;
        }

        private void Unsubscribe()
        {
            if (controller != null && subscribed)
            {
                controller.StateChanged -= ObserveState;
            }

            subscribed = false;
        }

        private void EnsureQueue()
        {
            queue ??= new HudToastQueue(
                maximumPendingNotifications,
                maximumRememberedItemIds);
        }

        private void BuildRuntimeToast()
        {
            if (toastGroup != null)
            {
                return;
            }

            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            var canvasObject = new GameObject(
                "ItemSpawnToastCanvas",
                typeof(RectTransform),
                typeof(Canvas),
                typeof(CanvasScaler));
            canvasObject.transform.SetParent(transform, false);
            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 310;

            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.matchWidthOrHeight = 0.5f;

            var safeObject = new GameObject("SafeArea", typeof(RectTransform));
            safeObject.transform.SetParent(canvasObject.transform, false);
            RectTransform safeRect = safeObject.GetComponent<RectTransform>();
            Stretch(safeRect);
            safeObject.AddComponent<RuntimeSafeArea>();

            var panel = new GameObject(
                "ItemSpawnToast",
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image),
                typeof(CanvasGroup));
            panel.transform.SetParent(safeObject.transform, false);
            RectTransform panelRect = panel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0f, 1f);
            panelRect.anchorMax = panelRect.anchorMin;
            panelRect.pivot = new Vector2(0f, 1f);
            panelRect.anchoredPosition = new Vector2(24f, -150f);
            panelRect.sizeDelta = new Vector2(450f, 72f);
            panel.GetComponent<Image>().color = new Color(0.015f, 0.12f, 0.055f, 0.94f);
            toastGroup = panel.GetComponent<CanvasGroup>();
            toastGroup.blocksRaycasts = false;
            toastGroup.interactable = false;

            var icon = new GameObject(
                "HealthIcon",
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image));
            icon.transform.SetParent(panel.transform, false);
            RectTransform iconRect = icon.GetComponent<RectTransform>();
            iconRect.anchorMin = new Vector2(0f, 0.5f);
            iconRect.anchorMax = iconRect.anchorMin;
            iconRect.pivot = new Vector2(0f, 0.5f);
            iconRect.anchoredPosition = new Vector2(12f, 0f);
            iconRect.sizeDelta = new Vector2(50f, 50f);
            icon.GetComponent<Image>().color = new Color(0.08f, 0.82f, 0.30f, 1f);

            var plusObject = new GameObject(
                "Plus",
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Text));
            plusObject.transform.SetParent(icon.transform, false);
            RectTransform plusRect = plusObject.GetComponent<RectTransform>();
            Stretch(plusRect);
            Text plus = plusObject.GetComponent<Text>();
            plus.font = font;
            plus.fontSize = 38;
            plus.fontStyle = FontStyle.Bold;
            plus.alignment = TextAnchor.MiddleCenter;
            plus.color = Color.white;
            plus.text = "+";
            plus.raycastTarget = false;

            var textObject = new GameObject(
                "Message",
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Text));
            textObject.transform.SetParent(panel.transform, false);
            RectTransform textRect = textObject.GetComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero;
            textRect.anchorMax = Vector2.one;
            textRect.offsetMin = new Vector2(78f, 8f);
            textRect.offsetMax = new Vector2(-14f, -8f);
            messageText = textObject.GetComponent<Text>();
            messageText.font = font;
            messageText.fontSize = 24;
            messageText.fontStyle = FontStyle.Bold;
            messageText.alignment = TextAnchor.MiddleLeft;
            messageText.color = new Color(0.80f, 1f, 0.85f, 1f);
            messageText.raycastTarget = false;
        }

        private void RenderCurrentMessage()
        {
            if (messageText == null || queue == null || renderedMessage == queue.CurrentMessage)
            {
                return;
            }

            renderedMessage = queue.CurrentMessage;
            messageText.text = renderedMessage;
        }

        private void SetVisualAlpha(float alpha)
        {
            if (toastGroup != null)
            {
                toastGroup.alpha = Mathf.Clamp01(alpha);
            }
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = Vector2.zero;
        }

#if UNITY_EDITOR
        public int SeenItemCountForTesting => queue?.SeenCount ?? 0;

        public void ConfigureForTesting(
            MatchController source,
            int playerId = 1,
            int pendingCap = 4,
            float fadeIn = 0.18f,
            float hold = 1.35f,
            float fadeOut = 0.30f)
        {
            Unsubscribe();
            controller = source;
            localPlayerId = playerId;
            maximumPendingNotifications = pendingCap;
            fadeInSeconds = fadeIn;
            holdSeconds = hold;
            fadeOutSeconds = fadeOut;
            queue = new HudToastQueue(pendingCap, maximumRememberedItemIds);
            if (isActiveAndEnabled)
            {
                Subscribe();
            }
        }

        public void ApplySnapshotForTesting(MatchSnapshot snapshot)
        {
            ObserveState(snapshot);
        }

        public float TickForTesting(float unscaledDeltaTime)
        {
            Tick(unscaledDeltaTime);
            return toastGroup != null ? toastGroup.alpha : 0f;
        }
#endif

        private void OnValidate()
        {
            localPlayerId = Mathf.Clamp(localPlayerId, 1, 2);
            maximumPendingNotifications = Mathf.Clamp(maximumPendingNotifications, 1, 8);
            maximumRememberedItemIds = Mathf.Clamp(maximumRememberedItemIds, 8, 256);
            fadeInSeconds = Mathf.Max(0f, fadeInSeconds);
            holdSeconds = Mathf.Max(0f, holdSeconds);
            fadeOutSeconds = Mathf.Max(0f, fadeOutSeconds);
        }
    }
}
