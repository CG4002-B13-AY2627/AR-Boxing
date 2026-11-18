using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    /// <summary>Pure geometry for the presentation-only pickup reach.</summary>
    public static class PickupReachTargeting
    {
        public static bool ShouldUseLeftHand(float viewportX)
        {
            return float.IsFinite(viewportX) && viewportX <= 0.5f;
        }

        public static bool TryGetEndpoint(
            Vector3 start,
            Vector3 target,
            float standoffMetres,
            float maximumReachMetres,
            float minimumWorldHeight,
            out Vector3 endpoint)
        {
            endpoint = start;
            if (!IsFinite(start) || !IsFinite(target) ||
                !float.IsFinite(standoffMetres) || !float.IsFinite(maximumReachMetres) ||
                !float.IsFinite(minimumWorldHeight) || standoffMetres < 0f ||
                maximumReachMetres <= 0f)
            {
                return false;
            }

            Vector3 difference = target - start;
            float distance = difference.magnitude;
            if (distance <= Mathf.Epsilon)
            {
                endpoint.y = Mathf.Max(endpoint.y, minimumWorldHeight);
                return IsFinite(endpoint);
            }

            float travel = Mathf.Min(
                maximumReachMetres,
                Mathf.Max(0f, distance - standoffMetres));
            endpoint = start + difference / distance * travel;
            endpoint.y = Mathf.Max(endpoint.y, minimumWorldHeight);
            return IsFinite(endpoint);
        }

        public static Vector3 EvaluatePath(
            Vector3 start,
            Vector3 endpoint,
            Vector3 worldUp,
            Vector3 cameraForward,
            float arcHeightMetres,
            float forwardBowMetres,
            float amount)
        {
            Vector3 up = worldUp.sqrMagnitude > Mathf.Epsilon
                ? worldUp.normalized
                : Vector3.up;
            Vector3 forward = Vector3.ProjectOnPlane(cameraForward, up);
            if (forward.sqrMagnitude > Mathf.Epsilon)
            {
                forward.Normalize();
            }

            Vector3 control = Vector3.Lerp(start, endpoint, 0.5f) +
                up * Mathf.Max(0f, arcHeightMetres) +
                forward * forwardBowMetres;
            return PunchTargeting.QuadraticBezier(
                start,
                control,
                endpoint,
                Mathf.Clamp01(amount));
        }

        private static bool IsFinite(Vector3 value)
        {
            return float.IsFinite(value.x) &&
                   float.IsFinite(value.y) &&
                   float.IsFinite(value.z);
        }
    }
}
