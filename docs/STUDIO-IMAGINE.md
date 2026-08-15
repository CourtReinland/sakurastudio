# Sakura Studio · Grok Imagine & style board

How art generation, edit-with-refs, the **Canvas** tab, and the **project style board** work in Studio (v0.5.3+).

## Quick start

1. Put `XAI_API_KEY` in `SakuraSoft/.env` (from [console.x.ai](https://console.x.ai)).
2. Launch Studio: `./shared/scripts/sakura-studio.sh` → http://127.0.0.1:8787/
3. Project dropdown defaults to **Sakura Tea House** (`title.sakura_tea_house`) when present.
4. Open **Canvas** to iterate a look against mood-board / style refs (first-party; no grok.com iframe).
5. Or open **Swaps**, pick a slot: **Imagine** (new) or **Edit…** (refine with references).
6. (Optional) Set **Style lock** on Canvas or Swaps — they share one `studio.yaml` board.

## Architecture

```text
Prompt (+ refs)  →  Studio API  →  xAI Imagine  →  catalog asset  →  optional slot bind
                         ↑
              title studio.yaml style board (optional)
```

| Surface | Mode | Refs |
|---------|------|------|
| **Canvas · Generate** | Text → new art | None, selected mood-board pins, **or** style lock alone |
| **Canvas · Iterate** | Edit last stage + pins | Stage image + up to 3 send-checked pins (subject first, then style) |
| **Swaps · Imagine** | Text → new art | None, **or** style board alone if lock is ON |
| **Swaps · Edit…** | Refine existing | 1–3 images; style board appended if ON |

Results are always **new** library assets (`asset.studio.*`) under `catalog/assets/`. Originals are never overwritten. Canvas leaves bind optional; Swaps auto-binds the slot.

## Canvas tab

Desktop layout (~1280+): **mood-board rail** (left) · **center stage** · **prompt bar** · **history strip**.

### Mood board

Pin 1–N references from:

- Catalog image assets (**+ Catalog**)
- Repo `moodboards/` files — Gemini / Suki / pixiv refs (**+ Moodboards**)
- Local files (**+ File** or drag/drop) — uploaded as a new catalog asset, then pinned

Each pin has **subject** vs **style** and a **send** checkbox. xAI Imagine edit accepts at most **3** images. Extra pins stay on the board; the active 3 are outlined. Style pins are sent after subjects. Style lock (if ON) is still injected last by the server and may replace the 3rd ref.

### Stage, generate, iterate

- Empty stage invites generate or a dropped ref.
- **Generate** — no refs (or style-lock / selected pins only).
- **Iterate** — edit the staged output plus selected refs.
- Quality toggle: `fast` (`grok-imagine-image`) vs `quality` (`grok-imagine-image-quality`).
- History thumbs promote to stage; **Use stage as next ref** pins the look.

### Actions

- Every run **saves** a new `asset.studio.*` (same `/api/imagine` path as Swaps).
- Optional **Bind to slot** for a Tea House CG / BG / piece / UI slot.
- **Style lock** writes `catalog/titles/<title>/studio.yaml` via `GET/POST /api/studio-style` — shared with Swaps.

### Extra APIs (Canvas only)

```http
GET /api/moodboards
GET /api/moodboard-file?path=gemini/ref.png
GET /api/studio-recent?limit=16
```

`POST /api/imagine` `references[]` also accepts `{ "kind": "moodboard", "path": "…", "role": "style" }`.

## Project style board

Per-title settings live in:

```text
catalog/titles/<title>/studio.yaml
```

Example:

```yaml
title_id: title.sakura_tea_house
style:
  enabled: true
  asset_id: asset.piece.tea.flower   # any catalog image asset
  notes: Soft dusk lacquer, warm pastels, no harsh outlines
```

### UI

**Canvas** rail and top of **Swaps** share the same lock:

- **Style asset** dropdown (library)
- **Style lock ON/OFF** toggle (auto-saves)
- **Save style** on Swaps (also persists dropdown selection)
- Thumbnail when an asset is set

### Behaviour when lock is **ON** and `asset_id` is set

| Action | What happens |
|--------|----------------|
| **Imagine** | Request becomes an **edit** with the style image as the reference; prompt describes the new subject. Style instruction is appended server-side. |
| **Edit…** | Your refs (content first) are sent; style asset is **appended last** if not already in the list (max **3** total; if full, last ref is replaced by style). |
| Toggle **OFF** | No style injection; pure generate or your refs only. |

API field: `use_style_board` (default `true`) on `POST /api/imagine`. Set `false` to skip for a single call even if lock is on.

### APIs

```http
GET  /api/studio-style?title=title.sakura_tea_house
POST /api/studio-style
{
  "title_id": "title.sakura_tea_house",
  "enabled": true,
  "asset_id": "asset.xxx",
  "clear_asset": false
}
```

## Edit with multiple references

1. Click **Edit…** on a slot.
2. Default ref = current bound / selected image.
3. **×** removes a ref; **+** adds a local file; drag a library asset onto the strip.
4. Max **3** images (xAI Imagine multi-image edit limit).
5. Write the change prompt → **Apply edit → slot**.

There is **no** separate `style_ref` parameter on the xAI API. Style is either:

- text in the prompt, or  
- one of the image refs + prompt language (Studio’s style board does this automatically).

### Prompt tip for manual style + content

> Image 1 is the subject — keep composition and identity.  
> Image 2 is style only — match line, palette, finish. Do not copy image 2’s subject.  
> Change only: …

## Grok Imagine capabilities (current API surface)

### Image generate — `POST /v1/images/generations`

| Input | Notes |
|-------|--------|
| `prompt` | Required |
| `model` | `grok-imagine-image` (fast) or `grok-imagine-image-quality` |
| `n` | Up to 10 variations (Studio always uses 1) |
| `aspect_ratio` | `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, …, `auto` |
| `resolution` | `1k` or `2k` (Studio default `1k`) |
| `response_format` | URL or `b64_json` |

No image inputs on pure generate.

### Image edit — `POST /v1/images/edits`

| Input | Notes |
|-------|--------|
| `prompt` | Required |
| `image` | 1 object, or multi-image (up to **3**) |
| Each image | Public URL, base64 data URI, or Files API `file_id` |
| `aspect_ratio` | Multi-image: controllable; single image often keeps source aspect |
| `resolution` | `1k` / `2k` |
| `model` | Same Imagine image models |

Documented multi-image uses: combine subjects, **transfer styles**, compose scenes. Order matters; default aspect follows the **first** image.

### Also in Imagine (not in Canvas / Swaps UI yet)

- Image → video, reference-to-video, video edit/extend
- Files API persistence of inputs/outputs

Canvas covers multi-turn stills (history → stage → iterate). Video stays on the Assets / game-asset tools path.

## Studio ↔ catalog files

| Path | Role |
|------|------|
| `catalog/assets/library/*.yaml` | Asset metadata |
| `catalog/assets/files/studio/` | Uploaded / generated binaries |
| `catalog/titles/*/bindings.yaml` | Slot → asset |
| `catalog/titles/*/studio.yaml` | Style board + future Studio prefs |
| `moodboards/` | Loose style/content refs for Canvas (not catalog assets) |

## Auth note

Studio uses **console API keys** (`XAI_API_KEY`), not Grok Build browser OAuth. OAuth is for the Grok CLI/coding session; Imagine billing for Studio is the API key path.

## Related docs

- [`GDD-DASHBOARD-GAP.md`](./GDD-DASHBOARD-GAP.md) — product tab roadmap  
- [`catalog/SCHEMA.md`](../catalog/SCHEMA.md) — asset provenance (`tool: grok_imagine`)  
- [xAI Imagine overview](https://docs.x.ai/developers/model-capabilities/imagine)  
- [Image editing](https://docs.x.ai/developers/model-capabilities/images/editing)  
- [Multi-image editing](https://docs.x.ai/developers/model-capabilities/images/multi-image-editing)  
