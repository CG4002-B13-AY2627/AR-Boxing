using CG4002.Visualizer.AR;
using UnityEngine;
using UnityEngine.UI;

namespace CG4002.Visualizer.UI
{
    /// <summary>Safe-area-aware, debounced floor guidance separate from ordinary HUD toasts.</summary>
    public sealed class FloorStatusPresenter : MonoBehaviour
    {
        [SerializeField] private FloorPlaneProvider floorProvider;
        [SerializeField, Min(0f)] private float visibilityDebounceSeconds = 0.2f;

        private GameObject promptPanel;
        private bool requestedVisible;
        private float requestChangedAt;

        public bool IsPromptVisible => promptPanel != null && promptPanel.activeSelf;

        private void Awake()
        {
            BuildRuntimePrompt();
        }

        private void Update()
        {
            bool desired = floorProvider != null &&
                floorProvider.PlacementRequested && !floorProvider.IsReady;
            if (desired != requestedVisible)
            {
                requestedVisible = desired;
                requestChangedAt = Time.unscaledTime;
            }

            if (promptPanel != null && promptPanel.activeSelf != requestedVisible &&
                Time.unscaledTime - requestChangedAt >= visibilityDebounceSeconds)
            {
                promptPanel.SetActive(requestedVisible);
            }
        }

        private void BuildRuntimePrompt()
        {
            if (promptPanel != null)
            {
                return;
            }

            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            var canvasObject = new GameObject(
                "FloorStatusCanvas",
                typeof(RectTransform),
                typeof(Canvas),
                typeof(CanvasScaler));
            canvasObject.transform.SetParent(transform, false);
            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 320;

            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.matchWidthOrHeight = 0.5f;

            var safeObject = new GameObject("SafeArea", typeof(RectTransform));
            safeObject.transform.SetParent(canvasObject.transform, false);
            RectTransform safeRect = safeObject.GetComponent<RectTransform>();
            Stretch(safeRect);
            safeObject.AddComponent<RuntimeSafeArea>();

            promptPanel = new GameObject(
                "FloorNotDetectedPrompt",
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Image));
            promptPanel.transform.SetParent(safeObject.transform, false);
            RectTransform panelRect = promptPanel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.5f, 0f);
            panelRect.anchorMax = panelRect.anchorMin;
            panelRect.pivot = new Vector2(0.5f, 0f);
            panelRect.anchoredPosition = new Vector2(0f, 42f);
            panelRect.sizeDelta = new Vector2(660f, 78f);
            promptPanel.GetComponent<Image>().color = new Color(0.25f, 0.12f, 0.01f, 0.90f);

            var textObject = new GameObject(
                "Message",
                typeof(RectTransform),
                typeof(CanvasRenderer),
                typeof(Text));
            textObject.transform.SetParent(promptPanel.transform, false);
            RectTransform textRect = textObject.GetComponent<RectTransform>();
            Stretch(textRect);
            textRect.offsetMin = new Vector2(18f, 8f);
            textRect.offsetMax = new Vector2(-18f, -8f);
            Text text = textObject.GetComponent<Text>();
            text.font = font;
            text.fontSize = 24;
            text.fontStyle = FontStyle.Bold;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = new Color(1f, 0.86f, 0.35f, 1f);
            text.text = "FLOOR NOT DETECTED  -  Pause and look down slowly.";
            text.raycastTarget = false;

            promptPanel.SetActive(false);
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
        public void ConfigureForTesting(FloorPlaneProvider provider)
        {
            floorProvider = provider;
        }
#endif
    }
}
