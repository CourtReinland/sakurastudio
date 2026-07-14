# Sakura Soft Catalog Schema

**Schema version:** `1.0.0`  
**Status:** draft (v0 — lock before building the GUI)  
**Purpose:** single source of truth for titles, design graph, assets, and agent jobs.

This catalog is the **data plane**. Chat is coordination. Engines (Unity, web) are adapters that *consume* catalog IDs — they do not own product meaning.

---

## 1. Goals

| Goal | How the schema supports it |
|------|----------------------------|
| Stop clumsy “swap image 8 with 201” | Stable `asset_id` + named `slot` + `binding` |
| Multi-title company | Shared brands/characters/engines; per-title GGD + bindings |
| Agent-safe long runs | Narrow job packages; validate against JSON Schema |
| Human + AI editability | YAML entities, git-diffable, no binary as truth |
| Otome + match-3 + future lines | Extensible `kind` enums; title `genre_tags` |
| Approval workflows | `status` on creative objects (draft → review → approved) |

### Non-goals (v1)

- Real-time multiplayer catalog sync
- Full Unreal/Unity editor replacement
- Binary asset storage *inside* git (use paths / LFS / content store; catalog holds metadata + relative paths)
- Automatic “taste” approval (humans approve CGs and ship)

---

## 2. Directory layout

```text
catalog/
  SCHEMA.md                 # this document
  schemas/                  # JSON Schema (draft 2020-12)
  _meta/
    catalog.yaml            # studio-wide meta (schema version, defaults)
  brands/
    <brand_id>/
      brand.yaml
  characters/               # optional shared cast pool (cross-title)
    <character_id>.yaml
  assets/
    library/
      <asset_id>.yaml       # one metadata file per library asset
      # binaries live outside or via path fields, e.g. files/…
  engines/
    <engine_id>.yaml
  titles/
    <title_id>/
      title.yaml            # title root
      cast.yaml             # cast entries (local and/or refs to shared)
      ggd.yaml              # game graph: nodes + edges
      slots.yaml            # semantic holes the runtime must fill
      bindings.yaml         # slot → asset (and other wiring)
      levels.yaml           # optional; match-3 / progression
      localization/         # optional; string tables by locale
      scenes/               # optional; large scene bodies split out
        <scene_id>.yaml
  jobs/
    examples/
    <job_id>.yaml           # agent task packages (or live under agents/)
```

**Rule:** anything an agent or human needs to *mean* something about the product lives here. Runtime code may cache/export copies, but catalog wins conflicts.

---

## 3. Identity rules

### 3.1 ID format

```
<type_prefix>.<dot.separated.slug>
```

| Prefix | Entity |
|--------|--------|
| `brand` | Brand / game line |
| `chr` | Character |
| `asset` | Library asset |
| `engine` | Engine pack |
| `title` | Shippable title |
| `slot` | Semantic content hole |
| `node` | GGD node (scene, route, level, …) |
| `edge` | GGD edge (optional explicit id) |
| `job` | Agent job |
| `str` | Localization string key |

**Slug rules**

- lowercase
- `[a-z0-9_]` only; dots separate hierarchy
- never reuse an ID for a different meaning
- never renumber (“image 8”) — IDs are permanent

**Good**

- `title.sakura_match`
- `slot.tile.red`
- `node.scene.prologue.cafe`
- `asset.tile_red_pastel_v1`
- `chr.sakura_match.miko`

**Bad**

- `img_8`, `CG21`, `final_final2.png` as IDs
- changing `slot.tile.red` to mean blue later

### 3.2 Human labels vs IDs

Every entity has:

- `id` — stable machine key  
- `label` — human UI string (can change)  
- optional `aliases[]` — search helpers, never used as foreign keys  

Agents and bindings always reference `id`.

### 3.3 Schema versioning

- `_meta/catalog.yaml` carries `schema_version: "1.0.0"`.
- JSON Schema files are the machine contract.
- Breaking changes bump minor/major; add a short migration note under `schemas/CHANGELOG.md` when that happens.
- Readers should reject unknown required fields carefully; **ignore unknown optional fields** (forward compatible).

---

## 4. Status & workflow

Shared enum `Status`:

| Value | Meaning |
|-------|---------|
| `draft` | WIP; agents may overwrite |
| `review` | Waiting on human (Brian) |
| `approved` | Safe for ship candidates |
| `deprecated` | Do not use for new bindings |
| `blocked` | Known problem; do not ship |

**Creative gate:** assets and story nodes that are player-facing should be `approved` before release jobs run. Validate can enforce this per title config.

