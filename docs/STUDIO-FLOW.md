# Sakura Studio · Flow graph (node editor)

v0.6.0+ — Nuke/Fusion-style **branch / chain** view of a title: story beats, player choices, art slots, bound assets, and the game engine.

## Open it

1. `./shared/scripts/sakura-studio.sh` → http://127.0.0.1:8787/
2. Select a catalog title (e.g. Sakura Tea House).
3. Tab **Flow ★**.

## What the connectors mean

Edges are labeled in plain language so the graph reads as a sentence:

| Edge kind | On-canvas phrase | Meaning |
|-----------|------------------|---------|
| `leads_to` | **then opens** | Level/scene continues to the next beat |
| `unlocks` | **unlocks** | Scene unlocks a romance route, etc. |
| `contains` | **contains** | Route contains a scene |
| `uses_slot` | **uses art slot** | Scene/system needs a catalog slot |
| `binds` | **shows asset** | Slot is bound to a library asset |
| `has_dialogue` | **plays dialogue** | Scene has a dialogue ledger |
| `choice` | **player chooses** | Dialogue choice point |
| `option` | **player picks** / option | Branch the player can take |
| `runs` | **runs system** | Engine runs a gameplay system |

Example reading of a chain:

> **Level 1** *then opens* **scene “A Visitor at Dusk”** *plays dialogue* **Dialogue hub** *player chooses* **welcome choice** *player picks* **warm welcome**…  
> Scene *uses art slot* **portrait Ren** *shows asset* **asset.portrait…**  
> **Three.js engine** *runs system* **Match-3 board** *uses art slot* **gem flower**…

## Layers

Toggle **story · dialogue · art · engine · cast** to hide noise while you rework a spine.

- **story** — routes, levels, scenes, endings  
- **dialogue** — dialogue hubs, choices, options (optional detail)  
- **art** — slots + bound assets (previews on asset nodes)  
- **engine** — engine pack + systems  

**Dialogue detail** checkbox: when off, only dialogue *hubs* (one per scene) appear, not every choice/option.

## Rearrange & save

| Action | How |
|--------|-----|
| Move node | Drag the card |
| Pan canvas | Drag empty space (or middle-mouse) |
| Zoom | Scroll wheel |
| Auto column layout | **Auto-layout** |
| Persist positions | **Save layout** |

Positions are written to the title’s Studio prefs:

```yaml
# catalog/titles/<title>/studio.yaml
flow:
  positions:
    node.level.1: {x: 40.0, y: 128.0}
    node.scene.visitor_dusk: {x: 280.0, y: 128.0}
```

Same file as the style board (`style:` key is preserved).

## Data sources

| Source | Contribution |
|--------|----------------|
| `ggd.yaml` | Primary nodes + `leads_to` / `unlocks` / `uses_slot` / … |
| `dialogue.yaml` | Dialogue hubs; choices/options when detail is on |
| `slots.yaml` + `bindings.yaml` | Slot nodes + asset nodes + `binds` edges |
| `title.yaml` + engines | Engine node + `runs` into systems |

API:

```http
GET  /api/flow?title=title.sakura_tea_house&dialogue_detail=true
POST /api/flow/layout     { "title_id", "positions": { "node…": {"x","y"} } }
POST /api/flow/auto-layout?title=…&persist=true
```

## Not yet (next iterations)

- Draw new edges in UI (edit GGD from canvas)
- Collapse / expand groups (whole route as super-node)
- Live preview scrub along a path  
- Two-way sync with external tools (Blender/Nuke)

## Related

- [`STUDIO-IMAGINE.md`](./STUDIO-IMAGINE.md) — art generate/edit + style board  
- [`GDD-DASHBOARD-GAP.md`](./GDD-DASHBOARD-GAP.md) — product map  
- [`catalog/SCHEMA.md`](../catalog/SCHEMA.md) — GGD node/edge kinds  
