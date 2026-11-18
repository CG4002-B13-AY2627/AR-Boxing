using System.Reflection;
using CG4002.Visualizer.Tracking;
using NUnit.Framework;
using UnityEngine;

namespace CG4002.Visualizer.Tests
{
    public sealed class OpponentBodyGloveTrackerTests
    {
        private GameObject root;
        private GameObject glove;
        private Material material;
        private Renderer gloveRenderer;
        private OpponentBodyGloveTracker tracker;

        [SetUp]
        public void SetUp()
        {
            root = new GameObject("Body glove test");
            root.SetActive(false);
            glove = GameObject.CreatePrimitive(PrimitiveType.Cube);
            glove.transform.SetParent(root.transform);
            gloveRenderer = glove.GetComponent<Renderer>();
            material = new Material(Shader.Find("Standard"));
            material.color = new Color(0.25f, 0.4f, 1f, 1f);
            gloveRenderer.sharedMaterial = material;
            tracker = root.AddComponent<OpponentBodyGloveTracker>();
            SetField("leftGlove", glove.transform);
            SetField("rightGlove", glove.transform);
            SetField("leftGloveColor", Color.red);
            SetField("rightGloveColor", Color.red);
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(root);
            Object.DestroyImmediate(material);
        }

        private void SetField(string name, object value) =>
            typeof(OpponentBodyGloveTracker)
                .GetField(name, BindingFlags.NonPublic | BindingFlags.Instance)
                .SetValue(tracker, value);

        private void ApplyColors() => typeof(OpponentBodyGloveTracker)
            .GetMethod("ApplyGloveColors", BindingFlags.NonPublic | BindingFlags.Instance)
            .Invoke(tracker, null);

        [Test]
        public void AuthoredMaterial_IsUntouchedWhenOverrideIsDisabled()
        {
            var existing = new MaterialPropertyBlock();
            existing.SetFloat("_Glossiness", 0.123f);
            gloveRenderer.SetPropertyBlock(existing);

            SetField("overrideMaterialColor", false);
            ApplyColors();

            var actual = new MaterialPropertyBlock();
            gloveRenderer.GetPropertyBlock(actual, 0);
            Assert.That(actual.GetFloat("_Glossiness"), Is.EqualTo(0.123f).Within(0.0001f));
            Assert.That(actual.GetColor("_Color"), Is.EqualTo(material.color));
            Assert.That(material.color, Is.EqualTo(new Color(0.25f, 0.4f, 1f, 1f)));
        }

        [Test]
        public void PrototypeTint_IsAppliedOnlyWhenExplicitlyEnabled()
        {
            SetField("overrideMaterialColor", true);
            ApplyColors();

            var actual = new MaterialPropertyBlock();
            gloveRenderer.GetPropertyBlock(actual, 0);
            Assert.That(actual.GetColor("_Color"), Is.EqualTo(Color.red));
            if (material.HasProperty("_BaseColor"))
            {
                Assert.That(actual.GetColor("_BaseColor"), Is.EqualTo(Color.red));
            }
            Assert.That(material.color, Is.EqualTo(new Color(0.25f, 0.4f, 1f, 1f)));
        }
    }
}