---

## 5. Core entities

### 5.1 Catalog meta (`_meta/catalog.yaml`)

```yaml
schema_version: "1.0.0"
studio: sakura_soft
default_locale: en
locales: [en, ja]
path_conventions:
  asset_files_root: ../files   # relative to catalog/, or absolute later
id_prefixes:
  brand: brand
  character: chr
  asset: asset
  # …
```

### 5.2 Brand

Owns aesthetic line: palette, tone, style-guide refs, target audience.

```yaml
id: brand.sakura_soft
label: Sakura Soft
status: approved
style:
  aesthetic: soft pastel anime, kawaii
  audience: women 18-35
  palette:
    primary: "#FF8FAB"
    secondary: "#C8B6FF"
    accent: "#FFD6A5"
docs:
  - path: ../../shared/style-guides/sakura-soft.md
tags: [anime, casual, romance-friendly]
```

### 5.3 Character

Shared or title-local. Otome leads, side cast, mascots, narrator.

```yaml
id: chr.bloom.hiro
label: Hiro
status: draft
brand_id: brand.sakura_soft
role_tags: [love_interest, route_lead]
profile:
  age: 24
  occupation: architect
  one_liner: Quiet hands, loud storms.
  personality: [reserved, loyal, dry_humor]
voice:
  register: low-soft
  notes: never shout except route climax
visual:
  hair: black, slightly messy
  eyes: grey
  default_outfit: casual_coat
relationships: []   # optional graph edges to other chr.*
```

### 5.4 Asset (library)

A **file-backed** creative object. Not a game slot.

```yaml
id: asset.tile_red_pastel_v1
label: Match tile — red (pastel)
status: approved
brand_id: brand.sakura_soft
kind: sprite          # see AssetKind
files:
  - role: master
    path: files/tiles/red_pastel_v1.png
    mime: image/png
    width: 128
    height: 128
tags: [tile, match3, red, pastel]
characters: []        # chr.* if portrait/CG
provenance:
  source: generated   # generated | commissioned | stock | internal
  tool: grok_imagine
  prompt: "soft pastel red candy tile, kawaii match-3, no text"
  created_at: "2026-07-14"
  license: internal_all_rights
variants: []          # optional child asset ids (lang, resolution)
```

**AssetKind (v1):**  
`sprite` | `texture` | `cg` | `portrait` | `ui` | `icon` | `bg` | `audio_bgm` | `audio_sfx` | `audio_voice` | `font` | `video` | `spine` | `other`

### 5.5 Engine pack

Reusable runtime capability set. Titles declare which engine (and semver range) they use.

```yaml
id: engine.unity_match3
label: Unity Match-3 Kit
status: draft
runtime: unity
unity:
  min_version: "2022.3"
repo_path: projects/sakura-match   # until extracted to engines/
capabilities:
  - match3.grid
  - match3.swap
  - match3.cascade
exports:
  # how catalog maps into runtime (documentary for agents)
  bindings_consumer: AddressablesOrResources
  config_consumer: ScriptableObjects
```

### 5.6 Title

Root record for a shippable product.

```yaml
id: title.sakura_match
label: Sakura Match
status: draft
brand_id: brand.sakura_soft
engine_id: engine.unity_match3
genre_tags: [match3, casual, anime]
platforms: [ios, android]
repo_path: projects/sakura-match
default_locale: en
content_files:
  cast: cast.yaml
  ggd: ggd.yaml
  slots: slots.yaml
  bindings: bindings.yaml
  levels: levels.yaml
gates:
  require_approved_bindings_for_release: true
  require_approved_player_facing_nodes: true
```

### 5.7 Cast (`cast.yaml`)

Title-specific cast list: references shared characters and/or inlines local ones.

```yaml
title_id: title.sakura_match
entries:
  - character_id: chr.sakura_match.miko
    billing: heroine
    unlock: always
  - character_id: chr.sakura_match.narrator
    billing: system
    unlock: always
```

### 5.8 Slot (`slots.yaml`)

A **named hole** the product needs filled. Independent of which file currently fills it.

```yaml
title_id: title.sakura_match
slots:
  - id: slot.tile.red
    label: Board tile — Red
    kind: sprite
    required: true
    constraints:
      max_width: 256
      max_height: 256
      aspect_ratio: "1:1"
      tags_any: [tile, match3]
    used_by:
      - node.system.board
  - id: slot.ui.logo_title
    label: Title logo
    kind: ui
    required: true
    constraints:
      tags_any: [logo, ui]
```

**Why slots exist:** agents rebind slots; they do not invent new semantic names mid-task unless the job says so.

