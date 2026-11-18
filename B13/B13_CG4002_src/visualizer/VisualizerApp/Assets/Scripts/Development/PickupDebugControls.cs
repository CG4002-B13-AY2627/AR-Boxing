using CG4002.Visualizer.UI;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using CG4002.Visualizer.Presentation;

namespace CG4002.Visualizer.Development
{
    /// <summary>Editor-only buttons that inject normal protocol messages for WP2/WP3 simulation.</summary>
    public sealed class PickupDebugControls : MonoBehaviour
    {
        [SerializeField] private MockGameEventSource eventSource;
        [SerializeField] private PickupReachPresenter reachPresenter;
        [SerializeField] private PickupCollectionPresenter collectionPresenter;

        private void Awake()
        {
#if UNITY_EDITOR
            BuildRuntimeControls();
#endif
        }

#if UNITY_EDITOR
        private void BuildRuntimeControls()
        {
            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            var canvasObject = new GameObject(
                "PickupDebugCanvas",
                typeof(RectTransform),
                typeof(Canvas),
                typeof(CanvasScaler),
                typeof(GraphicRaycaster));
            canvasObject.transform.SetParent(transform, false);
            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 340;

            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 0.5f;

            var safeObject = new GameObject("SafeArea", typeof(RectTransform));
            safeObject.transform.SetParent(canvasObject.transform, false);
            RectTransform safeRect = safeObject.GetComponent<RectTransform>();
            Stretch(safeRect);
            safeObject.AddComponent<RuntimeSafeArea>();

            RectTransform panel = CreateRect("PickupDebugPanel", safeObject.transform);
            panel.anchorMin = Vector2.zero;
            panel.anchorMax = Vector2.zero;
            panel.pivot = Vector2.zero;
            panel.anchoredPosition = new Vector2(22f, 22f);
            panel.sizeDelta = new Vector2(710f, 174f);
            Image background = panel.gameObject.AddComponent<Image>();
            background.color = new Color(0.015f, 0.02f, 0.035f, 0.88f);

            CreateButton(panel, font, "HealthLeft", "HEALTH LEFT", 12f, 110f,
                eventSource != null ? eventSource.EmitHealthPickupLeft : null);
            CreateButton(panel, font, "HealthCentre", "HEALTH CENTRE", 182f, 110f,
                eventSource != null ? eventSource.EmitHealthPickupCentre : null);
            CreateButton(panel, font, "HealthRight", "HEALTH RIGHT", 352f, 110f,
                eventSource != null ? eventSource.EmitHealthPickupRight : null);
            CreateButton(panel, font, "ClearItems", "CLEAR ITEMS", 522f, 110f,
                eventSource != null ? eventSource.ClearHealthPickups : null);

            CreateButton(panel, font, "ReachLeft", "REACH LEFT", 12f, 48f,
                reachPresenter != null ? reachPresenter.ReachLeft : null);
            CreateButton(panel, font, "ReachAutomatic", "REACH AUTO", 182f, 48f,
                reachPresenter != null ? reachPresenter.ReachAutomatic : null);
            CreateButton(panel, font, "ReachRight", "REACH RIGHT", 352f, 48f,
                reachPresenter != null ? reachPresenter.ReachRight : null);
            CreateButton(panel, font, "CollectNearest", "COLLECT NEAREST", 522f, 48f,
                collectionPresenter != null
                    ? collectionPresenter.CollectNearestHealthForDebug
                    : null);

            RectTransform hintRect = CreateRect("SimulationNavigationHint", panel);
            hintRect.anchorMin = Vector2.zero;
            hintRect.anchorMax = new Vector2(1f, 0f);
            hintRect.pivot = new Vector2(0.5f, 0f);
            hintRect.anchoredPosition = new Vector2(0f, 8f);
            hintRect.sizeDelta = new Vector2(-24f, 30f);
            Text hint = hintRect.gameObject.AddComponent<Text>();
            hint.font = font;
            hint.fontSize = 17;
            hint.alignment = TextAnchor.MiddleLeft;
            hint.color = new Color(0.75f, 0.83f, 0.94f, 1f);
            hint.text = "MOVE: click Game view, then HOLD RIGHT MOUSE + WASD  |  Q/E vertical  |  Shift faster";
            hint.raycastTarget = false;
        }

        private static void CreateButton(
            RectTransform parent,
            Font font,
            string name,
            string label,
            float x,
            float y,
            UnityAction callback)
        {
            RectTransform rect = CreateRect(name, parent);
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.zero;
            rect.pivot = Vector2.zero;
            rect.anchoredPosition = new Vector2(x, y);
            rect.sizeDelta = new Vector2(158f, 52f);
            Image image = rect.gameObject.AddComponent<Image>();
            image.color = new Color(0.12f, 0.55f, 0.28f, 0.95f);
            Button button = rect.gameObject.AddComponent<Button>();
            button.targetGraphic = image;
            button.navigation = new Navigation { mode = Navigation.Mode.None };
            if (callback != null)
            {
                button.onClick.AddListener(callback);
            }

            RectTransform labelRect = CreateRect("Label", rect);
            Stretch(labelRect);
            Text text = labelRect.gameObject.AddComponent<Text>();
            text.font = font;
            text.fontSize = 16;
            text.fontStyle = FontStyle.Bold;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = Color.white;
            text.text = label;
            text.raycastTarget = false;
        }

        private static RectTransform CreateRect(string name, Transform parent)
        {
            var value = new GameObject(name, typeof(RectTransform));
            value.transform.SetParent(parent, false);
            return value.GetComponent<RectTransform>();
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = Vector2.zero;
        }
#endif
    }
}
