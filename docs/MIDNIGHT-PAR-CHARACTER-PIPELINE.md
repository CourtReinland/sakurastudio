# Midnight Par / Nightmare Golf — character pipeline diagnosis

**Game:** [CourtReinland/nightmaregolf](https://github.com/CourtReinland/nightmaregolf) (local checkout via `SAKURA_GAME_ROOT` / `NIGHTMARE_GOLF_ROOT`)  
**Catalog title:** `title.midnight_par`  
**Date:** 2026-07-19  

## Executive summary

The walk/swing “gank” is **not** primarily a Swaps binding bug. Catalog slots map correctly to PNG files. The problems stack:

1. **Wrong generation method** for animation frames (independent still gens, not video-first identity-locked cycle).  
2. **Runtime facing logic inverted** relative to actual art (right-facing cutouts treated as left-facing).  
3. **Texture swap without re-scaling** when frame aspect/content bbox differs → feet/scale pop.  
4. **Studio ↔ game is one-way copy**, not live binding — rebinding in Swaps does not change what Three.js loads until binaries are re-exported.  
5. **Flow had no character/world entities**, so anim + voice + hero image were disconnected lists.

## Skill suite vs Studio Assets tools

| Official skill | Studio Assets ✦ | Gap |
|----------------|-----------------|-----|
| **game-asset-core** — isolated subject, keyable BG, no text, edit-chain same character | Core tool forces similar prompt suffix | Studio does not yet run blind read-back / defect flagging |
| **game-animation-frames** — **video-first**: base → `image_to_video` → harvest → flip-test loop | Animation tool uses **still pose edit-chain** only | **Critical for walk cycles** — still pose guessing produces non-looping, non-gait frames |
| **game-character-consistency** — one base, freeze-list edits, asymmetry bookkeeping | Character tool edit-chains with freeze-list | No turnaround side-map verification UI |
| **game-tilesets** — seamless + 2×2 composite check | Tileset tool does 2×2 | OK |
| **game-ui-icons** — state freeze-list, 32px legible | UI icons batch | No hover/pressed state variants yet |

`tools/gen_anim.py` in the game repo generates each Hana walk frame as a **fresh** `images/generations` call with a different pose sentence — the opposite of video-first + identity lock. Frames are same size (864×1152) and somewhat similar (pixel diff ~22–26) but **not** a real gait period.

## Runtime analysis (`js/engine.js`)

```text
idle:  hana_full.png
walk:  hana_walk1,2,3  → sequence [0,1,2,1] @ ~7 fps
swing: hana_swing1 (backswing), hana_swing2 (follow-through)
```

### Facing

- Art mass analysis: Hana cutouts are **RIGHT-heavy** (face/body toward image right).  
- Old code assumed “default art faces **left**” and flipped when aim was screen-right → **wrong direction relative to the ball**.  
- **Fix applied:** faceSign = right-facing; face walk direction while moving; face aim when planted; preserve scale sign on texture swap.

### Scale pop

- `_hanaFrame` only swapped `material.map`. Different frame content boxes / aspects left the sprite scale from the idle texture.  
- **Fix applied:** recompute `scale` from texture aspect × fixed height, keep facing sign.

### Catalog ↔ game

| Layer | Path |
|-------|------|
| Catalog master | `catalog/assets/files/midnight_par/img/cut/hana_walk1.png` |
| Slot | `slot.sprite.par.anim_hana_walk1` → `asset.sprite.par.anim_hana_walk1` |
| Game loads | **hardcoded** `assets/img/cut/hana_walk1.png` |

Swaps rebinds change the catalog YAML only. Live game needs a re-copy (`sakura_integrate` / export step) or a future runtime manifest.

## Expert pipeline for Hana walk (what “good” looks like)

1. **Base idle** — side or ¾ view consistent with gameplay (billboard sprite). Keyable BG.  
2. **Video-first cycle** (skill): `image_to_video` “walks in place, side view, camera locked, 6s”.  
3. **Harvest** dense frames; **select one period** (foot contacts); flip-test last→first.  
4. **Clean** BG/palette with edit if video drifted; **do not** change pose.  
5. **Normalize** canvas size, feet on same baseline, **same facing** for all frames.  
6. **Package** zero-padded names + optional sheet; set fps in engine.  
7. **Engine:** face using movement vector; optional root-motion vs in-place + world lerp (current = world lerp + in-place flipbook).

Golf swing: 3–6 **key** poses from base (anticipation → impact → follow-through), freeze body identity — not two random stills.

## Studio product direction (your node vision)

```text
[Character: Hana] ──hero portrait──► portrait asset
       │
       ├──full body──► idle sprite
       ├──walk cycle──► [anim_clip walk] ──frames──► walk1..n slots/assets
       ├──swing clip──► [anim_clip swing]
       └──speaks with──► voice map (ElevenLabs v3 + [tags])

[World: course] ──contains──► hole 11 / 12 / 13
       │
       └──uses──► turf texture, sky, lighting (slots)

[Engine] ──runs──► world + systems
```

**Implemented now:**
- Flow **character** + **anim_clip** + **world** nodes for Midnight Par  
- **Double-click character** → inspector: portrait, body, walk/swing filmstrip, voice, pipeline diagnosis, jumps to Swaps / Assets / Dialogue  
- Nightmare Golf engine facing + scale fixes  

## Status (goal 2026-07-19)

| Item | Status |
|------|--------|
| Engine facing + scale fix | **Done** (`js/engine.js`) |
| Video-first Hana walk (8 frames) | **Done** — image_to_video → harvest → rembg → catalog + game |
| `POST /api/export-game` + header button | **Done** |
| Runtime `assets/catalog_bindings.json` | **Done** — engine prefers manifest walk list |
| Flow character double-click inspector | **Done** |
| Flow world inspector (turf/sky slots) | **Done** |
| Studio Assets animation = video-first | **Done** (fallback still-chain) |

### How to re-export after Swaps rebinds

Studio header **Export → Game** (or `POST /api/export-game` with `title_id=title.midnight_par`).

## Quick verification

```bash
# Studio
curl -s 'http://127.0.0.1:8787/api/character-bundle?title=title.midnight_par&character_id=chr.par.hana' | jq '.clips.walk.count,.diagnosis'
curl -s -X POST http://127.0.0.1:8787/api/export-game -H 'Content-Type: application/json' \
  -d '{"title_id":"title.midnight_par"}'

# Game — hard refresh; Hana walk uses 8 video-first frames; faces aim/walk correctly.
ls assets/img/cut/hana_walk*.png
cat assets/catalog_bindings.json | head -30
```

## Status (goal 2026-07-19)

| Item | Status |
|------|--------|
| Engine facing + scale fix | **Done** |
| Video-first Hana walk (8 frames) | **Done** |
| Export → Game API + header button | **Done** |
| `assets/catalog_bindings.json` runtime manifest | **Done** |
| Flow character double-click inspector | **Done** |
| Flow world inspector (turf/sky) | **Done** |
| Assets ✦ animation video-first | **Done** |
