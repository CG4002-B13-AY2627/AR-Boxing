using UnityEngine;

namespace CG4002.Visualizer.AR
{
    /// <summary>
    /// Allocation-free exponential smoothing for an AprilTag world pose.
    /// Kept independent of MonoBehaviour so it can be edit-mode tested.
    /// </summary>
    public sealed class OpponentTargetPoseFilter
    {
        public bool IsInitialized { get; private set; }
        public Pose Current { get; private set; }

        public void Reset(Pose pose)
        {
            Current = pose;
            IsInitialized = true;
        }

        public Pose Step(
            Pose target,
            float deltaTime,
            float positionSharpness,
            float rotationSharpness)
        {
            if (!IsInitialized)
            {
                Reset(target);
                return Current;
            }

            float positionAlpha = SmoothingFactor(positionSharpness, deltaTime);
            float rotationAlpha = SmoothingFactor(rotationSharpness, deltaTime);
            Current = new Pose(
                Vector3.Lerp(Current.position, target.position, positionAlpha),
                Quaternion.Slerp(Current.rotation, target.rotation, rotationAlpha));
            return Current;
        }

        public static float SmoothingFactor(float sharpness, float deltaTime)
        {
            if (sharpness <= 0f || deltaTime <= 0f)
            {
                return 0f;
            }

            return 1f - Mathf.Exp(-sharpness * deltaTime);
        }
    }
}
