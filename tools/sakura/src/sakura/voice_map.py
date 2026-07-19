from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sakura.yaml_io import dump_yaml, load_yaml

# dialogue speaker keys → default character ids (tea house)
DEFAULT_SPEAKER_CHARS = {
    "ren": "chr.tea.ren",
    "mizu": "chr.tea.mizu",
    "akira": "chr.tea.akira",
    "you": "chr.tea.keeper",
    "narrator": None,
}


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def voice_map_path(title_dir: Path) -> Path:
    return title_dir / "voices.yaml"


def load_voice_map(title_dir: Path) -> dict[str, Any]:
    path = voice_map_path(title_dir)
    if not path.is_file():
        return {
            "title_id": None,
            "provider": "elevenlabs",
            "model_id": "eleven_v3",
            "by_speaker": {},
            "by_character": {},
        }
    data = load_yaml(path) or {}
    data.setdefault("provider", "elevenlabs")
    # Prefer Eleven v3 (audio tags like [whispers] are performance cues)
    mid = data.get("model_id") or "eleven_v3"
    if mid in {
        "eleven_multilingual_v2",
        "eleven_multilingual_v1",
        "eleven_flash_v2",
        "eleven_flash_v2_5",
        "eleven_turbo_v2",
        "eleven_turbo_v2_5",
    }:
        mid = "eleven_v3"
    data["model_id"] = mid
    data.setdefault("by_speaker", {})
    data.setdefault("by_character", {})
    return data


def save_voice_map(title_dir: Path, data: dict[str, Any]) -> None:
    dump_yaml(voice_map_path(title_dir), data)


def set_speaker_voice(
    title_dir: Path,
    *,
    title_id: str,
    speaker: str,
    voice_id: str,
    voice_name: str | None = None,
    character_id: str | None = None,
) -> dict[str, Any]:
    data = load_voice_map(title_dir)
    data["title_id"] = title_id
    speaker_key = (speaker or "").strip().lower()
    if not speaker_key:
        raise ValueError("speaker required")
    entry = {
        "voice_id": voice_id,
        "voice_name": voice_name,
        "character_id": character_id or DEFAULT_SPEAKER_CHARS.get(speaker_key),
    }
    data.setdefault("by_speaker", {})[speaker_key] = entry
    cid = entry.get("character_id")
    if cid:
        data.setdefault("by_character", {})[cid] = {
            "voice_id": voice_id,
            "voice_name": voice_name,
            "speaker": speaker_key,
        }
    save_voice_map(title_dir, data)
    return entry


def resolve_voice_for_speaker(title_dir: Path, speaker: str | None) -> dict[str, Any] | None:
    data = load_voice_map(title_dir)
    if not speaker:
        return None
    key = speaker.strip().lower()
    entry = (data.get("by_speaker") or {}).get(key)
    if entry:
        return entry
    # try character id if speaker looks like chr.*
    if key.startswith("chr."):
        return (data.get("by_character") or {}).get(key)
    cid = DEFAULT_SPEAKER_CHARS.get(key)
    if cid:
        return (data.get("by_character") or {}).get(cid)
    return None


# Per-title catalog roots for line VO files (relative to catalog root).
# Older callers omit title_id and fall through to the tea-house default.
TITLE_AUDIO_ROOTS = {
    "title.sakura_tea_house": "assets/files/tea_house/audio",
    "title.midnight_par": "assets/files/midnight_par/audio/vo",
}
_DEFAULT_AUDIO_ROOT = TITLE_AUDIO_ROOTS["title.sakura_tea_house"]


def line_audio_rel(scene_id: str, node_id: str, title_id: str | None = None) -> str:
    root = TITLE_AUDIO_ROOTS.get(title_id, _DEFAULT_AUDIO_ROOT) if title_id else _DEFAULT_AUDIO_ROOT
    return f"{root}/{_slug(scene_id)}/{_slug(node_id)}.mp3"


def line_audio_path(catalog_root: Path, scene_id: str, node_id: str, title_id: str | None = None) -> Path:
    return catalog_root / line_audio_rel(scene_id, node_id, title_id)


def game_audio_rel(scene_id: str, node_id: str) -> str:
    """Path inside a game app public folder."""
    return f"audio/vo/{_slug(scene_id)}/{_slug(node_id)}.mp3"
