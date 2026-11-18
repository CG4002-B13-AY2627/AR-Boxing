using CG4002.Visualizer.AR;
using CG4002.Visualizer.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class PunchTargetingTests
    {
        [TestCase(-60f, 0f)]
        [TestCase(-60f, 0.5f)]
        [TestCase(-60f, 1f)]
        [TestCase(60f, 1f)]
        public void JabPose_LocalYawTwistsHandWithoutMovingKnucklePath(float yaw, float extension)
        {
            Vector3 root = new(0.3f, -0.2f, 0.6f);
            Quaternion rest = Quaternion.Euler(10f, -20f, 10f);
            // Off-axis contact makes this catch missing pivot compensation.
            Vector3 offset = new(0.04f, 0.12f, 0.02f);
            Vector3 target = new(0.18f, 0f, 1.4f);
            Pose untwisted = PunchTargeting.JabPose(root, rest, offset, Vector3.up,
                target, 0.08f, extension);
            Pose twisted = PunchTargeting.JabPose(root, rest, offset, Vector3.up,
                target, 0.08f, extension, 0.65f, yaw);
            Assert.That(Vector3.Distance(
                twisted.position + twisted.rotation * offset,
                untwisted.position + untwisted.rotation * offset), Is.LessThan(0.00001f));
            Quaternion expected = untwisted.rotation * Quaternion.AngleAxis(
                yaw * Mathf.SmoothStep(0f, 1f, extension), Vector3.up);
            Assert.That(Quaternion.Angle(twisted.rotation, expected), Is.LessThan(0.05f));
            Assert.That(Vector3.Angle(twisted.rotation * Vector3.up,
                untwisted.rotation * Vector3.up), Is.LessThan(0.05f));
        }

        [TestCase(0f)]
        [TestCase(0.25f)]
        [TestCase(0.65f)]
        [TestCase(1f)]
        public void JabPose_KnucklesFollowStraightPathWhileRootRotates(float extension)
        {
            Vector3 root = new(-0.3f, -0.2f, 0.6f);
            Quaternion rotation = Quaternion.Euler(10f, 20f, -10f);
            Vector3 offset = new(0.02f, 0.16f, -0.01f);
            Vector3 target = new(-0.18f, 0f, 1.4f);
            Pose pose = PunchTargeting.JabPose(root, rotation, offset, Vector3.up,
                target, 0.08f, extension);
            Vector3 start = root + rotation * offset;
            Vector3 expected = Vector3.Lerp(start,
                PunchTargeting.StopShortOfTarget(start, target, 0.08f), extension);
            Assert.That(Vector3.Distance(pose.position + pose.rotation * offset, expected),
                Is.LessThan(0.00001f));
            if (extension == 0f)
            {
                Assert.That(Vector3.Distance(pose.position, root), Is.LessThan(0.00001f));
                Assert.That(Quaternion.Angle(pose.rotation, rotation), Is.LessThan(0.01f));
            }
            if (extension >= 0.65f)
            {
                Assert.That(Vector3.Angle(pose.rotation * Vector3.up, target - start),
                    Is.LessThan(0.05f));
            }
        }

        [Test]
        public void JabPose_CoincidentContactAndTargetRemainsFinite()
        {
            Vector3 offset = Vector3.up * 0.12f;
            Pose pose = PunchTargeting.JabPose(Vector3.zero, Quaternion.identity,
                offset, Vector3.zero, offset, 0.08f, 1f);
            Assert.That(pose.position, Is.EqualTo(Vector3.zero));
            Assert.That(pose.rotation, Is.EqualTo(Quaternion.identity));
        }

        [TestCase(true, VisualPunchType.Jab, OpponentTargetZone.LeftBody)]
        [TestCase(false, VisualPunchType.Jab, OpponentTargetZone.RightBody)]
        [TestCase(true, VisualPunchType.Hook, OpponentTargetZone.Head)]
        [TestCase(false, VisualPunchType.Hook, OpponentTargetZone.Head)]
        [TestCase(true, VisualPunchType.Uppercut, OpponentTargetZone.Head)]
        [TestCase(false, VisualPunchType.Uppercut, OpponentTargetZone.Head)]
        public void ResolveTarget_UsesExpectedZone(
            bool isLeftGlove,
            VisualPunchType punchType,
            OpponentTargetZone expected)
        {
            Assert.That(
                PunchTargeting.ResolveTarget(isLeftGlove, punchType),
                Is.EqualTo(expected));
        }

        [Test]
        public void QuadraticBezier_ReturnsExactEndpoints()
        {
            Vector3 start = new(-1f, 0f, 0f);
            Vector3 control = new(0f, 1f, 0f);
            Vector3 end = new(1f, 0f, 0f);

            Assert.That(
                Vector3.Distance(
                    PunchTargeting.QuadraticBezier(start, control, end, 0f),
                    start),
                Is.LessThan(0.0001f));
            Assert.That(
                Vector3.Distance(
                    PunchTargeting.QuadraticBezier(start, control, end, 1f),
                    end),
                Is.LessThan(0.0001f));
        }

        [Test]
        public void StopShortOfTarget_LeavesRequestedGap()
        {
            Vector3 start = Vector3.zero;
            Vector3 target = new(0f, 0f, 2f);

            Vector3 endpoint = PunchTargeting.StopShortOfTarget(
                start,
                target,
                0.1f);

            Assert.That(Vector3.Distance(endpoint, target), Is.EqualTo(0.1f).Within(0.0001f));
            Assert.That(endpoint.z, Is.LessThan(target.z));
        }

        [Test]
        public void StraightLine_MidpointStaysOnDirectPath()
        {
            Vector3 start = new(-1f, 2f, 0f);
            Vector3 end = new(1f, 4f, 2f);

            Vector3 midpoint = PunchTargeting.StraightLine(start, end, 0.5f);

            Assert.That(
                Vector3.Distance(midpoint, (start + end) * 0.5f),
                Is.LessThan(0.0001f));
        }

        [Test]
        public void CubicBezier_ReturnsExactEndpoints()
        {
            Vector3 start = Vector3.zero;
            Vector3 firstControl = new(1f, 1f, 0f);
            Vector3 secondControl = new(2f, 1f, 0f);
            Vector3 end = new(3f, 0f, 0f);

            Assert.That(
                Vector3.Distance(
                    PunchTargeting.CubicBezier(
                        start,
                        firstControl,
                        secondControl,
                        end,
                        0f),
                    start),
                Is.LessThan(0.0001f));
            Assert.That(
                Vector3.Distance(
                    PunchTargeting.CubicBezier(
                        start,
                        firstControl,
                        secondControl,
                        end,
                        1f),
                    end),
                Is.LessThan(0.0001f));
        }

        [Test]
        public void HookArc_BowsOutwardAndUpInCameraPlane()
        {
            Vector3 start = Vector3.zero;
            Vector3 end = new(0f, 0f, 2f);

            Vector3 midpoint = PunchTargeting.HookArc(
                start,
                end,
                Vector3.right,
                Vector3.up,
                -1f,
                0.2f,
                0.1f,
                0.5f);

            Assert.That(midpoint.x, Is.LessThan(0f));
            Assert.That(midpoint.y, Is.GreaterThan(0f));
            Assert.That(midpoint.z, Is.GreaterThan(0f).And.LessThan(2f));
        }

        [Test]
        public void HookArc_LeftAndRightAreMirrored()
        {
            Vector3 start = Vector3.zero;
            Vector3 end = new(0f, 0f, 2f);

            Vector3 left = PunchTargeting.HookArc(
                start, end, Vector3.right, Vector3.up,
                -1f, 0.2f, 0.1f, 0.5f);
            Vector3 right = PunchTargeting.HookArc(
                start, end, Vector3.right, Vector3.up,
                1f, 0.2f, 0.1f, 0.5f);

            Assert.That(left.x, Is.EqualTo(-right.x).Within(0.0001f));
            Assert.That(left.y, Is.EqualTo(right.y).Within(0.0001f));
            Assert.That(left.z, Is.EqualTo(right.z).Within(0.0001f));
        }

        [Test]
        public void ProgressRotation_StartsAtIdentityAndReachesPeak()
        {
            Vector3 peakEuler = new(-60f, 65f, -16f);

            Quaternion start = PunchTargeting.ProgressRotation(peakEuler, 0f);
            Quaternion end = PunchTargeting.ProgressRotation(peakEuler, 1f);

            Assert.That(
                Quaternion.Angle(start, Quaternion.identity),
                Is.LessThan(0.0001f));
            Assert.That(
                Quaternion.Angle(end, Quaternion.Euler(peakEuler)),
                Is.LessThan(0.0001f));
        }

        [TestCase(-90f, 0f)]
        [TestCase(-90f, 0.25f)]
        [TestCase(-90f, 0.5f)]
        [TestCase(-90f, 1f)]
        [TestCase(90f, 1f)]
        [TestCase(0f, 1f)]
        [TestCase(90f, -1f)]
        [TestCase(90f, 2f)]
        public void UppercutRotation_UsesSignedLocalYawWithoutTippingWrist(float yaw, float amount)
        {
            Quaternion rest = Quaternion.Euler(10f, -20f, 10f);
            Quaternion offset = PunchTargeting.UppercutRotation(yaw, 0f, amount);
            Quaternion expected = Quaternion.AngleAxis(
                yaw * Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(amount)), Vector3.up);
            Assert.That(Quaternion.Angle(offset, expected), Is.LessThan(0.05f));
            Assert.That(Vector3.Angle(rest * offset * Vector3.up, rest * Vector3.up),
                Is.LessThan(0.05f));
        }

        [Test]
        public void UppercutRotation_OptionalPitchIsSeparateFromLocalYaw()
        {
            Quaternion expected = Quaternion.AngleAxis(-20f, Vector3.right) *
                Quaternion.AngleAxis(90f, Vector3.up);
            Quaternion actual = PunchTargeting.UppercutRotation(90f, -20f, 1f);
            Assert.That(Quaternion.Angle(actual, expected), Is.LessThan(0.05f));
            Assert.That(Quaternion.Angle(PunchTargeting.UppercutRotation(90f, -20f, 0f),
                Quaternion.identity), Is.LessThan(0.05f));
        }

        [Test]
        public void UppercutRotation_UnwindsAsExtensionFalls()
        {
            // Both halves of the animation use extension 0 -> 1 -> 0.
            float[] extensions = { 0f, 0.5f, 1f, 0.5f, 0f };
            float[] angles = { 0f, 45f, 90f, 45f, 0f };
            for (int i = 0; i < extensions.Length; i++)
            {
                Quaternion rotation = PunchTargeting.UppercutRotation(90f, 0f, extensions[i]);
                Assert.That(Quaternion.Angle(Quaternion.identity, rotation),
                    Is.EqualTo(angles[i]).Within(0.05f));
            }
        }
    }
}
