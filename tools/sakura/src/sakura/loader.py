from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sakura.models import CatalogIndex, Entity, Finding, Severity

# filename / path pattern → schema kind
TITLE_CONTENT_KINDS = ("cast", "slots", "bindings", "ggd", "levels")


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_under_examples(path: Path, catalog_root: Path) -> bool:
    try:
        rel = path.relative_to(catalog_root)
    except ValueError:
        return False
    return "_examples" in rel.parts


def discover_catalog_root(explicit: Path | None) -> Path:
    if explicit is not None:
        root = explicit.resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Catalog path is not a directory: {root}")
        return root

    cwd = Path.cwd().resolve()
    candidates = [
        cwd / "catalog",
        cwd,
        cwd.parent / "catalog",
    ]
    # Walk up a few levels looking for catalog/_meta/catalog.yaml
    here = cwd
    for _ in range(6):
        candidates.append(here / "catalog")
        candidates.append(here)
        here = here.parent

    seen: set[Path] = set()
    for c in candidates:
        c = c.resolve()
        if c in seen:
            continue
        seen.add(c)
        if (c / "_meta" / "catalog.yaml").is_file():
            return c
        if (c / "catalog" / "_meta" / "catalog.yaml").is_file():
            return (c / "catalog").resolve()

    raise FileNotFoundError(
        "Could not find catalog root (expected _meta/catalog.yaml). "
        "Pass --catalog PATH."
    )


def _register(
    index: CatalogIndex,
    registry: dict[str, Entity],
    entity: Entity,
    *,
    require_id: bool = True,
) -> None:
    eid = entity.entity_id
    if not eid:
        if require_id:
            index.load_findings.append(
                Finding(
                    Severity.ERROR,
                    "missing_id",
                    "Entity is missing required 'id' field",
                    path=entity.path,
                )
            )
        return
    if eid in registry:
        other = registry[eid]
        index.load_findings.append(
            Finding(
                Severity.ERROR,
                "duplicate_id",
                f"Duplicate id already defined at {other.path}",
                path=entity.path,
                entity_id=eid,
            )
        )
        return
    registry[eid] = entity


def load_catalog(catalog_root: Path, *, include_examples: bool = False) -> CatalogIndex:
    root = catalog_root.resolve()
    index = CatalogIndex(root=root)

    meta_path = root / "_meta" / "catalog.yaml"
    if meta_path.is_file():
        try:
            data = load_yaml(meta_path)
            if not isinstance(data, dict):
                raise ValueError("catalog meta must be a mapping")
            index.meta = data
            index.titles  # touch
        except Exception as e:  # noqa: BLE001 — collect load errors
            index.load_findings.append(
                Finding(
                    Severity.ERROR,
                    "yaml_load",
                    f"Failed to load catalog meta: {e}",
                    path=meta_path,
                )
            )
    else:
        index.load_findings.append(
            Finding(
                Severity.ERROR,
                "missing_meta",
                "Missing _meta/catalog.yaml",
                path=meta_path,
            )
        )

    def maybe_skip(path: Path) -> bool:
        return (not include_examples) and _is_under_examples(path, root)

    # Brands
    for path in sorted((root / "brands").glob("*/brand.yaml")):
        if maybe_skip(path):
            continue
        _load_entity(index, path, "brand", index.brands)

    # Characters
    for path in sorted((root / "characters").glob("*.yaml")):
        if maybe_skip(path):
            continue
        _load_entity(index, path, "character", index.characters)

    # Assets
    for path in sorted((root / "assets" / "library").glob("*.yaml")):
        if maybe_skip(path):
            continue
        _load_entity(index, path, "asset", index.assets)

    # Engines
    for path in sorted((root / "engines").glob("*.yaml")):
        if maybe_skip(path):
            continue
        _load_entity(index, path, "engine", index.engines)

    # Titles
    titles_dir = root / "titles"
    if titles_dir.is_dir():
        for title_dir in sorted(p for p in titles_dir.iterdir() if p.is_dir()):
            if title_dir.name.startswith("."):
                continue
            if title_dir.name == "_examples":
                if not include_examples:
                    continue
                for example_dir in sorted(
                    p for p in title_dir.iterdir() if p.is_dir()
                ):
                    _load_title_dir(index, example_dir)
                continue
            _load_title_dir(index, title_dir)

    # Jobs
    jobs_dir = root / "jobs"
    if jobs_dir.is_dir():
        for path in sorted(jobs_dir.rglob("*.yaml")):
            if path.name.startswith("."):
                continue
            _load_entity(index, path, "job", index.jobs)

    return index


