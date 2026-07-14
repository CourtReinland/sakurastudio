from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "ios",
    "android",
    "public",
    "Library",
    ".venv",
}
CODE_EXTS = {".ts", ".tsx", ".js", ".mjs", ".jsx", ".css", ".md", ".json"}
IMPORT_PATTERNS = [
    re.compile(r"""from\s+['"]([^'"]+)['"]"""),
    re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
]


def _file_id(rel: str) -> str:
    return "code." + rel.replace("/", ".").replace("\\", ".")


def _community(rel: str) -> str:
    parts = Path(rel).parts
    if parts and parts[0] == "src" and len(parts) > 1:
        return f"src/{parts[1]}"
    if parts and parts[0] == "docs":
        return "docs"
    return parts[0] if parts else "root"


def build_code_graph(
    source_root: Path,
    *,
    title_id: str | None = None,
    source_repo: str | None = None,
) -> dict[str, Any]:
    """Graphify-inspired local import/module graph (no LLM, no embeddings)."""
    root = source_root.resolve()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    edge_set: set[tuple[str, str, str]] = set()

    files: list[tuple[Path, str]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix not in CODE_EXTS:
            continue
        if p.name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
            continue
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            continue
        files.append((p, rel))

    for _p, rel in files:
        nid = _file_id(rel)
        nodes[nid] = {
            "id": nid,
            "label": rel,
            "path": rel,
            "kind": "doc" if Path(rel).suffix == ".md" else "module",
            "community": _community(rel),
            "degree": 0,
        }

    def resolve_import(from_rel: str, spec: str) -> str | None:
        if not spec.startswith("."):
            pkg = spec.split("/")[0]
            if pkg.startswith("@"):
                bits = spec.split("/")
                pkg = "/".join(bits[:2]) if len(bits) > 1 else pkg
            return f"pkg.{pkg}"
        base = (root / from_rel).parent
        cand = (base / spec).resolve()
        tries: list[Path] = [cand]
        if cand.suffix == "":
            for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
                tries.append(cand.with_suffix(ext))
            tries.append(cand / "index.ts")
            tries.append(cand / "index.js")
        for t in tries:
            try:
                rel = str(t.relative_to(root))
            except ValueError:
                continue
            nid = _file_id(rel)
            if nid in nodes:
                return nid
        return None

    for p, rel in files:
        if p.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        fr = _file_id(rel)
        specs: set[str] = set()
        for pat in IMPORT_PATTERNS:
            specs.update(pat.findall(text))
        for spec in specs:
            to = resolve_import(rel, spec)
            if not to:
                continue
            if to.startswith("pkg.") and to not in nodes:
                nodes[to] = {
                    "id": to,
                    "label": to[4:],
                    "path": None,
                    "kind": "package",
                    "community": "external",
                    "degree": 0,
                }
            key = (fr, to, "imports")
            if key in edge_set:
                continue
            edge_set.add(key)
            edges.append({"from": fr, "to": to, "kind": "imports"})

    deg: dict[str, int] = defaultdict(int)
    for e in edges:
        deg[e["from"]] += 1
        deg[e["to"]] += 1
    for nid, d in deg.items():
        if nid in nodes:
            nodes[nid]["degree"] = d

    god = sorted(nodes.values(), key=lambda n: -n["degree"])[:30]
    comm: dict[str, list[str]] = defaultdict(list)
    for n in nodes.values():
        comm[n["community"]].append(n["id"])

    return {
        "schema_version": "1.0.0",
        "title_id": title_id,
        "source_repo": source_repo,
        "source_root": str(root),
        "style": "graphify-inspired (local import graph; no embeddings)",
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "communities": len(comm),
        },
        "god_nodes": [
            {
                "id": n["id"],
                "label": n["label"],
                "degree": n["degree"],
                "community": n["community"],
                "kind": n["kind"],
            }
            for n in god
            if n["degree"] > 0
        ],
        "communities": {
            k: {"count": len(v), "sample": v[:10]}
            for k, v in sorted(comm.items(), key=lambda x: -len(x[1]))
        },
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def load_title_code_graph(catalog_root: Path, title_id: str) -> dict[str, Any] | None:
    """Load committed graph next to title, e.g. titles/foo/code_graph.json."""
    # title dirs use hyphenated folder names
    titles_dir = catalog_root / "titles"
    if not titles_dir.is_dir():
        return None
    for d in titles_dir.iterdir():
        if not d.is_dir():
            continue
        path = d / "code_graph.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("title_id") == title_id:
            return data
    # also try slug from title id
    slug = title_id.replace("title.", "").replace("_", "-")
    path = titles_dir / slug / "code_graph.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def write_code_graph(path: Path, graph: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
