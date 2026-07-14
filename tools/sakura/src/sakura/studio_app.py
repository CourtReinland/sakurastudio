from __future__ import annotations

import json
import mimetypes
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from sakura.bind import bind_set, bind_set_status, bind_unbind, resolve_title_id
from sakura.code_graph import load_title_code_graph
from sakura.github_projects import project_tabs
from sakura.import_unity import import_title
from sakura.loader import discover_catalog_root, load_catalog
from sakura.validate import run_validate, summarize
from sakura.yaml_io import load_yaml

app = FastAPI(title="Sakura Studio", version="0.4.0")

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


@app.get("/api/health")
def health(catalog: str | None = None) -> dict[str, Any]:
    root = _catalog(catalog)
    return {"ok": True, "catalog": str(root), "version": "0.4.0"}


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
    return {
        "title_id": title_id,
        "source": data.get("source"),
        "imported_at": data.get("imported_at"),
        "summary": summary,
        "scenes": scenes,
    }


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
def index() -> str:
    return STUDIO_HTML


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
    .thumb {
      width: 100%; aspect-ratio: 1; object-fit: contain; background: #100c16;
      border-radius: 8px; border: 1px dashed var(--border);
    }
    .thumb.placeholder {
      display: grid; place-items: center; color: var(--muted); font-size: 0.82rem; min-height: 120px;
    }
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
      <h1>🌸 <span>Sakura</span> Studio</h1>
      <div class="muted">Catalog control surface · swaps · story map · multi-repo tabs</div>
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
  <main>
    <div class="tabs" id="mainTabs">
      <button type="button" data-tab="overview" class="active">Overview</button>
      <button type="button" data-tab="swaps">Swaps ★</button>
      <button type="button" data-tab="story">Story</button>
      <button type="button" data-tab="dialogue">Dialogue</button>
      <button type="button" data-tab="cast">Cast</button>
      <button type="button" data-tab="code">Code map</button>
    </div>

    <section id="panel-overview" class="panel active"></section>
    <section id="panel-swaps" class="panel">
      <div class="filter-row row">
        <span class="muted">Filter:</span>
        <button type="button" class="secondary cat-filter active" data-cat="all">All</button>
        <button type="button" class="secondary cat-filter" data-cat="graphic">Graphics</button>
        <button type="button" class="secondary cat-filter" data-cat="piece">Game pieces</button>
        <button type="button" class="secondary cat-filter" data-cat="dialogue">Character lines</button>
        <button type="button" class="secondary cat-filter" data-cat="story">Story elements</button>
      </div>
      <div class="muted" style="margin-bottom:6px">Asset library — drag onto a slot card to rebind</div>
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
        document.getElementById('panel-overview').innerHTML =
          `<div class="empty">This GitHub repo is not mapped to a catalog title yet.<br/>
           Add it in <code>catalog/_meta/github_projects.yaml</code> or create <code>titles/…</code>.
           <p class="muted">${opt.textContent}</p></div>`;
        document.getElementById('swapCards').innerHTML = '';
        document.getElementById('library').innerHTML = '';
        document.getElementById('panel-story').innerHTML = '';
        document.getElementById('panel-dialogue').innerHTML = '';
        document.getElementById('panel-cast').innerHTML = '';
        document.getElementById('panel-code').innerHTML = '';
        log('Selected unmapped project: ' + opt.textContent);
        return;
      }
      currentTitleId = titleId;
      await Promise.all([
        loadOverview(), loadSwaps(), loadStory(), loadDialogue(), loadCast(), loadCode(),
      ]);
    }

    projectEl.addEventListener('change', () => onProjectChange().catch(e => log(e.message)));

    /* ---- overview ---- */
    async function loadOverview() {
      if (!currentTitleId) return;
      const o = await api('/api/overview?examples=true&title=' + encodeURIComponent(currentTitleId));
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
        <div class="statgrid">
          <div class="stat"><b>${o.stats.nodes}</b><span class="muted">GGD nodes</span></div>
          <div class="stat"><b>${o.stats.slots}</b><span class="muted">Slots</span></div>
          <div class="stat"><b>${o.stats.bindings}</b><span class="muted">Bindings</span></div>
          <div class="stat"><b>${o.stats.cast}</b><span class="muted">Cast</span></div>
          <div class="stat"><b>${o.stats.unbound_required}</b><span class="muted">Unbound required</span></div>
          <div class="stat"><b>${o.stats.assets_library}</b><span class="muted">Library assets</span></div>
        </div>
        <div class="two-col">
          <div class="card">
            <h3>GGD node kinds</h3>
            <table><thead><tr><th>Kind</th><th>Count</th></tr></thead><tbody>${kindRows || '<tr><td colspan=2 class="muted">none</td></tr>'}</tbody></table>
          </div>
          <div class="card">
            <h3>Notes</h3>
            <p class="muted" style="white-space:pre-wrap;margin:0">${o.notes || '—'}</p>
            <p class="muted" style="margin-top:10px">Platforms: ${(o.platforms||[]).join(', ') || '—'}</p>
            <p class="muted">Brand: ${o.brand ? o.brand.label : '—'}</p>
          </div>
        </div>
      `;
    }

    /* ---- swaps + dnd ---- */
    async function loadSwaps() {
      if (!currentTitleId) return;
      const q = new URLSearchParams({ examples: 'true', title: currentTitleId });
      if (swapCategory !== 'all') q.set('category', swapCategory);
      const data = await api('/api/bindings?' + q.toString());
      renderLibrary(data.assets || []);
      renderSwapCards(data);
    }

    function renderLibrary(assets) {
      const lib = document.getElementById('library');
      if (!assets.length) {
        lib.innerHTML = '<div class="muted">No library assets yet — import or generate art into catalog/assets/</div>';
        return;
      }
      lib.innerHTML = assets.map(a => `
        <div class="lib-item" draggable="true" data-asset-id="${a.id}" title="${a.id}">
          <img src="${a.preview_url}" alt="" onerror="this.style.opacity=0.2" />
          <div class="id">${a.id.replace(/^asset\\./,'')}</div>
        </div>
      `).join('');
      lib.querySelectorAll('.lib-item').forEach(el => {
        el.addEventListener('dragstart', (ev) => {
          dragAssetId = el.dataset.assetId;
          ev.dataTransfer.setData('text/plain', dragAssetId);
          ev.dataTransfer.effectAllowed = 'copy';
        });
      });
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
        const thumb = row.preview_url
          ? `<img class="thumb" src="${row.preview_url}" alt="" />`
          : `<div class="thumb placeholder">drop asset here</div>`;
        card.innerHTML = `
          <div class="row" style="justify-content:space-between">
            <h3>${slot.label || slot.id}</h3>
            <span class="badge ${badgeStatus(status)}">${status}</span>
          </div>
          <div class="muted">${slot.id}</div>
          <div class="row">
            <span class="badge cat">${row.category}</span>
            <span class="badge">${slot.kind || '?'}</span>
            ${slot.required === false ? '<span class="badge">optional</span>' : '<span class="badge warn">required</span>'}
          </div>
          ${thumb}
          <div class="field">
            <label>Asset</label>
            <select class="asset-select"><option value="">—</option>${assetOpts}</select>
          </div>
          <div class="row">
            <button type="button" class="btn-bind">Bind</button>
            <button type="button" class="btn-approve secondary">Approve</button>
            <button type="button" class="btn-unbind danger">Unbind</button>
          </div>
        `;
        const sel = card.querySelector('.asset-select');
        card.querySelector('.btn-bind').onclick = () => doBind(slot.id, sel.value);
        card.querySelector('.btn-approve').onclick = () => doStatus(slot.id, 'approved');
        card.querySelector('.btn-unbind').onclick = () => doUnbind(slot.id);
        card.addEventListener('dragover', (ev) => {
          ev.preventDefault();
          card.classList.add('drop-target');
        });
        card.addEventListener('dragleave', () => card.classList.remove('drop-target'));
        card.addEventListener('drop', async (ev) => {
          ev.preventDefault();
          card.classList.remove('drop-target');
          const id = ev.dataTransfer.getData('text/plain') || dragAssetId;
          if (!id) return;
          sel.value = id;
          await doBind(slot.id, id);
        });
        host.appendChild(card);
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
        if (confirm('Force bind despite constraints?\n' + e.message)) {
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

    /* ---- dialogue ledger ---- */
    async function loadDialogue() {
      if (!currentTitleId) return;
      const d = await api('/api/dialogue?examples=true&title=' + encodeURIComponent(currentTitleId));
      if (!(d.summary || []).length) {
        document.getElementById('panel-dialogue').innerHTML =
          '<div class="empty">No dialogue ledger. Run: sakura sync-tea-house --source &lt;sakura-match&gt;</div>';
        return;
      }
      let html = `<p class="muted">${d.source || ''} · ${d.summary.length} scenes ·
        ${d.summary.reduce((a,s)=>a+(s.line_count||0),0)} lines</p>
        <div class="row" style="margin-bottom:10px">
          <label class="muted">Scene</label>
          <select id="dialogueScene"><option value="">All scenes (summary)</option>
          ${d.summary.map(s => `<option value="${s.id}">${s.label} (${s.line_count} lines)</option>`).join('')}
          </select>
        </div>
        <div id="dialogueBody"></div>`;
      document.getElementById('panel-dialogue').innerHTML = html;
      const body = document.getElementById('dialogueBody');
      function renderSummary() {
        body.innerHTML = `<table><thead><tr><th>Scene</th><th>Id</th><th>Lines</th><th>Choices</th><th>Nodes</th></tr></thead><tbody>
          ${d.summary.map(s => `<tr>
            <td>${s.label}</td><td class="muted">${s.id}</td>
            <td>${s.line_count}</td><td>${s.choice_count}</td><td>${s.node_count}</td>
          </tr>`).join('')}
        </tbody></table>
        <p class="muted">Open a scene for full ledger. Line text is also bound as <code>slot.line.tea.*</code> under Swaps → Character lines.</p>`;
      }
      async function renderScene(sid) {
        const full = await api('/api/dialogue?examples=true&title=' + encodeURIComponent(currentTitleId) + '&scene=' + encodeURIComponent(sid));
        const sc = (full.scenes || [])[0];
        if (!sc) { body.innerHTML = '<div class="empty">Scene not found</div>'; return; }
        body.innerHTML = `<div class="card"><h3>${sc.label}</h3>
          <div class="muted">start: ${sc.start_node || '—'} · terminals: ${(sc.terminal_paths||[]).join(', ') || '—'}</div>
          <table><thead><tr><th>Node</th><th>Kind</th><th>Speaker</th><th>Text</th></tr></thead><tbody>
          ${(sc.nodes||[]).map(n => `<tr>
            <td class="muted" style="font-size:0.75rem">${n.id}</td>
            <td><span class="badge cat">${n.kind}</span></td>
            <td>${n.speaker || '—'}</td>
            <td style="font-size:0.85rem">${(n.text||'').replace(/</g,'&lt;')}</td>
          </tr>`).join('')}
          </tbody></table></div>`;
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
        await loadProjects();
        log('Studio v0.4 — Dialogue ledger, asset library, Code map (graphify-style).');
      } catch (e) {
        log('ERROR: ' + e.message);
      }
    })();
  </script>
</body>
</html>
"""
