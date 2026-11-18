using System;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    /// <summary>
    /// Resolves a rendered pickup into a glove reach target. This is presentation only:
    /// it never removes an item, emits collection, or changes player state.
    /// </summary>
    public sealed class PickupReachPresenter : MonoBehaviour
    {
        [SerializeField] private PickupSpawnPresenter pickupPresenter;
        [SerializeField] private CameraRelativeGloveRig gloveRig;
        [SerializeField] private Camera arCamera;

        public bool LastReachUsedLeftHand { get; private set; }

        private void Awake()
        {
            if (arCamera == null)
            {
                arCamera = Camera.main;
            }

            if (gloveRig == null)
            {
                gloveRig = FindFirstObjectByType<CameraRelativeGloveRig>();
            }
        }

        public void ReachLeft()
        {
            TryReachLeft();
        }

        public void ReachRight()
        {
            TryReachRight();
        }

        public void ReachAutomatic()
        {
            TryReachAutomatic();
        }

        public bool TryReachLeft()
        {
            return TryReach(true);
        }

        public bool TryReachRight()
        {
            return TryReach(false);
        }

        public bool TryReachAutomatic()
        {
            if (!TryGetTarget(out PickupVisual pickup) || arCamera == null)
            {
                return false;
            }

            return TryReachPickup(pickup, string.Empty);
        }

        public bool TryReachPickup(
            PickupVisual pickup,
            string hand,
            Action onContact = null)
        {
            if (pickup == null || arCamera == null)
            {
                return false;
            }

            bool isLeft;
            if (hand == "LEFT")
            {
                isLeft = true;
            }
            else if (hand == "RIGHT")
            {
                isLeft = false;
            }
            else
            {
                Vector3 viewport = arCamera.WorldToViewportPoint(pickup.ContactPosition);
                if (!float.IsFinite(viewport.x) || viewport.z <= 0f)
                {
                    return false;
                }

                isLeft = PickupReachTargeting.ShouldUseLeftHand(viewport.x);
            }

            return TryReach(isLeft, pickup, onContact);
        }

        private bool TryReach(bool isLeft)
        {
            return TryGetTarget(out PickupVisual pickup) && TryReach(isLeft, pickup, null);
        }

        private bool TryReach(bool isLeft, PickupVisual pickup, Action onContact)
        {
            if (gloveRig == null || pickup == null ||
                !gloveRig.TryStartPickupReach(
                    isLeft,
                    pickup.ContactPosition,
                    pickup.transform.position.y,
                    onContact))
            {
                return false;
            }

            LastReachUsedLeftHand = isLeft;
            return true;
        }

        private bool TryGetTarget(out PickupVisual pickup)
        {
            pickup = null;
            if (pickupPresenter == null || arCamera == null)
            {
                return false;
            }

            return pickupPresenter.TryGetNearestVisual(
                arCamera.transform.position,
                out pickup);
        }

#if UNITY_EDITOR
        public void ConfigureForTesting(
            PickupSpawnPresenter presenter,
            CameraRelativeGloveRig rig,
            Camera camera)
        {
            pickupPresenter = presenter;
            gloveRig = rig;
            arCamera = camera;
        }
#endif
    }
}
