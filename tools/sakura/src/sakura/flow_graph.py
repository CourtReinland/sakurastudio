"""Scene-centric flow graph for Sakura Studio.

Canvas nodes = playable screens (menu / level / cinematic / ending).
Assets hang *inside* each scene (expand/collapse), not as separate graph noise.
Edges = player progression between scenes only.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sakura.loader import load_catalog
from sakura.yaml_io import dump_yaml, load_yaml

# Progression edges only (scene ↔ scene)
SCENE_EDGE_KINDS = frozenset(
    {"leads_to", "unlocks", "after_level", "choice", "option", "contains"}
)

EDGE_PHRASE: dict[str, str] = {
    "leads_to": "then",
    "unlocks": "unlocks",
    "after_level": "clears →",
    "choice": "choice",
    "option": "if chosen",
    "contains": "contains",
}

# GGD kinds that appear as primary canvas nodes
SCENE_KINDS = frozenset(
    {"scene", "level", "ending", "ui_screen", "minigame", "cg_moment", "system"}
)

NODE_W = 280
NODE_H_COLLAPSED = 72
COL_GAP = 320
ROW_GAP = 160


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "x"


def _title_dir(catalog: Path, title_id: str) -> Path | None:
    index = load_catalog(catalog, include_examples=True)
    ent = index.titles.get(title_id)
    return ent.path.parent if ent else None


def load_flow_positions(catalog: Path, title_id: str) -> dict[str, dict[str, float]]:
    td = _title_dir(catalog, title_id)
    if not td:
        return {}
    path = td / "studio.yaml"
    if not path.is_file():
        return {}
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        return {}
    flow = raw.get("flow") if isinstance(raw.get("flow"), dict) else {}
    pos = flow.get("positions") if isinstance(flow.get("positions"), dict) else {}
    out: dict[str, dict[str, float]] = {}
    for k, v in pos.items():
        if isinstance(v, dict) and "x" in v and "y" in v:
            try:
                out[str(k)] = {"x": float(v["x"]), "y": float(v["y"])}
            except (TypeError, ValueError):
                continue
    return out


def save_flow_positions(
    catalog: Path,
    title_id: str,
    positions: dict[str, dict[str, float]],
) -> Path:
    td = _title_dir(catalog, title_id)
    if not td:
        raise ValueError(f"Unknown title: {title_id}")
    path = td / "studio.yaml"
    if path.is_file():
        raw = load_yaml(path)
        doc = raw if isinstance(raw, dict) else {"title_id": title_id}
    else:
        doc = {"title_id": title_id}
    doc["title_id"] = title_id
    flow = doc.get("flow") if isinstance(doc.get("flow"), dict) else {}
    clean: dict[str, dict[str, float]] = {}
    for k, v in positions.items():
        if not isinstance(v, dict):
            continue
        try:
            clean[str(k)] = {"x": round(float(v["x"]), 1), "y": round(float(v["y"]), 1)}
        except (KeyError, TypeError, ValueError):
            continue
    flow["positions"] = clean
    doc["flow"] = flow
    if "style" not in doc:
        doc["style"] = {
            "enabled": False,
            "asset_id": None,
            "notes": "Project-wide style lock for Grok Imagine.",
        }
    dump_yaml(path, doc)
    return path


def _match_dialogue_scene(
    ggd_scene: dict[str, Any], dlg_scenes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    label = (ggd_scene.get("label") or "").strip().lower()
    sid = str(ggd_scene.get("id") or "")
    tail = sid.split("scene.", 1)[-1].replace("_", "-")
    for sc in dlg_scenes:
        if not isinstance(sc, dict):
            continue
        if (sc.get("label") or "").strip().lower() == label:
            return sc
        did = str(sc.get("id") or "")
        if did == tail or did.replace("-", "_") == tail.replace("-", "_"):
            return sc
        if label and label in (sc.get("label") or "").lower():
            return sc
    return None


def _scene_type(kind: str, data: dict[str, Any] | None = None) -> str:
    data = data or {}
    if data.get("splash") or data.get("is_menu") or kind == "ui_screen":
        return "menu"
    if kind in ("level", "minigame"):
        return "gameplay"
    if kind == "system":
        # e.g. match-3 board hub — gameplay surface, not a title menu
        return "gameplay"
    if kind == "ending":
        return "ending"
    if kind in ("scene", "cg_moment"):
        return "cinematic"
    return "scene"


def auto_layout(nodes: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Left-to-right by story order; stack vertically within column."""
    # columns by type
    col_for = {
        "menu": 0,
        "gameplay": 1,
        "cinematic": 2,
        "scene": 2,
        "ending": 3,
    }
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        st = str(n.get("scene_type") or "scene")
        buckets[col_for.get(st, 2)].append(n)

    def sort_key(n: dict[str, Any]) -> tuple:
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        idx = data.get("index")
        if isinstance(idx, int):
            return (0, idx, n.get("label") or "")
        # splash / menu first
        if n.get("scene_type") == "menu":
            return (-1, 0, n.get("label") or "")
        return (1, n.get("label") or n.get("id") or "")

    positions: dict[str, dict[str, float]] = {}
    for col, items in buckets.items():
        items_sorted = sorted(items, key=sort_key)
        for row, n in enumerate(items_sorted):
            positions[str(n["id"])] = {
                "x": 48.0 + col * COL_GAP,
                "y": 48.0 + row * ROW_GAP,
            }
    return positions


