from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE = "https://api.elevenlabs.io/v1"
# Eleven v3 — expressive delivery; understands [audio tags] as style, not spoken text
DEFAULT_MODEL = "eleven_v3"


def resolve_api_key(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit.strip() or None
    for name in ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY", "XI_API_KEY"):
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    # optional dotenv files next to catalog / studio
    # __file__ = .../tools/sakura/src/sakura/elevenlabs_client.py
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
                if k in ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY", "XI_API_KEY") and v:
                    return v
        except OSError:
            continue
    return None


class ElevenLabsError(RuntimeError):
    pass


def list_voices(api_key: str | None = None) -> list[dict[str, Any]]:
    key = resolve_api_key(api_key)
    if not key:
        raise ElevenLabsError(
            "No ElevenLabs API key. Set ELEVENLABS_API_KEY in the environment "
            "or create SakuraSoft/.env with ELEVENLABS_API_KEY=..."
        )
    url = f"{DEFAULT_BASE}/voices"
    with httpx.Client(timeout=60.0) as client:
        r = client.get(url, headers={"xi-api-key": key})
        if r.status_code >= 400:
            raise ElevenLabsError(f"ElevenLabs voices failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
    voices = []
    for v in data.get("voices") or []:
        voices.append(
            {
                "voice_id": v.get("voice_id"),
                "name": v.get("name"),
                "category": v.get("category"),
                "description": (v.get("description") or "")[:200],
                "preview_url": v.get("preview_url"),
                "labels": v.get("labels") or {},
            }
        )
    voices.sort(key=lambda x: (x.get("name") or "").lower())
    return voices


def text_to_speech(
    text: str,
    voice_id: str,
    *,
    api_key: str | None = None,
    model_id: str = DEFAULT_MODEL,
    output_format: str = "mp3_44100_128",
) -> bytes:
    key = resolve_api_key(api_key)
    if not key:
        raise ElevenLabsError("No ElevenLabs API key configured")
    if not text or not text.strip():
        raise ElevenLabsError("Empty text — nothing to synthesize")
    if not voice_id:
        raise ElevenLabsError("voice_id required")

    # Prefer v3 for expressiveness + [audio tag] stylization unless caller overrides.
    mid = (model_id or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    url = f"{DEFAULT_BASE}/text-to-speech/{voice_id}"
    params = {"output_format": output_format}
    body: dict[str, Any] = {
        "text": text.strip(),
        "model_id": mid,
    }
    # v3: keep text mostly as written so [whispers]/[sad]/etc. stay performance tags
    if mid == "eleven_v3" or mid.startswith("eleven_v3"):
        body["apply_text_normalization"] = "off"

    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, params=params, headers=headers, json=body)
        if r.status_code >= 400:
            raise ElevenLabsError(f"TTS failed ({r.status_code}): {r.text[:400]}")
        return r.content
