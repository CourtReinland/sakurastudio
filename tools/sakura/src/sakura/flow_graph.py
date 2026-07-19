"""Build a rearrangeable story/art/engine flow graph for Studio."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sakura.loader import load_catalog
from sakura.yaml_io import dump_yaml, load_yaml

# Human-readable connector copy (Nuke-style: edge says what happens)
EDGE_PHRASE: dict[str, str] = {
    "leads_to": "then opens",
    "unlocks": "unlocks",
    "contains": "contains",
    "uses_slot": "uses art slot",
    "requires": "requires",
    "modifies": "modifies",
    "references": "references",
    "binds": "shows asset",
    "has_dialogue": "plays dialogue",
    "runs": "runs in engine",
    "choice": "player chooses",
    "option": "choice leads to",
    "after_level": "level completes →",
    "has_portrait": "hero portrait",
    "has_body": "full body",
    "has_anim": "anim clip frame",
    "has_voice": "speaks with",
    "plays_on": "plays on course",
}

LAYER_FOR_KIND: dict[str, str] = {
    "route": "story",
    "level": "story",
    "scene": "story",
    "ending": "story",
    "choice": "dialogue",
    "option": "dialogue",
    "dialogue": "dialogue",
    "system": "engine",
    "engine": "engine",
    "slot": "art",
    "asset": "art",
    "character": "cast",
    "anim_clip": "cast",
    "world": "engine",
    "gate": "story",
    "beat": "story",
    "cg_moment": "art",
    "minigame": "story",
    "flag": "story",
    "other": "story",
}

NODE_W = 180
NODE_H = 64
COL_GAP = 240
ROW_GAP = 88


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s


def _match_dialogue_scene(ggd_scene: dict[str, Any], dlg_scenes: list[dict[str, Any]]) -> dict[str, Any] | None:
    label = (ggd_scene.get("label") or "").strip().lower()
    sid = str(ggd_scene.get("id") or "")
    # node.scene.visitor_dusk → visitor-dusk-ish
    tail = sid.split("scene.", 1)[-1].replace("_", "-")
    for sc in dlg_scenes:
        if not isinstance(sc, dict):
            continue
        if (sc.get("label") or "").strip().lower() == label:
            return sc
        did = str(sc.get("id") or "")
        if did == tail or did.replace("-", "_") == tail.replace("-", "_"):
            return sc
        # fuzzy: token overlap
        if label and label in (sc.get("label") or "").lower():
            return sc
    return None


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
    doc: dict[str, Any]
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
    # preserve style if missing
    if "style" not in doc:
        doc["style"] = {
            "enabled": False,
            "asset_id": None,
            "notes": "Project-wide style lock for Grok Imagine.",
        }
    dump_yaml(path, doc)
    return path


def auto_layout(nodes: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Column layout by narrative role; stable sort within columns."""
    columns: dict[str, int] = {
        "route": 0,
        "character": 0,
        "level": 1,
        "minigame": 1,
        "world": 1,
        "scene": 2,
        "dialogue": 3,
        "choice": 3,
        "option": 4,
        "ending": 5,
        "anim_clip": 5,
        "system": 6,
        "engine": 6,
        "slot": 7,
        "asset": 8,
        "gate": 2,
        "cg_moment": 7,
        "flag": 4,
        "other": 4,
    }
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        kind = str(n.get("kind") or "other")
        buckets[columns.get(kind, 4)].append(n)

    def sort_key(n: dict[str, Any]) -> tuple:
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        idx = data.get("index")
        if isinstance(idx, int):
            return (0, idx, n.get("label") or n.get("id") or "")
        return (1, n.get("label") or n.get("id") or "")

    positions: dict[str, dict[str, float]] = {}
    for col, items in buckets.items():
        items_sorted = sorted(items, key=sort_key)
        for row, n in enumerate(items_sorted):
            nid = str(n["id"])
            positions[nid] = {
                "x": 40 + col * COL_GAP,
                "y": 40 + row * ROW_GAP,
            }
    return positions


