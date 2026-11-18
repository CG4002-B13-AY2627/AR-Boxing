using System.Collections.Generic;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Networking;
using UnityEngine;
using UnityEngine.UI;

namespace CG4002.Visualizer.UI
{
    public sealed class HudPresenter : MonoBehaviour
    {
        [Header("Data source")]
        [SerializeField] private MatchController controller;
        [SerializeField] private int localPlayerId = 1;

        [Header("Match HUD")]
        [SerializeField] private Slider playerHealth;
        [SerializeField] private Slider playerStamina;
        [SerializeField] private Slider opponentHealth;
        [SerializeField] private Slider opponentStamina;
        [SerializeField] private Text playerHealthValue;
        [SerializeField] private Text playerStaminaValue;
        [SerializeField] private Text opponentHealthValue;
        [SerializeField] private Text opponentStaminaValue;
        [SerializeField] private Text roundTimer;
        [SerializeField] private Text matchState;

        [Header("Network HUD")]
        [SerializeField] private Text networkIcon;
        [SerializeField] private Text networkStatus;
        [SerializeField] private Button debugToggle;
        [SerializeField] private GameObject debugPanel;
        [SerializeField] private Text debugOutput;
        [SerializeField] private bool showNetworkDebugOnStart;
        [SerializeField, Min(0.25f)] private float staleAfterSeconds = 1f;
        [SerializeField, Range(1, 20)] private int debugLineLimit = 8;

        [Header("Runtime setup")]
        [SerializeField] private bool buildMissingUiAtRuntime = true;

        private readonly Queue<string> debugLines = new();
        private float packetPulseUntil;
        private bool debugVisible;

        private static readonly Color ConnectedColor = new(0.2f, 0.9f, 0.38f, 1f);
        private static readonly Color WaitingColor = new(1f, 0.72f, 0.16f, 1f);
        private static readonly Color StaleColor = new(1f, 0.43f, 0.12f, 1f);
        private static readonly Color DisconnectedColor = new(0.62f, 0.65f, 0.7f, 1f);

        private void Awake()
        {
            if (buildMissingUiAtRuntime && !HasCompleteUi())
            {
                BuildRuntimeHud();
            }

            debugVisible = showNetworkDebugOnStart;
            ApplyDebugVisibility();
            if (debugToggle != null)
            {
                debugToggle.onClick.AddListener(ToggleDebugPanel);
            }
        }

        private void OnEnable()
        {
            if (controller == null)
            {
                return;
            }

            controller.StateChanged += RefreshState;
            controller.ConnectionStatusChanged += RefreshConnection;
            controller.NetworkMessageObserved += ObserveNetworkMessage;
            RefreshState(controller.Current);
            RefreshConnection(controller.ConnectionStatus);
        }

        private void OnDisable()
        {
            if (controller == null)
            {
                return;
            }

            controller.StateChanged -= RefreshState;
            controller.ConnectionStatusChanged -= RefreshConnection;
            controller.NetworkMessageObserved -= ObserveNetworkMessage;
        }

        private void Update()
        {
            RefreshNetworkPresentation();
        }

        private void RefreshState(MatchSnapshot snapshot)
        {
            bool playerOneIsLocal = localPlayerId == 1;
            float localHealth = playerOneIsLocal ? snapshot.PlayerOneHealth : snapshot.PlayerTwoHealth;
            float localStamina = playerOneIsLocal ? snapshot.PlayerOneStamina : snapshot.PlayerTwoStamina;
            float remoteHealth = playerOneIsLocal ? snapshot.PlayerTwoHealth : snapshot.PlayerOneHealth;
            float remoteStamina = playerOneIsLocal ? snapshot.PlayerTwoStamina : snapshot.PlayerOneStamina;

            SetSlider(playerHealth, localHealth);
            SetSlider(playerStamina, localStamina);
            SetSlider(opponentHealth, remoteHealth);
            SetSlider(opponentStamina, remoteStamina);
            SetValue(playerHealthValue, localHealth);
            SetValue(playerStaminaValue, localStamina);
            SetValue(opponentHealthValue, remoteHealth);
            SetValue(opponentStaminaValue, remoteStamina);

            if (roundTimer != null)
            {
                int totalSeconds = Mathf.Max(0, Mathf.CeilToInt(snapshot.RoundTime));
                roundTimer.text = $"{totalSeconds / 60:00}:{totalSeconds % 60:00}";
            }

            if (matchState != null)
            {
                matchState.text = snapshot.State;
            }
        }

        private void RefreshConnection(ConnectionStatus status)
        {
            AddDebugLine("STATUS  " + status.ToString().ToUpperInvariant());
            RefreshNetworkPresentation();
        }

