from __future__ import annotations

import json
import mimetypes
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from sakura.asset_write import create_image_asset
from sakura.bind import bind_set, bind_set_status, bind_unbind, resolve_title_id
from sakura.code_graph import load_title_code_graph
from sakura.dialogue_edit import update_line
from sakura.elevenlabs_client import ElevenLabsError, list_voices, resolve_api_key
from sakura.github_projects import project_tabs
from sakura.imagine_client import (
    DEFAULT_MODEL,
    QUALITY_MODEL,
    ImagineError,
    edit_image,
    generate_image,
    resolve_xai_api_key,
)
from sakura.import_unity import import_title
from sakura.loader import discover_catalog_root, load_catalog
from sakura.flow_graph import auto_layout, build_flow_graph, save_flow_positions
from sakura.studio_style import load_studio_style, save_studio_style
from sakura.tts import generate_line_audio
from sakura.validate import run_validate, summarize
from sakura.voice_map import (
    load_voice_map,
    line_audio_path,
    line_audio_rel,
    save_voice_map,
    set_speaker_voice,
)
from sakura.yaml_io import load_yaml

app = FastAPI(title="Sakura Studio", version="0.6.0")

# Swap categories for dashboard filters
SWAP_CATEGORIES = {
    "graphic": {
        "label": "Graphics",
        "kinds": {"cg", "bg", "portrait", "ui", "sprite", "texture", "icon"},
        "tag_any": {"swap", "graphic", "cinematic", "character", "room", "ui"},
    },
    "piece": {
        "label": "Game pieces",
        "kinds": {"sprite"},
        "tag_any": {"piece", "gem", "tile", "match3"},
        "id_prefix": "slot.piece.",
    },
    "dialogue": {
        "label": "Character lines",
        "kinds": {"other"},
        "tag_any": {"dialogue", "line"},
        "id_prefix": "slot.line.",
    },
    "story": {
        "label": "Story elements",
        "kinds": set(),
        "tag_any": {"story", "scene_body"},
        "id_prefix": "slot.story.",
    },
}


def _catalog(path: str | None = None) -> Path:
    try:
        if path:
            return discover_catalog_root(Path(path))
        env = os.environ.get("SAKURA_CATALOG")
        if env:
            return discover_catalog_root(Path(env))
        return discover_catalog_root(None)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


def _slot_category(slot: dict[str, Any]) -> str:
    sid = str(slot.get("id") or "")
    tags = set(slot.get("tags") or [])
    kind = slot.get("kind")
    if sid.startswith("slot.piece.") or "piece" in tags or "gem" in tags:
        return "piece"
    if sid.startswith("slot.line.") or "dialogue" in tags or "line" in tags:
        return "dialogue"
    if sid.startswith("slot.story.") or "story" in tags:
        return "story"
    if kind in {"cg", "bg", "portrait", "ui", "texture", "icon"} or "graphic" in tags or "cinematic" in tags:
        return "graphic"
    if kind == "sprite" and ("tile" in tags or "match3" in tags):
        return "piece"
    if kind == "sprite":
        return "graphic"
    return "other"


class BindBody(BaseModel):
    title_id: str | None = None
    slot_id: str
    asset_id: str
    status: str = "review"
    bound_by: str = "studio"
    notes: str | None = None
    force: bool = False
    locale: str | None = None


class StatusBody(BaseModel):
    title_id: str | None = None
    slot_id: str
    status: str
    bound_by: str = "studio"
    locale: str | None = None


class ImportBody(BaseModel):
    title_id: str | None = None
    generate_missing: bool = True
    dry_run: bool = False


class DialogueLineBody(BaseModel):
    title_id: str | None = None
    scene_id: str
    node_id: str
    text: str


class VoiceAssignBody(BaseModel):
    title_id: str | None = None
    speaker: str
    voice_id: str
    voice_name: str | None = None
    character_id: str | None = None


class TtsGenerateBody(BaseModel):
    title_id: str | None = None
    scene_id: str
    node_id: str
    force: bool = False
    export_to_game: bool = True


class ImagineRefImage(BaseModel):
    """Ad-hoc reference image (local upload) as base64, not yet in catalog."""
    data_base64: str
    mime: str = "image/png"
    name: str | None = None


class ImagineReference(BaseModel):
    """Ordered edit reference — catalog asset or inline base64 image."""
    kind: str = "asset"  # asset | file
    asset_id: str | None = None
    data_base64: str | None = None
    mime: str = "image/png"
    name: str | None = None


class ImagineBody(BaseModel):
    prompt: str
    mode: str = Field(default="generate", description="generate | edit")
    title_id: str | None = None
    slot_id: str | None = None
    source_asset_id: str | None = None  # legacy single
    source_asset_ids: list[str] = Field(default_factory=list)
    source_images: list[ImagineRefImage] = Field(default_factory=list)
    references: list[ImagineReference] = Field(default_factory=list)
    kind: str | None = None
    label: str | None = None
    aspect_ratio: str = "1:1"
    resolution: str = "1k"
    model: str = "fast"  # fast | quality
    bind: bool = True
    force: bool = True
    status: str = "review"
    # When true (default), inject title style board asset if enabled
    use_style_board: bool = True


class StyleBoardBody(BaseModel):
    title_id: str
    enabled: bool | None = None
    asset_id: str | None = None
    clear_asset: bool = False
    notes: str | None = None


@app.get("/api/health")
def health(catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    return {
        "ok": True,
        "catalog": str(root),
        "version": "0.6.0",
        "elevenlabs_configured": bool(resolve_api_key()),
        "xai_configured": bool(resolve_xai_api_key()),
    }


class FlowLayoutBody(BaseModel):
    title_id: str
    positions: dict[str, dict[str, float]]


@app.get("/api/flow")
def api_flow(
    title: str | None = None,
    catalog: str | None = None,
    dialogue_detail: bool = True,
    all_slots: bool = False,
) -> dict[str, Any]:
    """Story / art / engine flow graph for the node editor."""
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=True)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    try:
        graph = build_flow_graph(
            root,
            title_id,
            include_dialogue_detail=dialogue_detail,
            include_all_slots=all_slots,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return graph


@app.post("/api/flow/layout")
def api_flow_layout(body: FlowLayoutBody, catalog: str | None = None) -> dict[str, Any]:
    """Persist node positions into title studio.yaml (flow.positions)."""
    root = _catalog(catalog)
    try:
        path = save_flow_positions(root, body.title_id, body.positions)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "ok": True,
        "path": str(path),
        "count": len(body.positions),
        "message": f"Saved {len(body.positions)} node positions → {path.name}",
    }


