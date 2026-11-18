using System;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.UI;
using NUnit.Framework;

namespace CG4002.Visualizer.Tests
{
    public sealed class MatchFlowPlaceholderContentTests
    {
        [Test]
        public void EveryPresentationPhaseHasVisibleCopy()
        {
            foreach (MatchFlowPhase phase in Enum.GetValues(typeof(MatchFlowPhase)))
            {
                MatchFlowPlaceholderCopy copy = MatchFlowPlaceholderContent.For(phase);

                Assert.That(copy.Title, Is.Not.Empty, phase.ToString());
                Assert.That(copy.Hint, Is.Not.Empty, phase.ToString());
            }
        }

        [Test]
        public void FightingUsesCompactPeripheralPresentation()
        {
            MatchFlowPlaceholderCopy copy = MatchFlowPlaceholderContent.For(MatchFlowPhase.Fighting);

            Assert.That(copy.Compact, Is.True);
            Assert.That(copy.Hint, Does.Contain("Pause"));
        }

        [Test]
        public void SafetyStopUsesExplicitStopLanguage()
        {
            MatchFlowPlaceholderCopy copy = MatchFlowPlaceholderContent.For(MatchFlowPhase.SafetyStop);

            Assert.That(copy.Title, Does.Contain("STOP"));
            Assert.That(copy.Detail, Does.Contain("unavailable"));
        }
    }
}