        private void ObserveNetworkMessage(NetworkMessageDiagnostic message)
        {
            string sequence = message.Sequence >= 0 ? $" #{message.Sequence}" : string.Empty;
            AddDebugLine($"{(message.Accepted ? "RX" : "DROP")}  {message.Kind}{sequence}  {message.Summary}");

            if (message.Accepted)
            {
                packetPulseUntil = Time.unscaledTime + 0.15f;
            }

            RefreshNetworkPresentation();
        }

        private void RefreshNetworkPresentation()
        {
            if (controller == null || networkStatus == null)
            {
                return;
            }

            string label;
            Color color;
            switch (controller.ConnectionStatus)
            {
                case ConnectionStatus.Connecting:
                    label = "CONNECTING";
                    color = WaitingColor;
                    break;
                case ConnectionStatus.Reconnecting:
                    label = "RECONNECTING";
                    color = WaitingColor;
                    break;
                case ConnectionStatus.Connected:
                {
                    if (controller.AcceptedPayloadCount == 0)
                    {
                        label = "CONNECTED - WAITING";
                        color = WaitingColor;
                    }
                    else
                    {
                        float age = Time.realtimeSinceStartup - controller.LastAcceptedMessageRealtime;
                        bool isFresh = age <= staleAfterSeconds;
                        label = $"{(isFresh ? "LIVE" : "STALE")} - RX {controller.AcceptedPayloadCount}";
                        color = isFresh ? ConnectedColor : StaleColor;
                    }

                    break;
                }
                default:
                    label = "OFFLINE";
                    color = DisconnectedColor;
                    break;
            }

            networkStatus.text = label;
            networkStatus.color = color;
            if (networkIcon != null)
            {
                networkIcon.color = Time.unscaledTime <= packetPulseUntil
                    ? Color.Lerp(color, Color.white, 0.8f)
                    : color;
            }
        }

        private void ToggleDebugPanel()
        {
            debugVisible = !debugVisible;
            ApplyDebugVisibility();
        }

        private void ApplyDebugVisibility()
        {
            if (debugPanel != null)
            {
                debugPanel.SetActive(debugVisible);
            }
        }

        private void AddDebugLine(string message)
        {
            if (debugOutput == null)
            {
                return;
            }

            debugLines.Enqueue($"{Time.realtimeSinceStartup,7:0.000}  {message}");
            while (debugLines.Count > debugLineLimit)
            {
                debugLines.Dequeue();
            }

            debugOutput.text = string.Join("\n", debugLines);
        }

        private bool HasCompleteUi()
        {
            return playerHealth != null && playerStamina != null &&
                   opponentHealth != null && opponentStamina != null &&
                   roundTimer != null && matchState != null &&
                   networkIcon != null && networkStatus != null &&
                   debugToggle != null && debugPanel != null && debugOutput != null;
        }

        private void BuildRuntimeHud()
        {
            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

            GameObject canvasObject = new(
                "VisualizerHUD",
                typeof(RectTransform),
                typeof(Canvas),
                typeof(CanvasScaler),
                typeof(GraphicRaycaster));
            canvasObject.transform.SetParent(transform, false);

            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 200;

            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 0.5f;

            RectTransform safeRoot = CreateRect("SafeArea", canvasObject.transform);
            Stretch(safeRoot);
            safeRoot.gameObject.AddComponent<RuntimeSafeArea>();

            BuildPlayerPanel(safeRoot, font, true);
            BuildPlayerPanel(safeRoot, font, false);
            BuildRoundPanel(safeRoot, font);
            BuildNetworkPanel(safeRoot, font);
        }

        private void BuildPlayerPanel(RectTransform parent, Font font, bool local)
        {
            RectTransform panel = CreatePanel(local ? "PlayerPanel" : "OpponentPanel", parent);
            panel.anchorMin = local ? new Vector2(0f, 1f) : new Vector2(1f, 1f);
            panel.anchorMax = panel.anchorMin;
            panel.pivot = panel.anchorMin;
            panel.anchoredPosition = local ? new Vector2(24f, -24f) : new Vector2(-24f, -24f);
            panel.sizeDelta = new Vector2(360f, 96f);

            Text title = CreateText(local ? "PlayerTitle" : "OpponentTitle", panel, font, 22, FontStyle.Bold);
            title.text = local ? "PLAYER" : "OPPONENT";
            title.alignment = local ? TextAnchor.UpperLeft : TextAnchor.UpperRight;
            SetRect(title.rectTransform, new Vector2(0f, 1f), new Vector2(1f, 1f),
                new Vector2(0.5f, 1f), Vector2.zero, new Vector2(-24f, 28f));

            Slider health = CreateLabeledSlider(panel, font, "Health", "HP", 48f,
                new Color(0.92f, 0.2f, 0.2f, 1f), out Text healthValue);
            Slider stamina = CreateLabeledSlider(panel, font, "Stamina", "ST", 16f,
                new Color(0.15f, 0.7f, 1f, 1f), out Text staminaValue);

            if (local)
            {
                playerHealth = health;
                playerStamina = stamina;
                playerHealthValue = healthValue;
                playerStaminaValue = staminaValue;
            }
            else
            {
                opponentHealth = health;
                opponentStamina = stamina;
                opponentHealthValue = healthValue;
                opponentStaminaValue = staminaValue;
            }
        }

