using System;
using System.Diagnostics;
using AprilTag;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace CG4002.Visualizer.AR
{
    /// <summary>
    /// WP1 diagnostic for one tagStandard41h12 marker. It exposes a presentation
    /// target only and never decides whether a punch hit the opponent.
    /// </summary>
    [AddComponentMenu("CG4002/AR/AprilTag Opponent Tracker")]
    public sealed class AprilTagOpponentTracker : MonoBehaviour
    {
        [Header("AR scene references")]
        [SerializeField] private ARCameraManager cameraManager;
        [SerializeField] private Camera arCamera;

        [Header("Printed tag")]
        [Tooltip("This detector package supports tagStandard41h12 only.")]
        [SerializeField, Min(0)] private int targetTagId;
        [Tooltip("Inner black detection-square width in metres, not full paper width.")]
        [SerializeField, Min(0.01f)] private float tagSizeMetres = 0.10f;

        [Header("Detection budget")]
        [SerializeField, Range(1, 4)] private int imageDownsample = 2;
        [SerializeField, Range(1, 4)] private int detectorDecimation = 1;
        [SerializeField, Range(1f, 30f)] private float detectionRateHz = 10f;
        [SerializeField, Min(0.05f)] private float trackingTimeout = 0.35f;
        [Tooltip("Rear-camera tracking should normally be None. MirrorY reverses left/right and reflects the AprilTag bit pattern.")]
        [SerializeField] private XRCpuImage.Transformation imageTransformation =
            XRCpuImage.Transformation.None;

        [Header("WP1 diagnostics")]
        [Tooltip("Corrects an image/camera roll mismatch found during device testing.")]
        [SerializeField] private float cameraImageRollCorrectionDegrees;
        [SerializeField] private Vector3 markerRotationCorrectionEuler;
        [SerializeField] private bool showWorldAxes = true;
        [SerializeField] private bool showStatusOverlay = true;
        [SerializeField, Min(0.01f)] private float axisLength = 0.12f;

        private TagDetector detector;
        private Vector2Int detectorDimensions;
        private XRCpuImage.AsyncConversion pendingConversion;
        private bool hasPendingConversion;
        private Matrix4x4 cameraLocalToWorldAtCapture;
        private Quaternion cameraRotationAtCapture;
        private float verticalFovAtCapture;
        private float nextCaptureTime;
        private float lastSeenTime = float.NegativeInfinity;
        private Pose latestWorldPose;
        private GameObject axesRoot;
        private string status = "Waiting for an AR camera frame";
        private double lastDetectionMilliseconds;
        private Vector2Int lastConversionDimensions;
        private int lastDetectedTagCount;
        private int lastDetectedTagId = -1;

        /// <summary>
        /// Raised on Unity's main thread whenever the requested tag produces a
        /// new world-space pose. Consumers should still check HasValidTarget.
        /// </summary>
        public event Action<Pose> TargetPoseUpdated;

        public bool HasValidTarget =>
            Time.unscaledTime - lastSeenTime <= trackingTimeout;

        public Pose LatestWorldPose => latestWorldPose;
        public int TargetTagId => targetTagId;
        public uint DetectionSequence { get; private set; }
        public float TrackingTimeout => trackingTimeout;
        public float SecondsSinceLastDetection => float.IsNegativeInfinity(lastSeenTime)
            ? float.PositiveInfinity
            : Mathf.Max(0f, Time.unscaledTime - lastSeenTime);

        private void Awake()
        {
            if (cameraManager == null)
            {
                cameraManager = FindFirstObjectByType<ARCameraManager>();
            }

            if (arCamera == null)
            {
                arCamera = cameraManager != null
                    ? cameraManager.GetComponent<Camera>()
                    : Camera.main;
            }

            if (showWorldAxes)
            {
                CreateDebugAxes();
            }
        }

        private void Update()
        {
            CompletePendingConversion();

            if (!hasPendingConversion && Time.unscaledTime >= nextCaptureTime)
            {
                QueueCameraFrame();
            }

            UpdateDebugAxes();
        }

        private void OnDisable()
        {
            DisposeNativeResources();
            if (axesRoot != null) axesRoot.SetActive(false);
        }

        private void OnDestroy()
        {
            DisposeNativeResources();
            if (axesRoot != null) Destroy(axesRoot);
        }

        private void QueueCameraFrame()
        {
            nextCaptureTime = Time.unscaledTime + 1f / detectionRateHz;

            if (cameraManager == null || arCamera == null)
            {
                status = "Missing AR Camera Manager or Camera";
                return;
            }

            if (!cameraManager.TryAcquireLatestCpuImage(out XRCpuImage image))
            {
                status = "Waiting for an ARKit CPU image";
                return;
            }

            try
            {
                var dimensions = new Vector2Int(
                    Mathf.Max(16, image.width / imageDownsample),
                    Mathf.Max(16, image.height / imageDownsample));
                EnsureDetector(dimensions);
                lastConversionDimensions = dimensions;

                var conversionParameters = new XRCpuImage.ConversionParams
                {
                    inputRect = new RectInt(0, 0, image.width, image.height),
                    outputDimensions = dimensions,
                    outputFormat = TextureFormat.RGBA32,
                    transformation = imageTransformation
                };

                cameraLocalToWorldAtCapture = arCamera.transform.localToWorldMatrix;
                cameraRotationAtCapture = arCamera.transform.rotation;
                verticalFovAtCapture = GetVerticalFieldOfViewRadians();
                pendingConversion = image.ConvertAsync(conversionParameters);
                hasPendingConversion = true;
                status = $"Processing {dimensions.x} x {dimensions.y} camera frame";
            }
            catch (Exception exception)
            {
                status = $"Camera conversion error: {exception.GetType().Name}";
                UnityEngine.Debug.LogException(exception, this);
            }
            finally
            {
                image.Dispose();
            }
        }

        private void CompletePendingConversion()
        {
            if (!hasPendingConversion || !pendingConversion.status.IsDone())
            {
                return;
            }

            try
            {
                if (pendingConversion.status != XRCpuImage.AsyncConversionStatus.Ready)
                {
                    status = $"Camera conversion failed: {pendingConversion.status}";
                    return;
                }

                var bytes = pendingConversion.GetData<byte>();
                if (!bytes.IsCreated)
                {
                    status = "Camera conversion returned no data";
                    return;
                }

                var pixels = bytes.Reinterpret<Color32>(1);
                var stopwatch = Stopwatch.StartNew();
                detector.ProcessImage(
                    pixels.AsReadOnlySpan(),
                    verticalFovAtCapture,
                    tagSizeMetres);
                stopwatch.Stop();
                lastDetectionMilliseconds = stopwatch.Elapsed.TotalMilliseconds;

                bool foundTarget = false;
                lastDetectedTagCount = 0;
                lastDetectedTagId = -1;
                foreach (TagPose tag in detector.DetectedTags)
                {
                    if (lastDetectedTagCount == 0)
                    {
                        lastDetectedTagId = tag.ID;
                    }

                    lastDetectedTagCount++;
                    if (tag.ID != targetTagId || foundTarget) continue;

                    ApplyDetection(tag);
                    foundTarget = true;
                }

                status = foundTarget
                    ? $"TRACKING tag {targetTagId}"
                    : lastDetectedTagCount > 0
                        ? $"Saw tag {lastDetectedTagId}, expected {targetTagId}"
                        : $"Searching for tag {targetTagId}";
            }
            catch (Exception exception)
            {
                status = $"AprilTag error: {exception.GetType().Name}";
                UnityEngine.Debug.LogException(exception, this);
            }
            finally
            {
                pendingConversion.Dispose();
                hasPendingConversion = false;
            }
        }

        private void ApplyDetection(TagPose tag)
        {
            Quaternion imageRoll = Quaternion.AngleAxis(
                cameraImageRollCorrectionDegrees,
                Vector3.forward);
            Vector3 cameraSpacePosition = imageRoll * tag.Position;
            Quaternion cameraSpaceRotation =
                imageRoll * tag.Rotation * Quaternion.Euler(markerRotationCorrectionEuler);

            latestWorldPose = new Pose(
                cameraLocalToWorldAtCapture.MultiplyPoint3x4(cameraSpacePosition),
                cameraRotationAtCapture * cameraSpaceRotation);
            lastSeenTime = Time.unscaledTime;
            DetectionSequence++;
            TargetPoseUpdated?.Invoke(latestWorldPose);
        }

        private float GetVerticalFieldOfViewRadians()
        {
            if (cameraManager.TryGetIntrinsics(out XRCameraIntrinsics intrinsics) &&
                intrinsics.focalLength.y > 0f)
            {
                return 2f * Mathf.Atan(
                    intrinsics.resolution.y / (2f * intrinsics.focalLength.y));
            }

            return arCamera.fieldOfView * Mathf.Deg2Rad;
        }

        private void EnsureDetector(Vector2Int dimensions)
        {
            if (detector != null && detectorDimensions == dimensions)
            {
                return;
            }

            detector?.Dispose();
            detector = new TagDetector(
                dimensions.x,
                dimensions.y,
                detectorDecimation);
            detectorDimensions = dimensions;
        }

        private void DisposeNativeResources()
        {
            if (hasPendingConversion)
            {
                pendingConversion.Dispose();
                hasPendingConversion = false;
            }

            detector?.Dispose();
            detector = null;
            detectorDimensions = default;
        }

        private void CreateDebugAxes()
        {
            axesRoot = new GameObject("AprilTag Debug Axes (runtime)");
            axesRoot.transform.SetParent(transform, false);

            CreateAxis("X (red)", Vector3.right, Color.red);
            CreateAxis("Y (green)", Vector3.up, Color.green);
            CreateAxis("Z (blue)", Vector3.forward, Color.blue);

            GameObject centre = GameObject.CreatePrimitive(PrimitiveType.Cube);
            centre.name = "Tag centre";
            centre.transform.SetParent(axesRoot.transform, false);
            centre.transform.localScale = Vector3.one * axisLength * 0.12f;
            SetDebugColourAndRemoveCollider(centre, Color.white);
            axesRoot.SetActive(false);
        }

        private void CreateAxis(string axisName, Vector3 direction, Color colour)
        {
            GameObject axis = GameObject.CreatePrimitive(PrimitiveType.Cube);
            axis.name = axisName;
            axis.transform.SetParent(axesRoot.transform, false);
            axis.transform.localPosition = direction * axisLength * 0.5f;
            axis.transform.localScale = new Vector3(
                direction.x == 0f ? axisLength * 0.04f : axisLength,
                direction.y == 0f ? axisLength * 0.04f : axisLength,
                direction.z == 0f ? axisLength * 0.04f : axisLength);
            SetDebugColourAndRemoveCollider(axis, colour);
        }

        private static void SetDebugColourAndRemoveCollider(
            GameObject gameObject,
            Color colour)
        {
            Collider collider = gameObject.GetComponent<Collider>();
            if (collider != null) Destroy(collider);

            Renderer renderer = gameObject.GetComponent<Renderer>();
            Shader shader = Shader.Find("Unlit/Color") ?? Shader.Find("Standard");
            if (renderer != null && shader != null)
            {
                renderer.material = new Material(shader) { color = colour };
            }
        }

        private void UpdateDebugAxes()
        {
            if (axesRoot == null) return;

            axesRoot.SetActive(showWorldAxes && HasValidTarget);
            if (!axesRoot.activeSelf) return;

            axesRoot.transform.SetPositionAndRotation(
                latestWorldPose.position,
                latestWorldPose.rotation);
        }

        private void OnGUI()
        {
            if (!showStatusOverlay) return;

            string validity = HasValidTarget ? "VALID" : "NOT VALID";
            float distance = HasValidTarget && arCamera != null
                ? Vector3.Distance(arCamera.transform.position, latestWorldPose.position)
                : 0f;
            bool horizontallyMirrored =
                (imageTransformation & XRCpuImage.Transformation.MirrorY) != 0;
            string orientation = horizontallyMirrored
                ? $"{imageTransformation} (LEFT/RIGHT REVERSED)"
                : imageTransformation.ToString();

            GUI.Box(
                new Rect(12f, 12f, 390f, 144f),
                "AprilTag WP1\n" +
                $"{status} ({validity})\n" +
                $"Distance: {distance:F2} m\n" +
                $"Detector: {lastDetectionMilliseconds:F1} ms | Tags: {lastDetectedTagCount}\n" +
                $"Image: {lastConversionDimensions.x}x{lastConversionDimensions.y} | {orientation}");
        }
    }
}