def build_character_bundle(
    catalog: Path,
    title_id: str,
    character_id: str,
) -> dict[str, Any]:
    """Cast member inspector (kept for deep-link from scene assets)."""
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    if title_id not in index.titles:
        raise ValueError(f"Unknown title: {title_id}")
    if character_id not in index.characters:
        raise ValueError(f"Unknown character: {character_id}")

    ch = index.characters[character_id].data
    short = character_id.split(".")[-1]
    files = index.title_files.get(title_id, {})
    slots_ent = files.get("slots")
    slots = (
        [s for s in (slots_ent.data.get("slots") or []) if isinstance(s, dict)]
        if slots_ent
        else []
    )
    bindings_ent = files.get("bindings")
    bind_by = {
        b["slot_id"]: b
        for b in ((bindings_ent.data.get("bindings") if bindings_ent else None) or [])
        if isinstance(b, dict) and b.get("slot_id")
    }

    def slot_pack(sid: str) -> dict[str, Any]:
        slot = next((s for s in slots if s.get("id") == sid), {"id": sid})
        b = bind_by.get(sid) or {}
        aid = b.get("asset_id")
        preview = f"/api/asset-file?asset_id={aid}" if aid else None
        return {
            "slot_id": sid,
            "label": slot.get("label") or sid,
            "kind": slot.get("kind"),
            "asset_id": aid,
            "preview_url": preview,
            "status": b.get("status"),
        }

    portrait, body, walk, swing = [], [], [], []
    for s in slots:
        sid = s.get("id")
        if not isinstance(sid, str) or short not in sid:
            continue
        pack = slot_pack(sid)
        if s.get("kind") == "portrait" or "portrait" in sid:
            portrait.append(pack)
        elif "walk" in sid:
            walk.append(sid and pack)
        elif "swing" in sid:
            swing.append(pack)
        elif s.get("kind") == "sprite" or "sprite" in sid or "full" in sid:
            body.append(pack)

    walk = [x for x in walk if isinstance(x, dict)]
    walk.sort(key=lambda x: x["slot_id"])
    swing.sort(key=lambda x: x["slot_id"])

    voice = None
    tdir = index.titles[title_id].path.parent
    vpath = tdir / "voices.yaml"
    if vpath.is_file():
        vmap = load_yaml(vpath) or {}
        voice = (vmap.get("by_character") or {}).get(character_id)
        if not voice:
            voice = (vmap.get("by_speaker") or {}).get(short)

    return {
        "title_id": title_id,
        "character_id": character_id,
        "label": ch.get("label"),
        "profile": ch.get("profile") or {},
        "visual": ch.get("visual") or {},
        "voice_profile": ch.get("voice") or {},
        "voice_map": voice,
        "portrait": portrait,
        "body": body,
        "clips": {
            "walk": {"frames": walk, "count": len(walk)},
            "swing": {"frames": swing, "count": len(swing)},
        },
    }


