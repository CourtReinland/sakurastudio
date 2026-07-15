# Sakura Studio · Grok Imagine & style board

How art generation, edit-with-refs, and the **project style board** work in Studio (v0.5.3+).

## Quick start

1. Put `XAI_API_KEY` in `SakuraSoft/.env` (from [console.x.ai](https://console.x.ai)).
2. Launch Studio: `./shared/scripts/sakura-studio.sh` → http://127.0.0.1:8787/
3. Open **Swaps ★**, pick a project title.
4. (Optional) Set **Project style board** → choose a style asset → toggle **Style lock ON**.
5. On a slot: **Imagine** (new) or **Edit…** (refine with references).

## Architecture

```text
Prompt (+ refs)  →  Studio API  →  xAI Imagine  →  catalog asset  →  slot bind
                         ↑
              title studio.yaml style board (optional)
```

| Mode | When | Refs |
|------|------|------|
| **Imagine** | Text → new art | None, **or** style board alone if lock is ON |
| **Edit…** | Refine existing | 1–3 images (content + optional extras); style board appended if ON |

Results are always **new** library assets (`asset.studio.*`) under `catalog/assets/`, then bound to the slot. Originals are not overwritten.

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

Top of **Swaps**:

- **Style asset** dropdown (library)
- **Style lock ON/OFF** toggle (auto-saves)
- **Save style** (also persists dropdown selection)
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

### Also in Imagine (not in Swaps UI yet)

- Multi-turn edit (chain outputs)
- Image → video, reference-to-video, video edit/extend
- Files API persistence of inputs/outputs

## Studio ↔ catalog files

| Path | Role |
|------|------|
| `catalog/assets/library/*.yaml` | Asset metadata |
| `catalog/assets/files/studio/` | Uploaded / generated binaries |
| `catalog/titles/*/bindings.yaml` | Slot → asset |
| `catalog/titles/*/studio.yaml` | Style board + future Studio prefs |

## Auth note

Studio uses **console API keys** (`XAI_API_KEY`), not Grok Build browser OAuth. OAuth is for the Grok CLI/coding session; Imagine billing for Studio is the API key path.

## Related docs

- [`GDD-DASHBOARD-GAP.md`](./GDD-DASHBOARD-GAP.md) — product tab roadmap  
- [`catalog/SCHEMA.md`](../catalog/SCHEMA.md) — asset provenance (`tool: grok_imagine`)  
- [xAI Imagine overview](https://docs.x.ai/developers/model-capabilities/imagine)  
- [Image editing](https://docs.x.ai/developers/model-capabilities/images/editing)  
- [Multi-image editing](https://docs.x.ai/developers/model-capabilities/images/multi-image-editing)  
