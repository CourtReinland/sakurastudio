# Sakura Studio · Flow graph

Canonical workstation docs: **[`FLOW-WORKSTATION.md`](./FLOW-WORKSTATION.md)** (v0.9 scene-centric Flow).

This page is a short index of edge kinds and layout persistence. Prefer the workstation doc for controls (rubber-band connect, splash slots, Open Unity/Blender).

## Open it

1. `./shared/scripts/sakura-studio.sh` → http://127.0.0.1:8787/
2. Select a catalog title (e.g. Sakura Tea House).
3. Tab **Flow ★**.

## Progression connectors

Edges are labeled in plain language:

| Edge kind | On-canvas phrase | Meaning |
|-----------|------------------|---------|
| `leads_to` | **then** / **Play** | Scene continues to the next beat |
| `unlocks` | **unlocks** | Scene unlocks a romance route, etc. |
| `contains` | (folded into progression) | Route contains a scene |
| `choice` / `option` | choice labels | Player branch |

Nested **assets** (graphics, dialogue, cast, code refs) live inside each scene node — expand with **+**.

## Rearrange & connect

| Action | How |
|--------|-----|
| Move node | Drag the card |
| Pan / zoom | Drag empty canvas · scroll |
| Connect A → B | Drag from out-port → target (rubber-band), or **C** then out/in |
| Disconnect | × on outbound link in detail panel |
| Add scene | **+ Scene** or **N** |
| Auto column layout | **Auto-layout** |
| Persist positions | **Save layout** → `studio.yaml` |

```yaml
# catalog/titles/<title>/studio.yaml
flow:
  positions:
    node.level.1: {x: 40.0, y: 128.0}
    node.scene.visitor_dusk: {x: 280.0, y: 128.0}
```

## APIs

```http
GET  /api/flow?title=title.sakura_tea_house
POST /api/flow/scene
POST /api/flow/connect
POST /api/flow/disconnect
POST /api/flow/layout     { "title_id", "positions": { "node…": {"x","y"} } }
POST /api/flow/auto-layout?title=…&persist=true
```

## Related

- [`FLOW-WORKSTATION.md`](./FLOW-WORKSTATION.md) — main Flow surface  
- [`STUDIO-IMAGINE.md`](./STUDIO-IMAGINE.md) — art generate/edit + style board  
- [`GDD-DASHBOARD-GAP.md`](./GDD-DASHBOARD-GAP.md) — product map  
- [`catalog/SCHEMA.md`](../catalog/SCHEMA.md) — GGD node/edge kinds  
