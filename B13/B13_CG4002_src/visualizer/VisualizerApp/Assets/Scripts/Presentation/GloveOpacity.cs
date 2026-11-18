using System.Collections.Generic;
using UnityEngine;

namespace CG4002.Visualizer.Presentation
{
    /// <summary>
    /// Per-hand fade for the project's Built-in Standard/Fade materials.
    /// Never edits shared materials or instantiates materials per frame.
    /// Owns the renderer's per-material property blocks while guard is active;
    /// restores the pre-guard blocks afterwards (including unrelated properties).
    /// Recreate this cache if glove renderers/material assignments are replaced.
    /// </summary>
    public sealed class GloveOpacity
    {
        private static readonly int ColorId = Shader.PropertyToID("_Color");

        private sealed class Slot
        {
            public Renderer Renderer;
            public int Index;
            public Material Material;
            public Color Color;
            public readonly MaterialPropertyBlock Original = new();
            public readonly MaterialPropertyBlock Working = new();
        }

        private readonly List<Slot> slots = new();
        private bool active;

        public GloveOpacity(Transform root)
        {
            if (root == null) return;
            foreach (Renderer renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                Material[] materials = renderer.sharedMaterials;
                for (int i = 0; i < materials.Length; i++)
                {
                    Material material = materials[i];
                    if (material == null) continue;
                    if (material.shader.name != "Standard" || material.GetFloat("_Mode") != 2f)
                    {
                        if (renderer.enabled && renderer.gameObject.activeInHierarchy)
                            Debug.LogWarning("Guard fade needs a Standard material in Fade mode: " +
                                material.name, renderer);
                        continue;
                    }
                    slots.Add(new Slot { Renderer = renderer, Index = i, Material = material });
                }
            }
        }

        public void SetOpacity(float opacity)
        {
            opacity = Mathf.Clamp01(opacity);
            if (opacity >= 1f)
            {
                Restore();
                return;
            }

            foreach (Slot slot in slots)
            {
                if (slot.Renderer == null || slot.Material == null) continue;
                if (!active)
                {
                    slot.Renderer.GetPropertyBlock(slot.Original, slot.Index);
                    slot.Renderer.GetPropertyBlock(slot.Working, slot.Index);
                    // A per-slot block overrides the renderer-wide block. Copy
                    // that block only when this slot did not already have one.
                    if (slot.Working.isEmpty)
                        slot.Renderer.GetPropertyBlock(slot.Working);
                    slot.Color = slot.Working.HasColor(ColorId)
                        ? slot.Working.GetColor(ColorId) : slot.Material.GetColor(ColorId);
                }
                Color color = slot.Color;
                color.a *= opacity;
                slot.Working.SetColor(ColorId, color);
                slot.Renderer.SetPropertyBlock(slot.Working, slot.Index);
            }
            active = true;
        }

        public void Restore()
        {
            if (!active) return;
            foreach (Slot slot in slots)
            {
                if (slot.Renderer != null)
                    slot.Renderer.SetPropertyBlock(slot.Original.isEmpty ? null : slot.Original, slot.Index);
            }
            active = false;
        }
    }
}