### 5.9 Binding (`bindings.yaml`)

Wiring: slot → asset (or config value). This is what replaces “swap image 8.”

```yaml
title_id: title.sakura_match
bindings:
  - slot_id: slot.tile.red
    asset_id: asset.tile_red_pastel_v1
    status: approved
    bound_at: "2026-07-14T12:00:00Z"
    bound_by: human.brian
  - slot_id: slot.tile.blue
    asset_id: asset.tile_blue_pastel_v1
    status: approved
```

**Operations agents should use**

- `sakura bind set <slot_id> <asset_id>` — change binding only  
- `sakura bind list` / `status` / `unbind`  
- never “replace file in place” without a new `asset_id` if provenance matters  

### 5.10 GGD — Game Graph Document (`ggd.yaml`)

Product structure as **nodes + edges**. This is the diagrammable heart of the studio GUI.

#### Node kinds (v1)

| Kind | Use |
|------|-----|
| `route` | Otome route / major path |
| `scene` | Playable scene / beat container |
| `beat` | Beat inside a scene (optional granularity) |
| `choice` | Player choice |
| `gate` | Condition (affection, flag, IAP, level clear) |
| `ending` | Ending node |
| `level` | Match-3 / progression level |
| `system` | Persistent system screen (board, gallery, shop) |
| `ui_screen` | Menu / settings / etc. |
| `cg_moment` | Story beat that expects a CG slot |
| `flag` | Story/gameplay flag definition |
| `minigame` | Embedded minigame |

#### Edge kinds (v1)

| Kind | Meaning |
|------|---------|
| `leads_to` | Narrative/flow succession |
| `unlocks` | Progress unlock |
| `requires` | Hard dependency (flag, asset slot, affection) |
| `uses_slot` | Node needs this slot filled |
| `modifies` | Sets flag / affection / currency |
| `contains` | Parent/child (route contains scenes) |
| `references` | Soft link (codex, gallery) |

#### Example (otome-shaped)

```yaml
title_id: title.bloom_and_blade
nodes:
  - id: node.route.hiro
    kind: route
    label: Hiro's Route
    status: draft
    data:
      love_interest: chr.bloom.hiro
  - id: node.scene.park_date
    kind: scene
    label: Park Date
    status: draft
    data:
      location: city_park
      estimated_minutes: 8
  - id: node.cg.park_kiss
    kind: cg_moment
    label: Park kiss CG
    status: draft
edges:
  - id: edge.route_hiro.contains.park
    kind: contains
    from: node.route.hiro
    to: node.scene.park_date
  - id: edge.park.uses.cg
    kind: uses_slot
    from: node.scene.park_date
    to: slot.cg.hiro.park_kiss
```

#### Example (match-3-shaped)

```yaml
title_id: title.sakura_match
nodes:
  - id: node.system.board
    kind: system
    label: Match-3 Board
    status: draft
  - id: node.level.1_1
    kind: level
    label: 1-1 First Bloom
    status: draft
    data:
      grid: { width: 8, height: 8 }
      moves: 20
      goals:
        - { type: score, value: 5000 }
edges:
  - id: edge.level.1_1.requires.board
    kind: requires
    from: node.level.1_1
    to: node.system.board
  - id: edge.board.uses.tile_red
    kind: uses_slot
    from: node.system.board
    to: slot.tile.red
```

Large scene dialogue bodies may live in `scenes/<id>.yaml` and be referenced from the node via `data.body_ref`.

### 5.11 Levels (`levels.yaml`) — optional convenience

For match-3, level nodes in GGD can stay light and point at structured level rows:

```yaml
title_id: title.sakura_match
levels:
  - id: node.level.1_1
    chapter: 1
    index: 1
    moves: 20
    grid: { width: 8, height: 8 }
    tile_pool:
      - slot.tile.red
      - slot.tile.blue
      - slot.tile.green
      - slot.tile.yellow
      - slot.tile.purple
    goals:
      - type: score
        value: 5000
```

### 5.12 Localization (optional)

```yaml
# titles/<id>/localization/en.yaml
locale: en
strings:
  str.ui.play: Play
  str.ui.settings: Settings
  str.level.1_1.title: First Bloom
```

Player-facing copy should use `str.*` keys, not hardcoded UI strings in C#.

### 5.13 Agent job (`jobs/*.yaml`)

Contracts for unattended work. Compatible in spirit with existing `task_config.yaml`, but catalog-scoped.

