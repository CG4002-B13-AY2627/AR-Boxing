using System.Collections.Generic;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Networking;
using NUnit.Framework;

namespace CG4002.Visualizer.Tests
{
    public sealed class MatchFlowRouterTests
    {
        private static IEnumerable<TestCaseData> AuthoritativeStates()
        {
            yield return new TestCaseData("LOBBY", MatchFlowPhase.Lobby);
            yield return new TestCaseData("CALIBRATING", MatchFlowPhase.Calibrating);
            yield return new TestCaseData("COUNTDOWN", MatchFlowPhase.Countdown);
            yield return new TestCaseData("FIGHTING", MatchFlowPhase.Fighting);
            yield return new TestCaseData("PAUSED", MatchFlowPhase.Paused);
            yield return new TestCaseData("ROUND_END", MatchFlowPhase.RoundEnd);
            yield return new TestCaseData("MATCH_END", MatchFlowPhase.MatchEnd);
        }

        [TestCaseSource(nameof(AuthoritativeStates))]
        public void RoutesEveryKnownAuthoritativeState(string state, MatchFlowPhase expected)
        {
            MatchFlowRouter router = new();

            MatchFlowRoute route = router.Route(state, ConnectionStatus.Connected);

            Assert.That(route.Current, Is.EqualTo(expected));
            Assert.That(route.AuthoritativeStateRecognized, Is.True);
        }

        [Test]
        public void ParserIgnoresCaseAndSurroundingWhitespace()
        {
            bool success = MatchFlowRouter.TryParseAuthoritativeState(
                "  fighting  ",
                out MatchFlowPhase phase);

            Assert.That(success, Is.True);
            Assert.That(phase, Is.EqualTo(MatchFlowPhase.Fighting));
        }

        [Test]
        public void UnknownAuthoritativeStateFailsToSafetyStop()
        {
            MatchFlowRouter router = new();

            MatchFlowRoute route = router.Route("SUDDEN_DEATH", ConnectionStatus.Connected);

            Assert.That(route.Current, Is.EqualTo(MatchFlowPhase.SafetyStop));
            Assert.That(route.AuthoritativeStateRecognized, Is.False);
        }

        [Test]
        public void AcceptsDirectKnownStateJumpForReconnectConvergence()
        {
            MatchFlowRouter router = new();
            router.Route("LOBBY", ConnectionStatus.Connected);

            MatchFlowRoute route = router.Route("MATCH_END", ConnectionStatus.Connected);

            Assert.That(route.Previous, Is.EqualTo(MatchFlowPhase.Lobby));
            Assert.That(route.Current, Is.EqualTo(MatchFlowPhase.MatchEnd));
            Assert.That(route.Changed, Is.True);
        }

        [Test]
        public void RepeatingCurrentStateDoesNotPublishAChange()
        {
            MatchFlowRouter router = new();
            router.Route("PAUSED", ConnectionStatus.Connected);

            MatchFlowRoute route = router.Route("PAUSED", ConnectionStatus.Connected);

            Assert.That(route.Changed, Is.False);
        }

        [Test]
        public void ReconnectingDuringFightFailsToSafetyStop()
        {
            MatchFlowRouter router = new();
            router.Route("FIGHTING", ConnectionStatus.Connected);

            MatchFlowRoute route = router.Route("FIGHTING", ConnectionStatus.Reconnecting);

            Assert.That(route.Current, Is.EqualTo(MatchFlowPhase.SafetyStop));
        }

        [Test]
        public void ConnectedSnapshotRestoresPhaseAfterSafetyStop()
        {
            MatchFlowRouter router = new();
            router.Route("FIGHTING", ConnectionStatus.Connected);
            router.Route("FIGHTING", ConnectionStatus.Reconnecting);

            MatchFlowRoute route = router.Route("PAUSED", ConnectionStatus.Connected);

            Assert.That(route.Previous, Is.EqualTo(MatchFlowPhase.SafetyStop));
            Assert.That(route.Current, Is.EqualTo(MatchFlowPhase.Paused));
        }

        [Test]
        public void InitialDisconnectedStateRemainsConnecting()
        {
            MatchFlowRouter router = new();

            MatchFlowRoute route = router.Route("LOBBY", ConnectionStatus.Disconnected);

            Assert.That(route.Current, Is.EqualTo(MatchFlowPhase.Connecting));
            Assert.That(route.Changed, Is.False);
        }
    }
}
