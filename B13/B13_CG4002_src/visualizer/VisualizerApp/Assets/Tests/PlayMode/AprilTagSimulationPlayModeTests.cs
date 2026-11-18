using System.Collections;
using CG4002.Visualizer.AR;
using CG4002.Visualizer.Development;
using CG4002.Visualizer.Game;
using CG4002.Visualizer.Models;
using CG4002.Visualizer.Networking;
using CG4002.Visualizer.Presentation;
using CG4002.Visualizer.UI;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace CG4002.Visualizer.Tests
{
    public sealed class AprilTagSimulationPlayModeTests
    {
        [TearDown]
        public void TearDown()
        {
            Time.timeScale = 1f;
        }

        [UnityTest]
        public IEnumerator MainScene_NavigatesAndRendersHealthPickupFromDebugState()
        {
            AsyncOperation load = SceneManager.LoadSceneAsync("Main", LoadSceneMode.Single);
            while (!load.isDone)
            {
                yield return null;
            }

            AprilTagOpponentTracker tracker =
                Object.FindFirstObjectByType<AprilTagOpponentTracker>();
            FloorPlaneProvider floor = Object.FindFirstObjectByType<FloorPlaneProvider>();
            PickupSpawnPresenter presenter =
                Object.FindFirstObjectByType<PickupSpawnPresenter>();
            PickupReachPresenter reach = Object.FindFirstObjectByType<PickupReachPresenter>();
            PickupCollectionPresenter collection =
                Object.FindFirstObjectByType<PickupCollectionPresenter>();
            CameraRelativeGloveRig gloveRig =
                Object.FindFirstObjectByType<CameraRelativeGloveRig>();
            HudToastPresenter toast = Object.FindFirstObjectByType<HudToastPresenter>();
            MockGameEventSource source = Object.FindFirstObjectByType<MockGameEventSource>(
                FindObjectsInactive.Include);
            GameNetworkClient network = Object.FindFirstObjectByType<GameNetworkClient>();
            MatchController controller = Object.FindFirstObjectByType<MatchController>();
            Camera camera = Camera.main;
            Assert.That(tracker, Is.Not.Null);
            Assert.That(floor, Is.Not.Null);
            Assert.That(presenter, Is.Not.Null);
            Assert.That(reach, Is.Not.Null);
            Assert.That(collection, Is.Not.Null);
            Assert.That(gloveRig, Is.Not.Null);
            Assert.That(toast, Is.Not.Null);
            Assert.That(source, Is.Not.Null);
            Assert.That(network, Is.Not.Null);
            Assert.That(controller, Is.Not.Null);
            Assert.That(camera, Is.Not.Null);

            // Keep this deterministic even when the developer's serialized localhost
            // endpoint is live. Development injection still uses the client's main-thread queue.
            network.enabled = false;
            while (network.TryDequeue(out _))
            {
            }

            float tagDeadline = Time.realtimeSinceStartup + 12f;
            while (!tracker.HasValidTarget && Time.realtimeSinceStartup < tagDeadline)
            {
                yield return null;
            }

            Assert.That(tracker.TargetTagId, Is.EqualTo(0));
            Assert.That(tracker.HasValidTarget, Is.True,
                "The real WP1 detector did not acquire the virtual ID 0 marker.");

            // The batch runner has no interactive Game view and does not return simulation
            // planes reliably. This editor-only hook tests the remaining protocol-to-visual
            // path; interactive validation still uses the real ARPlaneManager.
            floor.SetSyntheticFloorForTesting(
                new Pose(
                    new Vector3(
                        camera.transform.position.x,
                        camera.transform.position.y - 1.6f,
                        camera.transform.position.z),
                    Quaternion.identity),
                new Vector2(8f, 8f),
                camera);

            source.EmitHealthPickupCentre();
            float spawnDeadline = Time.realtimeSinceStartup + 3f;
            while ((presenter.ActiveVisualCount == 0 || !toast.IsVisible) &&
                   Time.realtimeSinceStartup < spawnDeadline)
            {
                yield return null;
            }

            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(1));
            Assert.That(toast.IsVisible, Is.True);
            Assert.That(toast.CurrentItemId, Is.EqualTo("health-debug-centre"));
            Assert.That(toast.SeenItemCountForTesting, Is.EqualTo(1));
            Assert.That(presenter.PendingItemCount, Is.Zero);
            Assert.That(presenter.TryGetVisualPoseForTesting(
                "health-debug-centre",
                out Pose firstPose), Is.True);

            source.EmitHealthPickupCentre();
            yield return null;
            yield return null;
            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(1),
                "A repeated state for the same authoritative ID created a duplicate visual.");
            Assert.That(toast.SeenItemCountForTesting, Is.EqualTo(1),
                "A repeated state for the same authoritative ID queued another toast.");
            Assert.That(toast.PendingNotificationCount, Is.Zero);
            Assert.That(presenter.TryGetVisualPoseForTesting(
                "health-debug-centre",
                out Pose repeatedPose), Is.True);
            Assert.That(repeatedPose.position, Is.EqualTo(firstPose.position));

            Assert.That(reach.TryReachAutomatic(), Is.True);
            bool automaticHand = reach.LastReachUsedLeftHand;
            Assert.That(gloveRig.IsPickupReachActive(automaticHand), Is.True);

            Time.timeScale = 0f;
            source.ClearHealthPickups();
            float toastDeadline = Time.realtimeSinceStartup + 3f;
            while ((toast.IsVisible || gloveRig.IsPickupReachActive(automaticHand) ||
                    presenter.ActiveVisualCount != 0) &&
                   Time.realtimeSinceStartup < toastDeadline)
            {
                yield return null;
            }

            Assert.That(toast.IsVisible, Is.False,
                "The spawn toast did not finish while scaled game time was paused.");
            Assert.That(presenter.ActiveVisualCount, Is.Zero,
                "Clearing the pickup did not remove its visual during the reach.");
            Assert.That(gloveRig.IsPickupReachActive(automaticHand), Is.False,
                "The pickup reach did not finish after its target visual disappeared.");
            Assert.That(gloveRig.TryGetGlovePoseForTesting(
                automaticHand,
                out Pose returnedPose), Is.True);
            Assert.That(Vector3.Distance(
                returnedPose.position,
                gloveRig.GetRestingPositionForTesting(automaticHand)),
                Is.LessThan(0.01f));
            Time.timeScale = 1f;

            toast.enabled = false;
            int seenBeforeDisable = toast.SeenItemCountForTesting;
            source.EmitHealthPickupRight();
            float rightSpawnDeadline = Time.realtimeSinceStartup + 2f;
            while (presenter.ActiveVisualCount == 0 &&
                   Time.realtimeSinceStartup < rightSpawnDeadline)
            {
                yield return null;
            }
            Assert.That(toast.SeenItemCountForTesting, Is.EqualTo(seenBeforeDisable),
                "The disabled toast presenter remained subscribed to state updates.");

            gloveRig.Guard();
            yield return null;
            yield return null;
            Assert.That(reach.TryReachRight(), Is.True,
                "A pickup reach could not interrupt guard.");
            Assert.That(gloveRig.IsPickupReachActive(false), Is.True);
            yield return null;
            yield return null;
            gloveRig.RightJab();
            Assert.That(gloveRig.IsPickupReachActive(false), Is.False,
                "A punch did not cancel the pickup reach.");

            float returnDeadline = Time.realtimeSinceStartup + 2f;
            while (Time.realtimeSinceStartup < returnDeadline)
            {
                yield return null;
                if (gloveRig.TryGetGlovePoseForTesting(false, out Pose rightPose) &&
                    Vector3.Distance(
                        rightPose.position,
                        gloveRig.GetRestingPositionForTesting(false)) < 0.01f)
                {
                    break;
                }
            }

            Assert.That(gloveRig.TryGetGlovePoseForTesting(false, out Pose finalRight), Is.True);
            Assert.That(Vector3.Distance(
                finalRight.position,
                gloveRig.GetRestingPositionForTesting(false)),
                Is.LessThan(0.01f));

            source.ClearHealthPickups();
            float clearDeadline = Time.realtimeSinceStartup + 2f;
            while (presenter.ActiveVisualCount != 0 &&
                   Time.realtimeSinceStartup < clearDeadline)
            {
                yield return null;
            }

            Assert.That(presenter.ActiveVisualCount, Is.Zero);

            // WP6: the debug command is camera-range-gated, while health and
            // removal are still applied only by the newer authoritative state.
            toast.enabled = true;
            source.SetPlayerHealthForTesting(60f);
            source.EmitHealthPickupCentre();
            float collectionSpawnDeadline = Time.realtimeSinceStartup + 2f;
            while ((presenter.ActiveVisualCount == 0 ||
                    controller.Current.PlayerOneHealth != 60f) &&
                   Time.realtimeSinceStartup < collectionSpawnDeadline)
            {
                yield return null;
            }

            Assert.That(controller.Current.PlayerOneHealth, Is.EqualTo(60f));
            Assert.That(collection.MaximumDebugPickupDistanceMetres,
                Is.EqualTo(2f).Within(0.001f));
            collection.SetMaximumDistanceForTesting(0.5f);
            Assert.That(collection.TryCollectNearestHealthForDebug(), Is.False,
                "A pickup outside the adjustable debug range was accepted.");
            yield return null;
            Assert.That(controller.Current.PlayerOneHealth, Is.EqualTo(60f),
                "A rejected local collection changed authoritative health.");
            Assert.That(presenter.ActiveVisualCount, Is.EqualTo(1));

            collection.SetMaximumDistanceForTesting(2f);
            int acceptedBefore = controller.AcceptedPayloadCount;
            Assert.That(collection.TryCollectNearestHealthForDebug(), Is.True);
            yield return null;
            Assert.That(
                gloveRig.IsPickupReachActive(true) ||
                gloveRig.IsPickupReachActive(false),
                Is.True,
                "The accepted pickup skipped the glove reach animation.");
            float collectionDeadline = Time.realtimeSinceStartup + 4f;
            while ((controller.Current.PlayerOneHealth != 85f ||
                    presenter.ActiveVisualCount != 0 ||
                    collection.PresentedCollectionCount == 0) &&
                   Time.realtimeSinceStartup < collectionDeadline)
            {
                yield return null;
            }

            Assert.That(controller.Current.PlayerOneHealth, Is.EqualTo(85f));
            Assert.That(controller.AcceptedPayloadCount,
                Is.GreaterThanOrEqualTo(acceptedBefore + 2),
                "The accepted ITEM_PICKUP and following MatchState did not both pass through the production queue.");
            Assert.That(presenter.ActiveVisualCount, Is.Zero);
            Assert.That(collection.TryCollectNearestHealthForDebug(), Is.False,
                "The same pickup could be collected twice after authoritative removal.");

            // Health is capped by the simulated authority before the newer state
            // reaches the client; the presenter never applies +25 itself.
            source.SetPlayerHealthForTesting(90f);
            source.EmitHealthPickupLeft();
            float fullHealthSpawnDeadline = Time.realtimeSinceStartup + 2f;
            while ((presenter.ActiveVisualCount == 0 ||
                    controller.Current.PlayerOneHealth != 90f) &&
                   Time.realtimeSinceStartup < fullHealthSpawnDeadline)
            {
                yield return null;
            }

            Assert.That(collection.TryCollectNearestHealthForDebug(), Is.True);
            float fullHealthDeadline = Time.realtimeSinceStartup + 4f;
            while ((controller.Current.PlayerOneHealth != 100f ||
                    presenter.ActiveVisualCount != 0) &&
                   Time.realtimeSinceStartup < fullHealthDeadline)
            {
                yield return null;
            }

            Assert.That(controller.Current.PlayerOneHealth, Is.EqualTo(100f));
            Assert.That(presenter.ActiveVisualCount, Is.Zero);

            // State-before-event ordering: retain a just-removed visual briefly so
            // a delayed transient event can still drive contact and collection FX.
            source.EmitHealthPickupRight();
            float raceSpawnDeadline = Time.realtimeSinceStartup + 2f;
            while (presenter.ActiveVisualCount == 0 &&
                   Time.realtimeSinceStartup < raceSpawnDeadline)
            {
                yield return null;
            }

            source.ClearHealthPickups();
            yield return null;
            yield return null;
            Assert.That(presenter.TryGetVisual(
                "health-debug-right", out PickupVisual retiringVisual), Is.True,
                "The removal grace did not retain the visual for a delayed pickup event.");
            Assert.That(retiringVisual.IsRetiring, Is.True);
            int presentedBeforeRace = collection.PresentedCollectionCount;
            collection.ApplyEventForTesting(new GameEventMessage
            {
                type = "GameEvent",
                seq = 99999,
                timestamp = 100,
                @event = "ITEM_PICKUP",
                source_player = 1,
                target_player = 1,
                punch = string.Empty,
                confidence = 1f,
                intensity = 0f,
                outcome = "NONE",
                item_id = "health-debug-right",
                item_type = "HEALTH",
                hand = "RIGHT"
            });

            float raceDeadline = Time.realtimeSinceStartup + 3f;
            while ((presenter.ActiveVisualCount != 0 ||
                    collection.PresentedCollectionCount == presentedBeforeRace) &&
                   Time.realtimeSinceStartup < raceDeadline)
            {
                yield return null;
            }

            Assert.That(collection.PresentedCollectionCount,
                Is.EqualTo(presentedBeforeRace + 1));
            Assert.That(presenter.ActiveVisualCount, Is.Zero);
        }
    }
}
