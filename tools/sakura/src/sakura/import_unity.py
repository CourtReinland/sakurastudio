from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from sakura.loader import discover_catalog_root, load_catalog
from sakura.models import CatalogIndex

# slot.tile.red → Red, slot.tile.blue → Blue
_SLOT_TILE_RE = re.compile(r"^slot\.tile\.([a-z0-9_]+)$", re.I)

# pastel brand colors for synthetic masters
_COLOR_HEX = {
    "red": (255, 107, 107),
    "blue": (107, 181, 255),
    "green": (107, 255, 138),
    "yellow": (255, 230, 107),
    "purple": (181, 107, 255),
    "orange": (255, 176, 102),
}

ACTIVE = frozenset({"draft", "review", "approved"})


@dataclass
class ImportResult:
    ok: bool
    message: str
    copied: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unity_root: Path | None = None
    manifest_path: Path | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _title_slug(title_id: str) -> str:
    # title.sakura_match → sakura_match
    if title_id.startswith("title."):
        return title_id[len("title.") :]
    return title_id.replace(".", "_")


def _slot_to_resources_name(slot_id: str) -> str:
    return slot_id.replace(".", "_")


def _slot_to_tile_type(slot_id: str) -> str | None:
    m = _SLOT_TILE_RE.match(slot_id)
    if not m:
        return None
    return m.group(1).capitalize()


def _studio_root(catalog_root: Path) -> Path:
    # catalog is typically SakuraSoft/catalog → studio root is parent
    return catalog_root.parent


def _resolve_unity_root(index: CatalogIndex, title_id: str) -> Path:
    title = index.titles[title_id].data
    repo = title.get("repo_path")
    if not repo:
        raise ValueError(f"Title {title_id} has no repo_path for Unity import")
    studio = _studio_root(index.root)
    unity = (studio / str(repo)).resolve()
    if not unity.is_dir():
        raise FileNotFoundError(f"Unity project not found: {unity}")
    assets = unity / "Assets"
    if not assets.is_dir():
        raise FileNotFoundError(f"Not a Unity project (no Assets/): {unity}")
    return unity


def _master_file(asset_data: dict[str, Any]) -> dict[str, Any] | None:
    files = asset_data.get("files") or []
    for f in files:
        if isinstance(f, dict) and f.get("role") == "master":
            return f
    if files and isinstance(files[0], dict):
        return files[0]
    return None


def _guess_color_from_asset(asset_data: dict[str, Any], slot_id: str) -> tuple[int, int, int]:
    tags = [t.lower() for t in (asset_data.get("tags") or [])]
    for name, rgb in _COLOR_HEX.items():
        if name in tags:
            return rgb
    m = _SLOT_TILE_RE.match(slot_id)
    if m:
        key = m.group(1).lower()
        if key in _COLOR_HEX:
            return _COLOR_HEX[key]
    return (200, 200, 200)


def _write_solid_png(path: Path, rgb: tuple[int, int, int], size: int = 128) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (size, size), (*rgb, 255))
    # soft inset so tiles aren't pure flat (slight bevel)
    px = img.load()
    assert px is not None
    for y in range(size):
        for x in range(size):
            edge = min(x, y, size - 1 - x, size - 1 - y)
            if edge < 4:
                factor = 0.75 + 0.05 * edge
                px[x, y] = (
                    int(rgb[0] * factor),
                    int(rgb[1] * factor),
                    int(rgb[2] * factor),
                    255,
                )
    img.save(path, format="PNG")


def _ensure_asset_file(
    index: CatalogIndex,
    asset_id: str,
    slot_id: str,
    *,
    generate_missing: bool,
) -> tuple[Path | None, bool]:
    """Return (path to source file, was_generated)."""
    ent = index.assets.get(asset_id)
    if not ent:
        return None, False
    master = _master_file(ent.data)
    if not master or not master.get("path"):
        return None, False
    rel = str(master["path"])
    full = (index.root / rel).resolve()
    if full.is_file():
        return full, False
    if not generate_missing:
        return None, False
    # write into catalog path and return
    rgb = _guess_color_from_asset(ent.data, slot_id)
    w = int(master.get("width") or 128)
    h = int(master.get("height") or 128)
    size = max(w, h, 64)
    full.parent.mkdir(parents=True, exist_ok=True)
    _write_solid_png(full, rgb, size=size)
    return full, True