def build_character_bundle(
    catalog: Path,
    title_id: str,
    character_id: str,
) -> dict[str, Any]:
    """Everything Studio needs to edit a cast member from Flow double-click."""
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
            walk.append(pack)
        elif "swing" in sid:
            swing.append(pack)
        elif s.get("kind") == "sprite" or "sprite" in sid or "full" in sid:
            body.append(pack)

    walk.sort(key=lambda x: x["slot_id"])
    swing.sort(key=lambda x: x["slot_id"])

    voice = None
    tdir = index.titles[title_id].path.parent
    vpath = tdir / "voices.yaml"
    if vpath.is_file():
        vmap = load_yaml(vpath) or {}
        voice = (vmap.get("by_character") or {}).get(character_id)
        if not voice:
            # try by speaker short name
            voice = (vmap.get("by_speaker") or {}).get(short)

    # Runtime path hints for nightmare-golf style games
    runtime_hints = {
        "idle": f"assets/img/cut/{short}_full.png" if short != "kirara" else "assets/img/cut/kirara_full2.png",
        "walk_pattern": f"assets/img/cut/{short}_walk{{n}}.png",
        "swing_pattern": f"assets/img/cut/{short}_swing{{n}}.png",
        "engine_note": (
            "Game currently hardcodes cutout paths in engine.js — "
            "Swaps rebinds update the catalog; re-export/copy binaries into the game to see them live."
        ),
    }

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
            "walk": {
                "frames": walk,
                "count": len(walk),
                "pipeline_skill": "game-animation-frames",
                "recommended": "video-first: base → image_to_video → harvest → flip-test loop",
            },
            "swing": {
                "frames": swing,
                "count": len(swing),
                "pipeline_skill": "game-animation-frames",
                "recommended": "key poses from base via image_edit with freeze-list (not independent gens)",
            },
        },
        "runtime_hints": runtime_hints,
        "diagnosis": _anim_diagnosis(walk, swing, body),
    }


def _anim_diagnosis(
    walk: list[dict[str, Any]],
    swing: list[dict[str, Any]],
    body: list[dict[str, Any]],
) -> list[str]:
    notes: list[str] = []
    if len(walk) < 4:
        notes.append(
            f"Walk has only {len(walk)} catalog frames (ideal 6–12 from a video cycle for smooth gait)."
        )
    if len(walk) >= 2:
        notes.append(
            "Walk frames were likely generated as independent stills (not video-harvested). "
            "Regenerate with game-animation-frames skill: base → video → extract → flip-test."
        )
    if not body:
        notes.append("No full-body / idle sprite slot matched this character.")
    if len(swing) < 3:
        notes.append(
            f"Swing has {len(swing)} frames — a golf swing usually wants anticipation, impact, follow-through (3–6)."
        )
    notes.append(
        "Runtime faces cutouts using scale.x flip; art must share a consistent facing "
        "(Midnight Par Hana art is right-facing). Mixed facing between frames = ganky turns."
    )
    return notes