def build_flow_graph(
    catalog: Path,
    title_id: str,
    *,
    include_dialogue_detail: bool = True,
    include_all_slots: bool = False,  # kept for API compat; ignored in scene mode
) -> dict[str, Any]:
    """
    Scene-centric flow graph.

    Canvas nodes = screens the player experiences.
    Nested `assets` = graphics, text, dialogue, characters, code refs for that screen.
    Edges = progression between scenes only.
    """
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    if title_id not in index.titles:
        raise ValueError(f"Unknown title: {title_id}")

    files = index.title_files.get(title_id, {})
    title_ent = index.titles[title_id]
    title_data = title_ent.data
    title_dir = title_ent.path.parent

    ggd_ent = files.get("ggd")
    ggd_nodes = (
        [n for n in (ggd_ent.data.get("nodes") or []) if isinstance(n, dict)]
        if ggd_ent
        else []
    )
    ggd_edges = (
        [e for e in (ggd_ent.data.get("edges") or []) if isinstance(e, dict)]
        if ggd_ent
        else []
    )

    slots_ent = files.get("slots")
    slots = (
        [s for s in (slots_ent.data.get("slots") or []) if isinstance(s, dict)]
        if slots_ent
        else []
    )
    slot_by_id = {s["id"]: s for s in slots if s.get("id")}

    bindings_ent = files.get("bindings")
    bindings = (
        [b for b in (bindings_ent.data.get("bindings") or []) if isinstance(b, dict)]
        if bindings_ent
        else []
    )
    bind_by_slot = {
        b["slot_id"]: b for b in bindings if isinstance(b.get("slot_id"), str)
    }

    # dialogue
    dlg_scenes: list[dict[str, Any]] = []
    for name in ("dialogue.yaml", "dialogue.json"):
        p = title_dir / name
        if not p.is_file():
            continue
        if p.suffix == ".json":
            raw = json.loads(p.read_text(encoding="utf-8"))
        else:
            raw = load_yaml(p)
        if isinstance(raw, dict):
            dlg_scenes = [s for s in (raw.get("scenes") or []) if isinstance(s, dict)]
        break

    # cast lookup
    cast_ent = files.get("cast")
    cast_entries = (
        [e for e in (cast_ent.data.get("entries") or []) if isinstance(e, dict)]
        if cast_ent
        else []
    )
    cast_by_id = {
        e["character_id"]: e
        for e in cast_entries
        if isinstance(e.get("character_id"), str)
    }

    # engine (once, as metadata — not a canvas node)
    engine_meta = None
    engine_id = title_data.get("engine_id")
    if isinstance(engine_id, str) and engine_id in index.engines:
        eng = index.engines[engine_id].data
        engine_meta = {
            "id": engine_id,
            "label": eng.get("label"),
            "runtime": eng.get("runtime"),
        }

    # --- Primary scene nodes ---
    scene_nodes_raw: list[dict[str, Any]] = []
    for n in ggd_nodes:
        kind = str(n.get("kind") or "")
        if kind not in SCENE_KINDS:
            continue
        # Skip pure engine systems that aren't player screens (keep board hub)
        if kind == "system":
            lid = str(n.get("id") or "").lower()
            lab = str(n.get("label") or "").lower()
            if "board" not in lid and "menu" not in lab and "title" not in lab:
                continue
        scene_nodes_raw.append(n)

    # Ensure a splash / start if none exists
    has_menu = any(
        _scene_type(str(n.get("kind")), n.get("data") if isinstance(n.get("data"), dict) else {})
        == "menu"
        for n in scene_nodes_raw
    )
    synthetic_splash = False
    if not has_menu:
        synthetic_splash = True
        scene_nodes_raw.insert(
            0,
            {
                "id": "node.ui_screen.title",
                "kind": "ui_screen",
                "label": "Title / Splash",
                "status": "draft",
                "data": {"splash": True, "is_menu": True, "synthetic": True},
                "tags": ["menu", "start"],
            },
        )

    scene_ids = {str(n["id"]) for n in scene_nodes_raw if n.get("id")}

    # Map uses_slot / related edges onto scenes
    slots_used_by_scene: dict[str, list[str]] = defaultdict(list)
    for e in ggd_edges:
        ek = str(e.get("kind") or "")
        frm, to = e.get("from"), e.get("to")
        if ek == "uses_slot" and isinstance(frm, str) and isinstance(to, str):
            if frm in scene_ids and to.startswith("slot."):
                slots_used_by_scene[frm].append(to)
        # also slot used_by field
    for sid, slot in slot_by_id.items():
        for used in slot.get("used_by") or []:
            if isinstance(used, str) and used in scene_ids:
                if sid not in slots_used_by_scene[used]:
                    slots_used_by_scene[used].append(sid)

    def pack_slot(sid: str) -> dict[str, Any] | None:
        slot = slot_by_id.get(sid)
        if not slot:
            # still show unbound reference
            slot = {"id": sid, "label": sid, "kind": "?"}
        b = bind_by_slot.get(sid) or {}
        aid = b.get("asset_id")
        kind = str(slot.get("kind") or "other")
        return {
            "slot_id": sid,
            "label": slot.get("label") or sid,
            "kind": kind,
            "asset_id": aid,
            "preview_url": f"/api/asset-file?asset_id={aid}" if aid else None,
            "status": b.get("status") or ("unbound" if not aid else "draft"),
            "category": _asset_category(kind, sid),
        }

    def code_refs_for(kind: str, nid: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        if kind == "level":
            refs.append(
                {
                    "ref": "levels.yaml",
                    "label": "Level config",
                    "hint": "Match-3 goals, moves, tile pool",
                    "open": "levels",
                }
            )
            refs.append(
                {
                    "ref": "engine.match3",
                    "label": "Match-3 systems (shared engine)",
                    "hint": "Not duplicated per level — edit engine pack once",
                    "open": "engine",
                }
            )
        elif kind in ("scene", "cg_moment"):
            refs.append(
                {
                    "ref": f"dialogue:{nid}",
                    "label": "Dialogue ledger scene",
                    "hint": "Edit lines in node expand or Dialogue tab",
                    "open": "dialogue",
                }
            )
            refs.append(
                {
                    "ref": "engine.vn",
                    "label": "VN / cinematic shell (shared)",
                    "hint": "Speaker UI, skip, save — engine layer",
                    "open": "engine",
                }
            )
        elif kind in ("ui_screen",) or data.get("splash"):
            refs.append(
                {
                    "ref": "ui.title",
                    "label": "Title screen UI controller",
                    "hint": "Buttons, continue/new journey — open IDE / game project",
                    "open": "ide",
                }
            )
        return refs

    nodes: list[dict[str, Any]] = []
    for n in scene_nodes_raw:
        nid = str(n["id"])
        kind = str(n.get("kind") or "scene")
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        stype = _scene_type(kind, data)

        graphics: list[dict[str, Any]] = []
        text_assets: list[dict[str, Any]] = []
        characters: list[dict[str, Any]] = []
        dialogue_lines: list[dict[str, Any]] = []
        choices: list[dict[str, Any]] = []

        for sid in slots_used_by_scene.get(nid, []):
            pack = pack_slot(sid)
            if not pack:
                continue
            cat = pack["category"]
            if cat == "graphic":
                graphics.append(pack)
            elif cat == "piece":
                graphics.append({**pack, "category": "piece"})
            else:
                graphics.append(pack)

        # dialogue attach
        dlg = _match_dialogue_scene(n, dlg_scenes) if include_dialogue_detail else None
        if dlg:
            for dn in dlg.get("nodes") or []:
                if not isinstance(dn, dict):
                    continue
                dkind = str(dn.get("kind") or "")
                if dkind == "line":
                    dialogue_lines.append(
                        {
                            "node_id": dn.get("id"),
                            "speaker": dn.get("speaker"),
                            "text": dn.get("text") or "",
                            "kind": "line",
                            "scene_id": dlg.get("id"),
                        }
                    )
                    sp = (dn.get("speaker") or "").lower()
                    # resolve character
                    for cid, cent in cast_by_id.items():
                        short = cid.split(".")[-1]
                        if sp and (sp == short or sp in cid):
                            if not any(c["character_id"] == cid for c in characters):
                                ch = index.characters.get(cid)
                                label = (
                                    ch.data.get("label")
                                    if ch
                                    else cent.get("character_id")
                                )
                                preview = None
                                for s in slots:
                                    ss = s.get("id") or ""
                                    if short in ss and (
                                        s.get("kind") == "portrait" or "portrait" in ss
                                    ):
                                        b = bind_by_slot.get(ss) or {}
                                        if b.get("asset_id"):
                                            preview = f"/api/asset-file?asset_id={b['asset_id']}"
                                            break
                                characters.append(
                                    {
                                        "character_id": cid,
                                        "label": label,
                                        "billing": cent.get("billing"),
                                        "preview_url": preview,
                                    }
                                )
                elif dkind == "choice":
                    choices.append(
                        {
                            "id": dn.get("id"),
                            "label": dn.get("text") or dn.get("id"),
                            "kind": "choice",
                        }
                    )
                elif dkind == "option":
                    choices.append(
                        {
                            "id": dn.get("id"),
                            "label": dn.get("text") or dn.get("id"),
                            "kind": "option",
                        }
                    )

        # level goals as text
        if kind == "level":
            levels_ent = files.get("levels")
            if levels_ent:
                for lv in levels_ent.data.get("levels") or []:
                    if isinstance(lv, dict) and lv.get("id") == nid:
                        for g in lv.get("goals") or []:
                            if isinstance(g, dict):
                                text_assets.append(
                                    {
                                        "key": f"goal.{g.get('type')}",
                                        "text": f"{g.get('type')}: {g.get('value')}"
                                        + (
                                            f" ({g.get('slot_id')})"
                                            if g.get("slot_id")
                                            else ""
                                        ),
                                        "role": "gameplay",
                                    }
                                )
                        if lv.get("moves"):
                            text_assets.append(
                                {
                                    "key": "moves",
                                    "text": f"Moves: {lv.get('moves')}",
                                    "role": "gameplay",
                                }
                            )
                        # tile pool as piece graphics
                        for ts in lv.get("tile_pool") or []:
                            if isinstance(ts, str) and ts not in [
                                g.get("slot_id") for g in graphics
                            ]:
                                pack = pack_slot(ts)
                                if pack:
                                    graphics.append(pack)
                        break

        # UI screen default text
        if stype == "menu":
            text_assets.append(
                {
                    "key": "ui.play",
                    "text": "Play / New journey",
                    "role": "ui",
                }
            )
            text_assets.append(
                {
                    "key": "ui.continue",
                    "text": "Continue",
                    "role": "ui",
                }
            )

        asset_counts = {
            "graphics": len(graphics),
            "text": len(text_assets),
            "dialogue": len(dialogue_lines),
            "characters": len(characters),
            "choices": len(choices),
            "code": len(code_refs_for(kind, nid, data)),
        }

        preview = None
        for g in graphics:
            if g.get("preview_url") and g.get("kind") in (
                "cg",
                "bg",
                "portrait",
                "ui",
                "sprite",
            ):
                preview = g["preview_url"]
                break

        nodes.append(
            {
                "id": nid,
                "kind": kind,
                "scene_type": stype,
                "layer": "scene",  # single layer for canvas
                "label": str(n.get("label") or nid),
                "subtitle": f"{stype} · {sum(asset_counts.values())} assets",
                "status": n.get("status"),
                "data": {**data, "open": "scene"},
                "preview_url": preview,
                "source": "synthetic" if data.get("synthetic") else "ggd",
                "assets": {
                    "graphics": graphics,
                    "text": text_assets,
                    "dialogue": dialogue_lines[:80],  # cap for payload
                    "characters": characters,
                    "choices": choices,
                    "code": code_refs_for(kind, nid, data),
                },
                "asset_counts": asset_counts,
                "dialogue_scene_id": (dlg or {}).get("id") if dlg else None,
            }
        )

    # --- Edges between scenes only ---
    edges: list[dict[str, Any]] = []
    seen_e: set[tuple[str, str, str]] = set()
    node_id_set = {n["id"] for n in nodes}

    def add_edge(ekind: str, frm: str, to: str, label: str | None = None, data: dict | None = None) -> None:
        if frm not in node_id_set or to not in node_id_set:
            return
        key = (ekind, frm, to)
        if key in seen_e:
            return
        seen_e.add(key)
        edges.append(
            {
                "id": f"edge.{_slug(ekind)}.{_slug(frm)}.{_slug(to)}",
                "kind": ekind,
                "from": frm,
                "to": to,
                "label": label or EDGE_PHRASE.get(ekind, ekind),
                "data": data or {},
            }
        )

    for e in ggd_edges:
        ek = str(e.get("kind") or "")
        frm, to = e.get("from"), e.get("to")
        if not isinstance(frm, str) or not isinstance(to, str):
            continue
        # promote level→scene and scene→scene
        if ek in ("leads_to", "unlocks", "contains") and frm in node_id_set and to in node_id_set:
            phrase = None
            if isinstance(e.get("data"), dict) and e["data"].get("choice"):
                phrase = str(e["data"]["choice"])
            elif e.get("label"):
                phrase = str(e["label"])
            add_edge(ek if ek != "contains" else "leads_to", frm, to, phrase, e.get("data") if isinstance(e.get("data"), dict) else {})
        # after_level style: level leads_to scene already covered

    # synthetic splash → first level or first scene
    if synthetic_splash and "node.ui_screen.title" in node_id_set:
        first = None
        for n in nodes:
            if n["id"] == "node.ui_screen.title":
                continue
            if n.get("scene_type") == "gameplay" and (n.get("data") or {}).get("index") == 1:
                first = n["id"]
                break
        if not first:
            for n in nodes:
                if n["id"] != "node.ui_screen.title" and n.get("kind") == "scene":
                    first = n["id"]
                    break
        if first:
            add_edge("leads_to", "node.ui_screen.title", first, "Play")

    # positions
    saved = load_flow_positions(root, title_id)
    auto = auto_layout(nodes)
    layout_saved = bool(saved)
    for n in nodes:
        nid = n["id"]
        pos = saved.get(nid) or auto.get(nid) or {"x": 40, "y": 40}
        n["x"] = pos["x"]
        n["y"] = pos["y"]

    return {
        "title_id": title_id,
        "mode": "scenes",
        "engine": engine_meta,
        "nodes": nodes,
        "edges": edges,
        "layers": ["scene"],
        "legend": [
            {"kind": "leads_to", "phrase": "then"},
            {"kind": "unlocks", "phrase": "unlocks"},
            {"kind": "menu", "phrase": "menu / splash"},
            {"kind": "gameplay", "phrase": "gameplay level"},
            {"kind": "cinematic", "phrase": "story scene"},
            {"kind": "ending", "phrase": "ending"},
        ],
        "layout_saved": layout_saved,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "scenes": sum(1 for n in nodes if n.get("scene_type") == "cinematic"),
            "levels": sum(1 for n in nodes if n.get("scene_type") == "gameplay"),
            "menus": sum(1 for n in nodes if n.get("scene_type") == "menu"),
            "endings": sum(1 for n in nodes if n.get("scene_type") == "ending"),
        },
    }


