using System;
using System.Collections;
using CG4002.Visualizer.AR;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    public sealed class CameraRelativeGloveRig : MonoBehaviour
    {
        private enum GloveMotion
        {
            Jab,
            Hook,
            Uppercut,
            Guard
        }

        [Header("Scene references")]
        [SerializeField] private Camera arCamera;
        [SerializeField] private Transform leftGlove;
        [SerializeField] private Transform rightGlove;

        [Header("Camera-relative resting pose")]
        [SerializeField] private Vector2 leftViewportPosition = new(0.18f, 0.20f);
        [SerializeField] private Vector2 rightViewportPosition = new(0.82f, 0.20f);
        [SerializeField, Min(0.1f)] private float distanceFromCamera = 0.65f;
        [SerializeField] private Vector3 leftRestEuler = new(10f, 20f, -10f);
        [SerializeField] private Vector3 rightRestEuler = new(10f, -20f, 10f);

        [Header("Prototype motion")]
        [SerializeField, Min(0.05f)] private float punchDuration = 0.34f;
        [SerializeField, Min(0.05f)] private float guardDuration = 0.60f;
        [SerializeField, Min(0f)] private float jabDistance = 0.32f;
        [SerializeField, Min(0f)] private float hookInwardDistance = 0.22f;
        [SerializeField, Min(0f)] private float hookForwardDistance = 0.18f;
        [SerializeField, Min(0f)] private float uppercutHeight = 0.28f;
        [SerializeField, Min(0f)] private float guardHeight = 0.20f;
        [SerializeField, Min(0f)] private float guardInwardDistance = 0.12f;
        [SerializeField] private AnimationCurve motionCurve = new(
            new Keyframe(0f, 0f),
            new Keyframe(0.42f, 1f),
            new Keyframe(1f, 0f));

        [Header("WP3 tracked-target punches")]
        [SerializeField] private OpponentTargetProvider targetProvider;
        [SerializeField] private bool useTrackedTargets = true;
        [SerializeField] private bool fallbackToPrototypeWhenTargetUnavailable = true;
        [SerializeField, Min(0f)] private float targetStandoffMetres = 0.08f;
        [SerializeField, Min(0.05f)] private float minimumTargetDepthMetres = 0.35f;
        [SerializeField, Min(0.1f)] private float maximumTargetDistanceMetres = 3f;
        [SerializeField, Min(0f)] private float targetedHookArcDistance = 0.18f;
        [SerializeField, Min(0f)] private float targetedHookVerticalLift = 0.12f;
        [SerializeField, Min(0f)] private float targetedUppercutDip = 0.12f;
        [SerializeField, Min(0.05f)] private float targetLossReturnDuration = 0.12f;
        [SerializeField] private bool showTargetingStatus = true;

        [Header("WP4 refined animation")]
        [SerializeField, Min(0.05f)] private float hookDuration = 0.46f;
        [SerializeField, Min(0.05f)] private float uppercutDuration = 0.48f;
        [Tooltip("Local green-Y twist at full extension: positive values turn left negative/right positive, matching the tuned jabs. Negate to reverse both hands. Independent of jab settings.")]
        [SerializeField, Range(-180f, 180f)] private float uppercutInwardYawDegrees = 65f;
        [Tooltip("Optional local X tilt, applied separately before the Y twist. Zero keeps the upright resting tilt; replaces the old hard-coded -60 degree tilt and roll.")]
        [SerializeField, Range(-90f, 90f)] private float uppercutPitchDegrees = 0f;

        [Header("Jab knuckle alignment")]
        [Tooltip("Optional child of LeftGlove placed on the knuckles. Its blue Z arrow points in the striking direction.")]
        [SerializeField] private Transform leftJabContact;
        [Tooltip("Optional child of RightGlove placed on the knuckles. Its blue Z arrow points in the striking direction.")]
        [SerializeField] private Transform rightJabContact;
        [Tooltip("Fallback contact point in glove-root local units. Tune to the padded knuckle surface, not the cuff.")]
        [SerializeField] private Vector3 leftJabContactOffset = new(0f, 0.12f, 0f);
        [SerializeField] private Vector3 rightJabContactOffset = new(0f, 0.12f, 0f);
        [Tooltip("Fallback wrist-to-knuckle direction in glove-root coordinates. Upright gloves normally use +Y.")]
        [SerializeField] private Vector3 leftJabStrikeAxis = Vector3.up;
        [SerializeField] private Vector3 rightJabStrikeAxis = Vector3.up;
        [Tooltip("Complete the turn at this fraction of extension, before the knuckles reach the target.")]
        [SerializeField, Range(0.05f, 1f)] private float jabRotationCompleteAtExtension = 0.65f;
        [Tooltip("Additional twist around the glove root's local green Y axis at full extension. Signed degrees; reverses on retraction.")]
        [SerializeField, Range(-180f, 180f)] private float leftJabLocalYawDegrees = 60f;
        [SerializeField, Range(-180f, 180f)] private float rightJabLocalYawDegrees = -60f;

        [Header("Guard pose and visibility")]
        [Tooltip("Signed local green-Y twist at full guard. Tune so the palm faces the camera.")]
        [SerializeField, Range(-180f, 180f)] private float leftGuardLocalYawDegrees = 55f;
        [SerializeField, Range(-180f, 180f)] private float rightGuardLocalYawDegrees = -55f;
        [Tooltip("Distance to pull the glove roots toward the camera, not toward the opponent.")]
        [SerializeField, Min(0f)] private float guardTowardCameraDistance = 0.12f;
        [Tooltip("Minimum camera depth for the guard roots. Also clamped beyond the near plane; leave room for the mesh.")]
        [SerializeField, Min(0.05f)] private float guardMinimumCameraDepth = 0.25f;
        [Tooltip("Opacity multiplier at full guard: 1 is solid, 0 is invisible. Player materials must support fading.")]
        [SerializeField, Range(0f, 1f)] private float guardPeakOpacity = 0.65f;

        [Header("WP5 pickup reach")]
        [SerializeField, Min(0.05f)] private float pickupReachDuration = 0.78f;
        [SerializeField, Min(0f)] private float pickupTargetStandoffMetres = 0.05f;
        [SerializeField, Min(0.1f)] private float pickupMaximumReachMetres = 1.15f;
        [SerializeField, Min(0f)] private float pickupMinimumHeightAboveFloor = 0.16f;
        [SerializeField, Min(0f)] private float pickupArcHeightMetres = 0.12f;
        [SerializeField] private float pickupForwardBowMetres = 0.04f;
        [SerializeField, Range(-90f, 90f)] private float pickupDownPitchDegrees = 32f;
        [SerializeField, Range(-90f, 90f)] private float pickupInwardYawDegrees = 12f;
        [SerializeField] private AnimationCurve pickupReachCurve = new(
            new Keyframe(0f, 0f),
            new Keyframe(0.46f, 1f),
            new Keyframe(0.62f, 1f),
            new Keyframe(1f, 0f));

        private GloveOpacity leftOpacity;
        private GloveOpacity rightOpacity;

        private Coroutine leftMotion;
        private Coroutine rightMotion;
        private Vector3 leftPositionOffset;
        private Vector3 rightPositionOffset;
        private Quaternion leftRotationOffset = Quaternion.identity;
        private Quaternion rightRotationOffset = Quaternion.identity;
        private bool leftPickupReachActive;
        private bool rightPickupReachActive;
        private Action leftPickupContact;
        private Action rightPickupContact;
        private string targetingStatus = "Waiting for a punch command";

        public void LeftJab() => StartMotion(true, GloveMotion.Jab);
        public void RightJab() => StartMotion(false, GloveMotion.Jab);
        public void LeftHook() => StartMotion(true, GloveMotion.Hook);
        public void RightHook() => StartMotion(false, GloveMotion.Hook);
        public void LeftUppercut() => StartMotion(true, GloveMotion.Uppercut);
        public void RightUppercut() => StartMotion(false, GloveMotion.Uppercut);

        public bool IsPickupReachActive(bool isLeft)
        {
            return isLeft ? leftPickupReachActive : rightPickupReachActive;
        }

        public bool TryStartPickupReach(
            bool isLeft,
            Vector3 targetWorldPosition,
            float floorWorldHeight,
            Action onContact = null)
        {
            if (!isActiveAndEnabled || arCamera == null ||
                (isLeft ? leftGlove : rightGlove) == null ||
                !IsFinite(targetWorldPosition) || !float.IsFinite(floorWorldHeight))
            {
                return false;
            }

            Vector3 rest = GetRestingPosition(isLeft);
            if (!PickupReachTargeting.TryGetEndpoint(
                    rest,
                    targetWorldPosition,
                    pickupTargetStandoffMetres,
                    pickupMaximumReachMetres,
                    floorWorldHeight + pickupMinimumHeightAboveFloor,
                    out _))
            {
                return false;
            }

            PrepareHandForNewMotion(isLeft);
            SetPickupReachActive(isLeft, true);
            SetPickupContact(isLeft, onContact);
            IEnumerator animation = AnimatePickupReach(
                isLeft,
                targetWorldPosition,
                floorWorldHeight);
            if (isLeft)
            {
                leftMotion = StartCoroutine(animation);
            }
            else
            {
                rightMotion = StartCoroutine(animation);
            }

            targetingStatus = $"PICKUP: {(isLeft ? "Left" : "Right")} reach";
            return true;
        }

        public void Guard()
        {
            StartMotion(true, GloveMotion.Guard);
            StartMotion(false, GloveMotion.Guard);
        }

        public void ResetPose()
        {
            InvokePickupContact(true);
            InvokePickupContact(false);
            if (leftMotion != null)
            {
                StopCoroutine(leftMotion);
                leftMotion = null;
            }

            if (rightMotion != null)
            {
                StopCoroutine(rightMotion);
                rightMotion = null;
            }

            leftPositionOffset = Vector3.zero;
            rightPositionOffset = Vector3.zero;
            leftRotationOffset = Quaternion.identity;
            rightRotationOffset = Quaternion.identity;
            leftPickupReachActive = false;
            rightPickupReachActive = false;
            leftOpacity?.Restore();
            rightOpacity?.Restore();
            ApplyPose();
        }

        private void Awake()
        {
            if (arCamera == null)
            {
                arCamera = Camera.main;
            }

            if (targetProvider == null)
            {
                targetProvider = FindFirstObjectByType<OpponentTargetProvider>();
            }
        }

        private void LateUpdate()
        {
            ApplyPose();
        }

        private void OnDisable()
        {
            ResetPose();
        }

        private void StartMotion(bool isLeft, GloveMotion motion)
        {
            if (!isActiveAndEnabled)
            {
                return;
            }

            // Cancel first, including blocked punches: no interrupted motion may
            // leave a hand displaced or partially transparent.
            PrepareHandForNewMotion(isLeft);

            IEnumerator animation = AnimateHand(isLeft, motion);
            if (motion != GloveMotion.Guard && useTrackedTargets)
            {
                OpponentTargetZone zone = PunchTargeting.ResolveTarget(
                    isLeft,
                    ToVisualPunchType(motion));
                if (TryGetUsableTarget(zone, out _))
                {
                    animation = AnimateTargetedHand(isLeft, motion, zone);
                    targetingStatus =
                        $"TARGETED: {(isLeft ? "Left" : "Right")} {motion} -> {zone}";
                }
                else if (!fallbackToPrototypeWhenTargetUnavailable)
                {
                    targetingStatus = $"BLOCKED: no valid {zone} target";
                    SetMotionOffset(isLeft, Vector3.zero, Quaternion.identity);
                    return;
                }
                else
                {
                    targetingStatus = $"FALLBACK: no valid {zone} target";
                }
            }

            if (isLeft)
            {
                leftMotion = StartCoroutine(animation);
            }
            else
            {
                rightMotion = StartCoroutine(animation);
            }
        }

        private IEnumerator AnimateTargetedHand(
            bool isLeft,
            GloveMotion motion,
            OpponentTargetZone zone)
        {
            GetPeakPose(isLeft, motion, out _, out Vector3 peakEuler);
            float duration = GetMotionDuration(motion);
            float elapsed = 0f;

            while (elapsed < duration)
            {
                if (!TryGetUsableTarget(zone, out Pose targetPose))
                {
                    targetingStatus = $"ABORTED: lost {zone} target";
                    yield return ReturnHandToRest(isLeft);
                    FinishMotion(isLeft);
                    yield break;
                }

                elapsed += Time.unscaledDeltaTime;
                float normalizedTime = Mathf.Clamp01(elapsed / duration);
                float amount = Mathf.Clamp01(motionCurve.Evaluate(normalizedTime));
                Vector3 restingPosition = GetRestingPosition(isLeft);
                if (motion == GloveMotion.Jab)
                {
                    SetJabPose(isLeft, restingPosition, targetPose.position, targetStandoffMetres, amount);
                    yield return null;
                    continue;
                }

                Vector3 endPosition = PunchTargeting.StopShortOfTarget(
                    restingPosition,
                    targetPose.position,
                    targetStandoffMetres);
                Vector3 worldPosition = GetTargetedWorldPosition(
                    isLeft,
                    motion,
                    restingPosition,
                    endPosition,
                    amount);
                Vector3 cameraLocalOffset = arCamera.transform.InverseTransformVector(
                    worldPosition - restingPosition);

                SetMotionOffset(
                    isLeft,
                    cameraLocalOffset,
                    GetMotionRotation(isLeft, motion, peakEuler, amount));
                yield return null;
            }

            SetMotionOffset(isLeft, Vector3.zero, Quaternion.identity);
            FinishMotion(isLeft);
        }

        private IEnumerator AnimatePickupReach(
            bool isLeft,
            Vector3 targetWorldPosition,
            float floorWorldHeight)
        {
            float elapsed = 0f;
            while (elapsed < pickupReachDuration)
            {
                elapsed += Time.unscaledDeltaTime;
                float normalizedTime = Mathf.Clamp01(elapsed / pickupReachDuration);
                float amount = Mathf.Clamp01(pickupReachCurve.Evaluate(normalizedTime));
                if (amount >= 0.999f)
                {
                    InvokePickupContact(isLeft);
                }
                Vector3 rest = GetRestingPosition(isLeft);
                if (!PickupReachTargeting.TryGetEndpoint(
                        rest,
                        targetWorldPosition,
                        pickupTargetStandoffMetres,
                        pickupMaximumReachMetres,
                        floorWorldHeight + pickupMinimumHeightAboveFloor,
                        out Vector3 endpoint))
                {
                    InvokePickupContact(isLeft);
                    yield return ReturnHandToRest(isLeft);
                    FinishMotion(isLeft);
                    yield break;
                }

                Vector3 worldPosition = PickupReachTargeting.EvaluatePath(
                    rest,
                    endpoint,
                    Vector3.up,
                    arCamera.transform.forward,
                    pickupArcHeightMetres,
                    pickupForwardBowMetres,
                    amount);
                float yaw = isLeft
                    ? pickupInwardYawDegrees
                    : -pickupInwardYawDegrees;
                Quaternion peakRotation = Quaternion.Euler(
                    pickupDownPitchDegrees,
                    yaw,
                    0f);
                SetMotionOffset(
                    isLeft,
                    arCamera.transform.InverseTransformVector(worldPosition - rest),
                    Quaternion.Slerp(
                        Quaternion.identity,
                        peakRotation,
                        Mathf.SmoothStep(0f, 1f, amount)));
                yield return null;
            }

            SetMotionOffset(isLeft, Vector3.zero, Quaternion.identity);
            FinishMotion(isLeft);
        }

        private IEnumerator ReturnHandToRest(bool isLeft)
        {
            Vector3 startPosition = isLeft ? leftPositionOffset : rightPositionOffset;
            Quaternion startRotation = isLeft
                ? leftRotationOffset
                : rightRotationOffset;
            float elapsed = 0f;

            while (elapsed < targetLossReturnDuration)
            {
                elapsed += Time.unscaledDeltaTime;
                float amount = Mathf.Clamp01(elapsed / targetLossReturnDuration);
                SetMotionOffset(
                    isLeft,
                    Vector3.Lerp(startPosition, Vector3.zero, amount),
                    Quaternion.Slerp(startRotation, Quaternion.identity, amount));
                yield return null;
            }

            SetMotionOffset(isLeft, Vector3.zero, Quaternion.identity);
        }

        private IEnumerator AnimateHand(bool isLeft, GloveMotion motion)
        {
            float duration = GetMotionDuration(motion);
            GetPeakPose(isLeft, motion, out Vector3 peakPosition, out Vector3 peakEuler);
            float elapsed = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.unscaledDeltaTime;
                float normalizedTime = Mathf.Clamp01(elapsed / duration);
                float amount = motionCurve.Evaluate(normalizedTime);
                if (motion == GloveMotion.Guard)
                {
                    SetGuardPose(isLeft, amount);
                    yield return null;
                    continue;
                }
                if (motion == GloveMotion.Jab)
                {
                    Vector3 rest = GetRestingPosition(isLeft);
                    GetJabGeometry(isLeft, out Vector3 contactOffset, out _);
                    Vector3 startContact = rest + GetRestingRotation(isLeft) * contactOffset;
                    SetJabPose(isLeft, rest,
                        startContact + arCamera.transform.forward * jabDistance, 0f, amount);
                    yield return null;
                    continue;
                }

                SetMotionOffset(
                    isLeft,
                    peakPosition * amount,
                    GetMotionRotation(isLeft, motion, peakEuler, amount));
                yield return null;
            }

            SetMotionOffset(isLeft, Vector3.zero, Quaternion.identity);
            FinishMotion(isLeft);
        }

        private Quaternion GetMotionRotation(
            bool isLeft, GloveMotion motion, Vector3 peakEuler, float amount)
        {
            if (motion == GloveMotion.Uppercut)
            {
                // Match Main's tuned jab signs (left negative/right positive),
                // but retain independent uppercut strength and timing.
                float yaw = isLeft ? -uppercutInwardYawDegrees : uppercutInwardYawDegrees;
                return PunchTargeting.UppercutRotation(yaw, uppercutPitchDegrees, amount);
            }

            return PunchTargeting.ProgressRotation(peakEuler, amount);
        }

        private void SetGuardPose(bool isLeft, float amount)
        {
            float minimumDepth = Mathf.Max(guardMinimumCameraDepth,
                arCamera != null ? arCamera.nearClipPlane + 0.15f : 0.25f);
            Vector3 offset = PunchTargeting.GuardPositionOffset(isLeft,
                guardInwardDistance, guardHeight, guardTowardCameraDistance,
                distanceFromCamera, minimumDepth, amount);
            Quaternion rotation = PunchTargeting.LocalYawRotation(
                isLeft ? leftGuardLocalYawDegrees : rightGuardLocalYawDegrees, amount);
            SetMotionOffset(isLeft, offset, rotation);

            float opacity = Mathf.Lerp(1f, Mathf.Clamp01(guardPeakOpacity),
                Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(amount)));
            if (isLeft)
            {
                leftOpacity ??= new GloveOpacity(leftGlove);
                leftOpacity.SetOpacity(opacity);
            }
            else
            {
                rightOpacity ??= new GloveOpacity(rightGlove);
                rightOpacity.SetOpacity(opacity);
            }
        }

        private Quaternion GetRestingRotation(bool isLeft)
        {
            return arCamera.transform.rotation *
                Quaternion.Euler(isLeft ? leftRestEuler : rightRestEuler);
        }

        private void GetJabGeometry(bool isLeft, out Vector3 offset, out Vector3 axis)
        {
            Transform glove = isLeft ? leftGlove : rightGlove;
            Transform contact = isLeft ? leftJabContact : rightJabContact;
            if (glove != null && contact != null && contact.IsChildOf(glove))
            {
                // Remove only rotation: the measured offset already includes model/root scale.
                Quaternion inverse = Quaternion.Inverse(glove.rotation);
                offset = inverse * (contact.position - glove.position);
                axis = inverse * contact.forward;
                return;
            }

            offset = isLeft ? leftJabContactOffset : rightJabContactOffset;
            axis = isLeft ? leftJabStrikeAxis : rightJabStrikeAxis;
            if (glove != null)
            {
                offset = Quaternion.Inverse(glove.rotation) * glove.TransformVector(offset);
                axis = Quaternion.Inverse(glove.rotation) * glove.TransformVector(axis);
            }
        }

        private void SetJabPose(bool isLeft, Vector3 rest, Vector3 target, float gap, float amount)
        {
            GetJabGeometry(isLeft, out Vector3 offset, out Vector3 axis);
            Quaternion restRotation = GetRestingRotation(isLeft);
            Pose pose = PunchTargeting.JabPose(rest, restRotation, offset, axis,
                target, gap, amount, jabRotationCompleteAtExtension,
                isLeft ? leftJabLocalYawDegrees : rightJabLocalYawDegrees);
            SetMotionOffset(isLeft,
                arCamera.transform.InverseTransformVector(pose.position - rest),
                Quaternion.Inverse(restRotation) * pose.rotation);
        }

        private void OnDrawGizmosSelected()
        {
            DrawJabContact(true);
            DrawJabContact(false);
        }

        private void DrawJabContact(bool isLeft)
        {
            Transform glove = isLeft ? leftGlove : rightGlove;
            if (glove == null) return;
            GetJabGeometry(isLeft, out Vector3 offset, out Vector3 axis);
            Vector3 point = glove.position + glove.rotation * offset;
            Gizmos.color = Color.yellow;
            Gizmos.DrawWireSphere(point, 0.012f);
            Gizmos.DrawLine(point, point + glove.rotation * axis.normalized * 0.10f);
        }

        private void FinishMotion(bool isLeft)
        {
            if (IsPickupReachActive(isLeft))
            {
                InvokePickupContact(isLeft);
            }

            SetPickupReachActive(isLeft, false);
            if (isLeft)
            {
                leftMotion = null;
                leftOpacity?.Restore();
            }
            else
            {
                rightMotion = null;
                rightOpacity?.Restore();
            }
        }

        private void PrepareHandForNewMotion(bool isLeft)
        {
            if (IsPickupReachActive(isLeft))
            {
                InvokePickupContact(isLeft);
            }

            if (isLeft)
            {
                if (leftMotion != null)
                {
                    StopCoroutine(leftMotion);
                }

                leftMotion = null;
                leftPickupReachActive = false;
                leftOpacity?.Restore();
            }
            else
            {
                if (rightMotion != null)
                {
                    StopCoroutine(rightMotion);
                }

                rightMotion = null;
                rightPickupReachActive = false;
                rightOpacity?.Restore();
            }

            SetMotionOffset(isLeft, Vector3.zero, Quaternion.identity);
        }

        private void SetPickupContact(bool isLeft, Action callback)
        {
            if (isLeft)
            {
                leftPickupContact = callback;
            }
            else
            {
                rightPickupContact = callback;
            }
        }

        private void InvokePickupContact(bool isLeft)
        {
            Action callback;
            if (isLeft)
            {
                callback = leftPickupContact;
                leftPickupContact = null;
            }
            else
            {
                callback = rightPickupContact;
                rightPickupContact = null;
            }

            callback?.Invoke();
        }

        private void SetPickupReachActive(bool isLeft, bool value)
        {
            if (isLeft)
            {
                leftPickupReachActive = value;
            }
            else
            {
                rightPickupReachActive = value;
            }
        }

        private bool TryGetUsableTarget(OpponentTargetZone zone, out Pose pose)
        {
            if (targetProvider == null)
            {
                targetProvider = FindFirstObjectByType<OpponentTargetProvider>();
            }

            if (targetProvider == null ||
                !targetProvider.TryGetTargetPose(zone, out pose) ||
                !IsFinite(pose.position))
            {
                pose = default;
                return false;
            }

            Vector3 cameraToTarget = pose.position - arCamera.transform.position;
            float depth = Vector3.Dot(arCamera.transform.forward, cameraToTarget);
            float distance = cameraToTarget.magnitude;
            if (depth < minimumTargetDepthMetres ||
                distance > maximumTargetDistanceMetres)
            {
                pose = default;
                return false;
            }

            return true;
        }

        private Vector3 GetTargetedWorldPosition(
            bool isLeft,
            GloveMotion motion,
            Vector3 start,
            Vector3 end,
            float amount)
        {
            switch (motion)
            {
                case GloveMotion.Jab:
                    return PunchTargeting.StraightLine(start, end, amount);
                case GloveMotion.Hook:
                    float outwardSide = isLeft ? -1f : 1f;
                    return PunchTargeting.HookArc(
                        start,
                        end,
                        arCamera.transform.right,
                        arCamera.transform.up,
                        outwardSide,
                        targetedHookArcDistance,
                        targetedHookVerticalLift,
                        amount);
                case GloveMotion.Uppercut:
                    Vector3 control = Vector3.Lerp(start, end, 0.5f) -
                        arCamera.transform.up * targetedUppercutDip +
                        arCamera.transform.forward * 0.04f;
                    return PunchTargeting.QuadraticBezier(
                        start,
                        control,
                        end,
                        amount);
                default:
                    return PunchTargeting.StraightLine(start, end, amount);
            }
        }

        private float GetMotionDuration(GloveMotion motion)
        {
            return motion switch
            {
                GloveMotion.Hook => hookDuration,
                GloveMotion.Uppercut => uppercutDuration,
                GloveMotion.Guard => guardDuration,
                _ => punchDuration
            };
        }

        private Vector3 GetRestingPosition(bool isLeft)
        {
            Vector2 viewportPosition = isLeft
                ? leftViewportPosition
                : rightViewportPosition;
            return arCamera.ViewportToWorldPoint(
                new Vector3(
                    viewportPosition.x,
                    viewportPosition.y,
                    distanceFromCamera));
        }

        private static VisualPunchType ToVisualPunchType(GloveMotion motion)
        {
            return motion switch
            {
                GloveMotion.Jab => VisualPunchType.Jab,
                GloveMotion.Hook => VisualPunchType.Hook,
                GloveMotion.Uppercut => VisualPunchType.Uppercut,
                _ => VisualPunchType.Jab
            };
        }

        private static bool IsFinite(Vector3 value)
        {
            return float.IsFinite(value.x) &&
                   float.IsFinite(value.y) &&
                   float.IsFinite(value.z);
        }

        private void GetPeakPose(
            bool isLeft,
            GloveMotion motion,
            out Vector3 positionOffset,
            out Vector3 eulerOffset)
        {
            float side = isLeft ? 1f : -1f;
            switch (motion)
            {
                case GloveMotion.Jab:
                    // Jab position and rotation are solved together by SetJabPose.
                    positionOffset = new Vector3(0f, 0f, jabDistance);
                    eulerOffset = Vector3.zero;
                    break;
                case GloveMotion.Hook:
                    positionOffset = new Vector3(
                        side * hookInwardDistance,
                        0.05f,
                        hookForwardDistance);
                    eulerOffset = new Vector3(0f, -side * 55f, -side * 32f);
                    break;
                case GloveMotion.Uppercut:
                    positionOffset = new Vector3(side * 0.06f, uppercutHeight, 0.16f);
                    // Rotation is solved separately by GetMotionRotation.
                    eulerOffset = Vector3.zero;
                    break;
                case GloveMotion.Guard:
                    // Guard translation, local yaw and fade share SetGuardPose.
                    positionOffset = Vector3.zero;
                    eulerOffset = Vector3.zero;
                    break;
                default:
                    positionOffset = Vector3.zero;
                    eulerOffset = Vector3.zero;
                    break;
            }
        }

        private void SetMotionOffset(bool isLeft, Vector3 position, Quaternion rotation)
        {
            if (isLeft)
            {
                leftPositionOffset = position;
                leftRotationOffset = rotation;
            }
            else
            {
                rightPositionOffset = position;
                rightRotationOffset = rotation;
            }
        }

        private void ApplyPose()
        {
            if (arCamera == null)
            {
                return;
            }

            ApplyHandPose(
                leftGlove,
                leftViewportPosition,
                leftRestEuler,
                leftPositionOffset,
                leftRotationOffset);
            ApplyHandPose(
                rightGlove,
                rightViewportPosition,
                rightRestEuler,
                rightPositionOffset,
                rightRotationOffset);
        }

        private void OnGUI()
        {
            if (!showTargetingStatus)
            {
                return;
            }

            GUI.Box(
                new Rect(12f, 266f, 420f, 54f),
                "AprilTag WP3 targeted punches\n" + targetingStatus);
        }

        private void ApplyHandPose(
            Transform glove,
            Vector2 viewportPosition,
            Vector3 restEuler,
            Vector3 positionOffset,
            Quaternion rotationOffset)
        {
            if (glove == null)
            {
                return;
            }

            Vector3 restingPosition = arCamera.ViewportToWorldPoint(
                new Vector3(viewportPosition.x, viewportPosition.y, distanceFromCamera));
            glove.position = restingPosition + arCamera.transform.TransformVector(positionOffset);
            glove.rotation = arCamera.transform.rotation * Quaternion.Euler(restEuler) * rotationOffset;
        }

#if UNITY_EDITOR
        public bool TryGetGlovePoseForTesting(bool isLeft, out Pose pose)
        {
            Transform glove = isLeft ? leftGlove : rightGlove;
            if (glove == null)
            {
                pose = default;
                return false;
            }

            pose = new Pose(glove.position, glove.rotation);
            return true;
        }

        public Vector3 GetRestingPositionForTesting(bool isLeft)
        {
            return GetRestingPosition(isLeft);
        }
#endif
    }
}
