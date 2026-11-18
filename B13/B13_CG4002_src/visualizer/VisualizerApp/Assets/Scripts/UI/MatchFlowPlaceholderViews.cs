using System;
using System.Collections.Generic;
using CG4002.Visualizer.Game;
using UnityEngine;
using UnityEngine.UI;

namespace CG4002.Visualizer.UI
{
    public readonly struct MatchFlowPlaceholderCopy
    {
        public MatchFlowPlaceholderCopy(string title, string detail, string hint, bool compact)
        {
            Title = title;
            Detail = detail;
            Hint = hint;
            Compact = compact;
        }

        public string Title { get; }
        public string Detail { get; }
        public string Hint { get; }
        public bool Compact { get; }
    }

    public static class MatchFlowPlaceholderContent
    {
        public static MatchFlowPlaceholderCopy For(MatchFlowPhase phase)
        {
            switch (phase)
            {
                case MatchFlowPhase.Connecting:
                    return new MatchFlowPlaceholderCopy(
                        "CONNECTING",
                        "Looking for the match server",
                        "Keep the headset still - camera view remains active",
                        false);
                case MatchFlowPhase.Lobby:
                    return new MatchFlowPlaceholderCopy(
                        "AR BOXING",
                        "Waiting for two players",
                        "DOUBLE TAP  Join / ready    |    TRIPLE TAP  Leave",
                        false);
                case MatchFlowPhase.Calibrating:
                    return new MatchFlowPlaceholderCopy(
                        "CALIBRATION",
                        "Face your opponent and keep their marker in view",
                        "Both cameras must detect the other player",
                        false);
                case MatchFlowPhase.Countdown:
                    return new MatchFlowPlaceholderCopy(
                        "GET READY",
                        "Match begins after the server countdown",
                        "Hold position and keep your opponent in view",
                        false);
                case MatchFlowPhase.Fighting:
                    return new MatchFlowPlaceholderCopy(
                        "FIGHTING",
                        string.Empty,
                        "DOUBLE TAP  Pause",
                        true);
                case MatchFlowPhase.Paused:
                    return new MatchFlowPlaceholderCopy(
                        "PAUSED",
                        "Hold position and keep looking at your opponent",
                        "DOUBLE TAP  Ready to resume    |    TRIPLE TAP  Leave",
                        false);
                case MatchFlowPhase.RoundEnd:
                    return new MatchFlowPlaceholderCopy(
                        "ROUND COMPLETE",
                        "Waiting for the authoritative result",
                        "Hold position",
                        false);
                case MatchFlowPhase.MatchEnd:
                    return new MatchFlowPlaceholderCopy(
                        "MATCH COMPLETE",
                        "Winner will be supplied by the game server",
                        "DOUBLE TAP  Rematch    |    TRIPLE TAP  Lobby",
                        false);
                case MatchFlowPhase.SafetyStop:
                    return new MatchFlowPlaceholderCopy(
                        "STOP - HOLD POSITION",
                        "Connection or match state is unavailable",
                        "Camera view remains active while the game reconnects",
                        false);
                default:
                    throw new ArgumentOutOfRangeException(nameof(phase), phase, null);
            }
        }
    }

    /// <summary>
    /// Builds deliberately simple, peripheral placeholder views. It is a temporary
    /// WP2 presentation layer: the match-flow and server-authority logic remain in
    /// MatchFlowRouter and MatchController respectively.
    /// </summary>
    public sealed class MatchFlowPlaceholderViews : MonoBehaviour
    {
        [SerializeField] private MatchFlowPresenter presenter;
        [SerializeField] private bool buildAtRuntime = true;

        private readonly Dictionary<MatchFlowPhase, GameObject> phaseRoots = new();
        private RectTransform canvasRoot;

        public MatchFlowPhase DisplayedPhase { get; private set; } = MatchFlowPhase.Connecting;

        private static readonly Color PanelColor = new(0.96f, 0.98f, 1f, 0.78f);
        private static readonly Color TextColor = new(0.07f, 0.10f, 0.14f, 1f);
        private static readonly Color Cyan = new(0.16f, 0.68f, 0.86f, 1f);
        private static readonly Color Amber = new(1f, 0.63f, 0.12f, 1f);
        private static readonly Color Red = new(0.92f, 0.18f, 0.16f, 1f);