        private void BuildRoundPanel(RectTransform parent, Font font)
        {
            RectTransform panel = CreatePanel("RoundPanel", parent);
            panel.anchorMin = new Vector2(0.5f, 1f);
            panel.anchorMax = panel.anchorMin;
            panel.pivot = new Vector2(0.5f, 1f);
            panel.anchoredPosition = new Vector2(0f, -24f);
            panel.sizeDelta = new Vector2(180f, 82f);

            roundTimer = CreateText("RoundTimer", panel, font, 34, FontStyle.Bold);
            roundTimer.alignment = TextAnchor.MiddleCenter;
            SetRect(roundTimer.rectTransform, new Vector2(0f, 0.42f), Vector2.one,
                new Vector2(0.5f, 0.5f), Vector2.zero, Vector2.zero);

            matchState = CreateText("MatchState", panel, font, 17, FontStyle.Normal);
            matchState.alignment = TextAnchor.MiddleCenter;
            matchState.color = new Color(0.82f, 0.85f, 0.9f, 1f);
            SetRect(matchState.rectTransform, Vector2.zero, new Vector2(1f, 0.42f),
                new Vector2(0.5f, 0.5f), Vector2.zero, Vector2.zero);
        }

        private void BuildNetworkPanel(RectTransform parent, Font font)
        {
            RectTransform panel = CreatePanel("NetworkPanel", parent);
            panel.anchorMin = Vector2.one;
            panel.anchorMax = Vector2.one;
            panel.pivot = Vector2.one;
            panel.anchoredPosition = new Vector2(-24f, -132f);
            panel.sizeDelta = new Vector2(300f, 42f);

            networkIcon = CreateText("ConnectionIcon", panel, font, 25, FontStyle.Bold);
            networkIcon.text = "●";
            networkIcon.alignment = TextAnchor.MiddleCenter;
            SetRect(networkIcon.rectTransform, Vector2.zero, new Vector2(0f, 1f),
                new Vector2(0f, 0.5f), new Vector2(20f, 0f), new Vector2(40f, 0f));

            networkStatus = CreateText("ConnectionStatus", panel, font, 16, FontStyle.Bold);
            networkStatus.alignment = TextAnchor.MiddleLeft;
            SetRect(networkStatus.rectTransform, Vector2.zero, Vector2.one,
                new Vector2(0.5f, 0.5f), new Vector2(28f, 0f), new Vector2(-92f, 0f));

            debugToggle = CreateButton("DebugToggle", panel, font, "NET LOG");
            SetRect(debugToggle.GetComponent<RectTransform>(), new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                new Vector2(1f, 0.5f), new Vector2(-8f, 0f), new Vector2(78f, 30f));

            RectTransform logPanel = CreatePanel("NetworkDebugPanel", parent);
            logPanel.anchorMin = Vector2.one;
            logPanel.anchorMax = Vector2.one;
            logPanel.pivot = Vector2.one;
            logPanel.anchoredPosition = new Vector2(-24f, -182f);
            logPanel.sizeDelta = new Vector2(560f, 210f);
            debugPanel = logPanel.gameObject;

            debugOutput = CreateText("NetworkDebugText", logPanel, font, 15, FontStyle.Normal);
            debugOutput.alignment = TextAnchor.UpperLeft;
            debugOutput.horizontalOverflow = HorizontalWrapMode.Wrap;
            debugOutput.verticalOverflow = VerticalWrapMode.Truncate;
            SetRect(debugOutput.rectTransform, Vector2.zero, Vector2.one,
                new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(-24f, -20f));
        }

