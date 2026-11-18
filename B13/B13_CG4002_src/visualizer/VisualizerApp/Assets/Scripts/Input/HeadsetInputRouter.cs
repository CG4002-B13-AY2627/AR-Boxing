using System;
using UnityEngine;
using UnityEngine.InputSystem;

namespace CG4002.Visualizer.Input
{
    public enum HeadsetAction
    {
        Primary,
        Secondary
    }

    /// <summary>
    /// Pure cooldown gate used to suppress repeated actions from one physical gesture.
    /// </summary>
    public sealed class HeadsetActionDebouncer
    {
        private readonly float cooldownSeconds;
        private bool hasAcceptedAction;
        private float lastAcceptedTime;

        public HeadsetActionDebouncer(float cooldownSeconds)
        {
            this.cooldownSeconds = Math.Max(0f, cooldownSeconds);
        }

        public bool TryAccept(float timestamp)
        {
            if (float.IsNaN(timestamp) || float.IsInfinity(timestamp))
            {
                return false;
            }

            if (!hasAcceptedAction || timestamp < lastAcceptedTime ||
                timestamp - lastAcceptedTime >= cooldownSeconds)
            {
                hasAcceptedAction = true;
                lastAcceptedTime = timestamp;
                return true;
            }

            return false;
        }
    }

    /// <summary>
    /// Converts editor keyboard or Game Controller input into two headset actions.
    /// The intended iOS experiment maps Back Tap switches to virtual controller A/B,
    /// which Unity exposes as buttonSouth/buttonEast if the controller is available.
    /// </summary>
    public sealed class HeadsetInputRouter : MonoBehaviour
    {
        [Header("Input sources")]
        [SerializeField] private bool enableEditorKeyboard = true;
        [SerializeField] private bool enableGameController = true;

        [Header("Filtering")]
        [SerializeField, Min(0f)] private float cooldownSeconds = 0.35f;

        private HeadsetActionDebouncer debouncer;

        public event Action<HeadsetAction> ActionTriggered;

        private void Awake()
        {
            debouncer = new HeadsetActionDebouncer(cooldownSeconds);
        }

        private void Update()
        {
            if (TryReadPrimary())
            {
                TryPublish(HeadsetAction.Primary);
            }
            else if (TryReadSecondary())
            {
                TryPublish(HeadsetAction.Secondary);
            }
        }

        public bool TryPublish(HeadsetAction action)
        {
            debouncer ??= new HeadsetActionDebouncer(cooldownSeconds);
            if (!debouncer.TryAccept(Time.unscaledTime))
            {
                return false;
            }

            ActionTriggered?.Invoke(action);
            return true;
        }

        private bool TryReadPrimary()
        {
            bool keyboardPressed = enableEditorKeyboard && Application.isEditor &&
                                   Keyboard.current != null &&
                                   (Keyboard.current.spaceKey.wasPressedThisFrame ||
                                    Keyboard.current.rightArrowKey.wasPressedThisFrame);

            bool controllerPressed = enableGameController && Gamepad.current != null &&
                                     Gamepad.current.buttonSouth.wasPressedThisFrame;
            return keyboardPressed || controllerPressed;
        }

        private bool TryReadSecondary()
        {
            bool keyboardPressed = enableEditorKeyboard && Application.isEditor &&
                                   Keyboard.current != null &&
                                   (Keyboard.current.backspaceKey.wasPressedThisFrame ||
                                    Keyboard.current.leftArrowKey.wasPressedThisFrame);

            bool controllerPressed = enableGameController && Gamepad.current != null &&
                                     Gamepad.current.buttonEast.wasPressedThisFrame;
            return keyboardPressed || controllerPressed;
        }
    }
}
