"""Title-scoped catalog asset matching for Studio Canvas (and similar pickers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

# Leading brand token in title ids like title.sakura_tea_house
_BRAND_PREFIXES = frozenset({"sakura"})


def title_scope_keys(title_id: str, title_dir: Path | None = None) -> dict[str, set[str]]:
    """
    Derive slug / short-code tokens for a catalog title.

    title.sakura_tea_house → slugs tea_house, sakura_tea_house, tea-house, …
                             shorts tea, house
    title.midnight_par     → slugs midnight_par, midnight-par; shorts midnight, par
    """
    raw = (title_id or "").strip()
    if raw.startswith("title."):
        raw = raw[6:]
    parts = [p for p in raw.replace("-", "_").split("_") if p]
    brandless = [p for p in parts if p not in _BRAND_PREFIXES]
    slugs: set[str] = set()
    if raw:
        slugs.add(raw)
        slugs.add(raw.replace("_", "-"))
    if brandless:
        joined = "_".join(brandless)
        slugs.add(joined)
        slugs.add(joined.replace("_", "-"))
    if title_dir is not None:
        slugs.add(title_dir.name)
        slugs.add(title_dir.name.replace("-", "_"))
    shorts: set[str] = set()
    if brandless:
        shorts.add(brandless[0])
        shorts.add(brandless[-1])
    if parts:
        shorts.add(parts[-1])
    shorts = {s for s in shorts if len(s) >= 3}
    return {"slugs": slugs, "shorts": shorts}


def _asset_paths(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for rec in data.get("files") or []:
        if isinstance(rec, dict) and rec.get("path"):
            out.append(str(rec["path"]).replace("\\", "/"))
    return out


def asset_belongs_to_title(
    asset_id: str,
    data: dict[str, Any],
    *,
    title_id: str,
    keys: dict[str, set[str]],
    bound_ids: Iterable[str] | None = None,
) -> bool:
    """True if the asset is in-scope for the title (OR of the documented rules)."""
    if not title_id or not asset_id:
        return False
    if data.get("title_id") == title_id:
        return True
    prov = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    if prov.get("title_id") == title_id:
        return True
    if bound_ids is not None and asset_id in set(bound_ids):
        return True

    tags = {str(t) for t in (data.get("tags") or [])}
    if tags & keys["slugs"]:
        return True

    aid = asset_id.lower()
    for short in keys["shorts"]:
        token = f".{short}."
        if token in aid or aid.endswith(f".{short}"):
            return True

    blob = " ".join(_asset_paths(data)).lower()
    for slug in keys["slugs"]:
        if slug.lower() in blob:
            return True
    return False


def filter_assets_for_title(
    index: Any,
    title_id: str,
    *,
    bound_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return title-scoped asset summaries (all kinds; caller may drop audio/font)."""
    ent = index.titles.get(title_id) if index is not None else None
    title_dir = ent.path.parent if ent is not None else None
    keys = title_scope_keys(title_id, title_dir)
    bound = set(bound_ids or [])
    out: list[dict[str, Any]] = []
    for aid, e in sorted(index.assets.items()):
        data = e.data if hasattr(e, "data") else e
        if not isinstance(data, dict):
            continue
        if not asset_belongs_to_title(
            aid, data, title_id=title_id, keys=keys, bound_ids=bound
        ):
            continue
        out.append(_asset_summary(aid, data))
    return out


def _asset_summary(aid: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": aid,
        "label": data.get("label"),
        "kind": data.get("kind"),
        "tags": data.get("tags") or [],
        "status": data.get("status"),
        "title_id": data.get("title_id"),
        "paths": _asset_paths(data),
        "preview_url": f"/api/asset-file?asset_id={aid}",
    }


def title_slug_tags(title_id: str) -> list[str]:
    """Tags to stamp on newly generated studio assets for this title."""
    keys = title_scope_keys(title_id)
    # Prefer the brandless slug (tea_house) then the raw id slug.
    preferred = sorted(keys["slugs"], key=lambda s: (s.count("_") + s.count("-"), len(s)))
    return [s for s in preferred if "_" in s or "-" in s][:2] or list(keys["slugs"])[:1]