@app.post("/api/flow/auto-layout")
def api_flow_auto_layout(
    title: str | None = None,
    catalog: str | None = None,
    dialogue_detail: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Recompute column layout; optionally write to studio.yaml."""
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=True)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    graph = build_flow_graph(
        root, title_id, include_dialogue_detail=dialogue_detail
    )
    # ignore saved positions for auto
    positions = auto_layout(graph["nodes"])
    if persist:
        path = save_flow_positions(root, title_id, positions)
    else:
        path = None
    for n in graph["nodes"]:
        p = positions.get(n["id"])
        if p:
            n["x"], n["y"] = p["x"], p["y"]
    return {
        "ok": True,
        "title_id": title_id,
        "positions": positions,
        "path": str(path) if path else None,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "message": "Auto-layout applied" + (" and saved" if persist else ""),
    }


@app.get("/api/studio-style")
def api_get_studio_style(
    title: str = Query(...),
    catalog: str | None = None,
) -> dict[str, Any]:
    root = _catalog(catalog)
    try:
        style = load_studio_style(root, title)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "style": style}


@app.post("/api/studio-style")
def api_set_studio_style(body: StyleBoardBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    try:
        asset_arg: Any = ...
        if body.clear_asset:
            asset_arg = None
        elif body.asset_id is not None:
            asset_arg = body.asset_id
        style = save_studio_style(
            root,
            body.title_id,
            enabled=body.enabled,
            asset_id=asset_arg,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "ok": True,
        "style": style,
        "message": (
            f"Style board: enabled={style['enabled']} "
            f"asset={style['asset_id'] or '—'} "
            f"({'ACTIVE' if style['active'] else 'inactive'})"
        ),
    }


@app.get("/api/projects")
def api_projects(catalog: str | None = None, examples: bool = True) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    tabs = project_tabs(root, index.titles)
    return {"projects": tabs, "catalog": str(root)}


@app.get("/api/titles")
def titles(catalog: str | None = None, examples: bool = True) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    items = []
    for tid, ent in sorted(index.titles.items()):
        items.append(
            {
                "id": tid,
                "label": ent.data.get("label", tid),
                "status": ent.data.get("status"),
                "repo_path": ent.data.get("repo_path"),
                "engine_id": ent.data.get("engine_id"),
            }
        )
    return {"titles": items}


@app.get("/api/overview")
def api_overview(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    t = index.titles[title_id].data
    engine = None
    eid = t.get("engine_id")
    if eid and eid in index.engines:
        ed = index.engines[eid].data
        engine = {
            "id": eid,
            "label": ed.get("label"),
            "runtime": ed.get("runtime"),
            "status": ed.get("status"),
            "capabilities": ed.get("capabilities") or [],
            "tags": ed.get("tags") or [],
        }
    brand = None
    bid = t.get("brand_id")
    if bid and bid in index.brands:
        bd = index.brands[bid].data
        brand = {"id": bid, "label": bd.get("label"), "style": bd.get("style")}

    files = index.title_files.get(title_id, {})
    ggd = files.get("ggd")
    nodes = (ggd.data.get("nodes") if ggd else None) or []
    by_kind: dict[str, int] = defaultdict(int)
    for n in nodes:
        if isinstance(n, dict):
            by_kind[str(n.get("kind") or "?")] += 1

    slots = (files.get("slots").data.get("slots") if files.get("slots") else None) or []
    bindings = (files.get("bindings").data.get("bindings") if files.get("bindings") else None) or []
    bound = {b.get("slot_id") for b in bindings if isinstance(b, dict)}
    required = [s for s in slots if isinstance(s, dict) and s.get("required", True)]
    unbound_req = [s for s in required if s.get("id") not in bound]

    return {
        "title_id": title_id,
        "label": t.get("label"),
        "status": t.get("status"),
        "genre_tags": t.get("genre_tags") or [],
        "platforms": t.get("platforms") or [],
        "notes": t.get("notes"),
        "gates": t.get("gates") or {},
        "engine": engine,
        "brand": brand,
        "stats": {
            "nodes": len(nodes),
            "nodes_by_kind": dict(by_kind),
            "slots": len(slots),
            "bindings": len(bindings),
            "unbound_required": len(unbound_req),
            "cast": len((files.get("cast").data.get("entries") if files.get("cast") else None) or []),
            "assets_library": len(index.assets),
        },
    }


@app.get("/api/ggd")
def api_ggd(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    files = index.title_files.get(title_id, {})
    ggd = files.get("ggd")
    if not ggd:
        return {"title_id": title_id, "nodes": [], "edges": []}
    nodes = [n for n in (ggd.data.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (ggd.data.get("edges") or []) if isinstance(e, dict)]
    grouped: dict[str, list] = defaultdict(list)
    for n in nodes:
        grouped[str(n.get("kind") or "other")].append(n)
    return {
        "title_id": title_id,
        "nodes": nodes,
        "edges": edges,
        "by_kind": {k: v for k, v in sorted(grouped.items())},
    }


@app.get("/api/cast")
def api_cast(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    files = index.title_files.get(title_id, {})
    cast = files.get("cast")
    entries = []
    for e in (cast.data.get("entries") if cast else None) or []:
        if not isinstance(e, dict):
            continue
        cid = e.get("character_id")
        ch = index.characters.get(cid)
        entries.append(
            {
                **e,
                "character": ch.data if ch else None,
            }
        )
    return {"title_id": title_id, "entries": entries}


@app.get("/api/bindings")
def api_bindings(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
    category: str | None = None,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    files = index.title_files.get(title_id, {})
    slots_ent = files.get("slots")
    bindings_ent = files.get("bindings")

    slots: list[dict[str, Any]] = []
    if slots_ent:
        for s in slots_ent.data.get("slots") or []:
            if isinstance(s, dict):
                slots.append(s)

    bindings: list[dict[str, Any]] = []
    if bindings_ent:
        for b in bindings_ent.data.get("bindings") or []:
            if isinstance(b, dict):
                bindings.append(b)

    by_slot = {b["slot_id"]: b for b in bindings if b.get("slot_id")}

    rows = []
    for s in slots:
        sid = s.get("id")
        cat = _slot_category(s)
        if category and category != "all" and cat != category:
            continue
        b = by_slot.pop(sid, None) if sid else None
        asset_id = b.get("asset_id") if b else None
        asset_meta = None
        preview_url = None
        if asset_id and asset_id in index.assets:
            ad = index.assets[asset_id].data
            asset_meta = {
                "id": asset_id,
                "label": ad.get("label"),
                "kind": ad.get("kind"),
                "tags": ad.get("tags"),
                "status": ad.get("status"),
            }
            files_list = ad.get("files") or []
            master = next(
                (f for f in files_list if isinstance(f, dict) and f.get("role") == "master"),
                files_list[0] if files_list else None,
            )
            if isinstance(master, dict) and master.get("path"):
                preview_url = f"/api/asset-file?asset_id={asset_id}"

        rows.append(
            {
                "slot": s,
                "category": cat,
                "binding": b,
                "asset": asset_meta,
                "preview_url": preview_url,
                "unbound": b is None,
            }
        )

    assets = [
        {
            "id": aid,
            "label": e.data.get("label"),
            "kind": e.data.get("kind"),
            "tags": e.data.get("tags") or [],
            "status": e.data.get("status"),
            "preview_url": f"/api/asset-file?asset_id={aid}",
        }
        for aid, e in sorted(index.assets.items())
    ]

    return {
        "title_id": title_id,
        "rows": rows,
        "assets": assets,
        "categories": {k: v["label"] for k, v in SWAP_CATEGORIES.items()},
    }


@app.get("/api/asset-file")
def asset_file(asset_id: str, catalog: str | None = None) -> Response:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=True)
    ent = index.assets.get(asset_id)
    if not ent:
        raise HTTPException(404, f"Unknown asset {asset_id}")
    files = ent.data.get("files") or []
    master = next(
        (f for f in files if isinstance(f, dict) and f.get("role") == "master"),
        files[0] if files else None,
    )
    if not isinstance(master, dict) or not master.get("path"):
        raise HTTPException(404, "No file path on asset")
    path = (root / str(master["path"])).resolve()
    if not path.is_file():
        raise HTTPException(404, f"File missing: {master['path']}")
    mime = master.get("mime") or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return Response(content=path.read_bytes(), media_type=mime)


@app.post("/api/bind")
def api_bind(body: BindBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    result = bind_set(
        catalog=root,
        title=body.title_id,
        slot_id=body.slot_id,
        asset_id=body.asset_id,
        status=body.status,
        locale=body.locale,
        bound_by=body.bound_by,
        notes=body.notes,
        force=body.force,
        no_validate=False,
        include_examples=True,
    )
    return {
        "ok": result.ok,
        "message": result.message,
        "previous_asset_id": result.previous_asset_id,
    }


@app.post("/api/bind/status")
def api_bind_status(body: StatusBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    result = bind_set_status(
        catalog=root,
        title=body.title_id,
        slot_id=body.slot_id,
        status=body.status,
        locale=body.locale,
        bound_by=body.bound_by,
        include_examples=True,
    )
    return {"ok": result.ok, "message": result.message}


@app.post("/api/unbind")
def api_unbind(
    slot_id: str = Query(...),
    title_id: str | None = None,
    catalog: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    root = _catalog(catalog)
    result = bind_unbind(
        catalog=root,
        title=title_id,
        slot_id=slot_id,
        locale=locale,
        include_examples=True,
    )
    return {"ok": result.ok, "message": result.message}


def _slot_kind_for_asset(root: Path, title_id: str | None, slot_id: str | None) -> str:
    if not title_id or not slot_id:
        return "sprite"
    try:
        index = load_catalog(root, include_examples=True)
        files = index.title_files.get(title_id, {})
        slots_ent = files.get("slots")
        if not slots_ent:
            return "sprite"
        for s in slots_ent.data.get("slots") or []:
            if isinstance(s, dict) and s.get("id") == slot_id:
                kind = s.get("kind")
                if isinstance(kind, str) and kind:
                    return kind
    except Exception:
        pass
    return "sprite"


def _bind_new_asset(
    root: Path,
    *,
    title_id: str | None,
    slot_id: str | None,
    asset_id: str,
    force: bool = True,
    notes: str | None = None,
) -> dict[str, Any] | None:
    if not title_id or not slot_id:
        return None
    # Skip full-catalog validate on creative paths (upload / Imagine) so unrelated
    # findings don't mark a successful slot write as failure. Use Validate button.
    result = bind_set(
        catalog=root,
        title=title_id,
        slot_id=slot_id,
        asset_id=asset_id,
        status="review",
        bound_by="studio",
        notes=notes,
        force=force,
        no_validate=True,
        include_examples=True,
    )
    return {
        "ok": result.ok,
        "message": result.message,
        "previous_asset_id": result.previous_asset_id,
    }


@app.post("/api/assets/upload")
async def api_asset_upload(
    file: UploadFile = File(...),
    title_id: str | None = Form(None),
    slot_id: str | None = Form(None),
    kind: str | None = Form(None),
    label: str | None = Form(None),
    asset_id: str | None = Form(None),
    force: bool = Form(True),
    bind: bool = Form(True),
    catalog: str | None = None,
) -> dict[str, Any]:
    """Import a local image into the catalog library; optionally bind to a slot."""
    root = _catalog(catalog)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    if len(raw) > 40 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 40MB)")

    mime = file.content_type or None
    if mime and not mime.startswith("image/"):
        raise HTTPException(400, f"Only image uploads supported (got {mime})")

    asset_kind = kind or _slot_kind_for_asset(root, title_id, slot_id)
    base = Path(file.filename or "upload").stem
    try:
        created = create_image_asset(
            root,
            image_bytes=raw,
            kind=asset_kind,
            label=label,
            asset_id=asset_id,
            base_name=base,
            mime=mime,
            filename=file.filename,
            provenance={
                "source": "internal",
                "tool": "studio_upload",
                "author": "studio",
            },
            status="review",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    bind_result = None
    if bind and title_id and slot_id:
        bind_result = _bind_new_asset(
            root,
            title_id=title_id,
            slot_id=slot_id,
            asset_id=created["asset_id"],
            force=force,
            notes=f"uploaded {file.filename}",
        )
        if bind_result and not bind_result.get("ok"):
            # asset is still created; surface bind failure
            return {
                "ok": False,
                "asset": created,
                "bind": bind_result,
                "message": bind_result.get("message") or "Asset created but bind failed",
            }

    return {
        "ok": True,
        "asset": created,
        "bind": bind_result,
        "message": f"Imported {created['asset_id']}"
        + (f" → {slot_id}" if slot_id and bind else ""),
    }


@app.post("/api/imagine")
def api_imagine(body: ImagineBody, catalog: str | None = None) -> dict[str, Any]:
    """Generate or edit an image via Grok Imagine and save it into the catalog."""
    root = _catalog(catalog)
    mode = (body.mode or "generate").lower().strip()
    if mode not in {"generate", "edit"}:
        raise HTTPException(400, "mode must be 'generate' or 'edit'")

    model = QUALITY_MODEL if body.model in {"quality", QUALITY_MODEL} else DEFAULT_MODEL
    asset_kind = body.kind or _slot_kind_for_asset(root, body.title_id, body.slot_id)

    style_board: dict[str, Any] | None = None
    style_injected = False
    if body.use_style_board and body.title_id:
        try:
            style_board = load_studio_style(root, body.title_id)
        except Exception:
            style_board = None

    import base64 as _b64

    def _load_asset_bytes(source_id: str, index: Any) -> tuple[bytes, str]:
        ent = index.assets.get(source_id)
        if not ent:
            raise HTTPException(404, f"Unknown source asset {source_id}")
        files_list = ent.data.get("files") or []
        master = next(
            (
                f
                for f in files_list
                if isinstance(f, dict) and f.get("role") == "master"
            ),
            files_list[0] if files_list else None,
        )
        if not isinstance(master, dict) or not master.get("path"):
            raise HTTPException(404, f"No master file on {source_id}")
        path = (root / str(master["path"])).resolve()
        if not path.is_file():
            raise HTTPException(404, f"Missing file for {source_id}")
        src_mime = (
            master.get("mime")
            or mimetypes.guess_type(str(path))[0]
            or "image/png"
        )
        return path.read_bytes(), str(src_mime)

    def _decode_b64(raw: str, mime: str) -> tuple[bytes, str]:
        data = raw or ""
        if "," in data and data.strip().startswith("data:"):
            data = data.split(",", 1)[1]
        try:
            return _b64.b64decode(data), mime or "image/png"
        except Exception as e:
            raise HTTPException(400, f"Invalid reference image base64: {e}") from e

    def _collect_edit_refs(index: Any) -> list[tuple[bytes, str]]:
        nonlocal style_injected
        refs: list[tuple[bytes, str]] = []
        seen_asset_ids: set[str] = set()

        if body.references:
            for ref in body.references:
                kind = (ref.kind or "asset").lower()
                if kind == "asset":
                    if not ref.asset_id:
                        raise HTTPException(400, "reference.asset kind needs asset_id")
                    refs.append(_load_asset_bytes(ref.asset_id, index))
                    seen_asset_ids.add(ref.asset_id)
                elif kind in {"file", "image", "upload"}:
                    if not ref.data_base64:
                        raise HTTPException(400, "reference.file kind needs data_base64")
                    refs.append(_decode_b64(ref.data_base64, ref.mime or "image/png"))
                else:
                    raise HTTPException(400, f"Unknown reference kind: {ref.kind}")
        else:
            asset_ids: list[str] = []
            for aid in body.source_asset_ids or []:
                if aid and aid not in asset_ids:
                    asset_ids.append(aid)
            if body.source_asset_id and body.source_asset_id not in asset_ids:
                asset_ids.insert(0, body.source_asset_id)
            if not asset_ids and not body.source_images and body.title_id and body.slot_id:
                files = index.title_files.get(body.title_id, {})
                bindings_ent = files.get("bindings")
                if bindings_ent:
                    for b in bindings_ent.data.get("bindings") or []:
                        if isinstance(b, dict) and b.get("slot_id") == body.slot_id:
                            aid = b.get("asset_id")
                            if isinstance(aid, str):
                                asset_ids.append(aid)
                            break
            for source_id in asset_ids:
                refs.append(_load_asset_bytes(source_id, index))
                seen_asset_ids.add(source_id)
            for img in body.source_images or []:
                refs.append(_decode_b64(img.data_base64 or "", img.mime or "image/png"))

        # Project style board: append as last ref when active (max 3)
        if (
            body.use_style_board
            and style_board
            and style_board.get("enabled")
            and style_board.get("asset_id")
        ):
            sid = str(style_board["asset_id"])
            if sid not in seen_asset_ids:
                if len(refs) >= 3:
                    refs = refs[:2]
                refs.append(_load_asset_bytes(sid, index))
                style_injected = True

        return refs

    try:
        style_active = bool(
            body.use_style_board
            and style_board
            and style_board.get("enabled")
            and style_board.get("asset_id")
        )
        # Generate with style lock → edit using style image as sole/base ref
        if mode == "generate" and style_active:
            mode = "edit"
            # leave references empty so style inject provides the only ref
            # unless client already sent refs
            if not body.references and not body.source_asset_ids and not body.source_images:
                pass  # style will be the only ref

        if mode == "generate":
            image_bytes = generate_image(
                body.prompt,
                model=model,
                aspect_ratio=body.aspect_ratio or "1:1",
                resolution=body.resolution or "1k",
            )
            mime = "image/png"
            tool = "grok_imagine"
        else:
            index = load_catalog(root, include_examples=True)
            refs = _collect_edit_refs(index)

            if not refs:
                raise HTTPException(
                    400,
                    "Edit needs at least one reference image "
                    "(bound slot, references, style board, or source_asset_ids)",
                )
            if len(refs) > 3:
                raise HTTPException(400, "At most 3 reference images allowed")

            prompt = body.prompt.strip()
            if style_injected:
                prompt = (
                    f"{prompt}\n\n"
                    "[Style lock] The last reference image is the project style board. "
                    "Match its line weight, palette, shading, and finish. "
                    "Do not copy the style board's subject matter."
                )

            image_bytes = edit_image(
                prompt,
                images=refs,
                model=model,
                aspect_ratio=body.aspect_ratio,
                resolution=body.resolution or "1k",
            )
            tool = "grok_imagine_edit" if not style_injected else "grok_imagine_style"
            mime = "image/png"
    except ImagineError as e:
        raise HTTPException(502, str(e)) from e

    base_name = body.slot_id.replace("slot.", "") if body.slot_id else "imagine"
    try:
        created = create_image_asset(
            root,
            image_bytes=image_bytes,
            kind=asset_kind,
            label=body.label,
            base_name=base_name,
            mime=mime,
            provenance={
                "source": "generated",
                "tool": tool,
                "prompt": body.prompt.strip(),
                "author": "studio",
                **(
                    {"style_asset_id": style_board.get("asset_id")}
                    if style_injected and style_board
                    else {}
                ),
            },
            status=body.status or "review",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    bind_result = None
    if body.bind and body.title_id and body.slot_id:
        bind_result = _bind_new_asset(
            root,
            title_id=body.title_id,
            slot_id=body.slot_id,
            asset_id=created["asset_id"],
            force=body.force,
            notes=f"imagine:{mode}" + (";style_lock" if style_injected else ""),
        )

    ok = True
    message = f"Imagine {mode}: {created['asset_id']}"
    if style_injected and style_board:
        message += f" · style lock {style_board.get('asset_id')}"
    if bind_result:
        ok = bool(bind_result.get("ok"))
        message = (bind_result.get("message") or message) + (
            f" · style {style_board.get('asset_id')}" if style_injected and style_board else ""
        )

    return {
        "ok": ok,
        "mode": mode,
        "model": model,
        "asset": created,
        "bind": bind_result,
        "message": message,
        "preview_url": created.get("preview_url"),
        "style_injected": style_injected,
        "style_board": style_board,
    }


@app.get("/api/validate")
def api_validate(
    title: str | None = None,
    catalog: str | None = None,
    strict: bool = False,
    release: bool = False,
    examples: bool = True,
) -> dict[str, Any]:
    root = _catalog(catalog)
    _, findings = run_validate(
        catalog=root,
        title=title,
        include_examples=examples,
        strict=strict,
        release=release,
    )
    errors, warnings = summarize(findings)
    return {
        "errors": errors,
        "warnings": warnings,
        "findings": [
            {
                "severity": f.severity.value,
                "code": f.code,
                "message": f.message,
                "path": str(f.path) if f.path else None,
                "entity_id": f.entity_id,
            }
            for f in findings
        ],
    }


@app.post("/api/import")
def api_import(body: ImportBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    result = import_title(
        catalog=root,
        title=body.title_id,
        generate_missing=body.generate_missing,
        dry_run=body.dry_run,
        include_examples=True,
    )
    return {
        "ok": result.ok,
        "message": result.message,
        "copied": result.copied,
        "generated": result.generated,
        "skipped": result.skipped,
        "unity_root": str(result.unity_root) if result.unity_root else None,
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
    }


def _title_dir(catalog_root: Path, title_id: str) -> Path | None:
    titles = catalog_root / "titles"
    if not titles.is_dir():
        return None
    # match by reading title.yaml id
    for d in titles.rglob("title.yaml"):
        try:
            data = load_yaml(d)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and data.get("id") == title_id:
            return d.parent
    slug = title_id.replace("title.", "").replace("_", "-")
    cand = titles / slug
    return cand if cand.is_dir() else None


@app.get("/api/dialogue")
def api_dialogue(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
    scene: str | None = None,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tdir = _title_dir(root, title_id)
    if not tdir:
        return {"title_id": title_id, "scenes": []}
    data = None
    for name in ("dialogue.json", "dialogue.yaml"):
        path = tdir / name
        if not path.is_file():
            continue
        if name.endswith(".json"):
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = load_yaml(path)
        break
    if not data:
        return {"title_id": title_id, "scenes": [], "source": None}
    scenes = data.get("scenes") or []
    if scene:
        scenes = [s for s in scenes if s.get("id") == scene]
    # summarize without dumping all text twice
    summary = []
    for s in data.get("scenes") or []:
        nodes = s.get("nodes") or []
        summary.append(
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "start_node": s.get("start_node"),
                "line_count": sum(1 for n in nodes if n.get("kind") == "line"),
                "choice_count": sum(1 for n in nodes if n.get("kind") == "choice"),
                "node_count": len(nodes),
            }
        )
    # annotate lines with audio cache status
    tdir = _title_dir(root, title_id)
    if tdir and scenes:
        for sc in scenes:
            for n in sc.get("nodes") or []:
                if n.get("kind") != "line":
                    continue
                ap = line_audio_path(root, sc.get("id") or "", n.get("id") or "", title_id)
                n["has_audio"] = ap.is_file()
                n["audio_url"] = (
                    f"/api/tts/audio?title={title_id}&scene_id={sc.get('id')}&node_id={n.get('id')}"
                    if ap.is_file()
                    else None
                )

    vmap = load_voice_map(tdir) if tdir else {}
    return {
        "title_id": title_id,
        "source": data.get("source"),
        "imported_at": data.get("imported_at"),
        "summary": summary,
        "scenes": scenes,
        "voices": vmap,
        "elevenlabs_configured": bool(resolve_api_key()),
    }


@app.put("/api/dialogue/line")
def api_dialogue_line_put(body: DialogueLineBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=True)
    try:
        title_id = resolve_title_id(index, body.title_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tdir = _title_dir(root, title_id)
    if not tdir:
        raise HTTPException(404, "Title directory not found")
    try:
        result = update_line(
            root,
            tdir,
            scene_id=body.scene_id,
            node_id=body.node_id,
            text=body.text,
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    result["title_id"] = title_id
    return result


@app.get("/api/voices")
def api_voices() -> dict[str, Any]:
    try:
        voices = list_voices()
    except ElevenLabsError as e:
        raise HTTPException(400, str(e)) from e
    return {"voices": voices, "count": len(voices)}


@app.get("/api/voice-map")
def api_voice_map_get(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tdir = _title_dir(root, title_id)
    if not tdir:
        raise HTTPException(404, "Title directory not found")
    data = load_voice_map(tdir)
    data["title_id"] = title_id
    data["elevenlabs_configured"] = bool(resolve_api_key())
    return data


@app.put("/api/voice-map")
def api_voice_map_put(body: VoiceAssignBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=True)
    try:
        title_id = resolve_title_id(index, body.title_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tdir = _title_dir(root, title_id)
    if not tdir:
        raise HTTPException(404, "Title directory not found")
    try:
        entry = set_speaker_voice(
            tdir,
            title_id=title_id,
            speaker=body.speaker,
            voice_id=body.voice_id,
            voice_name=body.voice_name,
            character_id=body.character_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "title_id": title_id, "speaker": body.speaker, "entry": entry}


@app.post("/api/tts/generate")
def api_tts_generate(body: TtsGenerateBody, catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=True)
    try:
        title_id = resolve_title_id(index, body.title_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tdir = _title_dir(root, title_id)
    if not tdir:
        raise HTTPException(404, "Title directory not found")
    try:
        result = generate_line_audio(
            root,
            tdir,
            scene_id=body.scene_id,
            node_id=body.node_id,
            force=body.force,
            export_to_game=body.export_to_game,
        )
    except (KeyError, ValueError, ElevenLabsError) as e:
        raise HTTPException(400, str(e)) from e
    result["title_id"] = title_id
    result["audio_url"] = (
        f"/api/tts/audio?title={title_id}&scene_id={body.scene_id}&node_id={body.node_id}"
    )
    return result


@app.get("/api/tts/audio")
def api_tts_audio(
    title: str | None = None,
    scene_id: str = Query(...),
    node_id: str = Query(...),
    catalog: str | None = None,
    generate: bool = False,
    examples: bool = True,
) -> Response:
    """Serve cached line audio; optionally generate on demand (runtime game path)."""
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tdir = _title_dir(root, title_id)
    if not tdir:
        raise HTTPException(404, "Title directory not found")
    path = line_audio_path(root, scene_id, node_id, title_id)
    if not path.is_file():
        if not generate:
            raise HTTPException(404, "Audio not generated yet")
        try:
            generate_line_audio(
                root,
                tdir,
                scene_id=scene_id,
                node_id=node_id,
                force=False,
                export_to_game=True,
            )
        except (KeyError, ValueError, ElevenLabsError) as e:
            raise HTTPException(400, str(e)) from e
        path = line_audio_path(root, scene_id, node_id, title_id)
    if not path.is_file():
        raise HTTPException(404, "Audio missing after generate")
    return Response(
        content=path.read_bytes(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/code-graph")
def api_code_graph(
    title: str | None = None,
    catalog: str | None = None,
    examples: bool = True,
    include_edges: bool = False,
) -> dict[str, Any]:
    root = _catalog(catalog)
    index = load_catalog(root, include_examples=examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    graph = load_title_code_graph(root, title_id)
    if not graph:
        return {
            "title_id": title_id,
            "available": False,
            "message": "No code_graph.json — run: sakura code-graph --source <repo> --title "
            + title_id,
        }
    out = {
        "available": True,
        "title_id": title_id,
        "source_repo": graph.get("source_repo"),
        "style": graph.get("style"),
        "stats": graph.get("stats"),
        "god_nodes": graph.get("god_nodes") or [],
        "communities": graph.get("communities") or {},
    }
    if include_edges:
        out["nodes"] = graph.get("nodes") or []
        out["edges"] = graph.get("edges") or []
    return out


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # Avoid sticky browser cache of the old cards-only shell
    return HTMLResponse(
        content=STUDIO_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sakura Studio</title>
  <style>
    :root {
      --bg: #140f1a;
      --panel: #22182c;
      --panel2: #2c2238;
      --text: #faf3f7;
      --muted: #b5a3c0;
      --accent: #ff8fab;
      --accent2: #c8b6ff;
      --ok: #7dffa0;
      --warn: #ffe66b;
      --err: #ff7b7b;
      --border: #3f3354;
      --radius: 12px;
      font-family: "Segoe UI", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; color: var(--text); min-height: 100vh;
      background: radial-gradient(1000px 500px at 0% 0%, #3a2450 0%, var(--bg) 50%);
    }
    header {
      display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; justify-content: space-between;
      padding: 14px 18px; border-bottom: 1px solid var(--border);
      background: rgba(20,15,26,0.92); backdrop-filter: blur(10px); position: sticky; top: 0; z-index: 20;
    }
    h1 { font-size: 1.1rem; margin: 0 0 4px; }
    h1 span { color: var(--accent); }
    .ver { font-size: 0.7rem; color: var(--muted); margin-left: 8px; }
    #contextBar {
      margin: 0 18px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px;
      background: linear-gradient(135deg, #c8b6ff18, #ff8fab14); display: none;
    }
    #contextBar.visible { display: block; margin-top: 12px; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    select, button, input {
      background: var(--panel2); color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 11px; font-size: 0.88rem;
    }
    select#project { min-width: 260px; max-width: 420px; }
    button {
      cursor: pointer; background: linear-gradient(135deg, #ff8fab44, #c8b6ff33);
      border-color: #ff8fab77;
    }
    button:hover { filter: brightness(1.07); }
    button.secondary { background: var(--panel2); border-color: var(--border); }
    button.danger { background: #ff6b6b22; border-color: #ff6b6b66; }
    button.active { outline: 2px solid var(--accent2); }
    main { padding: 16px 18px 40px; max-width: 1280px; margin: 0 auto; }
    .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
    .tabs button { border-radius: 999px; padding: 6px 14px; }
    .panel { display: none; }
    .panel.active { display: block; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
    .card {
      background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 12px; display: flex; flex-direction: column; gap: 8px;
      transition: border-color .15s, box-shadow .15s;
    }
    .card.drop-target { border-color: var(--accent); box-shadow: 0 0 0 2px #ff8fab55; }
    .card h3 { margin: 0; font-size: 0.92rem; }
    .muted { color: var(--muted); font-size: 0.8rem; }
    .thumb-wrap {
      position: relative; width: 100%; border-radius: 8px;
      border: 1px dashed var(--border); background: #100c16; overflow: hidden;
    }
    .thumb-wrap.drop-target { border-color: var(--accent); border-style: solid; box-shadow: inset 0 0 0 2px #ff8fab55; }
    .thumb {
      width: 100%; aspect-ratio: 1; object-fit: contain; display: block; background: #100c16;
    }
    .thumb.placeholder {
      display: grid; place-items: center; color: var(--muted); font-size: 0.82rem;
      min-height: 140px; aspect-ratio: 1; padding: 12px; text-align: center; line-height: 1.35;
    }
    .imagine-box {
      background: var(--panel2); border: 1px solid var(--border); border-radius: 8px;
      padding: 8px; display: flex; flex-direction: column; gap: 6px;
    }
    .imagine-box textarea {
      width: 100%; min-height: 56px; resize: vertical; background: #100c16; color: var(--text);
      border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 0.8rem;
      font-family: inherit;
    }
    .imagine-box .row select { flex: 1; min-width: 0; font-size: 0.75rem; padding: 5px 6px; }
    .edit-panel {
      display: none; flex-direction: column; gap: 8px; margin-top: 4px;
      padding-top: 8px; border-top: 1px solid var(--border);
    }
    .edit-panel.open { display: flex; }
    .edit-panel .edit-title {
      font-size: 0.78rem; color: var(--accent2); font-weight: 600;
    }
    .ref-strip {
      display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      min-height: 72px; padding: 6px; background: #100c16; border-radius: 8px;
      border: 1px dashed var(--border);
    }
    .ref-strip.drop-target { border-color: var(--accent); border-style: solid; }
    .ref-chip {
      position: relative; width: 64px; height: 64px; border-radius: 8px;
      border: 1px solid var(--border); background: var(--panel); overflow: hidden;
      flex: 0 0 auto;
    }
    .ref-chip img {
      width: 100%; height: 100%; object-fit: cover; display: block;
    }
    .ref-chip .ref-x {
      position: absolute; top: 2px; right: 2px; width: 20px; height: 20px;
      border-radius: 999px; border: none; padding: 0; font-size: 12px; line-height: 1;
      background: #000000cc; color: #fff; cursor: pointer; display: grid; place-items: center;
    }
    .ref-chip .ref-x:hover { background: var(--err); }
    .ref-chip .ref-label {
      position: absolute; left: 0; right: 0; bottom: 0; font-size: 0.55rem;
      background: #000000aa; color: #fff; padding: 1px 3px; text-align: center;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .ref-add {
      width: 64px; height: 64px; border-radius: 8px; border: 1px dashed var(--border);
      background: transparent; color: var(--muted); font-size: 1.6rem; cursor: pointer;
      display: grid; place-items: center; flex: 0 0 auto;
    }
    .ref-add:hover { border-color: var(--accent); color: var(--accent); }
    .ref-add:disabled { opacity: 0.35; cursor: not-allowed; }
    .style-board {
      display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
      margin-bottom: 12px; padding: 10px 12px;
      background: linear-gradient(135deg, #c8b6ff14, #ff8fab12);
      border: 1px solid var(--border); border-radius: 12px;
    }
    .style-board .style-thumb {
      width: 56px; height: 56px; border-radius: 8px; object-fit: cover;
      background: #100c16; border: 1px solid var(--border);
    }
    .style-board .style-thumb.placeholder {
      display: grid; place-items: center; color: var(--muted); font-size: 0.65rem;
      text-align: center; padding: 4px;
    }
    .style-board .style-meta { flex: 1; min-width: 160px; }
    .style-board .style-meta strong { display: block; font-size: 0.9rem; }
    .style-board select { min-width: 180px; max-width: 280px; }
    .toggle {
      display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
      user-select: none; font-size: 0.82rem;
    }
    .toggle input { accent-color: var(--accent); width: 16px; height: 16px; }
    .toggle.on { color: var(--ok); }
    .toggle.off { color: var(--muted); }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    button.busy { opacity: 0.7; pointer-events: none; }
    /* ---- Flow canvas (node graph) ---- */
    #panel-flow { position: relative; }
    .flow-toolbar {
      display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      margin-bottom: 10px; padding: 8px 10px;
      background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    }
    .flow-toolbar .legend {
      display: flex; flex-wrap: wrap; gap: 6px; font-size: 0.72rem; color: var(--muted);
    }
    .flow-toolbar .legend span {
      border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px;
    }
    .flow-wrap {
      position: relative; height: min(72vh, 820px); border: 1px solid var(--border);
      border-radius: 12px; overflow: hidden; background:
        radial-gradient(circle at 1px 1px, #3f335466 1px, transparent 0);
      background-size: 24px 24px; background-color: #100c16;
      cursor: grab;
    }
    .flow-wrap.panning { cursor: grabbing; }
    .flow-viewport {
      position: absolute; inset: 0; transform-origin: 0 0;
    }
    .flow-edges { position: absolute; inset: 0; width: 4000px; height: 3000px; pointer-events: none; overflow: visible; }
    .flow-edges path {
      fill: none; stroke: #c8b6ff88; stroke-width: 2;
    }
    .flow-edges path.kind-leads_to { stroke: #ff8fabcc; }
    .flow-edges path.kind-unlocks { stroke: #7dffa0aa; }
    .flow-edges path.kind-uses_slot, .flow-edges path.kind-binds { stroke: #c8b6ffaa; }
    .flow-edges path.kind-has_dialogue, .flow-edges path.kind-choice, .flow-edges path.kind-option { stroke: #ffe66baa; }
    .flow-edges path.kind-runs, .flow-edges path.kind-contains { stroke: #8ecae6aa; }
    .flow-edges text {
      fill: var(--muted); font-size: 11px; font-family: system-ui, sans-serif;
      paint-order: stroke; stroke: #100c16; stroke-width: 3px;
    }
    .flow-node {
      position: absolute; width: 176px; min-height: 56px;
      background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
      padding: 8px 10px; box-shadow: 0 4px 16px #0006; cursor: grab; user-select: none;
      z-index: 2;
    }
    .flow-node:active { cursor: grabbing; }
    .flow-node.selected { border-color: var(--accent); box-shadow: 0 0 0 2px #ff8fab55; }
    .flow-node .fn-kind {
      font-size: 0.62rem; text-transform: uppercase; letter-spacing: .06em;
      color: var(--muted); margin-bottom: 2px;
    }
    .flow-node .fn-label {
      font-size: 0.82rem; font-weight: 600; line-height: 1.25;
      word-break: break-word;
    }
    .flow-node .fn-sub { font-size: 0.68rem; color: var(--muted); margin-top: 3px; }
    .flow-node.kind-route { border-left: 3px solid #c8b6ff; }
    .flow-node.kind-level { border-left: 3px solid #ff8fab; }
    .flow-node.kind-scene { border-left: 3px solid #ffb4c8; }
    .flow-node.kind-ending { border-left: 3px solid #7dffa0; }
    .flow-node.kind-dialogue { border-left: 3px solid #ffe66b; }
    .flow-node.kind-choice, .flow-node.kind-option { border-left: 3px solid #e9c46a; }
    .flow-node.kind-system, .flow-node.kind-engine { border-left: 3px solid #8ecae6; }
    .flow-node.kind-slot, .flow-node.kind-asset { border-left: 3px solid #bdb2ff; }
    .flow-node .fn-thumb {
      width: 100%; height: 48px; object-fit: contain; margin-top: 4px;
      background: #100c16; border-radius: 6px;
    }
    .flow-detail {
      margin-top: 10px; padding: 10px 12px; background: var(--panel);
      border: 1px solid var(--border); border-radius: 10px; font-size: 0.82rem;
      min-height: 48px;
    }
    .flow-hidden { display: none !important; }
    .badge {
      display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.7rem;
      border: 1px solid var(--border); color: var(--muted);
    }
    .badge.ok { color: var(--ok); border-color: #6bff8a55; }
    .badge.warn { color: var(--warn); border-color: #ffe66b55; }
    .badge.cat { color: var(--accent2); border-color: #c8b6ff55; }
    .log {
      margin-top: 16px; background: #100c16; border: 1px solid var(--border);
      border-radius: var(--radius); padding: 10px; font-family: ui-monospace, monospace;
      font-size: 0.75rem; white-space: pre-wrap; max-height: 160px; overflow: auto; color: var(--muted);
    }
    label { font-size: 0.72rem; color: var(--muted); display: block; margin-bottom: 3px; }
    .field { flex: 1; min-width: 120px; }
    .statgrid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; margin: 12px 0;
    }
    .stat {
      background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 12px;
    }
    .stat b { display: block; font-size: 1.35rem; color: var(--accent); }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: .04em; }
    .library {
      display: flex; gap: 8px; overflow-x: auto; padding: 8px 0 12px; margin-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }
    .lib-item {
      flex: 0 0 auto; width: 88px; background: var(--panel2); border: 1px solid var(--border);
      border-radius: 10px; padding: 6px; cursor: grab; text-align: center; font-size: 0.65rem; color: var(--muted);
    }
    .lib-item:active { cursor: grabbing; }
    .lib-item img { width: 100%; aspect-ratio: 1; object-fit: contain; border-radius: 6px; background: #100c16; }
    .lib-item .id { word-break: break-all; margin-top: 4px; }
    .engine-pill {
      display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px;
      background: linear-gradient(135deg, #c8b6ff22, #ff8fab22); border: 1px solid var(--border);
      border-radius: 999px; font-size: 0.9rem;
    }
    .filter-row { margin-bottom: 10px; }
    .empty { color: var(--muted); padding: 24px; text-align: center; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>🌸 <span>Sakura</span> Studio <span class="ver" id="buildVer">v0.6.0</span></h1>
      <div class="muted">Flow · Swaps · Story · Dialogue · Imagine</div>
    </div>
    <div class="row">
      <div class="field">
        <label for="project">Project (repos + catalog titles)</label>
        <select id="project"></select>
      </div>
      <button id="btnReload" class="secondary" type="button">Reload</button>
      <button id="btnValidate" class="secondary" type="button">Validate</button>
      <button id="btnImport" type="button">Import → Unity</button>
    </div>
  </header>
  <div id="contextBar"></div>
  <main>
    <div class="tabs" id="mainTabs">
      <button type="button" data-tab="overview" class="active">Overview</button>
      <button type="button" data-tab="flow">Flow ★</button>
      <button type="button" data-tab="swaps">Swaps</button>
      <button type="button" data-tab="story">Story</button>
      <button type="button" data-tab="dialogue">Dialogue</button>
      <button type="button" data-tab="cast">Cast</button>
      <button type="button" data-tab="code">Code map</button>
    </div>

    <section id="panel-overview" class="panel active"></section>
    <section id="panel-flow" class="panel">
      <div class="flow-toolbar" id="flowToolbar">
        <strong style="font-size:0.9rem">Story · art · engine flow</strong>
        <button type="button" class="secondary" id="btnFlowReload">Reload</button>
        <button type="button" class="secondary" id="btnFlowAuto">Auto-layout</button>
        <button type="button" id="btnFlowSave">Save layout</button>
        <label class="toggle" style="margin:0"><input type="checkbox" id="flowDlgDetail" checked /> Dialogue detail</label>
        <span class="muted" style="font-size:0.75rem">Drag nodes · scroll zoom · space/middle-drag pan</span>
        <div class="legend" id="flowLegend"></div>
      </div>
      <div class="row" style="margin-bottom:8px;gap:10px" id="flowLayers"></div>
      <div class="flow-wrap" id="flowWrap">
        <div class="flow-viewport" id="flowViewport">
          <svg class="flow-edges" id="flowEdges"></svg>
          <div id="flowNodes"></div>
        </div>
      </div>
      <div class="flow-detail" id="flowDetail">Select a node to inspect connections.</div>
    </section>
    <section id="panel-swaps" class="panel">
      <div class="style-board" id="styleBoard">
        <div id="styleThumb" class="style-thumb placeholder">style</div>
        <div class="style-meta">
          <strong>Project style board</strong>
          <div class="muted" id="styleStatus">Pick a style asset · toggle lock for all Imagine/Edit</div>
        </div>
        <div class="field" style="min-width:200px">
          <label for="styleAssetSelect">Style asset</label>
          <select id="styleAssetSelect"><option value="">— none —</option></select>
        </div>
        <label class="toggle off" id="styleToggleLabel">
          <input type="checkbox" id="styleEnabled" />
          <span id="styleToggleText">Style lock OFF</span>
        </label>
        <button type="button" class="secondary" id="btnStyleSave">Save style</button>
      </div>
      <div class="filter-row row">
        <span class="muted">Filter:</span>
        <button type="button" class="secondary cat-filter active" data-cat="all">All</button>
        <button type="button" class="secondary cat-filter" data-cat="graphic">Graphics</button>
        <button type="button" class="secondary cat-filter" data-cat="piece">Game pieces</button>
        <button type="button" class="secondary cat-filter" data-cat="dialogue">Character lines</button>
        <button type="button" class="secondary cat-filter" data-cat="story">Story elements</button>
      </div>
      <div class="muted" style="margin-bottom:6px">
        Asset library — drag onto a slot · drop a local image file · or prompt with Grok Imagine
      </div>
      <div class="library" id="library"></div>
      <div class="cards" id="swapCards"></div>
    </section>
    <section id="panel-story" class="panel"></section>
    <section id="panel-dialogue" class="panel"></section>
    <section id="panel-cast" class="panel"></section>
    <section id="panel-code" class="panel"></section>

    <div class="log" id="log">Ready.</div>
  </main>
  <script>
    const logEl = document.getElementById('log');
    const projectEl = document.getElementById('project');
    let currentTitleId = null;
    let projects = [];
    let swapCategory = 'all';
    let dragAssetId = null;

    function log(msg) {
      const t = new Date().toLocaleTimeString();
      logEl.textContent = `[${t}] ${msg}\n` + logEl.textContent;
    }

    async function api(path, opts) {
      const res = await fetch(path, opts);
      let data = {};
      try { data = await res.json(); } catch (_) {}
      if (!res.ok) {
        const detail = data.detail;
        const msg = typeof detail === 'string' ? detail
          : (detail && detail[0] && detail[0].msg) || data.message || res.statusText;
        throw new Error(msg);
      }
      return data;
    }

    function badgeStatus(st) {
      if (st === 'approved') return 'ok';
      if (st === 'review' || st === 'draft' || st === 'unbound') return 'warn';
      return '';
    }

    /* ---- tabs ---- */
    document.getElementById('mainTabs').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-tab]');
      if (!btn) return;
      document.querySelectorAll('#mainTabs button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
    });

    document.querySelectorAll('.cat-filter').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.cat-filter').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        swapCategory = btn.dataset.cat;
        loadSwaps().catch(e => log(e.message));
      });
    });

    /* ---- projects ---- */
    async function loadProjects() {
      const data = await api('/api/projects?examples=true');
      projects = data.projects || [];
      projectEl.innerHTML = '';
      for (const p of projects) {
        const opt = document.createElement('option');
        opt.value = p.key;
        const mark = p.in_catalog ? '●' : '○';
        const gh = p.github ? ` · ${p.github}` : '';
        opt.textContent = `${mark} ${p.label}${gh}`;
        opt.dataset.titleId = p.title_id || '';
        opt.dataset.inCatalog = p.in_catalog ? '1' : '0';
        projectEl.appendChild(opt);
      }
      // prefer tea house if present
      const prefer = projects.find(p => p.title_id === 'title.sakura_tea_house')
        || projects.find(p => p.title_id === 'title.sakura_match')
        || projects.find(p => p.in_catalog);
      if (prefer) projectEl.value = prefer.key;
      await onProjectChange();
    }

    async function onProjectChange() {
      const opt = projectEl.selectedOptions[0];
      if (!opt) return;
      const titleId = opt.dataset.titleId;
      const inCatalog = opt.dataset.inCatalog === '1';
      if (!inCatalog || !titleId) {
        currentTitleId = null;
        document.getElementById('contextBar').classList.remove('visible');
        document.getElementById('panel-overview').innerHTML =
          `<div class="empty">This GitHub repo is not mapped to a catalog title yet.<br/>
           Pick <strong>Sakura Tea House</strong> (●) in the project dropdown for engine + story.<br/>
           Or add a mapping in <code>catalog/_meta/github_projects.yaml</code>.
           <p class="muted">${opt.textContent}</p></div>`;
        document.getElementById('swapCards').innerHTML = '';
        document.getElementById('library').innerHTML = '';
        document.getElementById('panel-story').innerHTML = '';
        document.getElementById('panel-dialogue').innerHTML = '';
        document.getElementById('panel-cast').innerHTML = '';
        document.getElementById('panel-code').innerHTML = '';
        document.getElementById('flowNodes').innerHTML = '';
        document.getElementById('flowEdges').innerHTML = '';
        log('Selected unmapped project: ' + opt.textContent);
        return;
      }
      currentTitleId = titleId;
      await Promise.all([
        loadOverview(), loadFlow(), loadSwaps(), loadStory(), loadDialogue(), loadCast(), loadCode(),
      ]);
    }

    projectEl.addEventListener('change', () => onProjectChange().catch(e => log(e.message)));

    /* ---- overview ---- */
    function fillContextBar(o) {
      const bar = document.getElementById('contextBar');
      if (!o || !o.title_id) {
        bar.classList.remove('visible');
        bar.innerHTML = '';
        return;
      }
      const eng = o.engine;
      const kinds = o.stats?.nodes_by_kind || {};
      bar.classList.add('visible');
      bar.innerHTML = `
        <div class="row" style="justify-content:space-between;gap:12px">
          <div>
            <div class="row" style="gap:10px;margin-bottom:6px">
              <strong style="font-size:1.05rem">${o.label || o.title_id}</strong>
              <span class="badge ${badgeStatus(o.status)}">${o.status || '?'}</span>
              ${(o.genre_tags||[]).map(t => `<span class="badge cat">${t}</span>`).join('')}
            </div>
            <div class="engine-pill">
              <strong>Engine</strong>
              ${eng ? `${eng.label} <span class="muted">(${eng.runtime} · ${eng.id})</span>` : '<span class="muted">none linked</span>'}
            </div>
          </div>
          <div class="row" style="gap:14px">
            <div class="stat" style="min-width:70px"><b>${kinds.scene || 0}</b><span class="muted">Scenes</span></div>
            <div class="stat" style="min-width:70px"><b>${kinds.route || 0}</b><span class="muted">Routes</span></div>
            <div class="stat" style="min-width:70px"><b>${kinds.level || 0}</b><span class="muted">Levels</span></div>
            <div class="stat" style="min-width:70px"><b>${o.stats?.cast || 0}</b><span class="muted">Cast</span></div>
            <div class="stat" style="min-width:70px"><b>${o.stats?.bindings || 0}</b><span class="muted">Bound</span></div>
          </div>
        </div>
        <div class="muted" style="margin-top:8px">Tabs: Overview (detail) · Story (arcs/scenes) · Dialogue · Cast · Code map · Swaps (drag-drop cards)</div>
      `;
    }

    async function loadOverview() {
      if (!currentTitleId) return;
      const o = await api('/api/overview?examples=true&title=' + encodeURIComponent(currentTitleId));
      fillContextBar(o);
      const eng = o.engine;
      const kinds = o.stats.nodes_by_kind || {};
      const kindRows = Object.entries(kinds).map(([k,v]) =>
        `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
      document.getElementById('panel-overview').innerHTML = `
        <div class="row" style="gap:16px;align-items:center;margin-bottom:8px">
          <h2 style="margin:0">${o.label || o.title_id}</h2>
          <span class="badge ${badgeStatus(o.status)}">${o.status}</span>
          ${(o.genre_tags||[]).map(t => `<span class="badge cat">${t}</span>`).join('')}
        </div>
        <div class="engine-pill">
          <strong>Engine</strong>
          ${eng ? `${eng.label} <span class="muted">(${eng.runtime} · ${eng.id})</span>` : '<span class="muted">none</span>'}
        </div>
        ${eng && eng.capabilities ? `<p class="muted">Capabilities: ${eng.capabilities.join(' · ')}</p>` : ''}
        <div class="statgrid">
          <div class="stat"><b>${o.stats.nodes}</b><span class="muted">GGD nodes</span></div>
          <div class="stat"><b>${kinds.scene || 0}</b><span class="muted">Scenes</span></div>
          <div class="stat"><b>${kinds.route || 0}</b><span class="muted">Routes</span></div>
          <div class="stat"><b>${kinds.level || 0}</b><span class="muted">Levels</span></div>
          <div class="stat"><b>${o.stats.slots}</b><span class="muted">Slots</span></div>
          <div class="stat"><b>${o.stats.bindings}</b><span class="muted">Bindings</span></div>
          <div class="stat"><b>${o.stats.cast}</b><span class="muted">Cast</span></div>
          <div class="stat"><b>${o.stats.unbound_required}</b><span class="muted">Unbound required</span></div>
          <div class="stat"><b>${o.stats.assets_library}</b><span class="muted">Library assets</span></div>
        </div>
        <div class="two-col">
          <div class="card">
            <h3>GGD node kinds (story graph)</h3>
            <table><thead><tr><th>Kind</th><th>Count</th></tr></thead><tbody>${kindRows || '<tr><td colspan=2 class="muted">none</td></tr>'}</tbody></table>
          </div>
          <div class="card">
            <h3>Notes</h3>
            <p class="muted" style="white-space:pre-wrap;margin:0">${o.notes || '—'}</p>
            <p class="muted" style="margin-top:10px">Platforms: ${(o.platforms||[]).join(', ') || '—'}</p>
            <p class="muted">Brand: ${o.brand ? o.brand.label : '—'}</p>
            <p class="muted">Title id: ${o.title_id}</p>
          </div>
        </div>
      `;
    }

    /* ---- swaps + dnd + imagine ---- */
    let swapAssetsById = {};
    let xaiConfigured = null;
    let styleBoard = { enabled: false, asset_id: null, active: false, asset: null };

    async function refreshHealthFlags() {
      try {
        const h = await api('/api/health');
        xaiConfigured = !!h.xai_configured;
        const ver = document.getElementById('buildVer');
        if (ver && h.version) ver.textContent = 'v' + h.version;
      } catch (_) { /* ignore */ }
    }

    async function loadStyleBoard() {
      if (!currentTitleId) return;
      try {
        const data = await api('/api/studio-style?title=' + encodeURIComponent(currentTitleId));
        styleBoard = data.style || styleBoard;
        renderStyleBoard();
      } catch (e) {
        log('Style board: ' + e.message);
      }
    }

    function renderStyleBoard() {
      const sel = document.getElementById('styleAssetSelect');
      const en = document.getElementById('styleEnabled');
      const thumb = document.getElementById('styleThumb');
      const status = document.getElementById('styleStatus');
      const toggleLabel = document.getElementById('styleToggleLabel');
      const toggleText = document.getElementById('styleToggleText');
      if (!sel) return;

      const prev = styleBoard.asset_id || '';
      const assets = Object.values(swapAssetsById);
      const visual = assets.filter(a => {
        const k = a.kind || '';
        return !String(k).startsWith('audio') && k !== 'font';
      });
      const list = visual.length ? visual : assets;
      sel.innerHTML = '<option value="">— none —</option>' + list.map(a =>
        `<option value="${a.id}" ${a.id === prev ? 'selected' : ''}>${a.id}</option>`
      ).join('');
      if (prev && ![...sel.options].some(o => o.value === prev)) {
        const opt = document.createElement('option');
        opt.value = prev;
        opt.textContent = prev + ' (missing?)';
        opt.selected = true;
        sel.appendChild(opt);
      }

      en.checked = !!styleBoard.enabled;
      toggleLabel.classList.toggle('on', !!styleBoard.enabled && !!styleBoard.asset_id);
      toggleLabel.classList.toggle('off', !(styleBoard.enabled && styleBoard.asset_id));
      toggleText.textContent = styleBoard.enabled
        ? (styleBoard.asset_id ? 'Style lock ON' : 'Style lock ON (pick asset)')
        : 'Style lock OFF';

      const preview = styleBoard.asset?.preview_url
        || (styleBoard.asset_id ? '/api/asset-file?asset_id=' + encodeURIComponent(styleBoard.asset_id) : null);
      const host = document.getElementById('styleThumb')?.parentElement || document.getElementById('styleBoard');
      const old = document.getElementById('styleThumb');
      if (old) {
        if (preview) {
          const img = document.createElement('img');
          img.id = 'styleThumb';
          img.className = 'style-thumb';
          img.src = preview;
          img.alt = 'style';
          old.replaceWith(img);
        } else if (old.tagName === 'IMG') {
          const div = document.createElement('div');
          div.id = 'styleThumb';
          div.className = 'style-thumb placeholder';
          div.textContent = 'style';
          old.replaceWith(div);
        } else {
          old.className = 'style-thumb placeholder';
          old.textContent = 'style';
        }
      }
      status.textContent = styleBoard.active
        ? `ACTIVE · ${styleBoard.asset_id} · injected on Imagine + Edit`
        : (styleBoard.enabled
          ? 'Enabled but no asset — pick a style asset and Save'
          : 'OFF · Imagine runs without project style ref');
    }

    async function saveStyleBoard() {
      if (!currentTitleId) { log('No title selected'); return; }
      const sel = document.getElementById('styleAssetSelect');
      const en = document.getElementById('styleEnabled');
      try {
        const r = await api('/api/studio-style', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            title_id: currentTitleId,
            enabled: !!en.checked,
            asset_id: sel.value || null,
            clear_asset: !sel.value,
          }),
        });
        styleBoard = r.style || styleBoard;
        renderStyleBoard();
        log(r.message || 'Style board saved');
      } catch (e) {
        log('Style save failed: ' + e.message);
      }
    }

    document.getElementById('btnStyleSave').onclick = () => saveStyleBoard();
    document.getElementById('styleEnabled').addEventListener('change', () => {
      // optimistic label; persist on Save (or auto-save toggle)
      saveStyleBoard();
    });
    document.getElementById('styleAssetSelect').addEventListener('change', () => {
      // preview immediately from library
      const id = document.getElementById('styleAssetSelect').value;
      if (id && swapAssetsById[id]) {
        styleBoard = { ...styleBoard, asset_id: id, asset: swapAssetsById[id] };
      } else if (!id) {
        styleBoard = { ...styleBoard, asset_id: null, asset: null, active: false };
      }
      renderStyleBoard();
    });

    async function loadSwaps() {
      if (!currentTitleId) return;
      const q = new URLSearchParams({ examples: 'true', title: currentTitleId });
      if (swapCategory !== 'all') q.set('category', swapCategory);
      const data = await api('/api/bindings?' + q.toString());
      swapAssetsById = {};
      for (const a of (data.assets || [])) swapAssetsById[a.id] = a;
      renderLibrary(data.assets || []);
      renderSwapCards(data);
      await loadStyleBoard();
      if (xaiConfigured === null) refreshHealthFlags().catch(() => {});
    }

    function renderLibrary(assets) {
      const lib = document.getElementById('library');
      if (!assets.length) {
        lib.innerHTML = '<div class="muted">No library assets yet — drop a file on a slot or use Imagine</div>';
        return;
      }
      // Prefer visual assets in the strip
      const visual = assets.filter(a => {
        const k = a.kind || '';
        return !String(k).startsWith('audio') && k !== 'font' && k !== 'other';
      });
      const list = visual.length ? visual : assets;
      lib.innerHTML = list.map(a => `
        <div class="lib-item" draggable="true" data-asset-id="${a.id}" title="${a.id}">
          <img src="${a.preview_url}" alt="" draggable="false" onerror="this.style.opacity=0.2" />
          <div class="id">${a.id.replace(/^asset\\./,'')}</div>
        </div>
      `).join('');
      lib.querySelectorAll('.lib-item').forEach(el => {
        el.addEventListener('dragstart', (ev) => {
          dragAssetId = el.dataset.assetId;
          try {
            ev.dataTransfer.setData('text/plain', dragAssetId);
            ev.dataTransfer.setData('application/x-sakura-asset', dragAssetId);
          } catch (_) {}
          ev.dataTransfer.effectAllowed = 'copy';
        });
        el.addEventListener('dragend', () => { /* keep dragAssetId until drop handled */ });
      });
    }

    function setThumbPreview(wrap, previewUrl, hint) {
      if (!wrap) return;
      if (previewUrl) {
        wrap.innerHTML = `<img class="thumb" src="${previewUrl}" alt="" draggable="false" />`;
      } else {
        wrap.innerHTML = `<div class="thumb placeholder">${hint || 'Drop library asset or local image file'}</div>`;
      }
    }

    function renderSwapCards(data) {
      const host = document.getElementById('swapCards');
      host.innerHTML = '';
      if (!data.rows.length) {
        host.innerHTML = '<div class="empty">No slots in this filter. Add slots in catalog or clear filter.</div>';
        return;
      }
      for (const row of data.rows) {
        const slot = row.slot || {};
        const binding = row.binding;
        const status = binding?.status || (row.unbound ? 'unbound' : '?');
        const card = document.createElement('div');
        card.className = 'card';
        card.dataset.slotId = slot.id;
        const assetOpts = (data.assets || [])
          .map(a => `<option value="${a.id}" ${binding?.asset_id === a.id ? 'selected' : ''}>${a.id}</option>`)
          .join('');
        const boundPreview = row.preview_url || '';
        card.innerHTML = `
          <div class="row" style="justify-content:space-between">
            <h3>${slot.label || slot.id}</h3>
            <span class="badge ${badgeStatus(status)} status-badge">${status}</span>
          </div>
          <div class="muted">${slot.id}</div>
          <div class="row">
            <span class="badge cat">${row.category}</span>
            <span class="badge">${slot.kind || '?'}</span>
            ${slot.required === false ? '<span class="badge">optional</span>' : '<span class="badge warn">required</span>'}
          </div>
          <div class="thumb-wrap" data-role="thumb">
            ${boundPreview
              ? `<img class="thumb" src="${boundPreview}" alt="" draggable="false" />`
              : `<div class="thumb placeholder">Drop library asset or local image file</div>`}
          </div>
          <div class="field">
            <label>Asset (preview updates on pick · Bind to commit)</label>
            <select class="asset-select"><option value="">—</option>${assetOpts}</select>
          </div>
          <div class="row">
            <button type="button" class="btn-bind">Bind</button>
            <button type="button" class="btn-approve secondary">Approve</button>
            <button type="button" class="btn-unbind danger">Unbind</button>
          </div>
          <div class="imagine-box">
            <label>Grok Imagine</label>
            <textarea class="imagine-prompt" placeholder="Describe art for this slot… e.g. soft pastel red candy tile, kawaii match-3, no text"></textarea>
            <div class="row">
              <select class="imagine-ratio" title="Aspect ratio">
                <option value="1:1">1:1</option>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
                <option value="4:3">4:3</option>
                <option value="3:4">3:4</option>
                <option value="auto">auto</option>
              </select>
              <select class="imagine-model" title="Model">
                <option value="fast">fast</option>
                <option value="quality">quality</option>
              </select>
            </div>
            <div class="row">
              <button type="button" class="btn-imagine-gen">Imagine</button>
              <button type="button" class="btn-imagine-edit secondary">Edit…</button>
            </div>
            <div class="edit-panel" data-role="edit-panel">
              <div class="edit-title">Edit with references</div>
              <div class="muted">Default = current slot image. × removes · + adds file · drag library asset here (max 3)</div>
              <div class="ref-strip" data-role="ref-strip"></div>
              <input type="file" class="ref-file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden />
              <div class="row">
                <button type="button" class="btn-edit-apply">Apply edit → slot</button>
                <button type="button" class="btn-edit-cancel secondary">Cancel</button>
              </div>
            </div>
            <div class="muted imagine-hint">${xaiConfigured === false ? 'Set XAI_API_KEY in SakuraSoft/.env' : 'Imagine = new · Edit… = refine with refs → auto-saves + binds'}</div>
          </div>
        `;
        const sel = card.querySelector('.asset-select');
        const thumbWrap = card.querySelector('[data-role="thumb"]');
        const editBtn = card.querySelector('.btn-imagine-edit');
        const editPanel = card.querySelector('[data-role="edit-panel"]');
        // per-card edit refs: [{kind:'asset', asset_id, preview_url, label}|{kind:'file', mime, data_base64, preview_url, name}]
        card._editRefs = [];

        const refreshPreviewFromSelect = () => {
          const id = sel.value;
          if (id && swapAssetsById[id]) {
            setThumbPreview(thumbWrap, swapAssetsById[id].preview_url);
            return;
          }
          if (!id) {
            setThumbPreview(thumbWrap, null);
          } else {
            setThumbPreview(thumbWrap, '/api/asset-file?asset_id=' + encodeURIComponent(id));
          }
        };

        sel.addEventListener('change', () => {
          refreshPreviewFromSelect();
          log('Preview: ' + (sel.value || '(none)'));
          // if edit panel open, re-seed default ref from new selection when empty
          if (editPanel.classList.contains('open') && card._editRefs.length === 0) {
            seedDefaultEditRef(card, slot, row, sel);
            renderEditRefs(card);
          }
        });

        card.querySelector('.btn-bind').onclick = () => doBind(slot.id, sel.value);
        card.querySelector('.btn-approve').onclick = () => doStatus(slot.id, 'approved');
        card.querySelector('.btn-unbind').onclick = () => doUnbind(slot.id);
        card.querySelector('.btn-imagine-gen').onclick = () => doImagine(slot, card, 'generate');
        editBtn.onclick = () => openEditPanel(card, slot, row, sel);
        card.querySelector('.btn-edit-cancel').onclick = () => closeEditPanel(card);
        card.querySelector('.btn-edit-apply').onclick = () => doImagine(slot, card, 'edit');

        const markDrop = (on) => {
          card.classList.toggle('drop-target', on);
          thumbWrap.classList.toggle('drop-target', on);
        };
        const onDragOver = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
          markDrop(true);
        };
        const onDragLeave = (ev) => {
          if (!card.contains(ev.relatedTarget)) markDrop(false);
        };
        const onDrop = async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          markDrop(false);
          // if edit panel open and drop on ref strip / panel, treat as ref add
          const strip = card.querySelector('[data-role="ref-strip"]');
          if (editPanel.classList.contains('open') &&
              (strip.contains(ev.target) || editPanel.contains(ev.target))) {
            await handleRefDrop(ev, card);
            return;
          }
          await handleSlotDrop(ev, slot, sel, thumbWrap, editBtn);
        };
        [card, thumbWrap].forEach(el => {
          el.addEventListener('dragover', onDragOver);
          el.addEventListener('dragenter', onDragOver);
          el.addEventListener('dragleave', onDragLeave);
          el.addEventListener('drop', onDrop);
        });
        host.appendChild(card);
      }
    }

    const MAX_EDIT_REFS = 3;

    function currentSlotAssetId(card, row, sel) {
      if (sel && sel.value) return sel.value;
      if (row && row.binding && row.binding.asset_id) return row.binding.asset_id;
      return null;
    }

    function seedDefaultEditRef(card, slot, row, sel) {
      card._editRefs = [];
      const aid = currentSlotAssetId(card, row, sel);
      if (!aid) return;
      const meta = swapAssetsById[aid] || {};
      const preview = meta.preview_url || ('/api/asset-file?asset_id=' + encodeURIComponent(aid));
      card._editRefs.push({
        kind: 'asset',
        asset_id: aid,
        preview_url: preview,
        label: (meta.label || aid.replace(/^asset\\./, '')).slice(0, 24),
      });
    }

    function renderEditRefs(card) {
      const strip = card.querySelector('[data-role="ref-strip"]');
      if (!strip) return;
      const refs = card._editRefs || [];
      strip.innerHTML = '';
      refs.forEach((ref, idx) => {
        const chip = document.createElement('div');
        chip.className = 'ref-chip';
        chip.title = ref.kind === 'asset' ? ref.asset_id : (ref.name || 'upload');
        chip.innerHTML = `
          <img src="${ref.preview_url}" alt="" draggable="false" />
          <button type="button" class="ref-x" title="Remove reference" aria-label="Remove">×</button>
          <div class="ref-label">${ref.kind === 'asset' ? 'asset' : 'file'}${idx === 0 ? ' · primary' : ''}</div>
        `;
        chip.querySelector('.ref-x').onclick = (ev) => {
          ev.stopPropagation();
          card._editRefs.splice(idx, 1);
          renderEditRefs(card);
          log('Removed reference ' + (idx + 1));
        };
        strip.appendChild(chip);
      });
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'ref-add';
      add.title = refs.length >= MAX_EDIT_REFS ? 'Max 3 references' : 'Add reference image';
      add.textContent = '+';
      add.disabled = refs.length >= MAX_EDIT_REFS;
      add.onclick = () => {
        const input = card.querySelector('.ref-file');
        if (input) input.click();
      };
      strip.appendChild(add);

      // drag-over highlight on strip for library assets / files
      strip.ondragover = (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        strip.classList.add('drop-target');
      };
      strip.ondragleave = () => strip.classList.remove('drop-target');
      strip.ondrop = async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        strip.classList.remove('drop-target');
        await handleRefDrop(ev, card);
      };
    }

    function openEditPanel(card, slot, row, sel) {
      const panel = card.querySelector('[data-role="edit-panel"]');
      const promptEl = card.querySelector('.imagine-prompt');
      seedDefaultEditRef(card, slot, row, sel);
      renderEditRefs(card);
      panel.classList.add('open');
      if (promptEl) {
        promptEl.placeholder = 'Describe what to change… e.g. keep composition, make petals a deeper pink';
        promptEl.focus();
      }
      // wire file input once
      const input = card.querySelector('.ref-file');
      if (input && !input._wired) {
        input._wired = true;
        input.addEventListener('change', async () => {
          const files = [...(input.files || [])];
          input.value = '';
          for (const f of files) {
            if (!(card._editRefs.length < MAX_EDIT_REFS)) break;
            await addFileRef(card, f);
          }
          renderEditRefs(card);
        });
      }
      if (!card._editRefs.length) {
        log('Edit open — no current image; add a reference with + or drag a library asset');
      } else {
        log('Edit open — primary ref: ' + (card._editRefs[0].asset_id || card._editRefs[0].name || 'image'));
      }
    }

    function closeEditPanel(card) {
      const panel = card.querySelector('[data-role="edit-panel"]');
      panel.classList.remove('open');
      card._editRefs = [];
      const promptEl = card.querySelector('.imagine-prompt');
      if (promptEl) {
        promptEl.placeholder = 'Describe art for this slot… e.g. soft pastel red candy tile, kawaii match-3, no text';
      }
    }

    async function fileToRef(file) {
      const buf = await file.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = '';
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
      }
      const b64 = btoa(binary);
      const mime = file.type || 'image/png';
      const preview_url = URL.createObjectURL(file);
      return {
        kind: 'file',
        mime,
        data_base64: b64,
        preview_url,
        name: file.name || 'upload',
      };
    }

    async function addFileRef(card, file) {
      if (!file || !(file.type || '').startsWith('image/')) {
        // allow by extension
        if (!/\\.(png|jpe?g|webp|gif)$/i.test(file.name || '')) {
          log('Skip non-image: ' + (file && file.name));
          return;
        }
      }
      if (card._editRefs.length >= MAX_EDIT_REFS) {
        log('Max ' + MAX_EDIT_REFS + ' references');
        return;
      }
      const ref = await fileToRef(file);
      card._editRefs.push(ref);
      log('Added file ref: ' + ref.name);
    }

    function addAssetRef(card, assetId) {
      if (!assetId || !assetId.startsWith('asset.')) return false;
      if (card._editRefs.some(r => r.kind === 'asset' && r.asset_id === assetId)) {
        log('Already a reference: ' + assetId);
        return false;
      }
      if (card._editRefs.length >= MAX_EDIT_REFS) {
        log('Max ' + MAX_EDIT_REFS + ' references');
        return false;
      }
      const meta = swapAssetsById[assetId] || {};
      card._editRefs.push({
        kind: 'asset',
        asset_id: assetId,
        preview_url: meta.preview_url || ('/api/asset-file?asset_id=' + encodeURIComponent(assetId)),
        label: (meta.label || assetId.replace(/^asset\\./, '')).slice(0, 24),
      });
      log('Added asset ref: ' + assetId);
      return true;
    }

    async function handleRefDrop(ev, card) {
      const dt = ev.dataTransfer;
      const files = dt && dt.files && dt.files.length ? [...dt.files] : [];
      for (const f of files) {
        if (card._editRefs.length >= MAX_EDIT_REFS) break;
        await addFileRef(card, f);
      }
      if (!files.length) {
        let id = '';
        try { id = dt.getData('application/x-sakura-asset') || dt.getData('text/plain'); } catch (_) {}
        id = (id || dragAssetId || '').trim();
        if (id) addAssetRef(card, id);
      }
      renderEditRefs(card);
    }

    async function handleSlotDrop(ev, slot, sel, thumbWrap, editBtn) {
      const dt = ev.dataTransfer;
      const files = dt && dt.files && dt.files.length ? dt.files : null;
      if (files && files[0] && files[0].type && files[0].type.startsWith('image/')) {
        await uploadFileToSlot(slot.id, files[0], sel, thumbWrap, editBtn);
        return;
      }
      // some browsers expose files without type
      if (files && files[0] && /\\.(png|jpe?g|webp|gif)$/i.test(files[0].name || '')) {
        await uploadFileToSlot(slot.id, files[0], sel, thumbWrap, editBtn);
        return;
      }
      let id = '';
      try { id = dt.getData('application/x-sakura-asset') || dt.getData('text/plain'); } catch (_) {}
      id = (id || dragAssetId || '').trim();
      if (id && id.startsWith('asset.')) {
        sel.value = id;
        if (swapAssetsById[id]) {
          setThumbPreview(thumbWrap, swapAssetsById[id].preview_url);
        } else {
          setThumbPreview(thumbWrap, '/api/asset-file?asset_id=' + encodeURIComponent(id));
        }
        if (editBtn) editBtn.disabled = false;
        await doBind(slot.id, id);
        return;
      }
      log('Drop ignored — use a library asset or an image file (png/jpg/webp/gif)');
    }

    async function uploadFileToSlot(slotId, file, sel, thumbWrap, editBtn) {
      log('Uploading ' + file.name + ' → ' + slotId + '…');
      // local preview immediately
      try {
        const objUrl = URL.createObjectURL(file);
        setThumbPreview(thumbWrap, objUrl);
      } catch (_) {}
      const fd = new FormData();
      fd.append('file', file);
      fd.append('title_id', currentTitleId);
      fd.append('slot_id', slotId);
      fd.append('bind', 'true');
      fd.append('force', 'true');
      try {
        const res = await fetch('/api/assets/upload', { method: 'POST', body: fd });
        let data = {};
        try { data = await res.json(); } catch (_) {}
        if (!res.ok) {
          const detail = data.detail;
          const msg = typeof detail === 'string' ? detail : (data.message || res.statusText);
          throw new Error(msg);
        }
        log(data.message || JSON.stringify(data));
        if (data.asset?.asset_id && sel) {
          // ensure option exists before select
          const aid = data.asset.asset_id;
          if (![...sel.options].some(o => o.value === aid)) {
            const opt = document.createElement('option');
            opt.value = aid;
            opt.textContent = aid;
            sel.appendChild(opt);
          }
          sel.value = aid;
          if (data.asset.preview_url) setThumbPreview(thumbWrap, data.asset.preview_url + '&t=' + Date.now());
          if (editBtn) editBtn.disabled = false;
        }
        await loadSwaps();
        await loadOverview();
      } catch (e) {
        log('Upload failed: ' + e.message);
      }
    }

    async function doImagine(slot, card, mode) {
      const promptEl = card.querySelector('.imagine-prompt');
      const ratioEl = card.querySelector('.imagine-ratio');
      const modelEl = card.querySelector('.imagine-model');
      const sel = card.querySelector('.asset-select');
      const thumbWrap = card.querySelector('[data-role="thumb"]');
      const prompt = (promptEl?.value || '').trim();
      if (!prompt) { log('Enter an Imagine prompt first'); promptEl?.focus(); return; }

      const body = {
        prompt,
        mode,
        title_id: currentTitleId,
        slot_id: slot.id,
        aspect_ratio: ratioEl?.value || '1:1',
        model: modelEl?.value || 'fast',
        bind: true,
        force: true,
        use_style_board: true,
      };

      if (mode === 'edit') {
        const refs = card._editRefs || [];
        if (!refs.length && !(styleBoard && styleBoard.active)) {
          log('Add at least one reference image (or reopen Edit… on a bound slot)');
          openEditPanel(card, slot, { binding: { asset_id: sel?.value }, preview_url: null }, sel);
          return;
        }
        body.references = refs.map(r => {
          if (r.kind === 'asset') {
            return { kind: 'asset', asset_id: r.asset_id };
          }
          return {
            kind: 'file',
            data_base64: r.data_base64,
            mime: r.mime || 'image/png',
            name: r.name || null,
          };
        });
      }

      const buttons = card.querySelectorAll('.btn-imagine-gen, .btn-imagine-edit, .btn-edit-apply');
      buttons.forEach(b => b.classList.add('busy'));
      const styleNote = (styleBoard && styleBoard.active) ? ' · style lock' : '';
      log(`Imagine ${mode} for ${slot.id}` +
        (mode === 'edit' ? ` (${(card._editRefs||[]).length} ref(s))` : '') + styleNote + '…');
      try {
        const r = await api('/api/imagine', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        log(r.message || JSON.stringify(r));
        if (r.preview_url) setThumbPreview(thumbWrap, r.preview_url + '&t=' + Date.now());
        if (r.asset?.asset_id && sel) {
          const aid = r.asset.asset_id;
          if (![...sel.options].some(o => o.value === aid)) {
            const opt = document.createElement('option');
            opt.value = aid;
            opt.textContent = aid;
            sel.appendChild(opt);
          }
          sel.value = aid;
        }
        closeEditPanel(card);
        await loadSwaps();
        await loadOverview();
      } catch (e) {
        log('Imagine failed: ' + e.message);
      } finally {
        buttons.forEach(b => b.classList.remove('busy'));
      }
    }

    async function doBind(slotId, assetId) {
      if (!assetId) { log('Pick an asset first'); return; }
      try {
        const r = await api('/api/bind', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            title_id: currentTitleId,
            slot_id: slotId,
            asset_id: assetId,
            status: 'review',
            bound_by: 'studio',
            force: false,
          }),
        });
        log(r.message || JSON.stringify(r));
        if (r.ok) {
          await loadSwaps();
          await loadOverview();
        }
      } catch (e) {
        log('Bind failed: ' + e.message + ' — retry with force?');
        if (confirm('Force bind despite constraints?\\n' + e.message)) {
          const r = await api('/api/bind', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              title_id: currentTitleId,
              slot_id: slotId,
              asset_id: assetId,
              status: 'review',
              bound_by: 'studio',
              force: true,
            }),
          });
          log(r.message);
          if (r.ok) { await loadSwaps(); await loadOverview(); }
        }
      }
    }

    async function doStatus(slotId, status) {
      try {
        const r = await api('/api/bind/status', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ title_id: currentTitleId, slot_id: slotId, status, bound_by: 'studio' }),
        });
        log(r.message);
        if (r.ok) await loadSwaps();
      } catch (e) { log('ERROR: ' + e.message); }
    }

    async function doUnbind(slotId) {
      if (!confirm('Unbind ' + slotId + '?')) return;
      try {
        const q = new URLSearchParams({ slot_id: slotId, title_id: currentTitleId });
        const r = await api('/api/unbind?' + q.toString(), { method: 'POST' });
        log(r.message);
        if (r.ok) { await loadSwaps(); await loadOverview(); }
      } catch (e) { log('ERROR: ' + e.message); }
    }

    /* ---- Flow node graph ---- */
    let flowGraph = { nodes: [], edges: [], legend: [] };
    let flowPos = {};
    let flowLayersOn = {};
    let flowScale = 1;
    let flowPan = { x: 20, y: 20 };
    let flowDrag = null;
    let flowPanDrag = null;
    let flowSelected = null;

    async function loadFlow() {
      if (!currentTitleId) return;
      const detail = document.getElementById('flowDlgDetail')?.checked !== false;
      const q = new URLSearchParams({
        title: currentTitleId,
        dialogue_detail: detail ? 'true' : 'false',
      });
      const g = await api('/api/flow?' + q.toString());
      flowGraph = g;
      flowPos = {};
      for (const n of g.nodes || []) {
        flowPos[n.id] = { x: n.x || 0, y: n.y || 0 };
      }
      const layers = g.layers || [];
      if (!Object.keys(flowLayersOn).length) {
        for (const L of layers) flowLayersOn[L] = true;
      } else {
        for (const L of layers) if (flowLayersOn[L] === undefined) flowLayersOn[L] = true;
      }
      renderFlowLayers();
      renderFlowLegend(g.legend || []);
      renderFlowGraph();
      log(`Flow: ${g.stats?.nodes || 0} nodes · ${g.stats?.edges || 0} edges` +
        (g.layout_saved ? ' (saved layout)' : ' (auto layout)'));
    }

    function renderFlowLayers() {
      const host = document.getElementById('flowLayers');
      if (!host) return;
      const layers = flowGraph.layers || Object.keys(flowLayersOn);
      host.innerHTML = '<span class="muted">Layers:</span>' + layers.map(L => `
        <label class="toggle" style="margin:0">
          <input type="checkbox" data-layer="${L}" ${flowLayersOn[L] !== false ? 'checked' : ''}/> ${L}
        </label>`).join('');
      host.querySelectorAll('input[data-layer]').forEach(inp => {
        inp.onchange = () => {
          flowLayersOn[inp.dataset.layer] = inp.checked;
          renderFlowGraph();
        };
      });
    }

    function renderFlowLegend(legend) {
      const el = document.getElementById('flowLegend');
      if (!el) return;
      el.innerHTML = (legend || []).map(x =>
        `<span title="${x.kind}">${x.phrase || x.kind}</span>`
      ).join('');
    }

    function nodeVisible(n) {
      return flowLayersOn[n.layer] !== false;
    }

    function applyFlowTransform() {
      const vp = document.getElementById('flowViewport');
      if (vp) vp.style.transform = `translate(${flowPan.x}px,${flowPan.y}px) scale(${flowScale})`;
    }

    function renderFlowGraph() {
      const nodesHost = document.getElementById('flowNodes');
      const svg = document.getElementById('flowEdges');
      if (!nodesHost || !svg) return;
      const nodes = (flowGraph.nodes || []).filter(nodeVisible);
      const ids = new Set(nodes.map(n => n.id));
      const edges = (flowGraph.edges || []).filter(e => ids.has(e.from) && ids.has(e.to));

      // nodes
      nodesHost.innerHTML = '';
      for (const n of nodes) {
        const pos = flowPos[n.id] || { x: n.x || 0, y: n.y || 0 };
        const el = document.createElement('div');
        el.className = 'flow-node kind-' + (n.kind || 'other') + (flowSelected === n.id ? ' selected' : '');
        el.dataset.id = n.id;
        el.style.left = pos.x + 'px';
        el.style.top = pos.y + 'px';
        const thumb = n.preview_url
          ? `<img class="fn-thumb" src="${n.preview_url}" alt="" draggable="false" />`
          : '';
        el.innerHTML = `
          <div class="fn-kind">${n.kind || '?'}</div>
          <div class="fn-label">${escapeHtml(n.label || n.id)}</div>
          ${n.subtitle ? `<div class="fn-sub">${escapeHtml(n.subtitle)}</div>` : ''}
          ${thumb}
        `;
        el.addEventListener('pointerdown', (ev) => onFlowNodeDown(ev, n, el));
        el.addEventListener('click', (ev) => {
          ev.stopPropagation();
          selectFlowNode(n.id);
        });
        nodesHost.appendChild(el);
      }

      // edges (after nodes so we can measure)
      requestAnimationFrame(() => {
        drawFlowEdges(svg, nodes, edges);
        applyFlowTransform();
      });
    }

    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function nodeCenter(id) {
      const el = document.querySelector('.flow-node[data-id="' + String(id).replace(/"/g, '\\"') + '"]');
      const pos = flowPos[id] || { x: 0, y: 0 };
      if (!el) return { x: pos.x + 88, y: pos.y + 28 };
      return {
        x: pos.x + el.offsetWidth / 2,
        y: pos.y + el.offsetHeight / 2,
      };
    }

    function drawFlowEdges(svg, nodes, edges) {
      const NS = 'http://www.w3.org/2000/svg';
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      // arrow marker
      const defs = document.createElementNS(NS, 'defs');
      const marker = document.createElementNS(NS, 'marker');
      marker.setAttribute('id', 'flowArrow');
      marker.setAttribute('viewBox', '0 0 10 10');
      marker.setAttribute('refX', '9');
      marker.setAttribute('refY', '5');
      marker.setAttribute('markerWidth', '7');
      marker.setAttribute('markerHeight', '7');
      marker.setAttribute('orient', 'auto-start-reverse');
      const ap = document.createElementNS(NS, 'path');
      ap.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
      ap.setAttribute('fill', '#c8b6ffaa');
      marker.appendChild(ap);
      defs.appendChild(marker);
      svg.appendChild(defs);

      for (const e of edges) {
        const a = nodeCenter(e.from);
        const b = nodeCenter(e.to);
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const c1x = a.x + dx * 0.45;
        const c1y = a.y;
        const c2x = a.x + dx * 0.55;
        const c2y = b.y;
        const path = document.createElementNS(NS, 'path');
        path.setAttribute('d', `M ${a.x} ${a.y} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${b.x} ${b.y}`);
        path.setAttribute('class', 'kind-' + (e.kind || ''));
        path.setAttribute('marker-end', 'url(#flowArrow)');
        svg.appendChild(path);
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2 - 6;
        const text = document.createElementNS(NS, 'text');
        text.setAttribute('x', String(mx));
        text.setAttribute('y', String(my));
        text.setAttribute('text-anchor', 'middle');
        text.textContent = e.label || e.kind || '';
        svg.appendChild(text);
      }
    }

    function selectFlowNode(id) {
      flowSelected = id;
      document.querySelectorAll('.flow-node').forEach(el => {
        el.classList.toggle('selected', el.dataset.id === id);
      });
      const n = (flowGraph.nodes || []).find(x => x.id === id);
      const detail = document.getElementById('flowDetail');
      if (!n || !detail) return;
      const outs = (flowGraph.edges || []).filter(e => e.from === id);
      const ins = (flowGraph.edges || []).filter(e => e.to === id);
      detail.innerHTML = `
        <div class="row" style="justify-content:space-between">
          <div>
            <strong>${escapeHtml(n.label || n.id)}</strong>
            <span class="badge cat">${escapeHtml(n.kind)}</span>
            <span class="badge">${escapeHtml(n.layer || '')}</span>
          </div>
          <span class="muted" style="font-size:0.72rem">${escapeHtml(n.id)}</span>
        </div>
        ${n.subtitle ? `<p class="muted" style="margin:6px 0 0">${escapeHtml(n.subtitle)}</p>` : ''}
        <div class="two-col" style="margin-top:8px">
          <div>
            <div class="muted" style="margin-bottom:4px">Inbound</div>
            ${ins.length ? ins.map(e =>
              `<div>• <em>${escapeHtml(e.label)}</em> ← ${escapeHtml(e.from)}</div>`
            ).join('') : '<div class="muted">—</div>'}
          </div>
          <div>
            <div class="muted" style="margin-bottom:4px">Outbound</div>
            ${outs.length ? outs.map(e =>
              `<div>• <em>${escapeHtml(e.label)}</em> → ${escapeHtml(e.to)}</div>`
            ).join('') : '<div class="muted">—</div>'}
          </div>
        </div>
      `;
    }

    function onFlowNodeDown(ev, n, el) {
      if (ev.button === 1 || ev.spaceKey) return;
      ev.stopPropagation();
      ev.preventDefault();
      const startX = ev.clientX;
      const startY = ev.clientY;
      const origin = flowPos[n.id] || { x: n.x || 0, y: n.y || 0 };
      flowDrag = { id: n.id, startX, startY, ox: origin.x, oy: origin.y, el };
      el.setPointerCapture?.(ev.pointerId);
    }

    function onFlowPointerMove(ev) {
      if (flowDrag) {
        const dx = (ev.clientX - flowDrag.startX) / flowScale;
        const dy = (ev.clientY - flowDrag.startY) / flowScale;
        const nx = flowDrag.ox + dx;
        const ny = flowDrag.oy + dy;
        flowPos[flowDrag.id] = { x: nx, y: ny };
        flowDrag.el.style.left = nx + 'px';
        flowDrag.el.style.top = ny + 'px';
        const svg = document.getElementById('flowEdges');
        const nodes = (flowGraph.nodes || []).filter(nodeVisible);
        const ids = new Set(nodes.map(n => n.id));
        const edges = (flowGraph.edges || []).filter(e => ids.has(e.from) && ids.has(e.to));
        drawFlowEdges(svg, nodes, edges);
        return;
      }
      if (flowPanDrag) {
        flowPan.x = flowPanDrag.ox + (ev.clientX - flowPanDrag.startX);
        flowPan.y = flowPanDrag.oy + (ev.clientY - flowPanDrag.startY);
        applyFlowTransform();
      }
    }

    function onFlowPointerUp() {
      flowDrag = null;
      flowPanDrag = null;
      document.getElementById('flowWrap')?.classList.remove('panning');
    }

    (function wireFlowCanvas() {
      const wrap = document.getElementById('flowWrap');
      if (!wrap) return;
      wrap.addEventListener('pointerdown', (ev) => {
        if (ev.target.closest('.flow-node')) return;
        // pan with middle button or when holding space via data attr
        if (ev.button === 1 || ev.button === 0) {
          flowPanDrag = {
            startX: ev.clientX,
            startY: ev.clientY,
            ox: flowPan.x,
            oy: flowPan.y,
          };
          wrap.classList.add('panning');
          wrap.setPointerCapture?.(ev.pointerId);
        }
      });
      wrap.addEventListener('pointermove', onFlowPointerMove);
      wrap.addEventListener('pointerup', onFlowPointerUp);
      wrap.addEventListener('pointercancel', onFlowPointerUp);
      wrap.addEventListener('wheel', (ev) => {
        ev.preventDefault();
        const delta = ev.deltaY > 0 ? 0.92 : 1.08;
        flowScale = Math.min(2.5, Math.max(0.35, flowScale * delta));
        applyFlowTransform();
      }, { passive: false });

      document.getElementById('btnFlowReload')?.addEventListener('click', () =>
        loadFlow().catch(e => log(e.message)));
      document.getElementById('flowDlgDetail')?.addEventListener('change', () =>
        loadFlow().catch(e => log(e.message)));
      document.getElementById('btnFlowSave')?.addEventListener('click', async () => {
        if (!currentTitleId) return;
        try {
          const r = await api('/api/flow/layout', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ title_id: currentTitleId, positions: flowPos }),
          });
          log(r.message || 'Layout saved');
        } catch (e) { log('Save layout failed: ' + e.message); }
      });
      document.getElementById('btnFlowAuto')?.addEventListener('click', async () => {
        if (!currentTitleId) return;
        try {
          const detail = document.getElementById('flowDlgDetail')?.checked !== false;
          const r = await api('/api/flow/auto-layout?title=' + encodeURIComponent(currentTitleId) +
            '&dialogue_detail=' + (detail ? 'true' : 'false') + '&persist=true', { method: 'POST' });
          for (const n of r.nodes || []) {
            flowPos[n.id] = { x: n.x, y: n.y };
          }
          if (r.edges) flowGraph.edges = r.edges;
          if (r.nodes) flowGraph.nodes = r.nodes;
          renderFlowGraph();
          log(r.message || 'Auto-layout');
        } catch (e) { log('Auto-layout failed: ' + e.message); }
      });
    })();

    /* ---- story ---- */
    async function loadStory() {
      if (!currentTitleId) return;
      const g = await api('/api/ggd?examples=true&title=' + encodeURIComponent(currentTitleId));
      const kinds = ['route', 'scene', 'level', 'ending', 'choice', 'gate', 'system', 'cg_moment'];
      let html = `<p class="muted">${g.nodes.length} nodes · ${g.edges.length} edges — Graphify-style product graph (list view)</p>`;
      for (const kind of kinds) {
        const list = (g.by_kind && g.by_kind[kind]) || [];
        if (!list.length) continue;
        html += `<div class="card" style="margin-bottom:10px"><h3>${kind} (${list.length})</h3><table>
          <thead><tr><th>Id</th><th>Label</th><th>Status</th><th>Data</th></tr></thead><tbody>`;
        for (const n of list) {
          const data = n.data ? JSON.stringify(n.data) : '';
          html += `<tr>
            <td class="muted" style="font-size:0.75rem">${n.id}</td>
            <td>${n.label || ''}</td>
            <td><span class="badge ${badgeStatus(n.status)}">${n.status || '—'}</span></td>
            <td class="muted" style="font-size:0.72rem;max-width:280px;word-break:break-all">${data}</td>
          </tr>`;
        }
        html += `</tbody></table></div>`;
      }
      // remaining kinds
      for (const [kind, list] of Object.entries(g.by_kind || {})) {
        if (kinds.includes(kind) || !list.length) continue;
        html += `<div class="card" style="margin-bottom:10px"><h3>${kind} (${list.length})</h3>
          <ul class="muted">${list.map(n => `<li>${n.label || n.id}</li>`).join('')}</ul></div>`;
      }
      document.getElementById('panel-story').innerHTML = html || '<div class="empty">No GGD yet</div>';
    }

    /* ---- dialogue ledger (editable + ElevenLabs) ---- */
    let elevenVoices = [];
    let voiceMapCache = {};

    async function ensureElevenVoices() {
      if (elevenVoices.length) return elevenVoices;
      try {
        const data = await api('/api/voices');
        elevenVoices = data.voices || [];
      } catch (e) {
        log('ElevenLabs voices: ' + e.message);
        elevenVoices = [];
      }
      return elevenVoices;
    }

    function speakerKeysFromSummary(d) {
      const keys = new Set();
      for (const sc of (d.scenes || [])) {
        for (const n of (sc.nodes || [])) {
          // option rows abuse `speaker` as a jump target ("→ `node`") — not a person
          if (n.speaker && n.kind !== 'option' && !String(n.speaker).startsWith('→')) {
            keys.add(String(n.speaker).toLowerCase());
          }
        }
      }
      // keep speakers that have an assigned voice even if they have no lines yet
      for (const sp of Object.keys(((d.voices || {}).by_speaker) || {})) keys.add(sp);
      return [...keys];
    }

    async function loadDialogue() {
      if (!currentTitleId) return;
      const d = await api('/api/dialogue?examples=true&title=' + encodeURIComponent(currentTitleId));
      if (!(d.summary || []).length) {
        document.getElementById('panel-dialogue').innerHTML =
          '<div class="empty">No dialogue ledger. Run: sakura sync-tea-house --source &lt;sakura-match&gt;</div>';
        return;
      }
      voiceMapCache = d.voices || {};
      const elStatus = d.elevenlabs_configured
        ? '<span class="badge ok">ElevenLabs key OK</span>'
        : '<span class="badge warn">Set ELEVENLABS_API_KEY or SakuraSoft/.env</span>';

      let html = `<p class="muted">${d.source || ''} · ${d.summary.length} scenes ·
        ${d.summary.reduce((a,s)=>a+(s.line_count||0),0)} lines · ${elStatus}</p>
        <div class="card" style="margin-bottom:12px" id="voiceAssignCard">
          <h3>Character → ElevenLabs voice</h3>
          <p class="muted">Assigned voices are used when you Generate TTS on a line. Game can pull
            <code>/api/tts/audio?...&amp;generate=true</code> at runtime and cache under public/audio/vo/.</p>
          <div id="voiceAssignRows" class="muted">Loading voices…</div>
        </div>
        <div class="row" style="margin-bottom:10px">
          <label class="muted">Scene</label>
          <select id="dialogueScene"><option value="">All scenes (summary)</option>
          ${d.summary.map(s => `<option value="${s.id}">${s.label} (${s.line_count} lines)</option>`).join('')}
          </select>
        </div>
        <div id="dialogueBody"></div>`;
      document.getElementById('panel-dialogue').innerHTML = html;
      const body = document.getElementById('dialogueBody');

      // voice assignment UI
      (async () => {
        let voicesErr = '';
        try {
          await ensureElevenVoices();
        } catch (e) {
          voicesErr = e.message || String(e);
        }
        // ensureElevenVoices swallows errors — recheck via API for message
        if (!elevenVoices.length) {
          try {
            const res = await fetch('/api/voices');
            const data = await res.json().catch(() => ({}));
            if (!res.ok) voicesErr = data.detail || res.statusText;
            else elevenVoices = data.voices || [];
          } catch (e) { voicesErr = e.message; }
        }
        const vm = await api('/api/voice-map?title=' + encodeURIComponent(currentTitleId)).catch(() => voiceMapCache);
        voiceMapCache = vm;
        const speakers = speakerKeysFromSummary(d);
        const opts = elevenVoices.length
          ? elevenVoices.map(v => `<option value="${v.voice_id}">${v.name}</option>`).join('')
          : '';
        const host = document.getElementById('voiceAssignRows');
        const errHtml = voicesErr
          ? `<p class="badge warn" style="display:block;margin-bottom:8px;white-space:normal;line-height:1.35">${voicesErr}</p>
             <p class="muted">You can still paste a Voice ID from elevenlabs.io → Voices → ⋮ → Copy voice ID.</p>`
          : (elevenVoices.length ? `<p class="muted">${elevenVoices.length} voices loaded from your account.</p>` : '');
        host.innerHTML = errHtml + speakers.map(sp => {
          const cur = (vm.by_speaker || {})[sp] || {};
          return `<div class="row" style="margin:6px 0;align-items:center">
            <span style="min-width:90px;color:var(--text)">${sp}</span>
            <select class="voice-select" data-speaker="${sp}" style="min-width:200px">
              <option value="">— pick listed voice —</option>
              ${opts}
            </select>
            <input class="voice-id-manual" data-speaker="${sp}" placeholder="or paste voice_id"
              value="${cur.voice_id || ''}"
              style="min-width:180px;background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px" />
            <button type="button" class="secondary btn-save-voice" data-speaker="${sp}">Save voice</button>
            <span class="muted voice-cur" data-speaker="${sp}">${cur.voice_name || cur.voice_id || ''}</span>
          </div>`;
        }).join('');
        // preselect dropdown if id is in list
        host.querySelectorAll('.voice-select').forEach(sel => {
          const sp = sel.dataset.speaker;
          const cur = (vm.by_speaker || {})[sp];
          if (cur && cur.voice_id) {
            const has = [...sel.options].some(o => o.value === cur.voice_id);
            if (has) sel.value = cur.voice_id;
          }
        });
        host.querySelectorAll('.btn-save-voice').forEach(btn => {
          btn.onclick = async () => {
            const sp = btn.dataset.speaker;
            const sel = host.querySelector(`.voice-select[data-speaker="${sp}"]`);
            const manual = host.querySelector(`.voice-id-manual[data-speaker="${sp}"]`);
            const voiceId = (manual && manual.value.trim()) || sel.value;
            if (!voiceId) { log('Pick or paste a voice id first'); return; }
            let name = '';
            if (sel.value === voiceId && sel.selectedOptions[0]) {
              name = sel.selectedOptions[0].textContent || '';
            } else {
              name = voiceId.slice(0, 12) + '…';
            }
            try {
              await api('/api/voice-map', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  title_id: currentTitleId,
                  speaker: sp,
                  voice_id: voiceId,
                  voice_name: name,
                }),
              });
              log(`Voice ${sp} → ${name} (${voiceId.slice(0,8)}…)`);
              const label = host.querySelector(`.voice-cur[data-speaker="${sp}"]`);
              if (label) label.textContent = name;
              if (manual) manual.value = voiceId;
            } catch (e) { log('ERROR: ' + e.message); }
          };
        });
      })();

      function renderSummary() {
        body.innerHTML = `<table><thead><tr><th>Scene</th><th>Id</th><th>Lines</th><th>Choices</th><th>Nodes</th></tr></thead><tbody>
          ${d.summary.map(s => `<tr>
            <td><a href="#" class="scene-link" data-id="${s.id}">${s.label}</a></td>
            <td class="muted">${s.id}</td>
            <td>${s.line_count}</td><td>${s.choice_count}</td><td>${s.node_count}</td>
          </tr>`).join('')}
        </tbody></table>
        <p class="muted">Click a scene to edit lines and generate VO. Edits write dialogue.yaml + localization + line assets.</p>`;
        body.querySelectorAll('.scene-link').forEach(a => {
          a.onclick = (ev) => {
            ev.preventDefault();
            document.getElementById('dialogueScene').value = a.dataset.id;
            renderScene(a.dataset.id).catch(err => log(err.message));
          };
        });
      }

      async function renderScene(sid) {
        const full = await api('/api/dialogue?examples=true&title=' + encodeURIComponent(currentTitleId) + '&scene=' + encodeURIComponent(sid));
        const sc = (full.scenes || [])[0];
        if (!sc) { body.innerHTML = '<div class="empty">Scene not found</div>'; return; }
        const rows = (sc.nodes || []).map((n, i) => {
          const esc = (n.text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;');
          if (n.kind === 'line') {
            const audioBadge = n.has_audio
              ? `<span class="badge ok">audio</span> <audio controls preload="none" src="${n.audio_url}" style="height:28px;vertical-align:middle"></audio>`
              : `<span class="badge warn">no audio</span>`;
            return `<tr data-node="${n.id}">
              <td class="muted" style="font-size:0.75rem">${n.id}</td>
              <td><span class="badge cat">line</span></td>
              <td>${n.speaker || '—'}</td>
              <td>
                <textarea class="line-edit" data-node="${n.id}" rows="2" style="width:100%;background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px;font:inherit">${esc}</textarea>
                <div class="row" style="margin-top:6px">
                  <button type="button" class="btn-save-line" data-node="${n.id}">Save text</button>
                  <button type="button" class="secondary btn-tts" data-node="${n.id}" data-speaker="${n.speaker || ''}">Generate VO</button>
                  ${audioBadge}
                </div>
              </td>
            </tr>`;
          }
          return `<tr>
            <td class="muted" style="font-size:0.75rem">${n.id}</td>
            <td><span class="badge cat">${n.kind}</span></td>
            <td>${n.speaker || '—'}</td>
            <td style="font-size:0.85rem">${esc}</td>
          </tr>`;
        }).join('');

        body.innerHTML = `<div class="card"><h3>${sc.label}</h3>
          <div class="muted">start: ${sc.start_node || '—'} · terminals: ${(sc.terminal_paths||[]).join(', ') || '—'}</div>
          <table><thead><tr><th>Node</th><th>Kind</th><th>Speaker</th><th>Text / VO</th></tr></thead><tbody>
          ${rows}
          </tbody></table></div>`;

        body.querySelectorAll('.btn-save-line').forEach(btn => {
          btn.onclick = async () => {
            const nid = btn.dataset.node;
            const ta = body.querySelector(`textarea.line-edit[data-node="${nid}"]`);
            try {
              const r = await api('/api/dialogue/line', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  title_id: currentTitleId,
                  scene_id: sid,
                  node_id: nid,
                  text: ta.value,
                }),
              });
              log(`Saved ${sid}/${nid}`);
              btn.textContent = 'Saved ✓';
              setTimeout(() => { btn.textContent = 'Save text'; }, 1200);
            } catch (e) { log('ERROR: ' + e.message); }
          };
        });
        body.querySelectorAll('.btn-tts').forEach(btn => {
          btn.onclick = async () => {
            const nid = btn.dataset.node;
            // save text first so VO matches editor
            const ta = body.querySelector(`textarea.line-edit[data-node="${nid}"]`);
            if (ta) {
              try {
                await api('/api/dialogue/line', {
                  method: 'PUT',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({
                    title_id: currentTitleId,
                    scene_id: sid,
                    node_id: nid,
                    text: ta.value,
                  }),
                });
              } catch (_) {}
            }
            btn.disabled = true;
            btn.textContent = 'Generating…';
            try {
              const r = await api('/api/tts/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  title_id: currentTitleId,
                  scene_id: sid,
                  node_id: nid,
                  force: true,
                  export_to_game: true,
                }),
              });
              log(`VO ${nid}: ${r.voice_name || r.voice_id} · ${r.bytes} bytes` +
                (r.game_path ? ` · game: ${r.game_path}` : ''));
              await renderScene(sid);
            } catch (e) {
              log('TTS ERROR: ' + e.message);
              btn.disabled = false;
              btn.textContent = 'Generate VO';
            }
          };
        });
      }

      renderSummary();
      document.getElementById('dialogueScene').onchange = (e) => {
        const v = e.target.value;
        if (!v) renderSummary();
        else renderScene(v).catch(err => log(err.message));
      };
    }

    /* ---- code map (graphify-inspired) ---- */
    async function loadCode() {
      if (!currentTitleId) return;
      const g = await api('/api/code-graph?examples=true&title=' + encodeURIComponent(currentTitleId));
      if (!g.available) {
        document.getElementById('panel-code').innerHTML =
          `<div class="empty">${g.message || 'No code graph'}</div>`;
        return;
      }
      const gods = (g.god_nodes || []).slice(0, 20);
      const comms = Object.entries(g.communities || {});
      document.getElementById('panel-code').innerHTML = `
        <p class="muted">${g.style || ''} · repo: ${g.source_repo || '—'} ·
          ${g.stats?.nodes || 0} nodes · ${g.stats?.edges || 0} edges · ${g.stats?.communities || 0} communities</p>
        <div class="two-col">
          <div class="card">
            <h3>God nodes (highest degree)</h3>
            <table><thead><tr><th>Module</th><th>Community</th><th>Degree</th></tr></thead><tbody>
              ${gods.map(n => `<tr>
                <td style="font-size:0.8rem">${n.label}</td>
                <td class="muted">${n.community}</td>
                <td><b style="color:var(--accent)">${n.degree}</b></td>
              </tr>`).join('')}
            </tbody></table>
          </div>
          <div class="card">
            <h3>Communities</h3>
            <table><thead><tr><th>Community</th><th>Count</th><th>Sample</th></tr></thead><tbody>
              ${comms.map(([k,v]) => `<tr>
                <td>${k}</td><td>${v.count}</td>
                <td class="muted" style="font-size:0.72rem">${(v.sample||[]).slice(0,4).map(s=>s.replace(/^code\\./,'')).join(', ')}</td>
              </tr>`).join('')}
            </tbody></table>
          </div>
        </div>
        <p class="muted" style="margin-top:12px">Graphify-inspired: import edges only, local, no embeddings.
          Rebuild: <code>sakura code-graph --source /path/to/repo --title ${currentTitleId}</code></p>`;
    }

    /* ---- cast ---- */
    async function loadCast() {
      if (!currentTitleId) return;
      const c = await api('/api/cast?examples=true&title=' + encodeURIComponent(currentTitleId));
      if (!c.entries.length) {
        document.getElementById('panel-cast').innerHTML = '<div class="empty">No cast entries</div>';
        return;
      }
      let html = '<div class="cards">';
      for (const e of c.entries) {
        const ch = e.character || {};
        const profile = ch.profile || {};
        html += `<div class="card">
          <div class="row" style="justify-content:space-between">
            <h3>${ch.label || e.character_id}</h3>
            <span class="badge cat">${e.billing || ''}</span>
          </div>
          <div class="muted">${e.character_id}</div>
          <p style="margin:0;font-size:0.9rem">${profile.one_liner || ch.notes || '—'}</p>
          <div class="muted">Unlock: ${e.unlock || '—'} · ${(ch.role_tags||[]).join(', ')}</div>
          <div class="muted">${(profile.personality||[]).join(' · ')}</div>
        </div>`;
      }
      html += '</div>';
      document.getElementById('panel-cast').innerHTML = html;
    }

    /* ---- actions ---- */
    document.getElementById('btnReload').onclick = () => loadProjects().catch(e => log(e.message));
    document.getElementById('btnValidate').onclick = async () => {
      if (!currentTitleId) { log('No catalog title selected'); return; }
      try {
        const data = await api('/api/validate?examples=true&title=' + encodeURIComponent(currentTitleId));
        log(`validate: ${data.errors} error(s), ${data.warnings} warning(s)`);
        for (const f of (data.findings || []).slice(0, 15)) {
          log(`  ${f.severity} ${f.code}: ${f.message}`);
        }
      } catch (e) { log('ERROR: ' + e.message); }
    };
    document.getElementById('btnImport').onclick = async () => {
      if (!currentTitleId) { log('No catalog title selected'); return; }
      try {
        const data = await api('/api/import', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ title_id: currentTitleId, generate_missing: true }),
        });
        log(data.message || JSON.stringify(data));
      } catch (e) { log('ERROR: ' + e.message); }
    };

    (async () => {
      try {
        await refreshHealthFlags();
        await loadProjects();
        const flags = [];
        if (xaiConfigured) flags.push('Imagine ready');
        else flags.push('set XAI_API_KEY for Imagine');
        log('Studio v0.6.0 — Flow node graph · style board · Imagine. ' + flags.join(' · '));
      } catch (e) {
        log('ERROR: ' + e.message);
      }
    })();
  </script>
</body>
</html>
"""
