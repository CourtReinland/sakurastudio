"""Export catalog-bound assets into a game checkout + write runtime manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sakura.loader import load_catalog
from sakura.yaml_io import load_yaml

# title_id → default game root + path map rules
DEFAULT_GAME_ROOTS = {
    "title.midnight_par": Path("/Users/capricorn/nightmare-golf"),
}


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def resolve_game_root(title_id: str, explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    # env
    import os

    env = os.environ.get("SAKURA_GAME_ROOT") or os.environ.get("NIGHTMARE_GOLF_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    if title_id in DEFAULT_GAME_ROOTS:
        p = DEFAULT_GAME_ROOTS[title_id]
        if p.is_dir():
            return p
    raise FileNotFoundError(
        f"No game root for {title_id}. Pass game_root or set SAKURA_GAME_ROOT."
    )


def _dest_for_slot(slot_id: str, asset_path: Path, game_root: Path) -> Path | None:
    """
    Map catalog slot → path under game assets/.

    Midnight Par convention: cut sprites → assets/img/cut/<basename>
    other img → assets/img/<basename>
    """
    name = asset_path.name
    if "cut" in str(asset_path) or "sprite" in slot_id or "anim_" in slot_id or "portrait" in slot_id:
        if "portrait" in slot_id or name.startswith("portrait_"):
            return game_root / "assets" / "img" / "cut" / name
        if name.endswith(".png"):
            # prefer cut/ for character sprites
            if any(x in name for x in ("hana", "kaito", "kirara", "walk", "swing")):
                return game_root / "assets" / "img" / "cut" / name
            return game_root / "assets" / "img" / name
    if "bg" in slot_id or "sky" in slot_id or "turf" in slot_id or "texture" in slot_id:
        return game_root / "assets" / "img" / name
    if "cg" in slot_id:
        return game_root / "assets" / "img" / name
    if name.endswith((".png", ".jpg", ".webp", ".mp3", ".ogg")):
        # default images
        if name.endswith(".mp3"):
            return game_root / "assets" / "audio" / name
        return game_root / "assets" / "img" / name
    return None


def export_title_to_game(
    catalog: Path,
    title_id: str,
    *,
    game_root: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = catalog.resolve()
    index = load_catalog(root, include_examples=True)
    if title_id not in index.titles:
        raise ValueError(f"Unknown title {title_id}")
    gpath = resolve_game_root(title_id, game_root)
    files = index.title_files.get(title_id, {})
    slots_ent = files.get("slots")
    binds_ent = files.get("bindings")
    slots = (slots_ent.data.get("slots") if slots_ent else None) or []
    binds = (binds_ent.data.get("bindings") if binds_ent else None) or []
    by_slot = {b["slot_id"]: b for b in binds if isinstance(b, dict) and b.get("slot_id")}

    copied: list[dict[str, str]] = []
    skipped: list[str] = []
    cast: dict[str, Any] = {"hana": {"walk": [], "swing": [], "idle": None}, "kaito": {}, "kirara": {}}

    for s in slots:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not isinstance(sid, str):
            continue
        b = by_slot.get(sid)
        if not b or not b.get("asset_id"):
            skipped.append(sid)
            continue
        aid = b["asset_id"]
        ent = index.assets.get(aid)
        if not ent:
            skipped.append(f"{sid}:missing_asset")
            continue
        fl = ent.data.get("files") or []
        master = next(
            (f for f in fl if isinstance(f, dict) and f.get("role") == "master"),
            fl[0] if fl else None,
        )
        if not isinstance(master, dict) or not master.get("path"):
            skipped.append(f"{sid}:no_file")
            continue
        src = (root / str(master["path"])).resolve()
        if not src.is_file():
            skipped.append(f"{sid}:file_missing")
            continue
        dest = _dest_for_slot(sid, src, gpath)
        if not dest:
            skipped.append(f"{sid}:no_dest_rule")
            continue
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        rel = str(dest.relative_to(gpath)).replace("\\", "/")
        copied.append({"slot_id": sid, "asset_id": aid, "dest": rel})

        # cast manifest for engine
        base = Path(rel).name.replace(".png", "")
        if "hana" in sid and "walk" in sid:
            cast["hana"]["walk"].append(base)
        elif "hana" in sid and "swing" in sid:
            cast["hana"]["swing"].append(base)
        elif "hana" in sid and ("full" in sid or "sprite_hana" in sid):
            cast["hana"]["idle"] = base
        elif "kaito" in sid and "full" in sid:
            cast["kaito"]["idle"] = base
        elif "kirara" in sid and ("full" in sid or "legs" in sid or "ghost" in sid):
            cast.setdefault("kirara", {})["idle"] = base

    # sort walk frames numerically
    def _walk_key(n: str) -> int:
        digits = "".join(ch for ch in n if ch.isdigit())
        return int(digits) if digits else 0

    cast["hana"]["walk"] = sorted(set(cast["hana"]["walk"]), key=_walk_key)
    cast["hana"]["swing"] = sorted(set(cast["hana"]["swing"]), key=_walk_key)

    manifest = {
        "title_id": title_id,
        "exported_at": _utc(),
        "game_root": str(gpath),
        "cast": cast,
        "files": copied,
    }
    man_path = gpath / "assets" / "catalog_bindings.json"
    if not dry_run:
        man_path.parent.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "title_id": title_id,
        "game_root": str(gpath),
        "copied": len(copied),
        "skipped": len(skipped),
        "manifest": str(man_path),
        "cast": cast,
        "files": copied,
        "skipped_ids": skipped[:40],
        "message": f"Exported {len(copied)} files → {gpath.name} (+ catalog_bindings.json)",
    }
