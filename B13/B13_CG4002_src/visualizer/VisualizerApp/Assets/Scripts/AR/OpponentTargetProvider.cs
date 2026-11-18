using System;
using UnityEngine;

namespace CG4002.Visualizer.AR
{
    public enum OpponentTargetStatus
    {
        MissingSource,
        Searching,
        Tracking,
        Lost
    }

    public enum OpponentTargetZone
    {
        Chest,
        Head,
        LeftBody,
        RightBody
    }

    /// <summary>
    /// WP2 presentation target derived from the WP1 AprilTag pose. It smooths
    /// visual motion and exposes target points for later punch animation work.
    /// It never decides whether a punch hit the opponent.
    /// </summary>
    [AddComponentMenu("CG4002/AR/Opponent Target Provider")]
    public sealed class OpponentTargetProvider : MonoBehaviour
    {
        [Header("WP1 source")]
        [SerializeField] private AprilTagOpponentTracker source;

        [Header("Smoothed marker rig")]
        [SerializeField] private Transform smoothedPoseRoot;
        [SerializeField] private Transform chestTarget;
        [SerializeField] private Transform headTarget;
        [SerializeField] private Transform leftBodyTarget;
        [SerializeField] private Transform rightBodyTarget;

        [Header("Smoothing")]
        [Tooltip("Higher values follow position changes more quickly.")]
        [SerializeField, Min(0f)] private float positionSharpness = 12f;
        [Tooltip("Higher values follow rotation changes more quickly.")]
        [SerializeField, Min(0f)] private float rotationSharpness = 10f;
        [Tooltip("Snap instead of smoothing when a valid pose moves farther than this.")]
        [SerializeField, Min(0f)] private float teleportDistanceMetres = 0.75f;
        [Tooltip("Snap instead of smoothing when a valid pose rotates farther than this.")]
        [SerializeField, Range(0f, 180f)] private float teleportAngleDegrees = 70f;

        [Header("WP2 diagnostics")]
        [SerializeField] private bool showTargetVisuals = true;
        [SerializeField] private bool showStatusOverlay = true;
        [SerializeField, Min(0.01f)] private float targetVisualDiameter = 0.07f;

        private readonly OpponentTargetPoseFilter poseFilter =
            new OpponentTargetPoseFilter();
        private AprilTagOpponentTracker subscribedSource;
        private Pose desiredPose;
        private uint lastProcessedSequence;
        private bool hasEverTracked;
        private GameObject diagnosticsRoot;
        private Transform chestVisual;
        private Transform headVisual;
        private Transform leftBodyVisual;
        private Transform rightBodyVisual;
        private OpponentTargetStatus status = OpponentTargetStatus.Searching;

        public event Action<OpponentTargetStatus> StatusChanged;

        public OpponentTargetStatus Status => status;
        public bool HasValidTarget =>
            status == OpponentTargetStatus.Tracking && poseFilter.IsInitialized;
        public Pose SmoothedMarkerPose => poseFilter.Current;
        public float SecondsSinceLastDetection => source != null
            ? source.SecondsSinceLastDetection
            : float.PositiveInfinity;

        private void Awake()
        {
            ResolveSource();
            EnsureTargetHierarchy();
            CreateDiagnosticVisuals();
            SetDiagnosticsActive(false);
        }

        private void OnEnable()
        {
            RefreshSubscription();
            ProcessCurrentSourcePoseIfNew();
        }

        private void Update()
        {
            RefreshSubscription();

            if (source == null)
            {
                SetStatus(OpponentTargetStatus.MissingSource);
                SetDiagnosticsActive(false);
                return;
            }

            ProcessCurrentSourcePoseIfNew();

            if (!source.HasValidTarget)
            {
                SetStatus(hasEverTracked
                    ? OpponentTargetStatus.Lost
                    : OpponentTargetStatus.Searching);
                SetDiagnosticsActive(false);
                return;
            }

            SetStatus(OpponentTargetStatus.Tracking);
            Pose smoothedPose = poseFilter.Step(
                desiredPose,
                Time.unscaledDeltaTime,
                positionSharpness,
                rotationSharpness);
            smoothedPoseRoot.SetPositionAndRotation(
                smoothedPose.position,
                smoothedPose.rotation);
            UpdateDiagnosticVisualPoses();
            SetDiagnosticsActive(showTargetVisuals);
        }

        private void OnDisable()
        {
            Unsubscribe();
            SetDiagnosticsActive(false);
        }

        private void OnDestroy()
        {
            Unsubscribe();
            if (diagnosticsRoot != null)
            {
                Destroy(diagnosticsRoot);
            }
        }

        public bool TryGetTargetPose(OpponentTargetZone zone, out Pose pose)
        {
            Transform target = GetTargetTransform(zone);
            if (!HasValidTarget || target == null)
            {
                pose = default;
                return false;
            }

            pose = new Pose(target.position, target.rotation);
            return true;
        }

        public Transform GetTargetTransform(OpponentTargetZone zone)
        {
            return zone switch
            {
                OpponentTargetZone.Chest => chestTarget,
                OpponentTargetZone.Head => headTarget,
                OpponentTargetZone.LeftBody => leftBodyTarget,
                OpponentTargetZone.RightBody => rightBodyTarget,
                _ => null
            };
        }

        private void ResolveSource()
        {
            if (source == null)
            {
                source = FindFirstObjectByType<AprilTagOpponentTracker>();
            }
        }

        private void RefreshSubscription()
        {
            ResolveSource();
            if (subscribedSource == source)
            {
                return;
            }

            Unsubscribe();
            subscribedSource = source;
            if (subscribedSource != null)
            {
                subscribedSource.TargetPoseUpdated += HandleTargetPoseUpdated;
            }
        }

