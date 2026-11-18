using System;
using System.Collections;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    /// <summary>Cheap, world-space animation for a pickup; the root pose remains fixed.</summary>
    public sealed class PickupVisual : MonoBehaviour
    {
        [SerializeField] private Transform floatingRoot;
        [SerializeField, Min(0f)] private float bobHeightMetres = 0.035f;
        [SerializeField, Min(0f)] private float bobCyclesPerSecond = 0.8f;
        [SerializeField] private float spinDegreesPerSecond = 55f;
        [SerializeField, Min(0f)] private float contactHeightMetres = 0.28f;
        [SerializeField, Min(0.05f)] private float collectionEffectSeconds = 0.32f;
        [SerializeField, Min(1f)] private float collectionBurstScale = 1.35f;

        private Vector3 initialLocalPosition;
        private Vector3 initialRootScale;
        private float phase;
        private Coroutine retirementRoutine;
        private Coroutine collectionRoutine;

        public string ItemId { get; private set; } = string.Empty;
        public float Magnitude { get; private set; }
        public bool IsCollecting { get; private set; }
        public bool IsRetiring { get; private set; }
        public Vector3 ContactPosition => transform.position +
            transform.up * contactHeightMetres;

        public event Action<PickupVisual> PresentationFinished;

        private void Awake()
        {
            if (floatingRoot == null)
            {
                floatingRoot = transform;
            }

            initialLocalPosition = floatingRoot.localPosition;
            initialRootScale = transform.localScale;
            phase = UnityEngine.Random.value * Mathf.PI * 2f;
        }

        private void Update()
        {
            if (floatingRoot == null || collectionRoutine != null)
            {
                return;
            }

            float wave = Mathf.Sin(
                (Time.unscaledTime * bobCyclesPerSecond * Mathf.PI * 2f) + phase);
            floatingRoot.localPosition = initialLocalPosition + Vector3.up * (wave * bobHeightMetres);
            floatingRoot.Rotate(Vector3.up, spinDegreesPerSecond * Time.unscaledDeltaTime, Space.Self);
        }

        public void Initialize(string itemId, float magnitude = 0f)
        {
            ItemId = itemId ?? string.Empty;
            Magnitude = Mathf.Max(0f, magnitude);
            gameObject.name = "HealthPickup_" + ItemId;
        }

        public void BeginAuthoritativeRemoval(float graceSeconds)
        {
            if (IsCollecting || collectionRoutine != null || retirementRoutine != null)
            {
                return;
            }

            IsRetiring = true;
            retirementRoutine = StartCoroutine(RetireAfterGrace(Mathf.Max(0f, graceSeconds)));
        }

        public void CancelAuthoritativeRemoval()
        {
            if (IsCollecting || retirementRoutine == null)
            {
                return;
            }

            StopCoroutine(retirementRoutine);
            retirementRoutine = null;
            IsRetiring = false;
        }

        public void BeginCollection()
        {
            if (collectionRoutine != null)
            {
                return;
            }

            if (retirementRoutine != null)
            {
                StopCoroutine(retirementRoutine);
                retirementRoutine = null;
            }

            IsRetiring = false;
            IsCollecting = true;
        }

        public void PlayCollectionEffect()
        {
            BeginCollection();
            if (collectionRoutine == null)
            {
                collectionRoutine = StartCoroutine(AnimateCollection());
            }
        }

        private IEnumerator RetireAfterGrace(float graceSeconds)
        {
            float elapsed = 0f;
            while (elapsed < graceSeconds)
            {
                elapsed += Time.unscaledDeltaTime;
                yield return null;
            }

            retirementRoutine = null;
            PlayCollectionEffect();
        }

        private IEnumerator AnimateCollection()
        {
            float elapsed = 0f;
            while (elapsed < collectionEffectSeconds)
            {
                elapsed += Time.unscaledDeltaTime;
                float amount = Mathf.Clamp01(elapsed / collectionEffectSeconds);
                float scale = amount < 0.35f
                    ? Mathf.Lerp(1f, collectionBurstScale, amount / 0.35f)
                    : Mathf.Lerp(collectionBurstScale, 0f, (amount - 0.35f) / 0.65f);
                transform.localScale = initialRootScale * scale;
                yield return null;
            }

            transform.localScale = Vector3.zero;
            collectionRoutine = null;
            PresentationFinished?.Invoke(this);
        }

        public static PickupVisual CreateFallback(Transform parent)
        {
            var root = new GameObject("HealthPickup_Fallback");
            root.transform.SetParent(parent, false);

            GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            marker.name = "GroundMarker";
            marker.transform.SetParent(root.transform, false);
            marker.transform.localPosition = new Vector3(0f, 0.006f, 0f);
            marker.transform.localScale = new Vector3(0.24f, 0.006f, 0.24f);
            DestroyRuntimeObject(marker.GetComponent<Collider>());

            var floating = new GameObject("FloatingVisual");
            floating.transform.SetParent(root.transform, false);
            floating.transform.localPosition = new Vector3(0f, 0.24f, 0f);

            GameObject orb = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            orb.name = "HealthOrb";
            orb.transform.SetParent(floating.transform, false);
            orb.transform.localScale = Vector3.one * 0.22f;
            DestroyRuntimeObject(orb.GetComponent<Collider>());

            GameObject horizontal = GameObject.CreatePrimitive(PrimitiveType.Cube);
            horizontal.name = "CrossHorizontal";
            horizontal.transform.SetParent(floating.transform, false);
            horizontal.transform.localPosition = new Vector3(0f, 0f, -0.12f);
            horizontal.transform.localScale = new Vector3(0.18f, 0.055f, 0.025f);
            DestroyRuntimeObject(horizontal.GetComponent<Collider>());

            GameObject vertical = GameObject.CreatePrimitive(PrimitiveType.Cube);
            vertical.name = "CrossVertical";
            vertical.transform.SetParent(floating.transform, false);
            vertical.transform.localPosition = new Vector3(0f, 0f, -0.12f);
            vertical.transform.localScale = new Vector3(0.055f, 0.18f, 0.025f);
            DestroyRuntimeObject(vertical.GetComponent<Collider>());

            PickupVisual visual = root.AddComponent<PickupVisual>();
            visual.floatingRoot = floating.transform;
            visual.initialLocalPosition = floating.transform.localPosition;
            return visual;
        }

        private static void DestroyRuntimeObject(UnityEngine.Object value)
        {
            if (value == null)
            {
                return;
            }

            if (Application.isPlaying)
            {
                Destroy(value);
            }
            else
            {
                DestroyImmediate(value);
            }
        }
    }
}
