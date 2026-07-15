"""Per-title Studio style board (project-wide Imagine style lock)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sakura.loader import load_catalog
from sakura.yaml_io import dump_yaml, load_yaml

STUDIO_FILENAME = "studio.yaml"


def _title_dir(catalog: Path, title_id: str) -> Path | None:
    index = load_catalog(catalog, include_examples=True)
    ent = index.titles.get(title_id)
    if not ent:
        return None
    return ent.path.parent


def studio_path(catalog: Path, title_id: str) -> Path | None:
    td = _title_dir(catalog, title_id)
    if not td:
        return None
    return td / STUDIO_FILENAME


def default_studio_doc(title_id: str) -> dict[str, Any]:
    return {
        "title_id": title_id,
        "style": {
            "enabled": False,
            "asset_id": None,
            "notes": "Project-wide style lock for Grok Imagine. Toggle enabled on/off in Studio Swaps.",
        },
    }


def load_studio_style(catalog: Path, title_id: str) -> dict[str, Any]:
    """
    Return style board state for a title.

    Shape:
      {
        title_id, enabled, asset_id, notes, path,
        asset: {id, label, kind, preview_url} | None
      }
    """
    path = studio_path(catalog, title_id)
    doc = default_studio_doc(title_id)
    if path and path.is_file():
        raw = load_yaml(path)
        if isinstance(raw, dict):
            doc["title_id"] = raw.get("title_id") or title_id
            style = raw.get("style") if isinstance(raw.get("style"), dict) else {}
            doc["style"]["enabled"] = bool(style.get("enabled", False))
            aid = style.get("asset_id")
            doc["style"]["asset_id"] = aid if isinstance(aid, str) and aid else None
            if style.get("notes"):
                doc["style"]["notes"] = str(style["notes"])

    style = doc["style"]
    asset_meta = None
    aid = style.get("asset_id")
    if aid:
        index = load_catalog(catalog, include_examples=True)
        ent = index.assets.get(aid)
        if ent:
            ad = ent.data
            asset_meta = {
                "id": aid,
                "label": ad.get("label"),
                "kind": ad.get("kind"),
                "tags": ad.get("tags") or [],
                "status": ad.get("status"),
                "preview_url": f"/api/asset-file?asset_id={aid}",
            }

    return {
        "title_id": doc["title_id"],
        "enabled": bool(style.get("enabled")),
        "asset_id": style.get("asset_id"),
        "notes": style.get("notes"),
        "path": str(path) if path else None,
        "asset": asset_meta,
        "active": bool(style.get("enabled") and style.get("asset_id") and asset_meta),
    }


def save_studio_style(
    catalog: Path,
    title_id: str,
    *,
    enabled: bool | None = None,
    asset_id: str | None | object = ...,  # type: ignore[assignment]
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Update studio.yaml for the title. Pass asset_id=None to clear.
    Omit asset_id (ellipsis) to leave unchanged.
    """
    path = studio_path(catalog, title_id)
    if not path:
        raise ValueError(f"Unknown title: {title_id}")

    if path.is_file():
        raw = load_yaml(path)
        doc = raw if isinstance(raw, dict) else default_studio_doc(title_id)
    else:
        doc = default_studio_doc(title_id)

    doc["title_id"] = title_id
    style = doc.get("style") if isinstance(doc.get("style"), dict) else {}
    if enabled is not None:
        style["enabled"] = bool(enabled)
    if asset_id is not ...:
        if asset_id is None or asset_id == "":
            style["asset_id"] = None
        else:
            aid = str(asset_id)
            index = load_catalog(catalog, include_examples=True)
            if aid not in index.assets:
                raise ValueError(f"Unknown asset: {aid}")
            style["asset_id"] = aid
    if notes is not None:
        style["notes"] = notes
    style.setdefault("enabled", False)
    style.setdefault("asset_id", None)
    style.setdefault(
        "notes",
        "Project-wide style lock for Grok Imagine. Toggle enabled on/off in Studio Swaps.",
    )
    doc["style"] = style
    dump_yaml(path, doc)
    return load_studio_style(catalog, title_id)


def inject_style_reference(
    refs: list[Any],
    style: dict[str, Any],
    *,
    max_refs: int = 3,
) -> tuple[list[Any], bool]:
    """
    Append project style asset as last reference if active and not already present.
    Returns (refs, injected).
    """
    if not style.get("active") and not (
        style.get("enabled") and style.get("asset_id")
    ):
        return refs, False
    aid = style.get("asset_id")
    if not aid:
        return refs, False

    # Already present?
    for r in refs:
        if isinstance(r, dict) and r.get("kind") == "asset" and r.get("asset_id") == aid:
            return refs, False
        # ImagineReference objects
        if getattr(r, "kind", None) == "asset" and getattr(r, "asset_id", None) == aid:
            return refs, False

    if len(refs) >= max_refs:
        # Replace last slot with style so lock still applies
        out = list(refs[: max_refs - 1])
        out.append({"kind": "asset", "asset_id": aid})
        return out, True

    out = list(refs)
    out.append({"kind": "asset", "asset_id": aid})
    return out, True