        private void Unsubscribe()
        {
            if (subscribedSource != null)
            {
                subscribedSource.TargetPoseUpdated -= HandleTargetPoseUpdated;
                subscribedSource = null;
            }
        }

        private void HandleTargetPoseUpdated(Pose pose)
        {
            if (source == null)
            {
                return;
            }

            lastProcessedSequence = source.DetectionSequence;
            AcceptPose(pose);
        }

        private void ProcessCurrentSourcePoseIfNew()
        {
            if (source == null || !source.HasValidTarget ||
                source.DetectionSequence == lastProcessedSequence)
            {
                return;
            }

            lastProcessedSequence = source.DetectionSequence;
            AcceptPose(source.LatestWorldPose);
        }

        private void AcceptPose(Pose pose)
        {
            bool wasNotTracking = status != OpponentTargetStatus.Tracking;
            bool jumped = poseFilter.IsInitialized &&
                (Vector3.Distance(poseFilter.Current.position, pose.position) >
                    teleportDistanceMetres ||
                 Quaternion.Angle(poseFilter.Current.rotation, pose.rotation) >
                    teleportAngleDegrees);

            desiredPose = pose;
            if (!poseFilter.IsInitialized || wasNotTracking || jumped)
            {
                poseFilter.Reset(pose);
                smoothedPoseRoot.SetPositionAndRotation(pose.position, pose.rotation);
            }

            hasEverTracked = true;
            SetStatus(OpponentTargetStatus.Tracking);
        }

        private void SetStatus(OpponentTargetStatus nextStatus)
        {
            if (status == nextStatus)
            {
                return;
            }

            status = nextStatus;
            StatusChanged?.Invoke(status);
        }

        private void EnsureTargetHierarchy()
        {
            smoothedPoseRoot = EnsureChild(
                smoothedPoseRoot,
                transform,
                "Smoothed Marker Pose",
                Vector3.zero);
            chestTarget = EnsureChild(
                chestTarget,
                smoothedPoseRoot,
                "Chest Target",
                Vector3.zero);
            headTarget = EnsureChild(
                headTarget,
                smoothedPoseRoot,
                "Head Target",
                new Vector3(0f, 0.35f, 0f));
            leftBodyTarget = EnsureChild(
                leftBodyTarget,
                smoothedPoseRoot,
                "Left Body Target",
                new Vector3(-0.18f, -0.10f, 0f));
            rightBodyTarget = EnsureChild(
                rightBodyTarget,
                smoothedPoseRoot,
                "Right Body Target",
                new Vector3(0.18f, -0.10f, 0f));
        }

        private static Transform EnsureChild(
            Transform existing,
            Transform parent,
            string objectName,
            Vector3 defaultLocalPosition)
        {
            if (existing != null)
            {
                return existing;
            }

            Transform found = parent.Find(objectName);
            if (found != null)
            {
                return found;
            }

            var child = new GameObject(objectName).transform;
            child.SetParent(parent, false);
            child.localPosition = defaultLocalPosition;
            return child;
        }

        private void CreateDiagnosticVisuals()
        {
            diagnosticsRoot = new GameObject("WP2 Target Visuals (runtime)");
            diagnosticsRoot.transform.SetParent(transform, false);
            chestVisual = CreateTargetVisual(
                "Chest (yellow)",
                new Color(1f, 0.82f, 0.1f));
            headVisual = CreateTargetVisual("Head (cyan)", Color.cyan);
            leftBodyVisual = CreateTargetVisual("Left body (magenta)", Color.magenta);
            rightBodyVisual = CreateTargetVisual(
                "Right body (orange)",
                new Color(1f, 0.35f, 0.05f));
        }

        private Transform CreateTargetVisual(string visualName, Color colour)
        {
            GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            sphere.name = visualName;
            sphere.transform.SetParent(diagnosticsRoot.transform, false);
            sphere.transform.localScale = Vector3.one * targetVisualDiameter;

            Collider collider = sphere.GetComponent<Collider>();
            if (collider != null)
            {
                Destroy(collider);
            }

            Renderer renderer = sphere.GetComponent<Renderer>();
            Shader shader = Shader.Find("Unlit/Color") ?? Shader.Find("Standard");
            if (renderer != null && shader != null)
            {
                renderer.material = new Material(shader) { color = colour };
            }

            return sphere.transform;
        }

        private void UpdateDiagnosticVisualPoses()
        {
            CopyPose(chestTarget, chestVisual);
            CopyPose(headTarget, headVisual);
            CopyPose(leftBodyTarget, leftBodyVisual);
            CopyPose(rightBodyTarget, rightBodyVisual);
        }

        private static void CopyPose(Transform sourceTransform, Transform destination)
        {
            if (sourceTransform != null && destination != null)
            {
                destination.SetPositionAndRotation(
                    sourceTransform.position,
                    sourceTransform.rotation);
            }
        }

        private void SetDiagnosticsActive(bool active)
        {
            if (diagnosticsRoot != null)
            {
                diagnosticsRoot.SetActive(active);
            }
        }

        private void OnGUI()
        {
            if (!showStatusOverlay)
            {
                return;
            }

            string age = float.IsPositiveInfinity(SecondsSinceLastDetection)
                ? "never"
                : $"{SecondsSinceLastDetection:F2} s";
            string position = poseFilter.IsInitialized
                ? $"{poseFilter.Current.position.x:F2}, {poseFilter.Current.position.y:F2}, {poseFilter.Current.position.z:F2}"
                : "not available";

            GUI.Box(
                new Rect(12f, 164f, 360f, 94f),
                "AprilTag WP2 target provider\n" +
                $"Status: {status} | Last seen: {age}\n" +
                $"Smoothed position: {position}");
        }

    }
}
