using System.Collections.Generic;
using UnityEngine;

namespace CG4002.Visualizer.AR
{
    /// <summary>
    /// Pure geometry used by floor acquisition and pickup presentation.
    /// Keeping this separate from AR Foundation makes the safety constraints
    /// deterministic and edit-mode testable.
    /// </summary>
    public static class PickupPlacement
    {
        private const float DirectionEpsilon = 0.0001f;

        public static bool TryCreateFloorPose(
            Vector3 cameraPosition,
            Vector3 cameraForward,
            Vector3 floorOrigin,
            Vector3 floorNormal,
            float distanceMetres,
            float bearingDegrees,
            float minimumDistanceMetres,
            float maximumDistanceMetres,
            float minimumBearingDegrees,
            float maximumBearingDegrees,
            out Pose pose)
        {
            pose = default;
            if (!IsFinite(cameraPosition) || !IsFinite(cameraForward) ||
                !IsFinite(floorOrigin) || !IsFinite(floorNormal) ||
                !IsFinite(distanceMetres) || !IsFinite(bearingDegrees) ||
                floorNormal.sqrMagnitude < DirectionEpsilon ||
                minimumDistanceMetres < 0f || maximumDistanceMetres < minimumDistanceMetres ||
                minimumBearingDegrees > maximumBearingDegrees ||
                distanceMetres < minimumDistanceMetres || distanceMetres > maximumDistanceMetres ||
                bearingDegrees < minimumBearingDegrees || bearingDegrees > maximumBearingDegrees)
            {
                return false;
            }

            Vector3 normal = floorNormal.normalized;
            Vector3 heading = Vector3.ProjectOnPlane(cameraForward, normal);
            if (heading.sqrMagnitude < DirectionEpsilon)
            {
                return false;
            }

            heading.Normalize();
            Vector3 projectedCamera = cameraPosition -
                Vector3.Dot(cameraPosition - floorOrigin, normal) * normal;
            Vector3 direction = Quaternion.AngleAxis(bearingDegrees, normal) * heading;
            Vector3 position = projectedCamera + direction * distanceMetres;
            pose = new Pose(position, Quaternion.LookRotation(direction, normal));
            return IsFinite(position) && IsFinite(pose.rotation);
        }

        public static bool IsPointInsidePolygon(
            IReadOnlyList<Vector2> polygon,
            Vector2 point,
            float edgeMargin = 0f)
        {
            if (polygon == null || polygon.Count < 3 || !IsFinite(point) || edgeMargin < 0f)
            {
                return false;
            }

            bool inside = false;
            int previous = polygon.Count - 1;
            for (int current = 0; current < polygon.Count; current++)
            {
                Vector2 a = polygon[previous];
                Vector2 b = polygon[current];
                if (!IsFinite(a) || !IsFinite(b))
                {
                    return false;
                }

                bool crosses = (a.y > point.y) != (b.y > point.y) &&
                    point.x < (b.x - a.x) * (point.y - a.y) /
                    (b.y - a.y) + a.x;
                if (crosses)
                {
                    inside = !inside;
                }

                if (edgeMargin > 0f && DistanceToSegment(point, a, b) < edgeMargin)
                {
                    return false;
                }

                previous = current;
            }

            return inside;
        }

        public static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        public static bool IsFinite(Vector2 value)
        {
            return IsFinite(value.x) && IsFinite(value.y);
        }

        public static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }

        private static bool IsFinite(Quaternion value)
        {
            return IsFinite(value.x) && IsFinite(value.y) &&
                   IsFinite(value.z) && IsFinite(value.w);
        }

        private static float DistanceToSegment(Vector2 point, Vector2 start, Vector2 end)
        {
            Vector2 segment = end - start;
            float lengthSquared = segment.sqrMagnitude;
            if (lengthSquared <= Mathf.Epsilon)
            {
                return Vector2.Distance(point, start);
            }

            float t = Mathf.Clamp01(Vector2.Dot(point - start, segment) / lengthSquared);
            return Vector2.Distance(point, start + segment * t);
        }
    }
}
