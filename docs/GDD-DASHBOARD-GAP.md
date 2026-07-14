# GDD ↔ Studio dashboard gap analysis

**Sources**

- Live GDD: [CourtReinland/sakura-match](https://github.com/CourtReinland/sakura-match) · `docs/GDD-current.md`, `story-arc-map.md`, `campaign-story-stage-bible.md`
- Studio today: bind cards for slots + validate/import (graphics-first)

**Goal of Studio:** spreadsheet-of-tabs for every repo; **swappable** fiction/art/pieces first-class; everything else listable.

---

## 1. What the Tea House GDD actually tracks

| GDD domain | Examples in sakura-match | Swappable? | Dashboard treatment |
|------------|--------------------------|------------|---------------------|
| **High concept / pillars** | Consent-first otome, puzzle=fiction | No (copy) | Listed on Overview |
| **Characters** | Keeper, Ren, Mizu, Akira, shadow, creditor | Portraits / expressions yes | Cast tab + portrait slots |
| **Rooms / spaces** | Entry hall, ledger nook, moon door | BG art yes | Listed; BG slots drag-drop |
| **Plot arcs / routes** | Ren / Mizu / Akira romance + plot spine | Structure rarely; labels yes | Story tab (list + graph) |
| **Scenes + choices** | 11 scenes, choice node ids | Lines + stills yes | Story list; line/CG slots |
| **Level → story map** | Levels 1–11 verbs, goals, timers | Level config + gem art | Game pieces + listed map |
| **Gems / pieces** | Tea leaf, flower, lantern, coin, charm, wagashi | **Yes** | Swaps → pieces |
| **Cinematic stills** | scene-01…scene-11 assets | **Yes** | Swaps → cinematics |
| **UI chrome / textures** | Board lacquer, HUD | **Yes** | Swaps → ui |
| **Audio / VO** | Pitch, StoryVoice | Clips yes | Listed + optional slots |
| **Dialogue ledger** | Full line set, `{name}` | **Yes (lines)** | Swaps → dialogue lines; bulk list |
| **Progression / save** | Stars, affinity matrix | Schema listed | Listed only |
| **Engine / stack** | Three.js + Vite + Capacitor | N/A | Overview: engine badge |

---

## 2. What Studio had before this upgrade

| Present | Missing |
|---------|---------|
| Slot → asset bind for match tiles | Multi-project / multi-repo tabs |
| Validate / import Unity | Story arcs, scenes, choices |
| Single title focus | Cast, dialogue, rooms |
| | Engine / stack surface |
| | Drag-and-drop rebinding |
| | Graphify-style “map any project” entity kinds |
| | GitHub repo switcher |

---

## 3. Product model (tabs like a multi-sheet workbook)

```text
[ Project dropdown: GitHub repos ∪ catalog titles ]
    ├── Overview     engine, brand, gates, health
    ├── Swaps ★      drag-drop: art / pieces / lines / story beats
    ├── Story        arcs, scenes, choices (list + light graph)
    ├── Cast         characters + portrait slots
    └── Meta         levels map, audio, progression (lists)
```

★ = primary creative surface (what agents and you thrash on daily).

---

## 4. Swappable categories (drag-drop)

| Category | Slot kind / prefix | Example |
|----------|--------------------|---------|
| **Graphics** | `cg`, `bg`, `portrait`, `ui`, `sprite` | cinematic stills, room BGs |
| **Game pieces** | `slot.piece.*` / match gems | tea leaf gem art |
| **Character lines** | `slot.line.*` or dialogue binding | Ren welcome line variant |
| **Story elements** | scene body / choice text assets | scene markdown or ink chunk |

Non-swappable (list only): affinity math, save schema, ADR notes, device matrix.

---

## 5. Graphify as transposition layer

Graphify maps *code + docs* into a queryable knowledge graph (nodes, communities, paths). We **imitate the idea**, not fork the runtime yet:

| Graphify idea | Studio analogue |
|---------------|-----------------|
| God nodes | Characters, engine, board system |
| Communities | Story / puzzle / UI / audio |
| Path A→B | `scene → uses_slot → asset` |
| Beyond-code nodes | GDD entities already in catalog GGD |
| Query instead of grep | `/api/ggd`, slot filters, later MCP |

When a GitHub repo is selected:

1. Resolve `catalog/_meta/github_projects.yaml` mapping → `title_id`
2. If unmapped → show Overview from repo README only + “Create catalog title” stub
3. Optionally later: run graphify on `src/` + `docs/` for code map panel

---

## 6. Implementation priority

1. **Done:** multi-tab UI, GitHub repo list, Overview (engine), Story/Cast, Swaps drag-drop, tea-house seed  
2. **Done:** dialogue ledger (§13) → `dialogue.yaml` + `slot.line.tea.*` + `localization/en.yaml`  
3. **Done:** `public/assets` wired as catalog library (gems, BGs, portraits, cinematics) + bindings  
4. **Done:** Graphify-inspired **Code map** tab (`code_graph.json`, god nodes + communities)  
5. **Later:** two-way export back into Three.js `content.ts` / Addressables; agent job emit from drag-drop  

---

## 7. Mapping sakura-match (GitHub) ↔ catalog

| GitHub | Catalog `title_id` | Engine |
|--------|--------------------|--------|
| `CourtReinland/sakura-match` | `title.sakura_tea_house` | `engine.threejs_tea_house` |
| (local Unity sketch) | `title.sakura_match` | `engine.unity_match3` |
| `CourtReinland/sakurastudio` | — (this repo) | n/a |
