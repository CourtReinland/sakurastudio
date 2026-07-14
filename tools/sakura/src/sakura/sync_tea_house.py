from __future__ import annotations

"""Sync CourtReinland/sakura-match → catalog (dialogue, assets, code graph)."""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from sakura.code_graph import build_code_graph, write_code_graph


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # noqa: ANN401
        return True


def _dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(
        data,
        Dumper=_Dumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def parse_dialogue_gdd(gdd_path: Path) -> dict[str, Any]:
    text = gdd_path.read_text(encoding="utf-8")
    start = text.find("## 13. Full dialogue ledger")
    if start < 0:
        raise ValueError("GDD missing ## 13. Full dialogue ledger")
    end = text.find("\n## 14.", start)
    section = text[start : end if end > 0 else len(text)]
    scenes: list[dict[str, Any]] = []
    parts = re.split(r"\n## Scene:\s*", section)
    for part in parts[1:]:
        first_line, _, body = part.partition("\n")
        m = re.match(r"(.+?)\s*\(`([^`]+)`\)", first_line.strip())
        if m:
            title, sid = m.group(1).strip(), m.group(2)
        else:
            title, sid = first_line.strip(), None
        sm = re.search(r"\*\*Start node:\*\*\s*`([^`]+)`", body)
        start_node = sm.group(1) if sm else None
        nodes: list[dict[str, Any]] = []
        for row in body.splitlines():
            row = row.strip()
            if not row.startswith("|"):
                continue
            cells = [c.strip() for c in row.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if cells[0] in ("Node",) or cells[0].startswith("---") or set(cells[0]) <= {"-"}:
                continue
            node_id = cells[0].replace("↳", "").strip().strip("`")
            kind = cells[1].strip()
            speaker = cells[2].strip()
            if speaker in ("—", "-"):
                speaker = None
            nodes.append(
                {
                    "id": node_id,
                    "kind": kind,
                    "speaker": speaker,
                    "text": cells[3],
                }
            )
        terminals: list[str] = []
        tm = re.search(r"\*\*Terminal paths:\*\*\s*(.+)", body)
        if tm:
            terminals = re.findall(r"`([^`]+)`", tm.group(1))
        scenes.append(
            {
                "id": sid or _slug(title),
                "label": title,
                "start_node": start_node,
                "nodes": nodes,
                "terminal_paths": terminals,
            }
        )
    return {
        "title_id": "title.sakura_tea_house",
        "source": "docs/GDD-current.md §13 / src/meta/content.ts",
        "imported_at": _utc(),
        "scenes": scenes,
    }


def sync_tea_house(
    catalog_root: Path,
    source_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    catalog_root = catalog_root.resolve()
    source_root = source_root.resolve()
    title_dir = catalog_root / "titles" / "sakura-tea-house"
    lib = catalog_root / "assets" / "library"
    gdd = source_root / "docs" / "GDD-current.md"
    if not gdd.is_file():
        raise FileNotFoundError(f"Missing {gdd}")

    dialogue = parse_dialogue_gdd(gdd)
    stats = {
        "scenes": len(dialogue["scenes"]),
        "line_assets": 0,
        "strings": 0,
        "visual_assets": 0,
        "bindings": 0,
        "slots": 0,
        "code_nodes": 0,
        "code_edges": 0,
    }

    if dry_run:
        lines = sum(
            1
            for s in dialogue["scenes"]
            for n in s["nodes"]
            if n["kind"] == "line"
        )
        stats["line_assets"] = lines
        return {"ok": True, "dry_run": True, "stats": stats, "message": "dry-run only"}

    _dump_yaml(title_dir / "dialogue.yaml", dialogue)

    strings: dict[str, str] = {}
    line_slots: list[dict[str, Any]] = []
    line_bindings: list[dict[str, Any]] = []
    title_id = "title.sakura_tea_house"

    for scene in dialogue["scenes"]:
        sid = scene["id"]
        for node in scene["nodes"]:
            nid = node["id"]
            str_id = f"str.tea.{_slug(sid)}.{_slug(nid)}"
            strings[str_id] = node["text"]
            if node["kind"] != "line":
                continue
            asset_id = f"asset.line.tea.{_slug(sid)}.{_slug(nid)}"
            slot_id = f"slot.line.tea.{_slug(sid)}.{_slug(nid)}"
            rel = f"assets/files/tea_house/dialogue/{_slug(sid)}/{_slug(nid)}.txt"
            fpath = catalog_root / rel
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(node["text"] + "\n", encoding="utf-8")
            speaker = node.get("speaker") or "unknown"
            asset: dict[str, Any] = {
                "id": asset_id,
                "label": f"Line · {scene['label']} · {nid}",
                "status": "approved",
                "brand_id": "brand.sakura_soft",
                "kind": "other",
                "tags": ["dialogue", "line", "tea_house", speaker, _slug(sid)],
                "characters": [],
                "files": [{"role": "master", "path": rel, "mime": "text/plain"}],
                "provenance": {
                    "source": "internal",
                    "tool": "gdd_import",
                    "created_at": _utc()[:10],
                    "license": "internal_all_rights",
                },
                "notes": f"speaker={speaker}; string_id={str_id}",
            }
            cmap = {
                "ren": "chr.tea.ren",
                "mizu": "chr.tea.mizu",
                "akira": "chr.tea.akira",
                "you": "chr.tea.keeper",
            }
            if speaker in cmap:
                asset["characters"] = [cmap[speaker]]
            _dump_yaml(lib / f"{asset_id}.yaml", asset)
            line_slots.append(
                {
                    "id": slot_id,
                    "label": f"{scene['label']} · {nid}",
                    "kind": "other",
                    "required": False,
                    "status": "approved",
                    "tags": ["swap", "dialogue", "line", speaker, _slug(sid)],
                    "notes": f"string_id={str_id}",
                }
            )
            line_bindings.append(
                {
                    "slot_id": slot_id,
                    "asset_id": asset_id,
                    "status": "approved",
                    "bound_at": _utc(),
                    "bound_by": "gdd_import",
                }
            )
            stats["line_assets"] += 1

    stats["strings"] = len(strings)
    _dump_yaml(
        title_dir / "localization" / "en.yaml",
        {"locale": "en", "title_id": title_id, "strings": strings},
    )

    # Visual assets
    slot_to_asset: dict[str, str] = {}

    def add_image(
        src: Path,
        asset_id: str,
        label: str,
        kind: str,
        tags: list[str],
        characters: list[str] | None = None,
    ) -> None:
        if not src.is_file():
            return
        rel = f"assets/files/tea_house/{src.relative_to(source_root / 'public' / 'assets')}"
        dest = catalog_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        w = h = None
        try:
            from PIL import Image

            im = Image.open(dest)
            w, h = im.size
        except Exception:  # noqa: BLE001
            pass
        f: dict[str, Any] = {
            "role": "master",
            "path": rel,
            "mime": "image/webp" if dest.suffix == ".webp" else "image/png",
        }
        if w:
            f["width"] = w
        if h:
            f["height"] = h
        asset = {
            "id": asset_id,
            "label": label,
            "status": "approved",
            "brand_id": "brand.sakura_soft",
            "kind": kind,
            "tags": tags,
            "characters": characters or [],
            "files": [f],
            "provenance": {
                "source": "internal",
                "tool": "tea_house_sync",
                "created_at": _utc()[:10],
                "license": "internal_all_rights",
                "author": "CourtReinland/sakura-match",
            },
        }
        _dump_yaml(lib / f"{asset_id}.yaml", asset)
        stats["visual_assets"] += 1

    gem_map = {
        "teaLeaf": ("slot.piece.tea_leaf", "tea_leaf"),
        "flower": ("slot.piece.flower", "flower"),
        "lantern": ("slot.piece.lantern", "lantern"),
        "coin": ("slot.piece.coin", "coin"),
        "charm": ("slot.piece.charm", "charm"),
        "wagashi": ("slot.piece.wagashi", "wagashi"),
    }
    for fname, (slot_id, key) in gem_map.items():
        aid = f"asset.piece.tea.{key}"
        add_image(
            source_root / "public/assets/textures/gems" / f"{fname}.webp",
            aid,
            f"Gem · {key}",
            "sprite",
            ["piece", "gem", key, "tea_house", "swap"],
        )
        slot_to_asset[slot_id] = aid

    add_image(
        source_root / "public/assets/textures/haunted-lacquer-board.webp",
        "asset.ui.tea.board_lacquer",
        "UI · haunted lacquer board",
        "ui",
        ["ui", "board", "tea_house", "swap", "graphic"],
    )
    slot_to_asset["slot.ui.board_lacquer"] = "asset.ui.tea.board_lacquer"

    bgs = {
        "entry-hall-dusk-dirty.webp": (
            "slot.bg.entry_hall_dirty",
            "asset.bg.tea.entry_hall_dirty",
            "BG · entry hall dirty",
            "bg",
            [],
        ),
        "entry-hall-dusk-clean.webp": (
            "slot.bg.entry_hall_clean",
            "asset.bg.tea.entry_hall_clean",
            "BG · entry hall clean",
            "bg",
            [],
        ),
        "ren-entry-hall-neutral.webp": (
            "slot.portrait.ren.neutral",
            "asset.portrait.tea.ren_neutral",
            "Portrait · Ren neutral",
            "portrait",
            ["chr.tea.ren"],
        ),
        "ren-entry-hall-warm.webp": (
            "slot.portrait.ren.warm",
            "asset.portrait.tea.ren_warm",
            "Portrait · Ren warm",
            "portrait",
            ["chr.tea.ren"],
        ),
        "ren-entry-hall-curious.webp": (
            "slot.portrait.ren.curious",
            "asset.portrait.tea.ren_curious",
            "Portrait · Ren curious",
            "portrait",
            ["chr.tea.ren"],
        ),
        "ren-entry-hall-portrait.webp": (
            "slot.portrait.ren.dusk",
            "asset.portrait.tea.ren_dusk",
            "Portrait · Ren dusk",
            "portrait",
            ["chr.tea.ren"],
        ),
        "mizu-rain-neutral.webp": (
            "slot.portrait.mizu.neutral",
            "asset.portrait.tea.mizu_neutral",
            "Portrait · Mizu",
            "portrait",
            ["chr.tea.mizu"],
        ),
        "akira-ledger-neutral.webp": (
            "slot.portrait.akira.neutral",
            "asset.portrait.tea.akira_neutral",
            "Portrait · Akira",
            "portrait",
            ["chr.tea.akira"],
        ),
    }
    for fname, (slot_id, aid, label, kind, chars) in bgs.items():
        add_image(
            source_root / "public/assets/backgrounds" / fname,
            aid,
            label,
            kind,
            ["tea_house", "swap", "graphic", kind],
            characters=chars,
        )
        slot_to_asset[slot_id] = aid

    cin = source_root / "public/assets/cinematics"
    if cin.is_dir():
        for src in sorted(cin.glob("*.webp")):
            key = _slug(src.stem)
            aid = f"asset.cg.tea.{key}"
            slot_id = f"slot.cg.tea.{key}"
            add_image(
                src,
                aid,
                f"CG · {src.stem}",
                "cg",
                ["tea_house", "swap", "graphic", "cinematic", key],
            )
            slot_to_asset[slot_id] = aid

    slots: list[dict[str, Any]] = []
    for slot_id, aid in slot_to_asset.items():
        if slot_id.startswith("slot.piece."):
            key = slot_id.split(".")[-1]
            slots.append(
                {
                    "id": slot_id,
                    "label": f"Gem · {key}",
                    "kind": "sprite",
                    "required": True,
                    "status": "approved",
                    "tags": ["swap", "piece", "gem", key],
                    "used_by": ["node.system.board"],
                }
            )
        else:
            kind = (
                "cg"
                if ".cg." in slot_id
                else "portrait"
                if "portrait" in slot_id
                else "bg"
                if ".bg." in slot_id
                else "ui"
            )
            slots.append(
                {
                    "id": slot_id,
                    "label": slot_id.replace("slot.", "").replace(".", " · "),
                    "kind": kind,
                    "required": False,
                    "status": "approved",
                    "tags": ["swap", "graphic", kind],
                }
            )
    slots.extend(line_slots)
    _dump_yaml(title_dir / "slots.yaml", {"title_id": title_id, "slots": slots})

    bindings = [
        {
            "slot_id": sid,
            "asset_id": aid,
            "status": "approved",
            "bound_at": _utc(),
            "bound_by": "tea_house_sync",
        }
        for sid, aid in slot_to_asset.items()
    ]
    bindings.extend(line_bindings)
    _dump_yaml(title_dir / "bindings.yaml", {"title_id": title_id, "bindings": bindings})
    stats["bindings"] = len(bindings)
    stats["slots"] = len(slots)

    # title meta
    title_path = title_dir / "title.yaml"
    title = yaml.safe_load(title_path.read_text(encoding="utf-8")) or {}
    title["content_files"] = {
        "cast": "cast.yaml",
        "ggd": "ggd.yaml",
        "slots": "slots.yaml",
        "bindings": "bindings.yaml",
        "levels": "levels.yaml",
        "dialogue": "dialogue.yaml",
    }
    title["notes"] = (
        "Maps to GitHub CourtReinland/sakura-match. "
        "Dialogue ledger + public/assets synced into catalog; code_graph.json for Studio Code tab."
    )
    _dump_yaml(title_path, title)

    # code graph
    graph = build_code_graph(
        source_root,
        title_id=title_id,
        source_repo="CourtReinland/sakura-match",
    )
    write_code_graph(title_dir / "code_graph.json", graph)
    stats["code_nodes"] = graph["stats"]["nodes"]
    stats["code_edges"] = graph["stats"]["edges"]

    # also stash a machine-readable dialogue index for Studio
    (title_dir / "dialogue.json").write_text(
        json.dumps(dialogue, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "ok": True,
        "dry_run": False,
        "stats": stats,
        "message": (
            f"Synced tea house: {stats['line_assets']} lines, "
            f"{stats['visual_assets']} visuals, {stats['bindings']} bindings, "
            f"code graph {stats['code_nodes']}n/{stats['code_edges']}e"
        ),
    }
