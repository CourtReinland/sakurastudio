"""
Sakura Studio game-asset tools — Studio port of the Grok Build skill suite:

  game-asset-core · game-character-consistency · game-tilesets
  game-ui-icons · game-animation-frames

These encode engine-ready defaults (isolated subjects, keyable backgrounds,
seamless tiles, no UI text, identity-locked character edits) and run through
the existing Grok Imagine + catalog asset pipeline.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

from sakura.asset_write import create_image_asset
from sakura.imagine_client import (
    DEFAULT_MODEL,
    QUALITY_MODEL,
    edit_image,
    generate_image,
)
from sakura.loader import load_catalog
from sakura.studio_style import load_studio_style

# ---------------------------------------------------------------------------
# Tool catalog (surfaced in Studio UI)
# ---------------------------------------------------------------------------

GAME_ASSET_TOOLS: list[dict[str, Any]] = [
    {
        "id": "core",
        "skill": "game-asset-core",
        "label": "Core sprite / prop",
        "icon": "◆",
        "summary": "Isolated game-ready subject on a flat keyable background.",
        "instructions": [
            "Describe one subject (gem, prop, portrait, cinematic still).",
            "Studio forces: isolated subject, flat solid keyable BG (chroma or pure color), no text, no UI chrome, no watermark.",
            "Project style board (if ON) is injected as a style reference automatically.",
            "Result is written into the catalog library and optionally bound to a slot.",
        ],
        "fields": [
            {"name": "prompt", "type": "textarea", "label": "Describe the asset", "required": True},
            {
                "name": "kind",
                "type": "select",
                "label": "Catalog kind",
                "options": ["sprite", "portrait", "cg", "bg", "ui", "icon", "texture"],
                "default": "sprite",
            },
            {
                "name": "aspect_ratio",
                "type": "select",
                "label": "Aspect",
                "options": ["1:1", "9:16", "16:9", "3:4", "4:3"],
                "default": "1:1",
            },
            {"name": "slot_id", "type": "text", "label": "Bind to slot (optional)", "required": False},
            {"name": "bg_color", "type": "text", "label": "Key color", "default": "pure #00FF00 chroma green"},
        ],
    },
    {
        "id": "character",
        "skill": "game-character-consistency",
        "label": "Character consistency",
        "icon": "◇",
        "summary": "Identity-locked variants from one base (turnaround, expression, gear, damage).",
        "instructions": [
            "Pick a base character asset (or generate a base first with Core).",
            "Choose a variation mode — everything is an edit of that base, not a new generation.",
            "Freeze-list is enforced in the prompt: face, hair, body proportions, costume silhouette stay locked.",
            "Use for turnarounds, expressions, damage states, palette swaps, equipment overlays.",
        ],
        "fields": [
            {"name": "base_asset_id", "type": "asset", "label": "Base character asset", "required": True},
            {
                "name": "mode",
                "type": "select",
                "label": "Variation",
                "options": [
                    "turnaround_front",
                    "turnaround_side",
                    "turnaround_back",
                    "expression",
                    "damage",
                    "equipment",
                    "palette_swap",
                ],
                "default": "expression",
            },
            {"name": "prompt", "type": "textarea", "label": "What changes (only)", "required": True,
             "placeholder": "e.g. soft smile, eyes half-closed, warm lantern light"},
            {"name": "slot_id", "type": "text", "label": "Bind to slot (optional)"},
        ],
    },
    {
        "id": "tileset",
        "skill": "game-tilesets",
        "label": "Tileset / seamless tile",
        "icon": "▦",
        "summary": "Seamless tile with automatic 2×2 composite seam check.",
        "instructions": [
            "Describe the tile motif (floor lacquer, grass, stone path, match gem).",
            "Prompt forces edge-seamless repeating texture, no text, even lighting.",
            "Studio generates the tile, then builds a 2×2 composite so you can spot seams and tone checkerboarding.",
            "Both the master tile and the 2×2 check image are saved to the catalog.",
        ],
        "fields": [
            {"name": "prompt", "type": "textarea", "label": "Tile description", "required": True},
            {"name": "tile_px", "type": "select", "label": "Tile size", "options": ["64", "128", "256"], "default": "128"},
            {"name": "slot_id", "type": "text", "label": "Bind to slot (optional)"},
        ],
    },
    {
        "id": "ui_icons",
        "skill": "game-ui-icons",
        "label": "UI icon set",
        "icon": "▣",
        "summary": "Geometry-consistent icon family under one style contract.",
        "instructions": [
            "List icon names (comma-separated): save, settings, heart, coin, map…",
            "All icons share stroke weight, corner radius, and empty/flat keyable background.",
            "No readable text glyphs inside icons (labels live in UI code).",
            "Each icon becomes its own catalog asset with shared provenance.",
        ],
        "fields": [
            {"name": "style_prompt", "type": "textarea", "label": "Shared style contract", "required": True,
             "placeholder": "soft sakura pastel UI, 2px rounded stroke, flat fill, subtle lacquer sheen"},
            {"name": "icons", "type": "text", "label": "Icon names (comma-separated)", "required": True,
             "placeholder": "save, settings, heart, coin, back"},
            {"name": "bg_color", "type": "text", "label": "Key color", "default": "pure #00FF00 chroma green"},
        ],
    },
    {
        "id": "animation",
        "skill": "game-animation-frames",
        "label": "Animation frames",
        "icon": "▸",
        "summary": "Pose-sequence frames from a base sprite (walk / idle / attack).",
        "instructions": [
            "Pick a base sprite (isolated character on keyable BG).",
            "Describe the cycle (walk right, idle breathe, attack slash).",
            "Studio generates N still frames via edit-chaining from the base (identity freeze-list).",
            "Frames are saved as ordered assets: …_f01, …_f02, … ready for spritesheet packing.",
            "Official skill (game-animation-frames) is VIDEO-FIRST: base → image_to_video → ffmpeg harvest → flip-test loop.",
            "Studio currently chains still pose edits (fallback). For walk cycles that look natural, regenerate offline with the skill’s video pipeline, then re-import frames into these slots.",
        ],
        "fields": [
            {"name": "base_asset_id", "type": "asset", "label": "Base sprite asset", "required": True},
            {"name": "prompt", "type": "textarea", "label": "Cycle description", "required": True,
             "placeholder": "side-view walk cycle, left to right, light bounce, kimono sleeve sway"},
            {"name": "frame_count", "type": "select", "label": "Frames", "options": ["6", "8", "10", "12"], "default": "8"},
            {"name": "slot_id", "type": "text", "label": "Bind first frame to slot (optional)"},
        ],
    },
]


def tool_catalog() -> list[dict[str, Any]]:
    return GAME_ASSET_TOOLS


def _model(quality: bool) -> str:
    return QUALITY_MODEL if quality else DEFAULT_MODEL


def _style_refs(catalog, title_id: str | None, use_style: bool) -> list[tuple[bytes, str]]:
    if not use_style or not title_id:
        return []
    style = load_studio_style(catalog, title_id)
    if not (style.get("enabled") and style.get("asset_id")):
        return []
    index = load_catalog(catalog, include_examples=True)
    ent = index.assets.get(style["asset_id"])
    if not ent:
        return []
    files = ent.data.get("files") or []
    master = next(
        (f for f in files if isinstance(f, dict) and f.get("role") == "master"),
        files[0] if files else None,
    )
    if not isinstance(master, dict) or not master.get("path"):
        return []
    path = (catalog / str(master["path"])).resolve()
    if not path.is_file():
        return []
    mime = master.get("mime") or "image/png"
    return [(path.read_bytes(), str(mime))]


def _load_asset_bytes(catalog, asset_id: str) -> tuple[bytes, str]:
    index = load_catalog(catalog, include_examples=True)
    ent = index.assets.get(asset_id)
    if not ent:
        raise ValueError(f"Unknown asset: {asset_id}")
    files = ent.data.get("files") or []
    master = next(
        (f for f in files if isinstance(f, dict) and f.get("role") == "master"),
        files[0] if files else None,
    )
    if not isinstance(master, dict) or not master.get("path"):
        raise ValueError(f"No master file on {asset_id}")
    path = (catalog / str(master["path"])).resolve()
    if not path.is_file():
        raise ValueError(f"Missing file for {asset_id}")
    mime = master.get("mime") or "image/png"
    return path.read_bytes(), str(mime)


def _bind(catalog, title_id: str | None, slot_id: str | None, asset_id: str) -> dict[str, Any] | None:
    if not title_id or not slot_id:
        return None
    from sakura.bind import bind_set

    r = bind_set(
        catalog=catalog,
        title=title_id,
        slot_id=slot_id,
        asset_id=asset_id,
        status="review",
        bound_by="studio.game_assets",
        notes="game_asset_tool",
        force=True,
        no_validate=True,
        include_examples=True,
    )
    return {"ok": r.ok, "message": r.message}


CORE_SUFFIX = (
    "Game production sprite sheet element. Single isolated subject, centered. "
    "Flat solid keyable background (no gradient, no scene, no props except the subject). "
    "No text, no watermark, no UI chrome, no logo, no border frame. "
    "Clean silhouette, engine-ready, even lighting."
)

TILE_SUFFIX = (
    "Seamless repeating tile texture for a 2D game. Perfect edge wrap in all directions. "
    "No text, no logo, even lighting, no strong vignette. "
    "Motif density suitable for tiling without obvious seams or checkerboard tone shifts."
)

UI_ICON_SUFFIX = (
    "Single game UI icon, centered, geometry simple and legible at 32px. "
    "Flat solid keyable background. No text glyphs, no letters, no numbers. "
    "Consistent stroke weight and corner radius. One icon only."
)


def _make_2x2_composite(tile_bytes: bytes, tile_px: int = 128) -> bytes:
    im = Image.open(BytesIO(tile_bytes)).convert("RGBA")
    im = im.resize((tile_px, tile_px), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (tile_px * 2, tile_px * 2))
    for y in range(2):
        for x in range(2):
            out.paste(im, (x * tile_px, y * tile_px))
    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def run_core(
    catalog,
    *,
    prompt: str,
    kind: str = "sprite",
    aspect_ratio: str = "1:1",
    title_id: str | None = None,
    slot_id: str | None = None,
    bg_color: str = "pure #00FF00 chroma green",
    quality: bool = True,
    use_style_board: bool = True,
) -> dict[str, Any]:
    full = (
        f"{prompt.strip()}. Background: {bg_color}. {CORE_SUFFIX}"
    )
    model = _model(quality)
    style = _style_refs(catalog, title_id, use_style_board)
    if style:
        # style-conditioned generate via edit with style as sole ref
        img = edit_image(
            full + " Match the style of the reference image only — do not copy its subject.",
            images=style,
            model=model,
            aspect_ratio=aspect_ratio,
        )
        tool = "game_asset_core_style"
    else:
        img = generate_image(full, model=model, aspect_ratio=aspect_ratio)
        tool = "game_asset_core"

    created = create_image_asset(
        catalog,
        image_bytes=img,
        kind=kind if kind in {
            "sprite", "portrait", "cg", "bg", "ui", "icon", "texture"
        } else "sprite",
        base_name="core",
        label=f"Core · {prompt.strip()[:48]}",
        mime="image/png",
        tags=["game_asset", "core", "keyable"],
        provenance={"source": "generated", "tool": tool, "prompt": full, "skill": "game-asset-core"},
    )
    bind = _bind(catalog, title_id, slot_id, created["asset_id"])
    return {"ok": True, "tool": "core", "assets": [created], "bind": bind, "message": f"Core asset {created['asset_id']}"}


def run_character(
    catalog,
    *,
    base_asset_id: str,
    mode: str,
    prompt: str,
    title_id: str | None = None,
    slot_id: str | None = None,
    quality: bool = True,
    use_style_board: bool = True,
) -> dict[str, Any]:
    base_bytes, base_mime = _load_asset_bytes(catalog, base_asset_id)
    mode_dir = {
        "turnaround_front": "front-facing turnaround pose, same character, full body if base is full body",
        "turnaround_side": "strict side-profile turnaround, same character, same scale",
        "turnaround_back": "back view turnaround, same character, same scale",
        "expression": "same character, change only facial expression as described",
        "damage": "same character, damaged/battle-worn state only as described",
        "equipment": "same character, add/change equipment only as described",
        "palette_swap": "same character silhouette and design, recolor palette only as described",
    }.get(mode, "same character variation")

    freeze = (
        "FREEZE (must not change): face identity, hair shape, body proportions, "
        "costume silhouette, art style, line weight, and keyable background treatment. "
        "This is an edit of the reference, not a new character."
    )
    full = f"{mode_dir}. Change only: {prompt.strip()}. {freeze} No text, no watermark."

    refs: list[tuple[bytes, str]] = [(base_bytes, base_mime)]
    refs.extend(_style_refs(catalog, title_id, use_style_board))
    if len(refs) > 3:
        refs = refs[:3]

    img = edit_image(full, images=refs, model=_model(quality))
    created = create_image_asset(
        catalog,
        image_bytes=img,
        kind="portrait" if "expression" in mode else "sprite",
        base_name=f"chr_{mode}",
        label=f"Character · {mode} · {prompt.strip()[:32]}",
        mime="image/png",
        tags=["game_asset", "character", mode, "consistency"],
        provenance={
            "source": "generated",
            "tool": "game_character_consistency",
            "prompt": full,
            "skill": "game-character-consistency",
            "base_asset_id": base_asset_id,
            "mode": mode,
        },
    )
    bind = _bind(catalog, title_id, slot_id, created["asset_id"])
    return {
        "ok": True,
        "tool": "character",
        "assets": [created],
        "bind": bind,
        "base_asset_id": base_asset_id,
        "message": f"Character variant {created['asset_id']} from {base_asset_id}",
    }


def run_tileset(
    catalog,
    *,
    prompt: str,
    tile_px: int = 128,
    title_id: str | None = None,
    slot_id: str | None = None,
    quality: bool = True,
    use_style_board: bool = True,
) -> dict[str, Any]:
    full = f"{prompt.strip()}. {TILE_SUFFIX}"
    model = _model(quality)
    style = _style_refs(catalog, title_id, use_style_board)
    if style:
        tile = edit_image(
            full + " Match style of reference only.",
            images=style,
            model=model,
            aspect_ratio="1:1",
        )
    else:
        tile = generate_image(full, model=model, aspect_ratio="1:1")

    master = create_image_asset(
        catalog,
        image_bytes=tile,
        kind="texture",
        base_name="tile",
        label=f"Tile · {prompt.strip()[:40]}",
        mime="image/png",
        tags=["game_asset", "tileset", "seamless"],
        provenance={"source": "generated", "tool": "game_tileset", "prompt": full, "skill": "game-tilesets"},
    )
    composite = _make_2x2_composite(tile, tile_px=tile_px)
    check = create_image_asset(
        catalog,
        image_bytes=composite,
        kind="texture",
        base_name="tile_2x2",
        label=f"Tile 2×2 check · {prompt.strip()[:32]}",
        mime="image/png",
        tags=["game_asset", "tileset", "seam_check"],
        provenance={
            "source": "generated",
            "tool": "game_tileset_2x2",
            "skill": "game-tilesets",
            "master_asset_id": master["asset_id"],
        },
    )
    bind = _bind(catalog, title_id, slot_id, master["asset_id"])
    return {
        "ok": True,
        "tool": "tileset",
        "assets": [master, check],
        "bind": bind,
        "message": f"Tile {master['asset_id']} + 2×2 check {check['asset_id']}",
    }


def run_ui_icons(
    catalog,
    *,
    style_prompt: str,
    icons: str,
    bg_color: str = "pure #00FF00 chroma green",
    title_id: str | None = None,
    quality: bool = True,
    use_style_board: bool = True,
) -> dict[str, Any]:
    names = [x.strip() for x in icons.split(",") if x.strip()]
    if not names:
        raise ValueError("Provide at least one icon name")
    if len(names) > 12:
        raise ValueError("Max 12 icons per batch")

    style = _style_refs(catalog, title_id, use_style_board)
    model = _model(quality)
    created_list = []
    for name in names:
        full = (
            f"UI icon representing '{name}'. Style contract: {style_prompt.strip()}. "
            f"Background: {bg_color}. {UI_ICON_SUFFIX}"
        )
        if style:
            img = edit_image(
                full + " Match the style of the reference image only.",
                images=style,
                model=model,
                aspect_ratio="1:1",
            )
        else:
            img = generate_image(full, model=model, aspect_ratio="1:1")
        created = create_image_asset(
            catalog,
            image_bytes=img,
            kind="icon",
            base_name=f"icon_{name.lower().replace(' ', '_')}",
            label=f"Icon · {name}",
            mime="image/png",
            tags=["game_asset", "ui", "icon", name.lower()],
            provenance={
                "source": "generated",
                "tool": "game_ui_icons",
                "prompt": full,
                "skill": "game-ui-icons",
                "icon_name": name,
            },
        )
        created_list.append(created)

    return {
        "ok": True,
        "tool": "ui_icons",
        "assets": created_list,
        "message": f"Created {len(created_list)} icons",
    }


def run_animation(
    catalog,
    *,
    base_asset_id: str,
    prompt: str,
    frame_count: int = 8,
    title_id: str | None = None,
    slot_id: str | None = None,
    quality: bool = True,
    use_style_board: bool = True,
    video_first: bool = True,
    duration: int = 6,
) -> dict[str, Any]:
    """
    Animation frames via official skill pipeline when video_first=True:
      base → image_to_video → ffmpeg harvest → select loop window → catalog assets.
    Falls back to still pose edit-chain if video fails or video_first=False.
    """
    frame_count = max(4, min(12, int(frame_count)))
    base_bytes, base_mime = _load_asset_bytes(catalog, base_asset_id)

    if video_first:
        try:
            from sakura.anim_harvest import video_to_cycle_frames
            from sakura.video_client import image_to_video

            vprompt = (
                f"{prompt.strip()}. In-place motion only, camera locked static, "
                f"full body visible, plain flat background, looping cycle, continuous limbs."
            )
            video = image_to_video(
                base_bytes,
                vprompt,
                mime=base_mime,
                duration=duration if duration in (5, 6, 8, 10) else 6,
            )
            pngs, metrics = video_to_cycle_frames(
                video, n_frames=frame_count, fps=12.0
            )
            frames = []
            for i, png in enumerate(pngs):
                created = create_image_asset(
                    catalog,
                    image_bytes=png,
                    kind="sprite",
                    base_name=f"anim_f{i + 1:02d}",
                    label=f"Anim f{i + 1:02d} · {prompt.strip()[:28]}",
                    mime="image/png",
                    tags=["game_asset", "animation", "video_first", f"frame_{i + 1}"],
                    provenance={
                        "source": "generated",
                        "tool": "game_animation_frames_video",
                        "skill": "game-animation-frames",
                        "base_asset_id": base_asset_id,
                        "frame_index": i + 1,
                        "frame_count": len(pngs),
                        "prompt": vprompt,
                        "metrics": metrics,
                    },
                )
                frames.append(created)
            bind = _bind(catalog, title_id, slot_id, frames[0]["asset_id"]) if frames else None
            return {
                "ok": True,
                "tool": "animation",
                "pipeline": "video_first",
                "assets": frames,
                "bind": bind,
                "metrics": metrics,
                "message": (
                    f"Video-first animation: {len(frames)} frames from {base_asset_id} "
                    f"(motion={metrics.get('motion'):.1f}, loopΔ={metrics.get('loop_distance'):.1f})"
                ),
            }
        except Exception as e:
            # fall through to still chain with note
            video_err = str(e)
    else:
        video_err = None

    # Still pose edit-chain fallback
    style = _style_refs(catalog, title_id, use_style_board)
    model = _model(quality)
    freeze = (
        "FREEZE: character identity, costume, proportions, line style, keyable background color. "
        "Only pose/limb positions change for animation frame continuity."
    )
    frames = []
    prev = base_bytes
    prev_mime = base_mime
    for i in range(min(frame_count, 8)):
        phase = (i + 1) / frame_count
        full = (
            f"Animation frame {i + 1} of {frame_count} for: {prompt.strip()}. "
            f"Pose phase ~{phase:.0%} through the cycle. "
            f"Same scale and camera as reference. Isolated subject, keyable BG. {freeze} No text."
        )
        refs: list[tuple[bytes, str]] = [(prev, prev_mime)]
        if style and len(refs) < 3:
            refs.extend(style[: 3 - len(refs)])
        img = edit_image(full, images=refs, model=model, aspect_ratio="1:1")
        created = create_image_asset(
            catalog,
            image_bytes=img,
            kind="sprite",
            base_name=f"anim_f{i + 1:02d}",
            label=f"Anim f{i + 1:02d} · {prompt.strip()[:28]}",
            mime="image/png",
            tags=["game_asset", "animation", f"frame_{i + 1}"],
            provenance={
                "source": "generated",
                "tool": "game_animation_frames",
                "skill": "game-animation-frames",
                "base_asset_id": base_asset_id,
                "frame_index": i + 1,
                "frame_count": frame_count,
                "prompt": full,
                "video_fallback_error": video_err,
            },
        )
        frames.append(created)
        prev, prev_mime = img, "image/png"

    bind = _bind(catalog, title_id, slot_id, frames[0]["asset_id"]) if frames else None
    note = f" (video failed: {video_err[:120]})" if video_err else ""
    return {
        "ok": True,
        "tool": "animation",
        "pipeline": "still_edit_chain",
        "assets": frames,
        "bind": bind,
        "message": f"Animation {len(frames)} frames from {base_asset_id}{note}",
    }


def run_tool(catalog, tool_id: str, body: dict[str, Any]) -> dict[str, Any]:
    tid = (tool_id or "").strip().lower()
    if tid == "core":
        return run_core(
            catalog,
            prompt=body.get("prompt") or "",
            kind=body.get("kind") or "sprite",
            aspect_ratio=body.get("aspect_ratio") or "1:1",
            title_id=body.get("title_id"),
            slot_id=body.get("slot_id") or None,
            bg_color=body.get("bg_color") or "pure #00FF00 chroma green",
            quality=bool(body.get("quality", True)),
            use_style_board=bool(body.get("use_style_board", True)),
        )
    if tid == "character":
        return run_character(
            catalog,
            base_asset_id=body.get("base_asset_id") or "",
            mode=body.get("mode") or "expression",
            prompt=body.get("prompt") or "",
            title_id=body.get("title_id"),
            slot_id=body.get("slot_id") or None,
            quality=bool(body.get("quality", True)),
            use_style_board=bool(body.get("use_style_board", True)),
        )
    if tid == "tileset":
        return run_tileset(
            catalog,
            prompt=body.get("prompt") or "",
            tile_px=int(body.get("tile_px") or 128),
            title_id=body.get("title_id"),
            slot_id=body.get("slot_id") or None,
            quality=bool(body.get("quality", True)),
            use_style_board=bool(body.get("use_style_board", True)),
        )
    if tid in {"ui_icons", "ui", "icons"}:
        return run_ui_icons(
            catalog,
            style_prompt=body.get("style_prompt") or body.get("prompt") or "",
            icons=body.get("icons") or "",
            bg_color=body.get("bg_color") or "pure #00FF00 chroma green",
            title_id=body.get("title_id"),
            quality=bool(body.get("quality", True)),
            use_style_board=bool(body.get("use_style_board", True)),
        )
    if tid in {"animation", "anim", "frames"}:
        return run_animation(
            catalog,
            base_asset_id=body.get("base_asset_id") or "",
            prompt=body.get("prompt") or "",
            frame_count=int(body.get("frame_count") or 8),
            title_id=body.get("title_id"),
            slot_id=body.get("slot_id") or None,
            quality=bool(body.get("quality", True)),
            use_style_board=bool(body.get("use_style_board", True)),
            video_first=bool(body.get("video_first", True)),
            duration=int(body.get("duration") or 6),
        )
    raise ValueError(f"Unknown game asset tool: {tool_id}")
