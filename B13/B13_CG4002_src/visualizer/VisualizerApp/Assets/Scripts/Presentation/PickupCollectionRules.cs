using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    public static class PickupCollectionRules
    {
        public static bool IsWithinCameraRange(
            Vector3 cameraPosition,
            Vector3 pickupPosition,
            float maximumDistanceMetres)
        {
            return IsFinite(cameraPosition) && IsFinite(pickupPosition) &&
                   float.IsFinite(maximumDistanceMetres) &&
                   maximumDistanceMetres > 0f &&
                   Vector3.Distance(cameraPosition, pickupPosition) <= maximumDistanceMetres;
        }

        private static bool IsFinite(Vector3 value)
        {
            return float.IsFinite(value.x) &&
                   float.IsFinite(value.y) &&
                   float.IsFinite(value.z);
        }
    }
}
