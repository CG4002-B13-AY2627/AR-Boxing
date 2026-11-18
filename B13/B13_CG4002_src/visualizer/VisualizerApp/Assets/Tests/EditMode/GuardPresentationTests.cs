using System.Reflection;
using CG4002.Visualizer.Presentation;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class GuardPresentationTests
    {
        private GameObject root;
        private Material material;
        private Renderer left;
        private Renderer right;
        private CameraRelativeGloveRig rig;

        [SetUp]
        public void SetUp()
        {
            root = new GameObject("Guard test rig");
            material = new Material(Shader.Find("Standard"));
            material.SetFloat("_Mode", 2f);
            material.color = new Color(0.8f, 0.2f, 0.1f, 0.8f);
            left = CreateHand("Left");
            right = CreateHand("Right");
            var cameraObject = new GameObject("Camera");
            cameraObject.transform.SetParent(root.transform);
            Camera camera = cameraObject.AddComponent<Camera>();
            camera.nearClipPlane = 0.1f;
            rig = root.AddComponent<CameraRelativeGloveRig>();
            SetField("arCamera", camera);
            SetField("leftGlove", left.transform);
            SetField("rightGlove", right.transform);
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(root);
            Object.DestroyImmediate(material);
        }

        private Renderer CreateHand(string name)
        {
            var hand = new GameObject(name);
            hand.transform.SetParent(root.transform);
            Renderer renderer = hand.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            return renderer;
        }

        private void SetField(string name, object value) => typeof(CameraRelativeGloveRig)
            .GetField(name, BindingFlags.NonPublic | BindingFlags.Instance).SetValue(rig, value);

        private void Guard(bool isLeft, float amount) => typeof(CameraRelativeGloveRig)
            .GetMethod("SetGuardPose", BindingFlags.NonPublic | BindingFlags.Instance)
            .Invoke(rig, new object[] { isLeft, amount });

        private void PrepareNewMotion(bool isLeft) => typeof(CameraRelativeGloveRig)
            .GetMethod("PrepareHandForNewMotion", BindingFlags.NonPublic | BindingFlags.Instance)
            .Invoke(rig, new object[] { isLeft });

        private static float Alpha(Renderer renderer, int index = 0)
        {
            var block = new MaterialPropertyBlock();
            renderer.GetPropertyBlock(block, index);
            return block.HasColor("_Color") ? block.GetColor("_Color").a : renderer.sharedMaterials[index].color.a;
        }

        [TestCase(true, 1f)]
        [TestCase(false, -1f)]
        public void GuardOffset_RaisesClosesAndPullsBack(bool isLeft, float side)
        {
            Vector3 actual = PunchTargeting.GuardPositionOffset(
                isLeft, 0.12f, 0.2f, 0.12f, 0.65f, 0.25f, 1f);
            Assert.That(actual.x, Is.EqualTo(side * 0.12f).Within(0.0001f));
            Assert.That(actual.y, Is.EqualTo(0.2f).Within(0.0001f));
            Assert.That(actual.z, Is.EqualTo(-0.12f).Within(0.0001f));
        }

        [TestCase(0.65f, 0.25f, -0.4f)]
        [TestCase(0.2f, 0.25f, 0f)]
        public void GuardOffset_ClampsExcessiveCameraApproach(float depth, float minimum, float expected)
        {
            Assert.That(PunchTargeting.GuardPositionOffset(true, 0f, 0f, 10f,
                depth, minimum, 1f).z, Is.EqualTo(expected).Within(0.0001f));
            Assert.That(PunchTargeting.GuardPositionOffset(true, 1f, 1f, 1f,
                depth, minimum, 0f), Is.EqualTo(Vector3.zero));
        }

        [Test]
        public void GuardPose_UsesIndependentLocalYawAndReturnsToRest()
        {
            Guard(true, 1f);
            Guard(false, 1f);
            // Apply the stored offsets and force a known camera-local rest pose.
            typeof(CameraRelativeGloveRig).GetMethod("ApplyPose",
                BindingFlags.NonPublic | BindingFlags.Instance).Invoke(rig, null);
            Quaternion expectedLeft = Quaternion.Euler(10f, 20f, -10f) *
                Quaternion.AngleAxis(55f, Vector3.up);
            Quaternion expectedRight = Quaternion.Euler(10f, -20f, 10f) *
                Quaternion.AngleAxis(-55f, Vector3.up);
            Assert.That(Quaternion.Angle(left.transform.rotation, expectedLeft), Is.LessThan(0.05f));
            Assert.That(Quaternion.Angle(right.transform.rotation, expectedRight), Is.LessThan(0.05f));
            Assert.That(left.transform.position.z, Is.EqualTo(0.53f).Within(0.0001f));
            rig.ResetPose();
            Assert.That(left.transform.position.z, Is.EqualTo(0.65f).Within(0.0001f));
        }

        [Test]
        public void GuardFade_IsProgressivePerHandAndDoesNotChangeSharedMaterial()
        {
            Guard(true, 0.5f);
            Assert.That(Alpha(left), Is.EqualTo(0.8f * 0.825f).Within(0.0001f));
            Assert.That(Alpha(right), Is.EqualTo(0.8f).Within(0.0001f));
            Guard(true, 1f);
            Assert.That(Alpha(left), Is.EqualTo(0.8f * 0.65f).Within(0.0001f));
            Guard(true, 0f);
            Assert.That(Alpha(left), Is.EqualTo(0.8f).Within(0.0001f));
            Assert.That(material.color.a, Is.EqualTo(0.8f).Within(0.0001f));
        }

        [TestCase(false)]
        [TestCase(true)]
        public void ResetOrDisableCallback_RestoresBothHands(bool disable)
        {
            Guard(true, 1f);
            Guard(false, 1f);
            // Non-ExecuteAlways behaviours do not receive play-mode lifecycle
            // messages in EditMode; exercise the callback explicitly here.
            if (disable) typeof(CameraRelativeGloveRig).GetMethod("OnDisable",
                BindingFlags.NonPublic | BindingFlags.Instance).Invoke(rig, null);
            else rig.ResetPose();
            Assert.That(Alpha(left), Is.EqualTo(0.8f).Within(0.0001f));
            Assert.That(Alpha(right), Is.EqualTo(0.8f).Within(0.0001f));
        }

        [Test]
        public void BlockedPunch_RestoresOnlyInterruptedHand()
        {
            Guard(true, 1f);
            Guard(false, 1f);
            SetField("fallbackToPrototypeWhenTargetUnavailable", false);
            SetField("maximumTargetDistanceMetres", 0f);
            rig.LeftJab();
            Assert.That(Alpha(left), Is.EqualTo(0.8f).Within(0.0001f));
            Assert.That(Alpha(right), Is.EqualTo(0.8f * 0.65f).Within(0.0001f));
        }

        [Test]
        public void GuardToPickupPreparation_RestoresOpacityAndRestPose()
        {
            Guard(true, 1f);
            Assert.That(Alpha(left), Is.LessThan(0.8f));

            PrepareNewMotion(true);
            typeof(CameraRelativeGloveRig).GetMethod("ApplyPose",
                BindingFlags.NonPublic | BindingFlags.Instance).Invoke(rig, null);

            Assert.That(Alpha(left), Is.EqualTo(0.8f).Within(0.0001f));
            Assert.That(left.transform.position,
                Is.EqualTo(rig.GetRestingPositionForTesting(true)));
        }

        [Test]
        public void PickupToPunchPreparation_ClearsDisplacementAndPickupFlag()
        {
            typeof(CameraRelativeGloveRig).GetMethod("SetMotionOffset",
                BindingFlags.NonPublic | BindingFlags.Instance).Invoke(
                    rig,
                    new object[] { true, new Vector3(0.2f, -0.3f, 0.4f), Quaternion.Euler(20f, 10f, 0f) });
            SetField("leftPickupReachActive", true);

            PrepareNewMotion(true);
            typeof(CameraRelativeGloveRig).GetMethod("ApplyPose",
                BindingFlags.NonPublic | BindingFlags.Instance).Invoke(rig, null);

            Assert.That(rig.IsPickupReachActive(true), Is.False);
            Assert.That(left.transform.position,
                Is.EqualTo(rig.GetRestingPositionForTesting(true)));
        }

        [Test]
        public void Fade_RestoresExistingPropertyBlocksAndHandlesMultipleMaterialSlots()
        {
            left.sharedMaterials = new[] { material, material };
            var original = new MaterialPropertyBlock();
            original.SetColor("_Color", new Color(0.3f, 0.4f, 0.5f, 0.6f));
            original.SetFloat("_Glossiness", 0.123f);
            left.SetPropertyBlock(original, 1);
            var fade = new GloveOpacity(left.transform);
            fade.SetOpacity(0.5f);
            Assert.That(Alpha(left, 0), Is.EqualTo(0.4f).Within(0.0001f));
            Assert.That(Alpha(left, 1), Is.EqualTo(0.3f).Within(0.0001f));
            fade.Restore();
            var restored = new MaterialPropertyBlock();
            left.GetPropertyBlock(restored, 1);
            Assert.That(restored.GetColor("_Color"), Is.EqualTo(original.GetColor("_Color")));
            Assert.That(restored.GetFloat("_Glossiness"), Is.EqualTo(0.123f).Within(0.0001f));
            left.GetPropertyBlock(restored, 0);
            Assert.That(restored.isEmpty, Is.True);
        }

        [Test]
        public void Fade_PreservesRendererWideBlockAndCanBeReused()
        {
            var original = new MaterialPropertyBlock();
            original.SetColor("_Color", new Color(0.3f, 0.4f, 0.5f, 0.6f));
            left.SetPropertyBlock(original);
            var fade = new GloveOpacity(left.transform);
            fade.SetOpacity(0.5f);
            Assert.That(Alpha(left), Is.EqualTo(0.3f).Within(0.0001f));
            fade.Restore();
            original.SetColor("_Color", Color.white);
            left.SetPropertyBlock(original);
            fade.SetOpacity(0.5f);
            Assert.That(Alpha(left), Is.EqualTo(0.5f).Within(0.0001f));
            fade.Restore();
            left.GetPropertyBlock(original, 0);
            Assert.That(original.isEmpty, Is.True);
        }

        [TestCase("M_PlayerGlove_Left_Red")]
        [TestCase("M_PlayeGlove_Right_Red")]
        public void PlayerMaterial_HasBuildTimeFadeConfiguration(string name)
        {
            Material asset = AssetDatabase.LoadAssetAtPath<Material>(
                "Assets/Art/Gloves/Materials/" + name + ".mat");
            Assert.That(asset, Is.Not.Null);
            Assert.That(asset.shader.name, Is.EqualTo("Standard"));
            Assert.That(asset.GetFloat("_Mode"), Is.EqualTo(2f));
            Assert.That(asset.GetFloat("_SrcBlend"), Is.EqualTo(5f));
            Assert.That(asset.GetFloat("_DstBlend"), Is.EqualTo(10f));
            Assert.That(asset.GetFloat("_ZWrite"), Is.Zero);
            Assert.That(asset.IsKeywordEnabled("_ALPHABLEND_ON"), Is.True);
            Assert.That(asset.renderQueue, Is.EqualTo(3000));
            Assert.That(asset.color.a, Is.EqualTo(1f));
            Assert.That(asset.mainTexture, Is.Not.Null);
        }

        [Test]
        public void PlayerFadeShader_RendersBackgroundThroughGlove()
        {
            Material asset = AssetDatabase.LoadAssetAtPath<Material>(
                "Assets/Art/Gloves/Materials/M_PlayerGlove_Left_Red.mat");
            var renderMaterial = new Material(asset);
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.transform.SetParent(root.transform);
            quad.layer = 31;
            quad.GetComponent<Renderer>().sharedMaterial = renderMaterial;
            // Use a predictable red surface against blue, preserving the real
            // player material's shader, blend state, keywords and render queue.
            renderMaterial.mainTexture = null;
            renderMaterial.color = Color.black;
            renderMaterial.SetFloat("_SpecularHighlights", 0f);
            renderMaterial.SetFloat("_GlossyReflections", 0f);
            renderMaterial.EnableKeyword("_EMISSION");
            renderMaterial.SetColor("_EmissionColor", Color.red);
            Camera camera = root.GetComponentInChildren<Camera>();
            camera.transform.position = new Vector3(0f, 0f, -2f);
            camera.orthographic = true;
            camera.orthographicSize = 1f;
            camera.cullingMask = 1 << 31;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.blue;
            camera.allowHDR = false;
            var target = new RenderTexture(32, 32, 24, RenderTextureFormat.ARGB32);
            var pixels = new Texture2D(32, 32, TextureFormat.RGB24, false);
            RenderTexture previous = RenderTexture.active;
            try
            {
                camera.targetTexture = target;
                camera.Render();
                RenderTexture.active = target;
                pixels.ReadPixels(new Rect(0, 0, 32, 32), 0, 0);
                Color solid = pixels.GetPixel(16, 16);
                var fade = new GloveOpacity(quad.transform);
                fade.SetOpacity(0.65f);
                camera.Render();
                pixels.ReadPixels(new Rect(0, 0, 32, 32), 0, 0);
                Color faded = pixels.GetPixel(16, 16);
                Assert.That(solid.r, Is.GreaterThan(0.8f));
                Assert.That(faded.b, Is.GreaterThan(solid.b + 0.1f),
                    "The blue background should show through at partial opacity.");
                Assert.That(faded.r, Is.LessThan(solid.r - 0.05f));
                fade.Restore();
            }
            finally
            {
                camera.targetTexture = null;
                RenderTexture.active = previous;
                target.Release();
                Object.DestroyImmediate(target);
                Object.DestroyImmediate(pixels);
                Object.DestroyImmediate(quad);
                Object.DestroyImmediate(renderMaterial);
            }
        }
    }
}
