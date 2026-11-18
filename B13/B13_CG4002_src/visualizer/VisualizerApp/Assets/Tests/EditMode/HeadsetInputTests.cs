using CG4002.Visualizer.Game;
using CG4002.Visualizer.Input;
using CG4002.Visualizer.UI;
using NUnit.Framework;

namespace CG4002.Visualizer.Tests
{
    public sealed class HeadsetInputTests
    {
        [Test]
        public void DebouncerAcceptsFirstAction()
        {
            HeadsetActionDebouncer debouncer = new(0.35f);

            Assert.That(debouncer.TryAccept(10f), Is.True);
        }

        [Test]
        public void DebouncerRejectsActionInsideCooldown()
        {
            HeadsetActionDebouncer debouncer = new(0.35f);
            debouncer.TryAccept(10f);

            Assert.That(debouncer.TryAccept(10.2f), Is.False);
            Assert.That(debouncer.TryAccept(10.35f), Is.True);
        }

        [Test]
        public void DebouncerResetsIfClockMovesBackwards()
        {
            HeadsetActionDebouncer debouncer = new(0.35f);
            debouncer.TryAccept(10f);

            Assert.That(debouncer.TryAccept(1f), Is.True);
        }

        [Test]
        public void DebugCycleMovesForwardAndBackward()
        {
            Assert.That(
                MatchFlowDebugPhaseCycle.Step(MatchFlowPhase.Lobby, 1),
                Is.EqualTo(MatchFlowPhase.Calibrating));
            Assert.That(
                MatchFlowDebugPhaseCycle.Step(MatchFlowPhase.Lobby, -1),
                Is.EqualTo(MatchFlowPhase.Connecting));
        }

        [Test]
        public void DebugCycleWrapsAtBothEnds()
        {
            Assert.That(
                MatchFlowDebugPhaseCycle.Step(MatchFlowPhase.Connecting, -1),
                Is.EqualTo(MatchFlowPhase.SafetyStop));
            Assert.That(
                MatchFlowDebugPhaseCycle.Step(MatchFlowPhase.SafetyStop, 1),
                Is.EqualTo(MatchFlowPhase.Connecting));
        }
    }
}