def import_title(
    *,
    catalog: Path | None = None,
    title: str | None = None,
    generate_missing: bool = True,
    dry_run: bool = False,
    include_examples: bool = False,
) -> ImportResult:
    root = discover_catalog_root(catalog)
    index = load_catalog(root, include_examples=include_examples)

    if title:
        if title not in index.titles:
            return ImportResult(False, f"Unknown title '{title}'")
        title_id = title
    elif len(index.titles) == 1:
        title_id = next(iter(index.titles))
    else:
        return ImportResult(
            False,
            "Pass --title. Known: " + ", ".join(sorted(index.titles)),
        )

    try:
        unity = _resolve_unity_root(index, title_id)
    except (ValueError, FileNotFoundError) as e:
        return ImportResult(False, str(e))

    files = index.title_files.get(title_id, {})
    bindings_ent = files.get("bindings")
    if not bindings_ent:
        return ImportResult(False, f"No bindings.yaml for {title_id}", unity_root=unity)

    slots_ent = files.get("slots")
    slots_by_id: dict[str, dict] = {}
    if slots_ent:
        for s in slots_ent.data.get("slots") or []:
            if isinstance(s, dict) and s.get("id"):
                slots_by_id[s["id"]] = s

    slug = _title_slug(title_id)
    out_dir = unity / "Assets" / "Resources" / "Catalog" / slug
    slots_dir = out_dir / "slots"
    manifest_path = out_dir / "bindings.json"

    copied: list[str] = []
    generated: list[str] = []
    skipped: list[str] = []
    manifest_bindings: list[dict[str, Any]] = []

    for b in bindings_ent.data.get("bindings") or []:
        if not isinstance(b, dict):
            continue
        status = b.get("status", "draft")
        if status not in ACTIVE:
            skipped.append(f"{b.get('slot_id')}: status={status}")
            continue
        slot_id = b.get("slot_id")
        asset_id = b.get("asset_id")
        if not slot_id or not asset_id:
            continue

        src, was_gen = _ensure_asset_file(
            index, asset_id, slot_id, generate_missing=generate_missing
        )
        if src is None:
            skipped.append(f"{slot_id}: missing file for {asset_id}")
            continue

        res_name = _slot_to_resources_name(slot_id)
        dest = slots_dir / f"{res_name}.png"
        resources_path = f"Catalog/{slug}/slots/{res_name}"

        if not dry_run:
            slots_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            # Unity will generate .meta on next open; optional placeholder not required

        copied.append(f"{slot_id} → {dest.relative_to(unity)}")
        if was_gen:
            generated.append(str(src.relative_to(index.root)))

        entry: dict[str, Any] = {
            "slot_id": slot_id,
            "asset_id": asset_id,
            "status": status,
            "resources_path": resources_path,
            "kind": (slots_by_id.get(slot_id) or {}).get("kind")
            or (index.assets.get(asset_id).data.get("kind") if asset_id in index.assets else None),
        }
        tile_type = _slot_to_tile_type(slot_id)
        if tile_type:
            entry["tile_type"] = tile_type
        manifest_bindings.append(entry)

    manifest = {
        "schema_version": "1.0.0",
        "title_id": title_id,
        "imported_at": _utc_now(),
        "source_catalog": str(index.root),
        "bindings": manifest_bindings,
    }

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    lines = [
        f"{'DRY-RUN ' if dry_run else ''}Imported {title_id} → {unity}",
        f"  bindings written: {len(manifest_bindings)}",
        f"  skipped: {len(skipped)}",
        f"  generated masters: {len(generated)}",
        f"  manifest: {manifest_path.relative_to(unity) if not dry_run else manifest_path}",
    ]
    if copied:
        lines.append("  files:")
        for c in copied:
            lines.append(f"    - {c}")
    if generated:
        lines.append("  synthesized catalog files:")
        for g in generated:
            lines.append(f"    - {g}")
    if skipped:
        lines.append("  skipped detail:")
        for s in skipped:
            lines.append(f"    - {s}")

    return ImportResult(
        ok=True,
        message="\n".join(lines),
        copied=copied,
        generated=generated,
        skipped=skipped,
        unity_root=unity,
        manifest_path=manifest_path if not dry_run else None,
    )
