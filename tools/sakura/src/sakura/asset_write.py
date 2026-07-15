"""Create catalog library assets from image bytes (upload or Imagine)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from sakura.yaml_io import dump_yaml

VALID_KINDS = frozenset(
    {
        "sprite",
        "texture",
        "cg",
        "portrait",
        "ui",
        "icon",
        "bg",
        "audio_bgm",
        "audio_sfx",
        "audio_voice",
        "font",
        "video",
        "spine",
        "other",
    }
)

IMAGE_EXTS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def slugify(text: str, *, max_len: int = 48) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or "asset")[:max_len]


def make_asset_id(kind: str, base: str | None = None) -> str:
    kind = kind if kind in VALID_KINDS else "sprite"
    core = slugify(base or "new")
    return f"asset.studio.{kind}.{core}_{_utc_stamp()}"


def _guess_mime(data: bytes, filename: str | None = None) -> str:
    if filename:
        lower = filename.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
        if lower.endswith(".gif"):
            return "image/gif"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


def _image_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(BytesIO(data)) as im:
            return im.size
    except OSError:
        return None, None


def create_image_asset(
    catalog_root: Path,
    *,
    image_bytes: bytes,
    kind: str = "sprite",
    label: str | None = None,
    asset_id: str | None = None,
    base_name: str | None = None,
    tags: list[str] | None = None,
    brand_id: str = "brand.sakura_soft",
    mime: str | None = None,
    filename: str | None = None,
    provenance: dict[str, Any] | None = None,
    status: str = "review",
) -> dict[str, Any]:
    """
    Write binary under assets/files/studio/ and YAML under assets/library/.

    Returns metadata including asset_id, yaml_path, file_path, preview_url.
    """
    root = catalog_root.resolve()
    if kind not in VALID_KINDS:
        kind = "sprite"

    mime = mime or _guess_mime(image_bytes, filename)
    ext = IMAGE_EXTS.get(mime, "png")
    if asset_id is None:
        asset_id = make_asset_id(kind, base_name or (filename or "upload"))
    if not re.match(r"^asset\.[a-z0-9_]+(\.[a-z0-9_]+)*$", asset_id):
        raise ValueError(f"Invalid asset_id: {asset_id}")

    # Avoid clobbering existing assets unless same id re-upload intended
    yaml_path = root / "assets" / "library" / f"{asset_id}.yaml"
    if yaml_path.is_file() and asset_id.startswith("asset.studio."):
        # regenerate unique id
        asset_id = make_asset_id(kind, base_name or (filename or "upload"))
        yaml_path = root / "assets" / "library" / f"{asset_id}.yaml"

    rel_bin = f"assets/files/studio/{kind}/{asset_id.split('.', 1)[-1].replace('.', '_')}.{ext}"
    bin_path = root / rel_bin
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_bytes(image_bytes)

    width, height = _image_size(image_bytes)
    file_rec: dict[str, Any] = {
        "role": "master",
        "path": rel_bin,
        "mime": mime,
    }
    if width:
        file_rec["width"] = width
    if height:
        file_rec["height"] = height

    tag_list = list(tags or [])
    for t in ("swap", "studio", kind):
        if t not in tag_list:
            tag_list.append(t)

    prov = {
        "source": "generated",
        "tool": "sakura_studio",
        "created_at": _utc_date(),
        "license": "internal_all_rights",
        "author": "studio",
    }
    if provenance:
        prov.update(provenance)

    doc: dict[str, Any] = {
        "id": asset_id,
        "label": label or f"Studio · {kind} · {base_name or asset_id.split('.')[-1]}",
        "status": status,
        "brand_id": brand_id,
        "kind": kind,
        "tags": tag_list,
        "characters": [],
        "files": [file_rec],
        "provenance": prov,
    }

    dump_yaml(yaml_path, doc)

    return {
        "asset_id": asset_id,
        "label": doc["label"],
        "kind": kind,
        "yaml_path": str(yaml_path),
        "file_path": str(bin_path),
        "rel_path": rel_bin,
        "mime": mime,
        "width": width,
        "height": height,
        "preview_url": f"/api/asset-file?asset_id={asset_id}",
    }
