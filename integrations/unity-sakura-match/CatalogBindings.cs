using System;
using System.Collections.Generic;
using UnityEngine;
using SakuraMatch.Core;

namespace SakuraMatch.Data
{
    /// <summary>
    /// Runtime loader for catalog bindings exported by <c>sakura import</c>.
    /// Loads <c>Resources/Catalog/sakura_match/bindings.json</c> and optional slot sprites.
    /// </summary>
    public static class CatalogBindings
    {
        public const string DefaultResourcesManifest = "Catalog/sakura_match/bindings";

        private static bool _loaded;
        private static string _titleId = string.Empty;
        private static readonly Dictionary<TileType, Sprite> TileSprites = new();
        private static readonly Dictionary<string, Sprite> SlotSprites = new();
        private static readonly Dictionary<string, BindingEntry> BySlot = new();

        [Serializable]
        public class Manifest
        {
            public string schema_version;
            public string title_id;
            public string imported_at;
            public string source_catalog;
            public BindingEntry[] bindings;
        }

        [Serializable]
        public class BindingEntry
        {
            public string slot_id;
            public string asset_id;
            public string status;
            public string resources_path;
            public string kind;
            public string tile_type;
        }

        public static string TitleId => _titleId;
        public static bool IsLoaded => _loaded;

        /// <summary>
        /// Loads the manifest and sprites. Safe to call multiple times.
        /// </summary>
        public static void EnsureLoaded(string resourcesManifestPath = null)
        {
            if (_loaded)
            {
                return;
            }

            var path = string.IsNullOrEmpty(resourcesManifestPath)
                ? DefaultResourcesManifest
                : resourcesManifestPath;

            var asset = Resources.Load<TextAsset>(path);
            if (asset == null)
            {
                Debug.LogWarning(
                    $"[CatalogBindings] No manifest at Resources/{path}.json — using color fallbacks.");
                _loaded = true;
                return;
            }

            Manifest manifest;
            try
            {
                manifest = JsonUtility.FromJson<Manifest>(asset.text);
            }
            catch (Exception e)
            {
                Debug.LogError($"[CatalogBindings] Failed to parse manifest: {e.Message}");
                _loaded = true;
                return;
            }

            if (manifest == null)
            {
                _loaded = true;
                return;
            }

            _titleId = manifest.title_id ?? string.Empty;

            if (manifest.bindings != null)
            {
                foreach (var entry in manifest.bindings)
                {
                    if (entry == null || string.IsNullOrEmpty(entry.slot_id))
                    {
                        continue;
                    }

                    BySlot[entry.slot_id] = entry;

                    if (string.IsNullOrEmpty(entry.resources_path))
                    {
                        continue;
                    }

                    var sprite = Resources.Load<Sprite>(entry.resources_path);
                    if (sprite == null)
                    {
                        // Texture-only import (no Sprite meta yet): load texture and wrap.
                        var tex = Resources.Load<Texture2D>(entry.resources_path);
                        if (tex != null)
                        {
                            sprite = Sprite.Create(
                                tex,
                                new Rect(0, 0, tex.width, tex.height),
                                new Vector2(0.5f, 0.5f),
                                100f);
                        }
                    }

                    if (sprite == null)
                    {
                        Debug.LogWarning(
                            $"[CatalogBindings] Missing sprite for {entry.slot_id} at {entry.resources_path}");
                        continue;
                    }

                    SlotSprites[entry.slot_id] = sprite;

                    if (!string.IsNullOrEmpty(entry.tile_type) &&
                        Enum.TryParse(entry.tile_type, ignoreCase: true, out TileType tileType) &&
                        tileType != TileType.None)
                    {
                        TileSprites[tileType] = sprite;
                    }
                }
            }

            _loaded = true;
            Debug.Log(
                $"[CatalogBindings] Loaded '{_titleId}' with {SlotSprites.Count} slot sprite(s), " +
                $"{TileSprites.Count} tile type map(s).");
        }

        public static bool TryGetTileSprite(TileType type, out Sprite sprite)
        {
            EnsureLoaded();
            return TileSprites.TryGetValue(type, out sprite) && sprite != null;
        }

        public static bool TryGetSlotSprite(string slotId, out Sprite sprite)
        {
            EnsureLoaded();
            return SlotSprites.TryGetValue(slotId, out sprite) && sprite != null;
        }

        public static bool TryGetBinding(string slotId, out BindingEntry entry)
        {
            EnsureLoaded();
            return BySlot.TryGetValue(slotId, out entry);
        }

        /// <summary>
        /// Clears cache (for editor tests / reimport without domain reload).
        /// </summary>
        public static void Unload()
        {
            _loaded = false;
            _titleId = string.Empty;
            TileSprites.Clear();
            SlotSprites.Clear();
            BySlot.Clear();
        }
    }
}
