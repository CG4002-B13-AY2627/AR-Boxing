using CG4002.Visualizer.AR;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    public enum VisualPunchType
    {
        Jab,
        Hook,
        Uppercut
    }

    /// <summary>
    /// Pure target-selection and trajectory helpers for presentation punches.
    /// These functions do not determine whether a punch hit.
    /// </summary>
    public static class PunchTargeting
    {
        public static OpponentTargetZone ResolveTarget(
            bool isLeftGlove,
            VisualPunchType punchType)
        {
            return punchType switch
            {
                VisualPunchType.Jab => isLeftGlove
                    ? OpponentTargetZone.LeftBody
                    : OpponentTargetZone.RightBody,
                VisualPunchType.Hook => OpponentTargetZone.Head,
                VisualPunchType.Uppercut => OpponentTargetZone.Head,
                _ => OpponentTargetZone.Chest
            };
        }

        public static Vector3 StopShortOfTarget(
            Vector3 start,
            Vector3 target,
            float standoffDistance)
        {
            Vector3 targetToStart = start - target;
            float distance = targetToStart.magnitude;
            if (distance <= Mathf.Epsilon)
            {
                return target;
            }

            return target + targetToStart / distance *
                Mathf.Clamp(standoffDistance, 0f, distance);
        }

        public static Vector3 QuadraticBezier(
            Vector3 start,
            Vector3 control,
            Vector3 end,
            float amount)
        {
            float t = Mathf.Clamp01(amount);
            float inverse = 1f - t;
            return inverse * inverse * start +
                   2f * inverse * t * control +
                   t * t * end;
        }

        public static Vector3 CubicBezier(
            Vector3 start,
            Vector3 firstControl,
            Vector3 secondControl,
            Vector3 end,
            float amount)
        {
            float t = Mathf.Clamp01(amount);
            float inverse = 1f - t;
            return inverse * inverse * inverse * start +
                   3f * inverse * inverse * t * firstControl +
                   3f * inverse * t * t * secondControl +
                   t * t * t * end;
        }

        public static Vector3 StraightLine(
            Vector3 start,
            Vector3 end,
            float amount)
        {
            return Vector3.Lerp(start, end, Mathf.Clamp01(amount));
        }

        /// <summary>
        /// Moves the knuckle contact point along a straight line and solves the
        /// root pose around it. contactOffset is in root-oriented metres (scale
        /// already applied); strikeAxis is the root-local wrist-to-knuckle axis.
        /// amount is extension, 0 at rest and 1 at impact, then back to 0.
        /// </summary>
        public static Pose JabPose(
            Vector3 restingRootPosition,
            Quaternion restingRootRotation,
            Vector3 contactOffset,
            Vector3 strikeAxis,
            Vector3 target,
            float standoffDistance,
            float amount,
            float rotationCompleteAtExtension = 0.65f,
            float localYawDegrees = 0f)
        {
            float extension = Mathf.Clamp01(amount);
            Vector3 startContact = restingRootPosition + restingRootRotation * contactOffset;
            Vector3 direction = target - startContact;
            Quaternion aimedRotation = restingRootRotation;
            if (direction.sqrMagnitude > 0.000001f && strikeAxis.sqrMagnitude > 0.000001f)
            {
                aimedRotation = Quaternion.FromToRotation(
                    restingRootRotation * strikeAxis.normalized,
                    direction.normalized) * restingRootRotation;
            }

            float turn = Mathf.Clamp01(extension /
                Mathf.Clamp(rotationCompleteAtExtension, 0.05f, 1f));
            Quaternion rotation = Quaternion.Slerp(
                restingRootRotation, aimedRotation, Mathf.SmoothStep(0f, 1f, turn));
            // Post-multiply to twist around the glove root's local green Y axis.
            // Twist follows extension and unwinds on retraction. Apply it before
            // solving the root position so the knuckle point stays on its line.
            rotation *= LocalYawRotation(localYawDegrees, extension);
            Vector3 endContact = StopShortOfTarget(startContact, target, standoffDistance);
            Vector3 contact = StraightLine(startContact, endContact, extension);

            // Contact = root + rotated offset, so solve for the root.
            return new Pose(contact - rotation * contactOffset, rotation);
        }

        /// <summary>
        /// Produces a broad hook whose added curvature lies in the supplied
        /// right/up plane while its base chord still advances to the target.
        /// </summary>
        public static Vector3 HookArc(
            Vector3 start,
            Vector3 end,
            Vector3 cameraRight,
            Vector3 cameraUp,
            float outwardSign,
            float horizontalRadius,
            float verticalLift,
            float amount)
        {
            Vector3 outward = cameraRight.normalized *
                Mathf.Sign(outwardSign) * Mathf.Max(0f, horizontalRadius);
            Vector3 upward = cameraUp.normalized * Mathf.Max(0f, verticalLift);
            Vector3 firstControl = Vector3.Lerp(start, end, 0.20f) +
                outward + upward;
            Vector3 secondControl = Vector3.Lerp(start, end, 0.72f) +
                outward + upward * 0.65f;

            return CubicBezier(
                start,
                firstControl,
                secondControl,
                end,
                amount);
        }

        public static Quaternion ProgressRotation(
            Vector3 peakEuler,
            float amount)
        {
            return Quaternion.Slerp(
                Quaternion.identity,
                Quaternion.Euler(peakEuler),
                Mathf.Clamp01(amount));
        }

        /// <summary>
        /// A signed twist about local Y, eased by extension rather than elapsed
        /// time so the same rotation unwinds as the hand retracts. Post-multiply
        /// the resting/aimed rotation by this to keep the axis glove-relative.
        /// </summary>
        public static Quaternion LocalYawRotation(float degrees, float amount)
        {
            return Quaternion.AngleAxis(
                degrees * Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(amount)),
                Vector3.up);
        }

        public static Vector3 GuardPositionOffset(
            bool isLeft, float inwardDistance, float height, float towardCameraDistance,
            float restingDepth, float minimumDepth, float amount)
        {
            float progress = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(amount));
            float pull = Mathf.Clamp(towardCameraDistance, 0f,
                Mathf.Max(0f, restingDepth - minimumDepth));
            return new Vector3((isLeft ? 1f : -1f) * Mathf.Max(0f, inwardDistance),
                Mathf.Max(0f, height), -pull) * progress;
        }

        /// <summary>
        /// Uppercuts keep the upright resting pose by default. Optional pitch
        /// is separate from the local-Y twist; no implicit roll is added.
        /// </summary>
        public static Quaternion UppercutRotation(
            float localYawDegrees, float pitchDegrees, float amount)
        {
            float progress = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(amount));
            Quaternion pitch = Quaternion.AngleAxis(pitchDegrees * progress, Vector3.right);
            return pitch * LocalYawRotation(localYawDegrees, amount);
        }
    }
}
