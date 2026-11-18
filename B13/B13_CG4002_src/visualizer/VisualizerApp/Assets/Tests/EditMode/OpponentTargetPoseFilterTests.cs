using CG4002.Visualizer.AR;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class OpponentTargetPoseFilterTests
    {
        [Test]
        public void Reset_UsesPoseExactly()
        {
            var filter = new OpponentTargetPoseFilter();
            var pose = new Pose(
                new Vector3(1f, 2f, 3f),
                Quaternion.Euler(10f, 20f, 30f));

            filter.Reset(pose);

            Assert.That(filter.IsInitialized, Is.True);
            Assert.That(Vector3.Distance(filter.Current.position, pose.position), Is.LessThan(0.0001f));
            Assert.That(Quaternion.Angle(filter.Current.rotation, pose.rotation), Is.LessThan(0.0001f));
        }

        [Test]
        public void Step_MovesTowardTargetWithoutOvershooting()
        {
            var filter = new OpponentTargetPoseFilter();
            filter.Reset(new Pose(Vector3.zero, Quaternion.identity));
            var target = new Pose(
                new Vector3(10f, 0f, 0f),
                Quaternion.Euler(0f, 90f, 0f));

            Pose result = filter.Step(target, 0.1f, 10f, 10f);

            Assert.That(result.position.x, Is.GreaterThan(0f).And.LessThan(10f));
            Assert.That(
                Quaternion.Angle(Quaternion.identity, result.rotation),
                Is.GreaterThan(0f).And.LessThan(90f));
        }

        [TestCase(10f, 0f)]
        [TestCase(0f, 0.1f)]
        [TestCase(-1f, 0.1f)]
        public void SmoothingFactor_InvalidInput_ReturnsZero(
            float sharpness,
            float deltaTime)
        {
            Assert.That(
                OpponentTargetPoseFilter.SmoothingFactor(sharpness, deltaTime),
                Is.EqualTo(0f));
        }
    }
}