def _asset_category(kind: str, slot_id: str) -> str:
    if kind in ("cg", "bg", "portrait", "ui", "texture", "icon") or "cg." in slot_id or "bg." in slot_id:
        return "graphic"
    if kind == "sprite" or "piece." in slot_id or "tile." in slot_id:
        return "piece"
    if "line." in slot_id or kind == "other":
        return "text"
    return "graphic"


def create_scene_node(
    catalog: Path,
    title_id: str,
    *,
    label: str,
    kind: str = "scene",
    scene_type: str | None = None,
    after_id: str | None = None,
) -> dict[str, Any]:
    """Append a scene to GGD and optional edge from after_id."""
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    if title_id not in index.titles:
        raise ValueError(f"Unknown title: {title_id}")
    files = index.title_files.get(title_id, {})
    ggd_ent = files.get("ggd")
    if not ggd_ent:
        raise ValueError("Title has no ggd.yaml")
    path = ggd_ent.path
    doc = load_yaml(path) if path.is_file() else {"title_id": title_id, "nodes": [], "edges": []}
    if not isinstance(doc, dict):
        doc = {"title_id": title_id, "nodes": [], "edges": []}
    nodes = list(doc.get("nodes") or [])
    edges = list(doc.get("edges") or [])

    base = _slug(label)
    nid = f"node.{kind}.{base.replace('-', '_')}"
    # unique
    existing = {n.get("id") for n in nodes if isinstance(n, dict)}
    i = 2
    orig = nid
    while nid in existing:
        nid = f"{orig}_{i}"
        i += 1

    st = scene_type or _scene_type(kind, {})
    node = {
        "id": nid,
        "kind": kind if kind in SCENE_KINDS else "scene",
        "label": label,
        "status": "draft",
        "data": {"scene_type": st, "created_in": "studio_flow"},
        "tags": ["flow", st],
    }
    nodes.append(node)
    if after_id and after_id in existing:
        edges.append(
            {
                "id": f"edge.leads_to.{_slug(after_id)}.{_slug(nid)}",
                "kind": "leads_to",
                "from": after_id,
                "to": nid,
                "label": "then",
            }
        )
    doc["nodes"] = nodes
    doc["edges"] = edges
    doc["title_id"] = title_id
    dump_yaml(path, doc)
    return {"ok": True, "node": node, "path": str(path)}


