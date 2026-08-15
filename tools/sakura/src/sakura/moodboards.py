"""Repo mood-board images (Gemini / Suki / pixiv refs) for Studio Canvas."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MOODBOARDS_DIRNAME = "moodboards"


def moodboards_root(catalog: Path) -> Path:
    """``moodboards/`` lives next to ``catalog/`` at the repo root."""
    return catalog.resolve().parent / MOODBOARDS_DIRNAME


def list_moodboard_images(catalog: Path) -> list[dict[str, Any]]:
    root = moodboards_root(catalog)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = path.relative_to(root).as_posix()
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        items.append(
            {
                "id": rel,
                "path": rel,
                "name": path.name,
                "folder": str(Path(rel).parent) if Path(rel).parent.as_posix() != "." else "",
                "mime": mime,
                "size": path.stat().st_size,
                "preview_url": f"/api/moodboard-file?path={quote(rel, safe='')}",
            }
        )
    return items


def resolve_moodboard_file(catalog: Path, rel: str) -> Path:
    """Resolve a mood-board relative path; reject traversal."""
    raw = (rel or "").strip().lstrip("/")
    if not raw:
        raise ValueError("Moodboard path is required")
    parts = Path(raw).parts
    if any(p in {".", ".."} or p.startswith("\\") for p in parts):
        raise ValueError("Invalid moodboard path")
    if Path(raw).is_absolute() or "\\" in raw:
        raise ValueError("Invalid moodboard path")

    root = moodboards_root(catalog).resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as e:
        raise ValueError("Invalid moodboard path") from e
    if not path.is_file():
        raise FileNotFoundError(f"Moodboard file not found: {raw}")
    if path.suffix.lower() not in IMAGE_EXTS:
        raise ValueError(f"Not an image: {raw}")
    return path


def load_moodboard_bytes(catalog: Path, rel: str) -> tuple[bytes, str]:
    path = resolve_moodboard_file(catalog, rel)
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return path.read_bytes(), mime


def list_recent_studio_assets(catalog: Path, *, limit: int = 24) -> list[dict[str, Any]]:
    """Recent ``asset.studio.*`` library entries (Canvas history seed)."""
    lib = catalog.resolve() / "assets" / "library"
    if not lib.is_dir():
        return []
    rows: list[tuple[float, dict[str, Any]]] = []
    for yml in lib.glob("asset.studio.*.yaml"):
        try:
            mtime = yml.stat().st_mtime
        except OSError:
            continue
        aid = yml.stem
        rows.append(
            (
                mtime,
                {
                    "id": aid,
                    "asset_id": aid,
                    "label": aid.replace("asset.studio.", ""),
                    "preview_url": f"/api/asset-file?asset_id={aid}",
                    "source": "studio",
                },
            )
        )
    rows.sort(key=lambda r: r[0], reverse=True)
    return [item for _, item in rows[: max(1, min(limit, 80))]]