def _load_entity(
    index: CatalogIndex,
    path: Path,
    kind: str,
    registry: dict[str, Entity],
    *,
    id_field: str = "id",
    require_id: bool = True,
) -> Entity | None:
    try:
        data = load_yaml(path)
    except Exception as e:  # noqa: BLE001
        index.load_findings.append(
            Finding(
                Severity.ERROR,
                "yaml_load",
                f"Failed to parse YAML: {e}",
                path=path,
            )
        )
        return None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        index.load_findings.append(
            Finding(
                Severity.ERROR,
                "yaml_type",
                "YAML root must be a mapping",
                path=path,
            )
        )
        return None
    raw_id = data.get(id_field)
    eid = raw_id if isinstance(raw_id, str) else None
    entity = Entity(kind=kind, path=path, data=data, entity_id=eid)
    if require_id:
        _register(index, registry, entity, require_id=True)
    return entity


def _load_title_dir(index: CatalogIndex, title_dir: Path) -> None:
    title_path = title_dir / "title.yaml"
    if not title_path.is_file():
        index.load_findings.append(
            Finding(
                Severity.ERROR,
                "missing_title",
                f"Title directory missing title.yaml: {title_dir.name}",
                path=title_dir,
            )
        )
        return

    title_entity = _load_entity(index, title_path, "title", index.titles)
    if title_entity is None or not title_entity.entity_id:
        return

    tid = title_entity.entity_id
    index.title_files[tid] = {}

    content_files = title_entity.data.get("content_files") or {}
    if not isinstance(content_files, dict):
        content_files = {}

    # Default filenames if content_files omitted
    defaults = {
        "cast": "cast.yaml",
        "ggd": "ggd.yaml",
        "slots": "slots.yaml",
        "bindings": "bindings.yaml",
        "levels": "levels.yaml",
    }
    for key, default_name in defaults.items():
        rel = content_files.get(key, default_name)
        if rel is None:
            continue
        path = title_dir / str(rel)
        if not path.is_file():
            # levels is optional; others required if listed or default exists expectation
            if key == "levels" and key not in content_files:
                continue
            if key not in content_files and key == "levels":
                continue
            # If content_files explicitly lists it, or it's a core file that exists as default expectation
            if key in content_files or key in ("cast", "ggd", "slots", "bindings"):
                # only error if content_files says so OR file is core — for core files, warn if missing
                severity = (
                    Severity.ERROR
                    if key in content_files
                    or key in ("slots", "bindings", "ggd")
                    else Severity.WARNING
                )
                index.load_findings.append(
                    Finding(
                        severity,
                        "missing_title_file",
                        f"Title content file not found: {rel}",
                        path=title_path,
                        entity_id=tid,
                    )
                )
            continue

        try:
            data = load_yaml(path)
        except Exception as e:  # noqa: BLE001
            index.load_findings.append(
                Finding(
                    Severity.ERROR,
                    "yaml_load",
                    f"Failed to parse YAML: {e}",
                    path=path,
                    entity_id=tid,
                )
            )
            continue
        if data is None:
            data = {}
        if not isinstance(data, dict):
            index.load_findings.append(
                Finding(
                    Severity.ERROR,
                    "yaml_type",
                    "YAML root must be a mapping",
                    path=path,
                    entity_id=tid,
                )
            )
            continue

        entity = Entity(kind=key, path=path, data=data, entity_id=tid)
        index.title_files[tid][key] = entity
