# Sakura Studio · Game asset tools

**v0.7.0+** — Studio port of the [Grok Build game-asset skill suite](https://x.com/tetsuoai/status/2078460006417223974)
(`game-asset-core`, `game-character-consistency`, `game-tilesets`, `game-ui-icons`, `game-animation-frames`).

> **Note on local skill files:** on some Grok installs these live under
> `~/.grok/bundled/skills/`. This machine’s Grok (`0.2.101`) did not ship those
> directories yet. Studio implements the *workflows* directly so your catalog
> pipeline does not depend on CLI skill discovery.

## Open it

1. Set `XAI_API_KEY` in `SakuraSoft/.env`
2. `./shared/scripts/sakura-studio.sh` → http://127.0.0.1:8787/
3. Select a catalog title
4. Tab **Assets ✦**

Optional but recommended: **Swaps → Project style board → Style lock ON** so every
tool injects your title’s look.

## Tools

| Tool | Skill analogue | What you get |
|------|----------------|--------------|
| **Core sprite / prop** | `game-asset-core` | Isolated subject, flat keyable BG, no text → catalog asset |
| **Character consistency** | `game-character-consistency` | Edit-chain from a base (turnaround / expression / damage / gear / palette) with identity freeze-list |
| **Tileset** | `game-tilesets` | Seamless tile + automatic **2×2 composite** seam check asset |
| **UI icon set** | `game-ui-icons` | Batch icons under one style contract, no glyphs |
| **Animation frames** | `game-animation-frames` | N pose-sequence frames edit-chained from a base sprite |

Each run writes `asset.studio.*` YAML + binaries under `catalog/assets/` with
provenance `skill: game-…`. Optional **slot bind** wires Swaps immediately.

## Engine-ready defaults (always forced)

- Isolated subject (no cluttered scenes unless you ask for a BG kind)
- Flat **keyable** background (default chroma green — override per form)
- No text / watermarks / UI chrome on sprites & icons
- Character variants are **edits of one base**, not new gens
- Tiles: seam language + 2×2 visual QA
- Style board ref when lock is ON

## How to call from the UI

1. Pick a tool tab  
2. Read the on-screen **instructions** (tool-specific)  
3. Fill fields → **Generate → catalog**  
4. Inspect result thumbnails → open **Swaps** to rebind / Imagine-edit further  

## API

```http
GET  /api/game-assets/tools
POST /api/game-assets/run
{
  "tool": "core" | "character" | "tileset" | "ui_icons" | "animation",
  "title_id": "title.sakura_tea_house",
  "prompt": "...",
  "use_style_board": true,
  "quality": true,
  ...
}
```

## Relationship to Grok Build CLI skills

| Layer | Role |
|-------|------|
| Grok Build skills (`~/.grok/bundled/skills/game-*`) | Agent playbooks for Imagine tools in the TUI |
| Sakura Studio **Assets ✦** | Same recipes, catalog-native, clickable, title-scoped |

When the skill packs appear on disk after a Grok update, they remain useful for
agent sessions; Studio stays the **source of truth** for bindings and library IDs.

## Related

- [`STUDIO-IMAGINE.md`](./STUDIO-IMAGINE.md) — raw Imagine + style board  
- [`STUDIO-FLOW.md`](./STUDIO-FLOW.md) — story/art/engine graph  
- [`ELEVENLABS-RUNTIME.md`](./ELEVENLABS-RUNTIME.md) — VO  