        private static Slider CreateLabeledSlider(
            RectTransform parent,
            Font font,
            string name,
            string label,
            float y,
            Color fillColor,
            out Text valueText)
        {
            RectTransform row = CreateRect(name + "Row", parent);
            row.anchorMin = Vector2.zero;
            row.anchorMax = new Vector2(1f, 0f);
            row.pivot = new Vector2(0.5f, 0f);
            row.anchoredPosition = new Vector2(0f, y);
            row.sizeDelta = new Vector2(-24f, 24f);

            Text rowLabel = CreateText(name + "Label", row, font, 14, FontStyle.Bold);
            rowLabel.text = label;
            rowLabel.alignment = TextAnchor.MiddleLeft;
            SetRect(rowLabel.rectTransform, Vector2.zero, new Vector2(0f, 1f),
                new Vector2(0f, 0.5f), new Vector2(10f, 0f), new Vector2(34f, 0f));

            RectTransform sliderRect = CreateRect(name + "Slider", row);
            SetRect(sliderRect, new Vector2(0f, 0.18f), new Vector2(1f, 0.82f),
                new Vector2(0.5f, 0.5f), new Vector2(45f, 0f), new Vector2(-92f, 0f));

            Slider slider = sliderRect.gameObject.AddComponent<Slider>();
            slider.minValue = 0f;
            slider.maxValue = 100f;
            slider.value = 100f;
            slider.interactable = false;
            slider.transition = Selectable.Transition.None;

            RectTransform background = CreateRect("Background", sliderRect);
            Stretch(background);
            Image backgroundImage = background.gameObject.AddComponent<Image>();
            backgroundImage.color = new Color(1f, 1f, 1f, 0.16f);

            RectTransform fill = CreateRect("Fill", sliderRect);
            Stretch(fill);
            fill.offsetMin = new Vector2(2f, 2f);
            fill.offsetMax = new Vector2(-2f, -2f);
            Image fillImage = fill.gameObject.AddComponent<Image>();
            fillImage.color = fillColor;

            slider.fillRect = fill;
            slider.targetGraphic = fillImage;
            slider.direction = Slider.Direction.LeftToRight;

            valueText = CreateText(name + "Value", row, font, 14, FontStyle.Bold);
            valueText.alignment = TextAnchor.MiddleRight;
            SetRect(valueText.rectTransform, new Vector2(1f, 0f), Vector2.one,
                new Vector2(1f, 0.5f), new Vector2(-8f, 0f), new Vector2(56f, 0f));
            return slider;
        }

        private static Button CreateButton(string name, RectTransform parent, Font font, string label)
        {
            RectTransform rect = CreateRect(name, parent);
            Image image = rect.gameObject.AddComponent<Image>();
            image.color = new Color(1f, 1f, 1f, 0.13f);

            Button button = rect.gameObject.AddComponent<Button>();
            button.targetGraphic = image;
            button.navigation = new Navigation { mode = Navigation.Mode.None };

            Text text = CreateText("Label", rect, font, 13, FontStyle.Bold);
            text.text = label;
            text.alignment = TextAnchor.MiddleCenter;
            Stretch(text.rectTransform);
            return button;
        }

        private static RectTransform CreatePanel(string name, RectTransform parent)
        {
            RectTransform rect = CreateRect(name, parent);
            Image image = rect.gameObject.AddComponent<Image>();
            image.color = new Color(0.015f, 0.02f, 0.035f, 0.78f);
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
            text.color = Color.white;
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

        private static void SetSlider(Slider slider, float value)
        {
            if (slider == null)
            {
                return;
            }

            slider.minValue = 0f;
            slider.maxValue = 100f;
            slider.value = value;
        }

        private static void SetValue(Text text, float value)
        {
            if (text != null)
            {
                text.text = $"{value:0}";
            }
        }
    }

    [RequireComponent(typeof(RectTransform))]
    public sealed class RuntimeSafeArea : MonoBehaviour
    {
        private RectTransform rectTransform;
        private Rect lastSafeArea;
        private int lastScreenWidth;
        private int lastScreenHeight;

        private void Awake()
        {
            rectTransform = GetComponent<RectTransform>();
            ApplySafeArea();
        }

        private void Update()
        {
            if (Screen.safeArea != lastSafeArea ||
                Screen.width != lastScreenWidth || Screen.height != lastScreenHeight)
            {
                ApplySafeArea();
            }
        }

        private void ApplySafeArea()
        {
            if (Screen.width <= 0 || Screen.height <= 0)
            {
                return;
            }

            Rect safeArea = Screen.safeArea;
            rectTransform.anchorMin = new Vector2(safeArea.xMin / Screen.width, safeArea.yMin / Screen.height);
            rectTransform.anchorMax = new Vector2(safeArea.xMax / Screen.width, safeArea.yMax / Screen.height);
            rectTransform.offsetMin = Vector2.zero;
            rectTransform.offsetMax = Vector2.zero;

            lastSafeArea = safeArea;
            lastScreenWidth = Screen.width;
            lastScreenHeight = Screen.height;
        }
    }
}
