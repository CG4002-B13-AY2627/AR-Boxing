using CG4002.Visualizer.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class PickupReachTargetingTests
    {
        [TestCase(0f, true)]
        [TestCase(0.49f, true)]
        [TestCase(0.5f, true)]
        [TestCase(0.51f, false)]
        [TestCase(1f, false)]
        public void AutomaticHandSelection_UsesPickupViewportSide(
            float viewportX,
            bool expectedLeft)
        {
            Assert.That(
                PickupReachTargeting.ShouldUseLeftHand(viewportX),
                Is.EqualTo(expectedLeft));
        }

        [Test]
        public void CurvedPath_ReturnsExactEndpointsAndBowsUpward()
        {
            Vector3 start = new(-0.2f, 1.2f, 0.5f);
            Vector3 end = new(0.1f, 0.3f, 1.1f);

            Assert.That(PickupReachTargeting.EvaluatePath(
                start, end, Vector3.up, Vector3.forward, 0.12f, 0.04f, 0f),
                Is.EqualTo(start));
            Assert.That(PickupReachTargeting.EvaluatePath(
                start, end, Vector3.up, Vector3.forward, 0.12f, 0.04f, 1f),
                Is.EqualTo(end));

            Vector3 directMidpoint = Vector3.Lerp(start, end, 0.5f);
            Vector3 curvedMidpoint = PickupReachTargeting.EvaluatePath(
                start, end, Vector3.up, Vector3.forward, 0.12f, 0.04f, 0.5f);
            Assert.That(curvedMidpoint.y, Is.GreaterThan(directMidpoint.y));
        }

        [Test]
        public void Endpoint_LeavesRequestedStandoff()
        {
            Vector3 start = new(0f, 1f, 0f);
            Vector3 target = new(0f, 1f, 1f);

            Assert.That(PickupReachTargeting.TryGetEndpoint(
                start, target, 0.08f, 2f, 0f, out Vector3 endpoint), Is.True);
            Assert.That(Vector3.Distance(endpoint, target),
                Is.EqualTo(0.08f).Within(0.0001f));
        }

        [Test]
        public void Endpoint_ClampsExcessiveReachDistance()
        {
            Vector3 start = new(0f, 1f, 0f);
            Vector3 target = new(0f, 1f, 4f);

            Assert.That(PickupReachTargeting.TryGetEndpoint(
                start, target, 0.05f, 1.15f, 0f, out Vector3 endpoint), Is.True);
            Assert.That(Vector3.Distance(start, endpoint),
                Is.EqualTo(1.15f).Within(0.0001f));
        }

        [Test]
        public void Endpoint_NeverDropsBelowFloorClearance()
        {
            Vector3 start = new(0f, 1f, 0f);
            Vector3 target = new(0f, 0.05f, 1f);

            Assert.That(PickupReachTargeting.TryGetEndpoint(
                start, target, 0f, 2f, 0.16f, out Vector3 endpoint), Is.True);
            Assert.That(endpoint.y, Is.EqualTo(0.16f).Within(0.0001f));
        }

        [Test]
        public void Endpoint_RejectsNonFiniteTarget()
        {
            Assert.That(PickupReachTargeting.TryGetEndpoint(
                Vector3.zero,
                new Vector3(float.NaN, 0f, 1f),
                0.05f,
                1f,
                0.1f,
                out _), Is.False);
        }
    }
}
