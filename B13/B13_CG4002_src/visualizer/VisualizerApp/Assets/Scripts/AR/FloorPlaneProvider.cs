using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace CG4002.Visualizer.AR
{
    /// <summary>
    /// Selects one stable upward-facing AR plane for the pickup arena.
    /// A classified floor wins; XR providers without classification fall back
    /// to the largest suitable horizontal plane below the camera.
    /// </summary>
    public sealed class FloorPlaneProvider : MonoBehaviour
    {
        [SerializeField] private ARPlaneManager planeManager;
        [SerializeField] private Camera arCamera;
        [SerializeField, Min(0.1f)] private float minimumPlaneSideMetres = 0.5f;
        [SerializeField, Min(0f)] private float stabilitySeconds = 0.35f;
        [SerializeField, Min(0f)] private float maximumHeightAboveCameraMetres = 0.15f;
        [SerializeField, Min(0f)] private float boundaryMarginMetres = 0.08f;

        private readonly List<Vector2> boundaryScratch = new(32);
        private ARPlane candidatePlane;
        private ARPlane lockedPlane;
        private float candidateSince;
        private bool placementRequested;
        private bool lastPublishedReady;

#if UNITY_EDITOR
        private bool syntheticFloorEnabled;
        private Pose syntheticFloorPose;
        private Vector2 syntheticFloorSize;
#endif

        public bool IsReady
        {
            get
            {
#if UNITY_EDITOR
                if (syntheticFloorEnabled)
                {
                    return true;
                }
#endif
                return lockedPlane != null && lockedPlane.trackingState == TrackingState.Tracking;
            }
        }

        public bool PlacementRequested => placementRequested;
        public ARPlane LockedPlane => lockedPlane;

        public event Action<bool> ReadinessChanged;

        private void Awake()
        {
            if (planeManager == null)
            {
                planeManager = GetComponentInParent<ARPlaneManager>();
            }

            if (arCamera == null)
            {
                arCamera = Camera.main;
            }

            if (planeManager != null)
            {
                planeManager.requestedDetectionMode = PlaneDetectionMode.Horizontal;
            }

            lastPublishedReady = IsReady;
        }

        private void Update()
        {
#if UNITY_EDITOR
            if (syntheticFloorEnabled)
            {
                return;
            }
#endif
            if (lockedPlane != null && lockedPlane.trackingState == TrackingState.Tracking)
            {
                return;
            }

            lockedPlane = null;
            ARPlane best = FindBestPlane();
            if (best == null)
            {
                candidatePlane = null;
                PublishReadinessChange();
                return;
            }

            if (candidatePlane != best)
            {
                candidatePlane = best;
                candidateSince = Time.unscaledTime;
            }
            else if (Time.unscaledTime - candidateSince >= stabilitySeconds)
            {
                lockedPlane = candidatePlane;
                candidatePlane = null;
            }

            PublishReadinessChange();
        }

        public void SetPlacementRequested(bool value)
        {
            placementRequested = value;
        }

        public bool TryCreatePlacementPose(
            float distanceMetres,
            float bearingDegrees,
            float minimumDistanceMetres,
            float maximumDistanceMetres,
            float minimumBearingDegrees,
            float maximumBearingDegrees,
            out Pose pose)
        {
            pose = default;
            if (arCamera == null)
            {
                return false;
            }

#if UNITY_EDITOR
            if (syntheticFloorEnabled)
            {
                if (!PickupPlacement.TryCreateFloorPose(
                        arCamera.transform.position,
                        arCamera.transform.forward,
                        syntheticFloorPose.position,
                        syntheticFloorPose.rotation * Vector3.up,
                        distanceMetres,
                        bearingDegrees,
                        minimumDistanceMetres,
                        maximumDistanceMetres,
                        minimumBearingDegrees,
                        maximumBearingDegrees,
                        out pose))
                {
                    return false;
                }

                Vector3 local = Quaternion.Inverse(syntheticFloorPose.rotation) *
                    (pose.position - syntheticFloorPose.position);
                return Mathf.Abs(local.x) <= syntheticFloorSize.x * 0.5f - boundaryMarginMetres &&
                       Mathf.Abs(local.z) <= syntheticFloorSize.y * 0.5f - boundaryMarginMetres;
            }
#endif

            if (!IsReady || !PickupPlacement.TryCreateFloorPose(
                    arCamera.transform.position,
                    arCamera.transform.forward,
                    lockedPlane.transform.position,
                    lockedPlane.transform.up,
                    distanceMetres,
                    bearingDegrees,
                    minimumDistanceMetres,
                    maximumDistanceMetres,
                    minimumBearingDegrees,
                    maximumBearingDegrees,
                    out pose))
            {
                return false;
            }

            return ContainsPoint(lockedPlane, pose.position);
        }

#if UNITY_EDITOR
        /// <summary>Test-only deterministic floor; never compiled into iOS builds.</summary>
        public void SetSyntheticFloorForTesting(Pose pose, Vector2 size, Camera camera)
        {
            syntheticFloorEnabled = true;
            syntheticFloorPose = pose;
            syntheticFloorSize = size;
            arCamera = camera;
            PublishReadinessChange();
        }
#endif

        private ARPlane FindBestPlane()
        {
            if (planeManager == null || arCamera == null)
            {
                return null;
            }

            ARPlane best = null;
            float bestScore = float.NegativeInfinity;
            foreach (ARPlane plane in planeManager.trackables)
            {
                if (plane == null || plane.trackingState != TrackingState.Tracking ||
                    plane.alignment != PlaneAlignment.HorizontalUp ||
                    plane.size.x < minimumPlaneSideMetres ||
                    plane.size.y < minimumPlaneSideMetres ||
                    plane.transform.position.y > arCamera.transform.position.y +
                    maximumHeightAboveCameraMetres)
                {
                    continue;
                }

                bool classifiedFloor =
                    (plane.classifications & PlaneClassifications.Floor) != 0;
                float area = plane.size.x * plane.size.y;
                float heightBelowCamera = arCamera.transform.position.y -
                    plane.transform.position.y;
                float score = (classifiedFloor ? 1000f : 0f) + area +
                    Mathf.Clamp(heightBelowCamera, 0f, 3f) * 0.1f;
                if (score > bestScore)
                {
                    best = plane;
                    bestScore = score;
                }
            }

            return best;
        }

        private bool ContainsPoint(ARPlane plane, Vector3 worldPoint)
        {
            Vector3 local = plane.transform.InverseTransformPoint(worldPoint);
            Vector2 point = new(local.x, local.z);
            var boundary = plane.boundary;
            if (boundary.IsCreated && boundary.Length >= 3)
            {
                boundaryScratch.Clear();
                for (int index = 0; index < boundary.Length; index++)
                {
                    boundaryScratch.Add(boundary[index]);
                }

                return PickupPlacement.IsPointInsidePolygon(
                    boundaryScratch,
                    point,
                    boundaryMarginMetres);
            }

            return Mathf.Abs(point.x) <= plane.size.x * 0.5f - boundaryMarginMetres &&
                   Mathf.Abs(point.y) <= plane.size.y * 0.5f - boundaryMarginMetres;
        }

        private void PublishReadinessChange()
        {
            bool current = IsReady;
            if (lastPublishedReady != current)
            {
                lastPublishedReady = current;
                ReadinessChanged?.Invoke(current);
            }
        }

        private void OnValidate()
        {
            minimumPlaneSideMetres = Mathf.Max(0.1f, minimumPlaneSideMetres);
            stabilitySeconds = Mathf.Max(0f, stabilitySeconds);
            maximumHeightAboveCameraMetres = Mathf.Max(0f, maximumHeightAboveCameraMetres);
            boundaryMarginMetres = Mathf.Max(0f, boundaryMarginMetres);
        }
    }
}