        private void Awake()
        {
            if (buildAtRuntime)
            {
                BuildViews();
            }
        }

        private void OnEnable()
        {
            if (presenter == null)
            {
                return;
            }

            presenter.PhaseChanged += HandlePhaseChanged;
            Show(presenter.CurrentPhase);
        }

        private void OnDisable()
        {
            if (presenter != null)
            {
                presenter.PhaseChanged -= HandlePhaseChanged;
            }
        }

        private void HandlePhaseChanged(MatchFlowRoute route)
        {
            Show(route.Current);
        }

        public void Preview(MatchFlowPhase phase)
        {
            Show(phase);
            Debug.Log("Previewing match-flow view locally: " + phase);
        }

        public void ReturnToLiveState()
        {
            if (presenter != null)
            {
                Show(presenter.CurrentPhase);
            }
        }

        private void Show(MatchFlowPhase phase)
        {
            DisplayedPhase = phase;
            foreach (KeyValuePair<MatchFlowPhase, GameObject> pair in phaseRoots)
            {
                pair.Value.SetActive(pair.Key == phase);
            }
        }

        private void BuildViews()
        {
            if (canvasRoot != null)
            {
                return;
            }

            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

            GameObject canvasObject = new(
                "MatchFlowPlaceholderCanvas",
                typeof(RectTransform),
                typeof(Canvas),
                typeof(CanvasScaler));
            canvasObject.transform.SetParent(transform, false);

            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 250;

            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 0.5f;

            canvasRoot = CreateRect("SafeArea", canvasObject.transform);
            Stretch(canvasRoot);
            canvasRoot.gameObject.AddComponent<RuntimeSafeArea>();

            foreach (MatchFlowPhase phase in Enum.GetValues(typeof(MatchFlowPhase)))
            {
                phaseRoots.Add(phase, BuildPhaseView(phase, font));
            }
        }

        private GameObject BuildPhaseView(MatchFlowPhase phase, Font font)
        {
            RectTransform root = CreateRect(phase + "View", canvasRoot);
            Stretch(root);

            MatchFlowPlaceholderCopy copy = MatchFlowPlaceholderContent.For(phase);
            Color accent = AccentFor(phase);

            if (copy.Compact)
            {
                BuildCompactFightingView(root, font, copy, accent);
            }
            else
            {
                BuildTopBanner(root, font, copy, accent);
                BuildBottomHint(root, font, copy.Hint, accent);
            }

            if (phase == MatchFlowPhase.SafetyStop)
            {
                BuildSafetyEdges(root);
            }

            root.gameObject.SetActive(false);
            return root.gameObject;
        }

        private static void BuildTopBanner(
            RectTransform root,
            Font font,
            MatchFlowPlaceholderCopy copy,
            Color accent)
        {
            RectTransform panel = CreatePanel("TopBanner", root, PanelColor);
            SetRect(
                panel,
                new Vector2(0.5f, 1f),
                new Vector2(0.5f, 1f),
                new Vector2(0.5f, 1f),
                new Vector2(0f, -26f),
                new Vector2(760f, 118f));

            RectTransform accentBar = CreatePanel("Accent", panel, accent);
            SetRect(
                accentBar,
                new Vector2(0f, 0f),
                new Vector2(0f, 1f),
                new Vector2(0f, 0.5f),
                Vector2.zero,
                new Vector2(12f, 0f));

            Text title = CreateText("Title", panel, font, 34, FontStyle.Bold);
            title.text = copy.Title;
            title.alignment = TextAnchor.MiddleCenter;
            title.color = TextColor;
            SetRect(
                title.rectTransform,
                new Vector2(0f, 0.48f),
                Vector2.one,
                new Vector2(0.5f, 0.5f),
                Vector2.zero,
                new Vector2(-48f, 0f));

            Text detail = CreateText("Detail", panel, font, 20, FontStyle.Normal);
            detail.text = copy.Detail;
            detail.alignment = TextAnchor.MiddleCenter;
            detail.color = new Color(TextColor.r, TextColor.g, TextColor.b, 0.82f);
            SetRect(
                detail.rectTransform,
                Vector2.zero,
                new Vector2(1f, 0.48f),
                new Vector2(0.5f, 0.5f),
                Vector2.zero,
                new Vector2(-48f, 0f));
        }