def build_flow_graph(
    catalog: Path,
    title_id: str,
    *,
    include_dialogue_detail: bool = True,
    include_all_slots: bool = False,
) -> dict[str, Any]:
    """
    Aggregate GGD + dialogue + bindings + engine into a flow graph.

    Node ids stay stable (node.*, slot.*, synth.*).
    """
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    if title_id not in index.titles:
        raise ValueError(f"Unknown title: {title_id}")

    files = index.title_files.get(title_id, {})
    title_ent = index.titles[title_id]
    title_data = title_ent.data

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
    title_dir = title_ent.path.parent
    for name in ("dialogue.yaml", "dialogue.json"):
        p = title_dir / name
        if p.is_file():
            raw = load_yaml(p) if p.suffix == ".yaml" else None
            if raw is None and p.suffix == ".json":
                import json

                raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                dlg_scenes = [
                    s for s in (raw.get("scenes") or []) if isinstance(s, dict)
                ]
            break

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(
        nid: str,
        *,
        kind: str,
        label: str,
        status: str | None = None,
        data: dict[str, Any] | None = None,
        subtitle: str | None = None,
        preview_url: str | None = None,
        source: str = "ggd",
    ) -> None:
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        layer = LAYER_FOR_KIND.get(kind, "story")
        nodes.append(
            {
                "id": nid,
                "kind": kind,
                "layer": layer,
                "label": label,
                "subtitle": subtitle,
                "status": status,
                "data": data or {},
                "preview_url": preview_url,
                "source": source,
            }
        )

    def add_edge(
        ekind: str,
        frm: str,
        to: str,
        *,
        label: str | None = None,
        eid: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        key = (ekind, frm, to)
        if key in seen_edges:
            return
        if frm not in seen_nodes or to not in seen_nodes:
            return
        seen_edges.add(key)
        phrase = label or EDGE_PHRASE.get(ekind, ekind.replace("_", " "))
        edges.append(
            {
                "id": eid or f"edge.{_slug(ekind)}.{_slug(frm)}.{_slug(to)}",
                "kind": ekind,
                "from": frm,
                "to": to,
                "label": phrase,
                "data": data or {},
            }
        )

    # --- GGD nodes ---
    for n in ggd_nodes:
        nid = n.get("id")
        if not isinstance(nid, str):
            continue
        add_node(
            nid,
            kind=str(n.get("kind") or "other"),
            label=str(n.get("label") or nid),
            status=n.get("status"),
            data=n.get("data") if isinstance(n.get("data"), dict) else {},
            source="ggd",
        )

    # --- Engine node ---
    engine_id = title_data.get("engine_id")
    engine_node_id = None
    if isinstance(engine_id, str) and engine_id in index.engines:
        eng = index.engines[engine_id].data
        engine_node_id = f"synth.engine.{engine_id.replace('engine.', '')}"
        add_node(
            engine_node_id,
            kind="engine",
            label=str(eng.get("label") or engine_id),
            subtitle=str(eng.get("runtime") or ""),
            status=eng.get("status"),
            data={"engine_id": engine_id, "runtime": eng.get("runtime")},
            source="title",
        )

    # --- Cast → first-class character nodes (+ anim clips) ---
    cast_ent = files.get("cast")
    cast_entries = (
        [e for e in (cast_ent.data.get("entries") or []) if isinstance(e, dict)]
        if cast_ent
        else []
    )
    # Character → slots to wire after slot nodes exist
    pending_char_edges: list[tuple[str, str, str, str]] = []  # (kind, from, to, label)
    char_nodes: dict[str, str] = {}  # character_id → node id

    for entry in cast_entries:
        cid = entry.get("character_id")
        if not isinstance(cid, str) or cid not in index.characters:
            continue
        ch = index.characters[cid].data
        short = cid.split(".")[-1]
        cnode = f"synth.character.{cid.replace('chr.', '').replace('.', '_')}"
        char_nodes[cid] = cnode
        portrait_preview = None
        walk_slots: list[str] = []
        swing_slots: list[str] = []
        body_slots: list[str] = []
        portrait_slots: list[str] = []
        for sid, slot in slot_by_id.items():
            if short not in sid:
                continue
            sk = str(slot.get("kind") or "")
            if sk == "portrait" or "portrait" in sid:
                portrait_slots.append(sid)
                b = bind_by_slot.get(sid)
                if b and b.get("asset_id") and not portrait_preview:
                    portrait_preview = f"/api/asset-file?asset_id={b['asset_id']}"
            elif "walk" in sid:
                walk_slots.append(sid)
            elif "swing" in sid:
                swing_slots.append(sid)
            elif sk == "sprite" or "sprite" in sid or "full" in sid:
                body_slots.append(sid)

        add_node(
            cnode,
            kind="character",
            label=str(ch.get("label") or cid),
            subtitle=str(entry.get("billing") or ",".join(ch.get("role_tags") or [])),
            status=ch.get("status"),
            preview_url=portrait_preview,
            data={
                "character_id": cid,
                "billing": entry.get("billing"),
                "role_tags": ch.get("role_tags") or [],
                "open": "character",
                "portrait_slots": portrait_slots,
                "body_slots": body_slots,
                "walk_slots": sorted(walk_slots),
                "swing_slots": sorted(swing_slots),
            },
            source="cast",
        )
        for sid in portrait_slots:
            pending_char_edges.append(("has_portrait", cnode, sid, "hero portrait"))
        for sid in body_slots:
            pending_char_edges.append(("has_body", cnode, sid, "full body"))
        if walk_slots:
            clip_id = f"synth.anim.{short}_walk"
            add_node(
                clip_id,
                kind="anim_clip",
                label=f"{ch.get('label') or short} · walk cycle",
                subtitle=f"{len(walk_slots)} frames · catalog slots",
                data={
                    "character_id": cid,
                    "clip": "walk",
                    "frame_slots": sorted(walk_slots),
                    "open": "character",
                    "fps_hint": 7,
                },
                source="slots",
            )
            pending_char_edges.append(("has_anim", cnode, clip_id, "walk cycle"))
            for sid in walk_slots:
                pending_char_edges.append(("has_anim", clip_id, sid, "frame"))
        if swing_slots:
            clip_id = f"synth.anim.{short}_swing"
            add_node(
                clip_id,
                kind="anim_clip",
                label=f"{ch.get('label') or short} · swing",
                subtitle=f"{len(swing_slots)} frames · catalog slots",
                data={
                    "character_id": cid,
                    "clip": "swing",
                    "frame_slots": sorted(swing_slots),
                    "open": "character",
                },
                source="slots",
            )
            pending_char_edges.append(("has_anim", cnode, clip_id, "swing clip"))
            for sid in swing_slots:
                pending_char_edges.append(("has_anim", clip_id, sid, "frame"))

    # World / course node for minigame titles
    world_id = None
    hole_nodes = [n for n in ggd_nodes if n.get("kind") in ("minigame", "level")]
    if hole_nodes:
        world_id = "synth.world.course"
        add_node(
            world_id,
            kind="world",
            label="Golf course / world",
            subtitle=f"{len(hole_nodes)} holes · turf · lighting",
            data={
                "open": "world",
                "holes": [n.get("id") for n in hole_nodes if n.get("id")],
            },
            source="ggd",
        )

    # --- GGD edges ---
    slot_ids_needed: set[str] = set()
    # Include every slot referenced by characters so art shows in Flow
    for _kind, _frm, to, _lab in pending_char_edges:
        if to.startswith("slot."):
            slot_ids_needed.add(to)
    for e in ggd_edges:
        frm = e.get("from")
        to = e.get("to")
        kind = str(e.get("kind") or "leads_to")
        if not isinstance(frm, str) or not isinstance(to, str):
            continue
        if kind == "uses_slot" and to.startswith("slot."):
            slot_ids_needed.add(to)
        if to.startswith("slot."):
            slot_ids_needed.add(to)

    if include_all_slots or cast_entries:
        for sid in slot_by_id:
            slot_ids_needed.add(sid)

    # From uses_slot edges collect slots
    for e in ggd_edges:
        if e.get("kind") == "uses_slot" and isinstance(e.get("to"), str):
            slot_ids_needed.add(e["to"])

    # --- Slot + asset nodes ---
    for sid in sorted(slot_ids_needed):
        if not sid or not sid.startswith("slot."):
            continue
        slot = slot_by_id.get(sid) or {"id": sid, "label": sid, "kind": "other"}
        add_node(
            sid,
            kind="slot",
            label=str(slot.get("label") or sid),
            subtitle=str(slot.get("kind") or "slot"),
            status=slot.get("status"),
            data={"slot_kind": slot.get("kind")},
            source="slots",
        )
        b = bind_by_slot.get(sid)
        if b and isinstance(b.get("asset_id"), str):
            aid = b["asset_id"]
            ad = index.assets.get(aid)
            label = aid
            preview = f"/api/asset-file?asset_id={aid}"
            if ad:
                label = str(ad.data.get("label") or aid)
            add_node(
                aid,
                kind="asset",
                label=label,
                subtitle=aid.replace("asset.", "")[:40],
                status=(ad.data.get("status") if ad else None),
                preview_url=preview,
                data={"asset_id": aid},
                source="bindings",
            )
            add_edge("binds", sid, aid, label="shows asset")

    # GGD edges (after slots exist)
    for e in ggd_edges:
        frm = e.get("from")
        to = e.get("to")
        kind = str(e.get("kind") or "leads_to")
        if not isinstance(frm, str) or not isinstance(to, str):
            continue
        # create dangling slot targets already handled
        if to.startswith("slot.") and to not in seen_nodes:
            continue
        if frm.startswith("slot.") and frm not in seen_nodes:
            continue
        add_edge(
            kind,
            frm,
            to,
            label=e.get("label") or EDGE_PHRASE.get(kind),
            eid=e.get("id"),
            data=e.get("data") if isinstance(e.get("data"), dict) else {},
        )

    # Engine runs board system / world
    if engine_node_id:
        for n in ggd_nodes:
            if n.get("kind") == "system" and isinstance(n.get("id"), str):
                add_edge("runs", engine_node_id, n["id"], label="runs system")
        if world_id:
            add_edge("runs", engine_node_id, world_id, label="renders world")
            for hn in hole_nodes:
                hid = hn.get("id")
                if isinstance(hid, str):
                    add_edge("contains", world_id, hid, label="contains hole")

    # Character → portrait/body/anim edges (slots must exist)
    for ekind, frm, to, lab in pending_char_edges:
        add_edge(ekind, frm, to, label=lab)

    # Voice edges from voices.yaml by_character
    try:
        vmap = load_yaml(title_dir / "voices.yaml") if (title_dir / "voices.yaml").is_file() else {}
        by_ch = (vmap or {}).get("by_character") or {}
        for cid, cnode in char_nodes.items():
            entry = by_ch.get(cid)
            if not isinstance(entry, dict):
                continue
            vname = entry.get("voice_name") or entry.get("voice_id") or "voice"
            # virtual voice node
            vnode = f"synth.voice.{cid.replace('chr.', '').replace('.', '_')}"
            add_node(
                vnode,
                kind="other",
                label=f"Voice · {vname}",
                subtitle=str(entry.get("voice_id") or "")[:16],
                data={
                    "open": "character",
                    "character_id": cid,
                    "voice_id": entry.get("voice_id"),
                    "voice_name": entry.get("voice_name"),
                },
                source="voices",
            )
            add_edge("has_voice", cnode, vnode, label="speaks with")
    except Exception:
        pass

    # --- Dialogue hubs + optional detail ---
    for n in ggd_nodes:
        if n.get("kind") != "scene" or not isinstance(n.get("id"), str):
            continue
        sc = _match_dialogue_scene(n, dlg_scenes)
        if not sc:
            continue
        dlg_id = f"synth.dialogue.{sc.get('id') or _slug(str(sc.get('label')))}"
        lines = [x for x in (sc.get("nodes") or []) if isinstance(x, dict)]
        n_lines = sum(1 for x in lines if x.get("kind") == "line")
        n_choices = sum(1 for x in lines if x.get("kind") == "choice")
        add_node(
            dlg_id,
            kind="dialogue",
            label=f"Dialogue · {sc.get('label') or sc.get('id')}",
            subtitle=f"{n_lines} lines · {n_choices} choices",
            data={
                "dialogue_scene_id": sc.get("id"),
                "line_count": n_lines,
                "choice_count": n_choices,
            },
            source="dialogue",
        )
        add_edge("has_dialogue", n["id"], dlg_id, label="plays dialogue")

        if not include_dialogue_detail:
            continue

        # choice / option fan-out (compact)
        for dn in lines:
            dkind = dn.get("kind")
            did = dn.get("id")
            if not isinstance(did, str):
                continue
            if dkind == "choice":
                cid = f"synth.choice.{sc.get('id')}.{did}"
                add_node(
                    cid,
                    kind="choice",
                    label=str(dn.get("text") or did)[:80],
                    subtitle="player choice",
                    data={"dialogue_node": did, "scene": sc.get("id")},
                    source="dialogue",
                )
                add_edge("choice", dlg_id, cid, label="player chooses")
            elif dkind == "option":
                oid = f"synth.option.{sc.get('id')}.{did}"
                add_node(
                    oid,
                    kind="option",
                    label=str(dn.get("text") or did)[:80],
                    subtitle=str(dn.get("speaker") or "option"),
                    data={"dialogue_node": did, "scene": sc.get("id")},
                    source="dialogue",
                )
                # link from last choice in same scene if any — heuristic: previous choice
                # attach to dialogue hub with option phrase if no parent
                # Prefer: any choice node already added gets option edges via terminal_paths later
                add_edge("option", dlg_id, oid, label="option")

        # terminal_paths: choice option ids
        for tp in sc.get("terminal_paths") or []:
            if not isinstance(tp, str):
                continue
            oid = f"synth.option.{sc.get('id')}.{tp}"
            # find a choice in scene to link
            for dn in lines:
                if dn.get("kind") == "choice" and isinstance(dn.get("id"), str):
                    cid = f"synth.choice.{sc.get('id')}.{dn['id']}"
                    if cid in seen_nodes and oid in seen_nodes:
                        add_edge("option", cid, oid, label="player picks")
                    break

    # Positions
    saved = load_flow_positions(root, title_id)
    auto = auto_layout(nodes)
    for n in nodes:
        nid = n["id"]
        pos = saved.get(nid) or auto.get(nid) or {"x": 40.0, "y": 40.0}
        n["x"] = pos["x"]
        n["y"] = pos["y"]

    layers = sorted({str(n.get("layer")) for n in nodes})
    kinds = sorted({str(n.get("kind")) for n in nodes})

    return {
        "title_id": title_id,
        "nodes": nodes,
        "edges": edges,
        "layers": layers,
        "kinds": kinds,
        "legend": [
            {"kind": k, "phrase": EDGE_PHRASE.get(k, k)}
            for k in sorted({e["kind"] for e in edges})
        ],
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "ggd_nodes": len(ggd_nodes),
            "dialogue_scenes": len(dlg_scenes),
        },
        "layout_saved": bool(saved),
    }
