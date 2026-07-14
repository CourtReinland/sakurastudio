from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from sakura.yaml_io import load_yaml


def load_github_mappings(catalog_root: Path) -> list[dict[str, Any]]:
    path = catalog_root / "_meta" / "github_projects.yaml"
    if not path.is_file():
        return []
    data = load_yaml(path) or {}
    return list(data.get("mappings") or [])


def list_github_repos(owner: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    """List repos via `gh` CLI. Returns [] if gh unavailable."""
    cmd = [
        "gh",
        "repo",
        "list",
        *( [owner] if owner else [] ),
        "--limit",
        str(limit),
        "--json",
        "name,nameWithOwner,description,url,isPrivate,updatedAt,primaryLanguage",
    ]
    try:
        out = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(out.stdout or "[]")
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def project_tabs(catalog_root: Path, titles: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Merge catalog titles + GitHub mappings + live gh repos into Studio tabs.
    Each tab: { key, label, title_id?, github?, source, notes? }
    """
    mappings = load_github_mappings(catalog_root)
    by_github = {m.get("github"): m for m in mappings if m.get("github")}
    tabs: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_gh: set[str] = set()

    # 1) Mapped github projects first
    for m in mappings:
        gh = m.get("github")
        tid = m.get("title_id")
        if tid:
            seen_titles.add(tid)
        if gh:
            seen_gh.add(gh)
        tabs.append(
            {
                "key": f"gh:{gh}" if gh else f"title:{tid}",
                "label": m.get("label") or gh or tid,
                "title_id": tid,
                "github": gh,
                "source": "mapping",
                "notes": m.get("notes"),
                "in_catalog": bool(tid and tid in titles),
            }
        )

    # 2) Remaining catalog titles
    for tid, ent in sorted(titles.items()):
        if tid in seen_titles:
            continue
        label = ent.data.get("label", tid) if hasattr(ent, "data") else tid
        tabs.append(
            {
                "key": f"title:{tid}",
                "label": label,
                "title_id": tid,
                "github": None,
                "source": "catalog",
                "notes": None,
                "in_catalog": True,
            }
        )

    # 3) Other GitHub repos (unmapped)
    for repo in list_github_repos():
        nwo = repo.get("nameWithOwner") or repo.get("name")
        if not nwo or nwo in seen_gh:
            continue
        tabs.append(
            {
                "key": f"gh:{nwo}",
                "label": repo.get("name") or nwo,
                "title_id": None,
                "github": nwo,
                "source": "github",
                "notes": repo.get("description"),
                "in_catalog": False,
                "url": repo.get("url"),
                "updated_at": repo.get("updatedAt"),
                "language": (repo.get("primaryLanguage") or {}).get("name")
                if isinstance(repo.get("primaryLanguage"), dict)
                else repo.get("primaryLanguage"),
            }
        )

    return tabs