        private static void BuildBottomHint(
            RectTransform root,
            Font font,
            string hint,
            Color accent)
        {
            RectTransform panel = CreatePanel("BottomHint", root, PanelColor);
            SetRect(
                panel,
                new Vector2(0.5f, 0f),
                new Vector2(0.5f, 0f),
                new Vector2(0.5f, 0f),
                new Vector2(0f, 30f),
                new Vector2(920f, 66f));

            Text text = CreateText("Hint", panel, font, 20, FontStyle.Bold);
            text.text = hint;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = TextColor;
            Stretch(text.rectTransform);

            RectTransform accentBar = CreatePanel("Accent", panel, accent);
            SetRect(
                accentBar,
                new Vector2(0f, 0f),
                new Vector2(1f, 0f),
                new Vector2(0.5f, 0f),
                Vector2.zero,
                new Vector2(0f, 7f));
        }

        private static void BuildCompactFightingView(
            RectTransform root,
            Font font,
            MatchFlowPlaceholderCopy copy,
            Color accent)
        {
            RectTransform hint = CreatePanel("PauseHint", root, new Color(PanelColor.r, PanelColor.g, PanelColor.b, 0.62f));
            SetRect(
                hint,
                new Vector2(0.5f, 0f),
                new Vector2(0.5f, 0f),
                new Vector2(0.5f, 0f),
                new Vector2(0f, 30f),
                new Vector2(360f, 54f));

            Text text = CreateText("Hint", hint, font, 18, FontStyle.Bold);
            text.text = copy.Hint;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = TextColor;
            Stretch(text.rectTransform);

            RectTransform accentBar = CreatePanel("Accent", hint, accent);
            SetRect(
                accentBar,
                new Vector2(0f, 0f),
                new Vector2(1f, 0f),
                new Vector2(0.5f, 0f),
                Vector2.zero,
                new Vector2(0f, 6f));
        }

        private static void BuildSafetyEdges(RectTransform root)
        {
            const float thickness = 12f;
            Color edgeColor = new(Red.r, Red.g, Red.b, 0.72f);

            CreateEdge("TopEdge", root, Vector2.up, new Vector2(1f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, thickness), edgeColor);
            CreateEdge("BottomEdge", root, Vector2.zero, Vector2.right, new Vector2(0.5f, 0f), new Vector2(0f, thickness), edgeColor);
            CreateEdge("LeftEdge", root, Vector2.zero, Vector2.up, new Vector2(0f, 0.5f), new Vector2(thickness, 0f), edgeColor);
            CreateEdge("RightEdge", root, Vector2.right, Vector2.one, new Vector2(1f, 0.5f), new Vector2(thickness, 0f), edgeColor);
        }

        private static void CreateEdge(
            string name,
            RectTransform parent,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Vector2 pivot,
            Vector2 sizeDelta,
            Color color)
        {
            RectTransform edge = CreatePanel(name, parent, color);
            SetRect(edge, anchorMin, anchorMax, pivot, Vector2.zero, sizeDelta);
        }

        private static Color AccentFor(MatchFlowPhase phase)
        {
            switch (phase)
            {
                case MatchFlowPhase.Paused:
                case MatchFlowPhase.RoundEnd:
                    return Amber;
                case MatchFlowPhase.SafetyStop:
                    return Red;
                default:
                    return Cyan;
            }
        }

        private static RectTransform CreatePanel(string name, Transform parent, Color color)
        {
            RectTransform rect = CreateRect(name, parent);
            Image image = rect.gameObject.AddComponent<Image>();
            image.color = color;
            image.raycastTarget = false;
            return rect;
        }

        private static Text CreateText(string name, Transform parent, Font font, int size, FontStyle style)
        {
            RectTransform rect = CreateRect(name, parent);
            Text text = rect.gameObject.AddComponent<Text>();
            text.font = font;
            text.fontSize = size;
            text.fontStyle = style;
            text.raycastTarget = false;
            return text;
        }

        private static RectTransform CreateRect(string name, Transform parent)
        {
            GameObject value = new(name, typeof(RectTransform));
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

        private static void SetRect(
            RectTransform rect,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Vector2 pivot,
            Vector2 anchoredPosition,
            Vector2 sizeDelta)
        {
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = pivot;
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = sizeDelta;
        }
    }
}
