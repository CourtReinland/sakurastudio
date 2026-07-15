from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from sakura.yaml_io import dump_yaml, load_yaml


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _dumper_dump(path: Path, data: Any) -> None:
    class D(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:  # noqa: ANN401
            return True

    text = yaml.dump(
        data,
        Dumper=D,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_dialogue(title_dir: Path) -> dict[str, Any]:
    for name in ("dialogue.json", "dialogue.yaml"):
        path = title_dir / name
        if not path.is_file():
            continue
        if name.endswith(".json"):
            return json.loads(path.read_text(encoding="utf-8"))
        data = load_yaml(path)
        if isinstance(data, dict):
            return data
    raise FileNotFoundError(f"No dialogue.yaml/json in {title_dir}")


def save_dialogue(title_dir: Path, data: dict[str, Any]) -> None:
    _dumper_dump(title_dir / "dialogue.yaml", data)
    (title_dir / "dialogue.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def update_line(
    catalog_root: Path,
    title_dir: Path,
    *,
    scene_id: str,
    node_id: str,
    text: str,
) -> dict[str, Any]:
    """Update a dialogue line across ledger, localization, and line asset text file."""
    text = text if text is not None else ""
    data = load_dialogue(title_dir)
    found = False
    scene_label = scene_id
    speaker = None
    for scene in data.get("scenes") or []:
        if scene.get("id") != scene_id:
            continue
        scene_label = scene.get("label") or scene_id
        for node in scene.get("nodes") or []:
            if node.get("id") != node_id:
                continue
            node["text"] = text
            speaker = node.get("speaker")
            found = True
            break
        break
    if not found:
        raise KeyError(f"Node {scene_id}/{node_id} not found")

    save_dialogue(title_dir, data)

    # localization
    loc_path = title_dir / "localization" / "en.yaml"
    str_id = f"str.tea.{_slug(scene_id)}.{_slug(node_id)}"
    if loc_path.is_file():
        loc = load_yaml(loc_path) or {}
    else:
        loc = {"locale": "en", "strings": {}}
    strings = loc.setdefault("strings", {})
    if not isinstance(strings, dict):
        strings = {}
        loc["strings"] = strings
    strings[str_id] = text
    _dumper_dump(loc_path, loc)

    # plain text asset
    rel = f"assets/files/tea_house/dialogue/{_slug(scene_id)}/{_slug(node_id)}.txt"
    fpath = catalog_root / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")

    # update asset meta notes if present
    asset_id = f"asset.line.tea.{_slug(scene_id)}.{_slug(node_id)}"
    asset_path = catalog_root / "assets" / "library" / f"{asset_id}.yaml"
    if asset_path.is_file():
        asset = load_yaml(asset_path) or {}
        asset["notes"] = f"speaker={speaker or 'unknown'}; string_id={str_id}"
        files = asset.get("files") or []
        if not files:
            asset["files"] = [{"role": "master", "path": rel, "mime": "text/plain"}]
        _dumper_dump(asset_path, asset)

    return {
        "ok": True,
        "scene_id": scene_id,
        "node_id": node_id,
        "scene_label": scene_label,
        "speaker": speaker,
        "text": text,
        "string_id": str_id,
        "asset_id": asset_id,
        "path": rel,
    }
