"""Open IDE / Unity / Unreal / Blender / folders from Studio deep links."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sakura.loader import load_catalog
from sakura.yaml_io import load_yaml

ALLOWED_APPS = frozenset(
    {
        "finder",
        "folder",
        "ide",
        "cursor",
        "vscode",
        "code",
        "unity",
        "unreal",
        "blender",
        "terminal",
        "file",
    }
)


def studio_root_from_catalog(catalog: Path) -> Path:
    return catalog.resolve().parent


def load_title_exports(catalog: Path, title_id: str) -> dict[str, Any]:
    index = load_catalog(catalog, include_examples=True)
    ent = index.titles.get(title_id)
    if not ent:
        return {}
    data = ent.data or {}
    exports = data.get("exports") if isinstance(data.get("exports"), dict) else {}
    # also merge repo_path convenience
    out = dict(exports)
    if data.get("repo_path") and "game_repo" not in out:
        out["game_repo"] = data["repo_path"]
    return out


def resolve_path(
    catalog: Path,
    title_id: str,
    *,
    path: str | None = None,
    key: str | None = None,
) -> Path | None:
    """Resolve absolute path from absolute, relative-to-studio, or exports key."""
    root = studio_root_from_catalog(catalog)
    exports = load_title_exports(catalog, title_id)
    raw = path
    if key and not raw:
        raw = exports.get(key)
        if isinstance(raw, dict):
            raw = raw.get("path")
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (root / p).resolve()
    else:
        p = p.resolve()
    return p


def open_target(
    catalog: Path,
    title_id: str,
    *,
    app: str = "folder",
    path: str | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    """
    Open a project path in the requested app (macOS-focused, Linux/Windows best-effort).

    app: folder|ide|cursor|vscode|unity|unreal|blender|file|terminal
    path: optional absolute/relative path (overrides key)
    key: exports key e.g. unity_project, blender_file, game_repo
    """
    app_l = (app or "folder").lower().strip()
    if app_l not in ALLOWED_APPS:
        raise ValueError(f"Unsupported app {app!r}. Allowed: {sorted(ALLOWED_APPS)}")

    # default keys by app
    if not path and not key:
        key = {
            "unity": "unity_project",
            "unreal": "unreal_project",
            "blender": "blender_file",
            "ide": "game_repo",
            "cursor": "game_repo",
            "vscode": "game_repo",
            "code": "game_repo",
            "folder": "game_repo",
            "finder": "game_repo",
            "terminal": "game_repo",
            "file": "game_repo",
        }.get(app_l, "game_repo")

    target = resolve_path(catalog, title_id, path=path, key=key)
    if target is None:
        exports = load_title_exports(catalog, title_id)
        raise ValueError(
            f"No path for app={app_l} key={key}. "
            f"Set title.exports in title.yaml (have keys: {list(exports.keys())})"
        )

    system = platform.system()
    cmds: list[list[str]] = []

    if app_l in ("folder", "finder"):
        folder = target if target.is_dir() else target.parent
        if system == "Darwin":
            cmds.append(["open", str(folder)])
        elif system == "Windows":
            cmds.append(["explorer", str(folder)])
        else:
            cmds.append(["xdg-open", str(folder)])

    elif app_l in ("file",):
        if system == "Darwin":
            cmds.append(["open", str(target)])
        elif system == "Windows":
            cmds.append(["explorer", f"/select,{target}"])
        else:
            cmds.append(["xdg-open", str(target if target.is_file() else target)])

    elif app_l in ("ide", "cursor"):
        cursor = shutil.which("cursor")
        if cursor:
            cmds.append([cursor, str(target)])
        code = shutil.which("code")
        if code:
            cmds.append([code, str(target)])
        if system == "Darwin":
            cmds.append(["open", "-a", "Cursor", str(target)])
            cmds.append(["open", "-a", "Visual Studio Code", str(target)])
        cmds.append(["open" if system == "Darwin" else "xdg-open", str(target)])

    elif app_l in ("vscode", "code"):
        code = shutil.which("code")
        if code:
            cmds.append([code, str(target)])
        if system == "Darwin":
            cmds.append(["open", "-a", "Visual Studio Code", str(target)])

    elif app_l == "unity":
        if system == "Darwin":
            # Unity Hub can open project folder
            cmds.append(["open", "-a", "Unity Hub", str(target if target.is_dir() else target.parent)])
            cmds.append(["open", "-a", "Unity", str(target if target.is_dir() else target.parent)])
        unity = shutil.which("unity-editor") or shutil.which("Unity")
        if unity:
            cmds.append([unity, "-projectPath", str(target if target.is_dir() else target.parent)])
        cmds.append(["open" if system == "Darwin" else "xdg-open", str(target)])

    elif app_l == "unreal":
        if system == "Darwin":
            cmds.append(["open", "-a", "Epic Games Launcher"])
            cmds.append(["open", str(target if target.is_dir() else target.parent)])
        else:
            cmds.append(["xdg-open", str(target)])

    elif app_l == "blender":
        blender = shutil.which("blender")
        if blender and target.is_file():
            cmds.append([blender, str(target)])
        if system == "Darwin":
            if target.is_file():
                cmds.append(["open", "-a", "Blender", str(target)])
            else:
                cmds.append(["open", "-a", "Blender"])
        cmds.append(["open" if system == "Darwin" else "xdg-open", str(target)])

    elif app_l == "terminal":
        folder = target if target.is_dir() else target.parent
        if system == "Darwin":
            # Open Terminal at folder
            script = f'tell application "Terminal" to do script "cd " & quoted form of "{folder}"'
            cmds.append(["osascript", "-e", script])
        else:
            term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal")
            if term:
                cmds.append([term, f"--working-directory={folder}"])

    last_err = None
    for cmd in cmds:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "ok": True,
                "app": app_l,
                "path": str(target),
                "command": cmd,
                "message": f"Opened {app_l}: {target}",
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    raise RuntimeError(
        f"Could not open {app_l} at {target}"
        + (f": {last_err}" if last_err else "")
    )