def connect_scenes(
    catalog: Path,
    title_id: str,
    *,
    from_id: str,
    to_id: str,
    kind: str = "leads_to",
    label: str | None = None,
) -> dict[str, Any]:
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    if title_id not in index.titles:
        raise ValueError(f"Unknown title: {title_id}")
    ggd_ent = index.title_files.get(title_id, {}).get("ggd")
    if not ggd_ent:
        raise ValueError("Title has no ggd.yaml")
    path = ggd_ent.path
    doc = load_yaml(path) or {"title_id": title_id, "nodes": [], "edges": []}
    edges = list(doc.get("edges") or [])
    # dedupe
    for e in edges:
        if (
            isinstance(e, dict)
            and e.get("from") == from_id
            and e.get("to") == to_id
            and e.get("kind") == kind
        ):
            return {"ok": True, "edge": e, "message": "already connected"}
    edge = {
        "id": f"edge.{_slug(kind)}.{_slug(from_id)}.{_slug(to_id)}",
        "kind": kind,
        "from": from_id,
        "to": to_id,
        "label": label or EDGE_PHRASE.get(kind, kind),
    }
    edges.append(edge)
    doc["edges"] = edges
    dump_yaml(path, doc)
    return {"ok": True, "edge": edge, "path": str(path)}


def disconnect_scenes(
    catalog: Path,
    title_id: str,
    *,
    from_id: str,
    to_id: str,
) -> dict[str, Any]:
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    ggd_ent = index.title_files.get(title_id, {}).get("ggd")
    if not ggd_ent:
        raise ValueError("Title has no ggd.yaml")
    path = ggd_ent.path
    doc = load_yaml(path) or {}
    edges = [
        e
        for e in (doc.get("edges") or [])
        if not (
            isinstance(e, dict)
            and e.get("from") == from_id
            and e.get("to") == to_id
            and str(e.get("kind")) in SCENE_EDGE_KINDS | {"leads_to", "unlocks"}
        )
    ]
    removed = len(doc.get("edges") or []) - len(edges)
    doc["edges"] = edges
    dump_yaml(path, doc)
    return {"ok": True, "removed": removed}
