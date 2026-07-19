"""xAI Grok Imagine video: image-to-video + poll + download."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from sakura.imagine_client import (
    DEFAULT_BASE,
    ImagineError,
    _headers,
    _to_data_uri,
    resolve_xai_api_key,
)

DEFAULT_VIDEO_MODEL = "grok-imagine-video"


def start_image_to_video(
    image_bytes: bytes,
    prompt: str,
    *,
    mime: str = "image/png",
    duration: int = 6,
    model: str = DEFAULT_VIDEO_MODEL,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE,
) -> str:
    """Start async image-to-video; returns request_id."""
    key = resolve_xai_api_key(api_key)
    if not key:
        raise ImagineError("No XAI_API_KEY for video generation")
    if not prompt.strip():
        raise ImagineError("Video prompt required")
    if duration not in (5, 6, 8, 10):
        # API accepts various; clamp to common
        duration = 6 if duration < 8 else 10

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "duration": duration,
        "image": {
            "url": _to_data_uri(image_bytes, mime),
            "type": "image_url",
        },
    }
    url = f"{base_url.rstrip('/')}/videos/generations"
    with httpx.Client(timeout=180.0) as client:
        r = client.post(url, headers=_headers(key), json=body)
        if r.status_code >= 400:
            raise ImagineError(f"Video start failed ({r.status_code}): {r.text[:800]}")
        data = r.json()
    rid = data.get("request_id")
    if not rid:
        raise ImagineError(f"No request_id in video response: {data}")
    return str(rid)


def poll_video(
    request_id: str,
    *,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE,
    timeout_s: float = 300.0,
    interval_s: float = 3.0,
) -> dict[str, Any]:
    """Poll until done/failed/expired. Returns final status payload."""
    key = resolve_xai_api_key(api_key)
    if not key:
        raise ImagineError("No XAI_API_KEY")
    url = f"{base_url.rstrip('/')}/videos/{request_id}"
    deadline = time.time() + timeout_s
    with httpx.Client(timeout=60.0) as client:
        while time.time() < deadline:
            r = client.get(url, headers=_headers(key))
            if r.status_code >= 400:
                raise ImagineError(f"Video poll failed ({r.status_code}): {r.text[:400]}")
            data = r.json()
            st = (data.get("status") or "").lower()
            if st in {"done", "failed", "expired"}:
                return data
            time.sleep(interval_s)
    raise ImagineError(f"Video poll timed out after {timeout_s}s ({request_id})")


def download_video_bytes(status_payload: dict[str, Any]) -> bytes:
    video = status_payload.get("video") or {}
    url = video.get("url") if isinstance(video, dict) else None
    url = url or status_payload.get("url")
    if not url:
        raise ImagineError(f"No video url in payload: {list(status_payload.keys())}")
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        r = client.get(url)
        if r.status_code >= 400:
            raise ImagineError(f"Video download failed ({r.status_code})")
        return r.content


def image_to_video(
    image_bytes: bytes,
    prompt: str,
    *,
    mime: str = "image/png",
    duration: int = 6,
    model: str = DEFAULT_VIDEO_MODEL,
    api_key: str | None = None,
    out_path: Path | None = None,
) -> bytes:
    """Full image→video: start, poll, download. Optionally write to out_path."""
    rid = start_image_to_video(
        image_bytes, prompt, mime=mime, duration=duration, model=model, api_key=api_key
    )
    status = poll_video(rid, api_key=api_key)
    st = (status.get("status") or "").lower()
    if st != "done":
        raise ImagineError(f"Video generation {st}: {status}")
    if status.get("video") and isinstance(status["video"], dict):
        if status["video"].get("respect_moderation") is False:
            raise ImagineError("Video blocked by moderation")
    raw = download_video_bytes(status)
    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
    return raw
