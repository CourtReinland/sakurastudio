"""xAI Grok Imagine client (image generate + edit)."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-imagine-image"
QUALITY_MODEL = "grok-imagine-image-quality"


def resolve_xai_api_key(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit.strip() or None
    for name in ("XAI_API_KEY", "GROK_API_KEY", "XAI_KEY"):
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    here = Path(__file__).resolve()
    for candidate in (
        Path.cwd() / ".env",
        here.parents[4] / ".env",  # SakuraSoft/.env
        here.parents[2] / ".env",  # tools/sakura/.env
    ):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k in ("XAI_API_KEY", "GROK_API_KEY", "XAI_KEY") and v:
                    return v
        except OSError:
            continue
    return None


class ImagineError(RuntimeError):
    pass


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _extract_image_bytes(payload: dict[str, Any]) -> bytes:
    """Parse OpenAI-style images response (url or b64_json)."""
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ImagineError(f"Unexpected Imagine response (no data): {list(payload.keys())}")
    item = data[0]
    if not isinstance(item, dict):
        raise ImagineError("Unexpected Imagine response item")

    b64 = item.get("b64_json")
    if b64:
        return base64.b64decode(b64)

    url = item.get("url")
    if url:
        with httpx.Client(timeout=120.0) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.content

    raise ImagineError("Imagine response had neither b64_json nor url")


def generate_image(
    prompt: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    aspect_ratio: str = "1:1",
    resolution: str = "1k",
    base_url: str = DEFAULT_BASE,
) -> bytes:
    key = resolve_xai_api_key(api_key)
    if not key:
        raise ImagineError(
            "No XAI_API_KEY found. Set env XAI_API_KEY or add it to SakuraSoft/.env"
        )
    if not prompt or not prompt.strip():
        raise ImagineError("Prompt is required")

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "n": 1,
        "response_format": "b64_json",
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    url = f"{base_url.rstrip('/')}/images/generations"
    with httpx.Client(timeout=180.0) as client:
        r = client.post(url, headers=_headers(key), json=body)
        if r.status_code >= 400:
            detail = r.text[:800]
            raise ImagineError(f"Imagine generate failed ({r.status_code}): {detail}")
        return _extract_image_bytes(r.json())


def _image_content(data_uri: str) -> dict[str, str]:
    return {"url": data_uri, "type": "image_url"}


def _to_data_uri(image_bytes: bytes, mime: str = "image/png") -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime or 'image/png'};base64,{b64}"


def edit_image(
    prompt: str,
    image_bytes: bytes | None = None,
    *,
    mime: str = "image/png",
    images: list[tuple[bytes, str]] | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    aspect_ratio: str | None = None,
    resolution: str = "1k",
    base_url: str = DEFAULT_BASE,
) -> bytes:
    """
    Edit from one or more reference images (max 3 per xAI Imagine).

    Prefer ``images=[(bytes, mime), ...]``. Legacy single ``image_bytes`` still works.
    """
    key = resolve_xai_api_key(api_key)
    if not key:
        raise ImagineError(
            "No XAI_API_KEY found. Set env XAI_API_KEY or add it to SakuraSoft/.env"
        )
    if not prompt or not prompt.strip():
        raise ImagineError("Prompt is required")

    refs: list[tuple[bytes, str]] = []
    if images:
        refs.extend((b, m or "image/png") for b, m in images if b)
    elif image_bytes:
        refs.append((image_bytes, mime or "image/png"))
    if not refs:
        raise ImagineError("At least one reference image is required for edit")
    if len(refs) > 3:
        raise ImagineError("Imagine edit supports at most 3 reference images")

    contents = [_image_content(_to_data_uri(b, m)) for b, m in refs]
    # REST: single object for one ref; array for multi (xAI multi-image edit)
    image_field: Any = contents[0] if len(contents) == 1 else contents

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "n": 1,
        "response_format": "b64_json",
        "resolution": resolution,
        "image": image_field,
    }
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio

    url = f"{base_url.rstrip('/')}/images/edits"
    with httpx.Client(timeout=180.0) as client:
        r = client.post(url, headers=_headers(key), json=body)
        if r.status_code >= 400:
            # Retry multi as "images" key if server rejects array on "image"
            if len(contents) > 1 and r.status_code in {400, 422}:
                body2 = dict(body)
                body2.pop("image", None)
                body2["images"] = contents
                r2 = client.post(url, headers=_headers(key), json=body2)
                if r2.status_code < 400:
                    return _extract_image_bytes(r2.json())
            detail = r.text[:800]
            raise ImagineError(f"Imagine edit failed ({r.status_code}): {detail}")
        return _extract_image_bytes(r.json())
