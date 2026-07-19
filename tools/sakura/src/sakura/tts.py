from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sakura.dialogue_edit import load_dialogue
from sakura.elevenlabs_client import DEFAULT_MODEL, text_to_speech
from sakura.voice_map import (
    game_audio_rel,
    line_audio_path,
    line_audio_rel,
    load_voice_map,
    resolve_voice_for_speaker,
)
from sakura.yaml_io import load_yaml


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# Square-bracket audio tags for Eleven v3, e.g. [whispers] [sad] [coughs]
_AUDIO_TAG_RE = re.compile(r"\[([^\]]*)\]")
# Parenthetical stage direction that should become a v3 audio tag (not spoken)
# e.g. (whispers) (softly) — but never affinity notes
_STAGE_PAREN_RE = re.compile(
    r"(?<!_)\(([a-zA-Z][a-zA-Z0-9_\-\s]{0,32})\)(?!_)"
)


def prepare_tts_text(text: str) -> str:
    """
    Clean dialogue text for ElevenLabs v3 while preserving [audio tags].

    Eleven v3 treats bracket tags as performance/style cues, not spoken words:
      "[whispers] Hello." → whisper delivery of "Hello."
    We must keep those brackets intact and not let cleanup strip or mangle them.
    """
    if not text:
        return ""

    t = str(text)
    # YAML soft line breaks → single spaces (tags must not split across newlines)
    t = re.sub(r"\s*\n\s*", " ", t)

    # Protect existing [tags] while we clean the rest
    protected: list[str] = []

    def _stash_tag(m: re.Match[str]) -> str:
        inner = re.sub(r"\s+", " ", (m.group(1) or "").strip())
        if not inner:
            return ""
        # Normalize common variants so the model recognizes them as style tags
        # e.g. [WHISPERS] / [whispering] stay as written but trimmed
        protected.append(f"[{inner}]")
        return f"\x00TAG{len(protected) - 1}\x00"

    t = _AUDIO_TAG_RE.sub(_stash_tag, t)

    # Strip markdown bold **…**
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    # Strip affinity / game notes written as italic underscore-parens: _(affinity: ren+2)_
    t = re.sub(r"_\([^)]*\)_", "", t)
    # Convert short stage parentheticals into audio tags (v3 style), not speech
    def _paren_to_tag(m: re.Match[str]) -> str:
        inner = re.sub(r"\s+", " ", m.group(1).strip())
        low = inner.lower()
        if low.startswith("affinity") or low.startswith("flag") or "+" in inner:
            return ""  # game meta — drop
        protected.append(f"[{inner}]")
        return f"\x00TAG{len(protected) - 1}\x00"

    t = _STAGE_PAREN_RE.sub(_paren_to_tag, t)

    # Collapse leftover whitespace
    t = re.sub(r"[ \t]{2,}", " ", t).strip()

    # Restore tags
    for i, tag in enumerate(protected):
        t = t.replace(f"\x00TAG{i}\x00", tag)

    # Ensure a space between tag and following word: ]Hello → ] Hello
    t = re.sub(r"\](\S)", r"] \1", t)
    # Space before a mid-sentence tag after a word: word[sad] → word [sad]
    t = re.sub(r"(\S)\[", r"\1 [", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return t


def find_line(
    title_dir: Path, scene_id: str, node_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_dialogue(title_dir)
    for scene in data.get("scenes") or []:
        if scene.get("id") != scene_id:
            continue
        for node in scene.get("nodes") or []:
            if node.get("id") == node_id:
                return scene, node
    raise KeyError(f"Line not found: {scene_id}/{node_id}")


def resolve_game_audio_root(title_dir: Path) -> Path | None:
    """Optional export root from title.yaml exports.game_audio_root or env."""
    import os

    env = os.environ.get("SAKURA_GAME_AUDIO_ROOT") or os.environ.get(
        "SAKURA_GAME_PUBLIC"
    )
    if env:
        return Path(env).expanduser()

    title_path = title_dir / "title.yaml"
    if title_path.is_file():
        title = load_yaml(title_path) or {}
        exports = title.get("exports") or {}
        root = exports.get("game_audio_root") or exports.get("game_public")
        if root:
            return Path(str(root)).expanduser()
    return None


def generate_line_audio(
    catalog_root: Path,
    title_dir: Path,
    *,
    scene_id: str,
    node_id: str,
    force: bool = False,
    export_to_game: bool = True,
) -> dict[str, Any]:
    scene, node = find_line(title_dir, scene_id, node_id)
    if node.get("kind") != "line":
        raise ValueError(f"Node kind {node.get('kind')!r} is not a speakable line")

    text = (node.get("text") or "").strip()
    # Preserve [audio tags] for v3 stylization; strip markdown / affinity only
    text_tts = prepare_tts_text(text)
    if not text_tts:
        raise ValueError("Line text is empty after cleanup")

    speaker = node.get("speaker")
    voice = resolve_voice_for_speaker(title_dir, speaker)
    if not voice or not voice.get("voice_id"):
        raise ValueError(
            f"No ElevenLabs voice assigned for speaker {speaker!r}. "
            "Set it in Studio Dialogue → Voices."
        )

    vmap = load_voice_map(title_dir)
    model_id = vmap.get("model_id") or DEFAULT_MODEL

    title_id = vmap.get("title_id")
    if not title_id:
        title_yaml = load_yaml(title_dir / "title.yaml") or {}
        title_id = title_yaml.get("id")

    out_path = line_audio_path(catalog_root, scene_id, node_id, title_id)
    cached = out_path.is_file() and not force
    if not cached:
        audio = text_to_speech(
            text_tts,
            voice["voice_id"],
            model_id=model_id,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
    else:
        audio = out_path.read_bytes()

    game_path = None
    game_rel = game_audio_rel(scene_id, node_id)
    if export_to_game:
        game_root = resolve_game_audio_root(title_dir)
        if game_root:
            # if root is public/, write audio/vo/...; if root is app root, use public/audio/vo
            dest = game_root / game_rel
            if game_root.name != "public" and (game_root / "public").is_dir():
                dest = game_root / "public" / game_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(audio)
            game_path = str(dest)

    return {
        "ok": True,
        "scene_id": scene_id,
        "node_id": node_id,
        "speaker": speaker,
        "voice_id": voice.get("voice_id"),
        "voice_name": voice.get("voice_name"),
        "model_id": model_id,
        "cached": cached,
        "bytes": len(audio),
        "catalog_path": line_audio_rel(scene_id, node_id, title_id),
        "catalog_abs": str(out_path),
        "game_path": game_path,
        "game_rel": game_rel,
        "text": text_tts,
        "text_source": text,
        "scene_label": scene.get("label"),
    }
