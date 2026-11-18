using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace CG4002.Visualizer.Tracking
{
    /// <summary>
    /// Places simple opponent-glove visuals on ARKit's 3D human-body hand joints.
    /// This is presentation only; it does not perform hit detection.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class OpponentBodyGloveTracker : MonoBehaviour
    {
        // ARKit's 91-joint skeleton indices, matching the AR Foundation 6.0 sample.
        private const int LeftForearmJoint = 21;
        private const int LeftHandJoint = 22;
        private const int RightForearmJoint = 65;
        private const int RightHandJoint = 66;

        [Header("AR scene references")]
        [SerializeField] private ARHumanBodyManager humanBodyManager;
        [SerializeField] private Camera arCamera;

        [Header("Glove visuals")]
        [SerializeField] private Transform leftGlove;
        [SerializeField] private Transform rightGlove;
        [Tooltip("Off preserves authored materials and textures. Enable only for deliberately tintable prototype materials.")]
        [SerializeField] private bool overrideMaterialColor;
        [SerializeField] private Color leftGloveColor = Color.white;
        [SerializeField] private Color rightGloveColor = Color.white;

        [Header("Joint alignment")]
        [Tooltip("Use the forearm-to-hand direction to keep each cuff pointing down the forearm.")]
        [SerializeField] private bool alignCuffToForearm = true;
        [SerializeField] private Vector3 leftPositionOffset;
        [SerializeField] private Vector3 rightPositionOffset;
        [SerializeField] private Vector3 leftRotationOffset;
        [SerializeField] private Vector3 rightRotationOffset;

        [Header("Tracking stability")]
        [SerializeField, Min(0f)] private float positionSmoothTime = 0.04f;
        [SerializeField, Min(0f)] private float rotationSharpness = 22f;
        [SerializeField, Min(0f)] private float lostTrackingGracePeriod = 0.20f;

        [Header("Runtime diagnostics")]
        [Tooltip("Shows why body gloves are hidden on the device. Disable after physical validation.")]
        [SerializeField] private bool showTrackingDiagnostics = true;
        [SerializeField] private bool logTrackingStateChanges = true;

        private ARHumanBody activeBody;
        private Vector3 leftVelocity;
        private Vector3 rightVelocity;
        private bool leftPoseInitialized;
        private bool rightPoseInitialized;
        private float leftLastTrackedTime = float.NegativeInfinity;
        private float rightLastTrackedTime = float.NegativeInfinity;
        private string trackingStatus = "BODY: starting";

        public bool HasTrackedBody => activeBody != null;
        public bool IsLeftGloveVisible => leftGlove != null && leftGlove.gameObject.activeSelf;
        public bool IsRightGloveVisible => rightGlove != null && rightGlove.gameObject.activeSelf;
        public string TrackingStatus => trackingStatus;

        private void Awake()
        {
            ResolveReferences();
            ApplyGloveColors();
        }

        private void OnEnable()
        {
            ResolveReferences();
            SetGloveVisible(leftGlove, false);
            SetGloveVisible(rightGlove, false);

            if (humanBodyManager == null)
            {
                SetTrackingStatus("BODY ERROR: AR Human Body Manager is missing", true);
                enabled = false;
                return;
            }

            // Request the data needed for world-space hand and forearm poses.
            humanBodyManager.pose3DRequested = true;
            humanBodyManager.pose3DScaleEstimationRequested = true;
            humanBodyManager.trackablesChanged.AddListener(OnHumanBodiesChanged);
            ValidateVisuals();
            SetTrackingStatus("BODY: waiting for ARKit 3D body subsystem");
        }

        private void OnDisable()
        {
            if (humanBodyManager != null)
            {
                humanBodyManager.trackablesChanged.RemoveListener(OnHumanBodiesChanged);
            }

            activeBody = null;
            ResetPoseState();
            SetGloveVisible(leftGlove, false);
            SetGloveVisible(rightGlove, false);
        }

        private void LateUpdate()
        {
            if (humanBodyManager == null)
            {
                SetTrackingStatus("BODY ERROR: AR Human Body Manager is missing");
                return;
            }

            if (humanBodyManager.subsystem == null)
            {
                HideExpiredGloves();
                SetTrackingStatus("BODY: no subsystem (Editor, unsupported device, or AR session not ready)");
                return;
            }

            if (!humanBodyManager.pose3DEnabled)
            {
                HideExpiredGloves();
                SetTrackingStatus("BODY: 3D pose requested but not active on this device/session");
                return;
            }

            if (activeBody == null || activeBody.trackingState == TrackingState.None)
            {
                SelectMostCenteredBody();
            }

            if (activeBody == null)
            {
                HideExpiredGloves();
                SetTrackingStatus("BODY: 3D active; no person detected (frame the full body)");
                return;
            }

            var joints = activeBody.joints;
            if (!joints.IsCreated)
            {
                HideExpiredGloves();
                SetTrackingStatus("BODY: person found; waiting for 3D skeleton joints");
                return;
            }

            if (joints.Length <= RightHandJoint)
            {
                HideExpiredGloves();
                SetTrackingStatus($"BODY ERROR: skeleton has {joints.Length} joints; expected at least 67", true);
                return;
            }

            UpdateGlove(
                leftGlove,
                LeftHandJoint,
                LeftForearmJoint,
                leftPositionOffset,
                leftRotationOffset,
                ref leftPoseInitialized,
                ref leftVelocity,
                ref leftLastTrackedTime);
            UpdateGlove(
                rightGlove,
                RightHandJoint,
                RightForearmJoint,
                rightPositionOffset,
                rightRotationOffset,
                ref rightPoseInitialized,
                ref rightVelocity,
                ref rightLastTrackedTime);
            SetTrackingStatus(
                IsLeftGloveVisible && IsRightGloveVisible
                    ? "BODY: tracking both hands"
                    : IsLeftGloveVisible
                        ? "BODY: tracking left; right hand/forearm unavailable"
                        : IsRightGloveVisible
                            ? "BODY: tracking right; left hand/forearm unavailable"
                            : "BODY: person found; hand and forearm joints are not tracked");
        }

        private void OnHumanBodiesChanged(ARTrackablesChangedEventArgs<ARHumanBody> eventArgs)
        {
            bool activeBodyWasRemoved = false;
            foreach (var removedBody in eventArgs.removed)
            {
                if (activeBody != null && removedBody.Key == activeBody.trackableId)
                {
                    activeBodyWasRemoved = true;
                    break;
                }
            }

            if (activeBodyWasRemoved)
            {
                activeBody = null;
                ResetPoseState();
            }

            SelectMostCenteredBody();
        }

        private void SelectMostCenteredBody()
        {
            ARHumanBody bestBody = null;
            float bestScore = float.PositiveInfinity;

            foreach (ARHumanBody candidate in humanBodyManager.trackables)
            {
                if (candidate == null || candidate.trackingState == TrackingState.None)
                {
                    continue;
                }

                float score = ScoreBody(candidate);
                if (score < bestScore)
                {
                    bestScore = score;
                    bestBody = candidate;
                }
            }

            if (bestBody == activeBody)
            {
                return;
            }

            activeBody = bestBody;
            ResetPoseState();
            SetGloveVisible(leftGlove, false);
            SetGloveVisible(rightGlove, false);
        }

        private float ScoreBody(ARHumanBody body)
        {
            if (arCamera == null)
            {
                return Vector3.SqrMagnitude(body.transform.position - transform.position);
            }

            Vector3 viewportPoint = arCamera.WorldToViewportPoint(body.transform.position);
            if (viewportPoint.z <= 0f)
            {
                return float.PositiveInfinity;
            }

            float horizontalOffset = viewportPoint.x - 0.5f;
            float verticalOffset = viewportPoint.y - 0.5f;
            return horizontalOffset * horizontalOffset
                + verticalOffset * verticalOffset
                + viewportPoint.z * 0.0001f;
        }

        private void UpdateGlove(
            Transform glove,
            int handJointIndex,
            int forearmJointIndex,
            Vector3 positionOffset,
            Vector3 rotationOffset,
            ref bool poseInitialized,
            ref Vector3 velocity,
            ref float lastTrackedTime)
        {
            if (glove == null)
            {
                return;
            }

            if (!TryGetGlovePose(
                    handJointIndex,
                    forearmJointIndex,
                    positionOffset,
                    rotationOffset,
                    out Vector3 targetPosition,
                    out Quaternion targetRotation))
            {
                if (Time.unscaledTime - lastTrackedTime > lostTrackingGracePeriod)
                {
                    SetGloveVisible(glove, false);
                    poseInitialized = false;
                    velocity = Vector3.zero;
                }

                return;
            }

            lastTrackedTime = Time.unscaledTime;
            SetGloveVisible(glove, true);

            if (!poseInitialized)
            {
                glove.SetPositionAndRotation(targetPosition, targetRotation);
                poseInitialized = true;
                velocity = Vector3.zero;
                return;
            }

            float deltaTime = Mathf.Max(Time.unscaledDeltaTime, 0.0001f);
            glove.position = positionSmoothTime <= 0f
                ? targetPosition
                : Vector3.SmoothDamp(
                    glove.position,
                    targetPosition,
                    ref velocity,
                    positionSmoothTime,
                    Mathf.Infinity,
                    deltaTime);

            float rotationAmount = rotationSharpness <= 0f
                ? 1f
                : 1f - Mathf.Exp(-rotationSharpness * deltaTime);
            glove.rotation = Quaternion.Slerp(glove.rotation, targetRotation, rotationAmount);
        }

        private bool TryGetGlovePose(
            int handJointIndex,
            int forearmJointIndex,
            Vector3 positionOffset,
            Vector3 rotationOffset,
            out Vector3 worldPosition,
            out Quaternion worldRotation)
        {
            worldPosition = default;
            worldRotation = Quaternion.identity;

            if (activeBody == null)
            {
                return false;
            }

            var joints = activeBody.joints;
            if (!joints.IsCreated || forearmJointIndex >= joints.Length)
            {
                return false;
            }

            bool handIsAvailable = handJointIndex < joints.Length && joints[handJointIndex].tracked;
            bool forearmIsAvailable = joints[forearmJointIndex].tracked;
            if (!handIsAvailable && !forearmIsAvailable)
            {
                return false;
            }

            XRHumanBodyJoint targetJoint = handIsAvailable
                ? joints[handJointIndex]
                : joints[forearmJointIndex];
            Pose targetPose = targetJoint.anchorPose;
            worldPosition = activeBody.transform.TransformPoint(targetPose.position);
            worldRotation = activeBody.transform.rotation * targetPose.rotation;

            if (alignCuffToForearm && handIsAvailable && forearmIsAvailable)
            {
                Vector3 forearmPosition = activeBody.transform.TransformPoint(
                    joints[forearmJointIndex].anchorPose.position);
                Vector3 forearmToHand = worldPosition - forearmPosition;
                if (forearmToHand.sqrMagnitude > 0.000001f)
                {
                    Vector3 up = forearmToHand.normalized;
                    Vector3 cameraForward = arCamera != null
                        ? arCamera.transform.forward
                        : activeBody.transform.forward;
                    Vector3 forward = Vector3.ProjectOnPlane(-cameraForward, up);
                    if (forward.sqrMagnitude < 0.000001f)
                    {
                        forward = Vector3.ProjectOnPlane(activeBody.transform.forward, up);
                    }

                    if (forward.sqrMagnitude > 0.000001f)
                    {
                        worldRotation = Quaternion.LookRotation(forward.normalized, up);
                    }
                }
            }

            worldPosition += worldRotation * positionOffset;
            worldRotation *= Quaternion.Euler(rotationOffset);
            return true;
        }

        private void HideExpiredGloves()
        {
            float now = Time.unscaledTime;
            if (now - leftLastTrackedTime > lostTrackingGracePeriod)
            {
                SetGloveVisible(leftGlove, false);
                leftPoseInitialized = false;
                leftVelocity = Vector3.zero;
            }

            if (now - rightLastTrackedTime > lostTrackingGracePeriod)
            {
                SetGloveVisible(rightGlove, false);
                rightPoseInitialized = false;
                rightVelocity = Vector3.zero;
            }
        }

        private void ResolveReferences()
        {
            if (humanBodyManager == null)
            {
                humanBodyManager = Object.FindFirstObjectByType<ARHumanBodyManager>();
            }

            if (arCamera == null)
            {
                arCamera = Camera.main != null
                    ? Camera.main
                    : Object.FindFirstObjectByType<Camera>();
            }
        }

        private void ResetPoseState()
        {
            leftPoseInitialized = false;
            rightPoseInitialized = false;
            leftVelocity = Vector3.zero;
            rightVelocity = Vector3.zero;
        }

        private void ApplyGloveColors()
        {
            ApplyColor(leftGlove, overrideMaterialColor ? leftGloveColor : null);
            ApplyColor(rightGlove, overrideMaterialColor ? rightGloveColor : null);
        }

        private static void ApplyColor(Transform glove, Color? overrideColor)
        {
            if (glove == null)
            {
                return;
            }

            foreach (Renderer gloveRenderer in glove.GetComponentsInChildren<Renderer>(true))
            {
                Material[] materials = gloveRenderer.sharedMaterials;
                for (int materialIndex = 0; materialIndex < materials.Length; materialIndex++)
                {
                    Material material = materials[materialIndex];
                    if (material == null)
                    {
                        continue;
                    }

                    var propertyBlock = new MaterialPropertyBlock();
                    gloveRenderer.GetPropertyBlock(propertyBlock, materialIndex);
                    if (propertyBlock.isEmpty)
                    {
                        // A material-slot block overrides the renderer-wide one.
                        // Carry the latter forward so tint restoration does not
                        // silently discard unrelated presentation properties.
                        gloveRenderer.GetPropertyBlock(propertyBlock);
                    }
                    if (material.HasProperty("_Color"))
                    {
                        propertyBlock.SetColor("_Color",
                            overrideColor ?? material.GetColor("_Color"));
                    }

                    if (material.HasProperty("_BaseColor"))
                    {
                        propertyBlock.SetColor("_BaseColor",
                            overrideColor ?? material.GetColor("_BaseColor"));
                    }

                    gloveRenderer.SetPropertyBlock(propertyBlock, materialIndex);
                }
            }
        }

        private static void SetGloveVisible(Transform glove, bool visible)
        {
            if (glove != null && glove.gameObject.activeSelf != visible)
            {
                glove.gameObject.SetActive(visible);
            }
        }

        private void ValidateVisuals()
        {
            ValidateVisual(leftGlove, "left");
            ValidateVisual(rightGlove, "right");
        }

        private void ValidateVisual(Transform glove, string side)
        {
            if (glove == null)
            {
                Debug.LogError($"Opponent {side} glove root is not assigned.", this);
                return;
            }

            Renderer[] renderers = glove.GetComponentsInChildren<Renderer>(true);
            bool hasEnabledRenderer = false;
            foreach (Renderer gloveRenderer in renderers)
            {
                if (gloveRenderer.enabled && gloveRenderer.gameObject.activeSelf)
                {
                    hasEnabledRenderer = true;
                    break;
                }
            }

            if (!hasEnabledRenderer)
            {
                Debug.LogError(
                    $"Opponent {side} glove has no enabled renderer on an active model child.",
                    glove);
            }
        }

        private void SetTrackingStatus(string status, bool forceLog = false)
        {
            if (trackingStatus == status)
            {
                return;
            }

            trackingStatus = status;
            if (forceLog || logTrackingStateChanges)
            {
                Debug.Log(status, this);
            }
        }

        private void OnGUI()
        {
            if (!showTrackingDiagnostics)
            {
                return;
            }

            GUI.Box(
                new Rect(12f, Mathf.Max(12f, Screen.height - 66f),
                    Mathf.Min(620f, Screen.width - 24f), 46f),
                trackingStatus);
        }

        private void OnValidate()
        {
            positionSmoothTime = Mathf.Max(0f, positionSmoothTime);
            rotationSharpness = Mathf.Max(0f, rotationSharpness);
            lostTrackingGracePeriod = Mathf.Max(0f, lostTrackingGracePeriod);
        }
    }
}