```yaml
id: job.2026_07_14.rebind_tiles
title_id: title.sakura_match
role: art_integrator
status: draft
goal: Bind pastel tile assets to board tile slots
constraints:
  - only_edit: [bindings.yaml]
  - do_not_edit: [ggd.yaml, cast.yaml]
  - no_merge_to_main: true
scope:
  slot_ids:
    - slot.tile.red
    - slot.tile.blue
    - slot.tile.green
    - slot.tile.yellow
    - slot.tile.purple
acceptance:
  - validate_bindings
  - all_scoped_slots_bound
  - binding_status_at_least: review
handoff:
  branch: feature/catalog-tile-bindings
  open_pr: true
```

**Roles (align with existing Sakura agents)**

| Role | Typical write scope |
|------|---------------------|
| `narrative` | ggd, scenes, cast, localization |
| `art_integrator` | assets library meta, bindings |
| `gameplay` | levels, engine-facing config exports |
| `qa` | jobs reports, not product content |
| `architect` | engines, title root, schema proposals |
| `release` | status gates, version fields |

---

## 6. Validation rules (v1)

Implement with `sakura validate` (see `tools/sakura/`); encode as policy:

1. **Referential integrity** — every `*_id` foreign key resolves.  
2. **Bindings** — every `required: true` slot has exactly one active binding (or explicit `unbound` exception list).  
3. **Asset constraints** — bound asset `kind` matches slot `kind`; dimension/tag constraints when present.  
4. **GGD** — edges reference existing nodes/slots; no dangling `from`/`to`.  
5. **ID format** — match prefix + slug rules.  
6. **Status gates** — if `gates.require_approved_bindings_for_release`, release jobs fail on non-approved bindings.  
7. **Job scope** — files touched outside `constraints.only_edit` fail CI.  
8. **No silent ID rewrite** — renames require explicit migration entry.

---

## 7. Mapping to Unity (sakura-match today)

| Catalog | Runtime today | Future |
|---------|---------------|--------|
| `slot.tile.*` + bindings | `Resources/Sprites/Tiles/*.png` + `TileType` enum | Addressables keyed by slot id |
| `levels.yaml` / GGD level nodes | `GameConfig` ScriptableObject | Generated SO or JSON import |
| `brand` palette | hardcoded in tasks | shared style tokens |
| agent `task_config.yaml` | free-text tasks | generated from `jobs/*.yaml` |

**Import rule for agents:** when implementing features, read catalog first; do not invent new tile color names that are not slots.

---

## 8. Mapping to agent chat

**Before (bad)**  
> swap images 8, 21, 55 with 201, 30, 95

**After (good)**  
> Run `job.…` / rebind:  
> - `slot.tile.red` → `asset.tile_red_pastel_v2`  
> - `slot.cg.hiro.park_kiss` → `asset.cg_hiro_park_kiss_v3`  
> then `sakura validate --title title.sakura_match`

The GUI will eventually emit that job YAML from drag-and-drop.

---

## 9. Extension points (do not implement yet)

- `markets` (App Store metadata, age rating) as title side files  
- `liveops` events as GGD node kinds  
- multi-variant bindings per locale (`bindings.ja.yaml`)  
- content-addressed blob store (`sha256:…`) replacing relative paths  
- Graphify bridge: export GGD + code symbols into one query surface  

---

## 10. File format conventions

- YAML 1.2, UTF-8  
- 2-space indent  
- keys: `snake_case`  
- dates: ISO-8601  
- booleans: `true`/`false`  
- do not use YAML anchors for cross-file refs — always use string IDs  

---

## 11. Minimal viable catalog (what we lock first)

For **sakura-match** v0:

1. `_meta/catalog.yaml`  
2. `brands/sakura-soft/brand.yaml`  
3. `engines/unity_match3.yaml`  
4. `titles/sakura-match/title.yaml`  
5. Tile slots + bindings + library assets for 5 colors  
6. GGD with `node.system.board` + sample level  
7. One example agent job  

Otome skeleton lives under `titles/_examples/otome-skeleton/` as a template, not a ship title.

---

## 12. Decision log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Format | YAML + JSON Schema | Diffable, agent-editable, validatable |
| Asset model | Library + slots + bindings | Industry DAM pattern; chat-proof |
| GGD | Explicit nodes/edges | GUI + agent path queries |
| IDs | Prefixed stable strings | No ordinal (“image 8”) fragility |
| Binaries | Path metadata, not embedded | Git stays sane |
| Jobs | First-class YAML | Unattended agents need contracts |

---

*Implemented:* `sakura validate`, `sakura bind`, `sakura import` (Unity Resources), `sakura studio` (thin GUI).
