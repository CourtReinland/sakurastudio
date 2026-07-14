from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from sakura.models import CatalogIndex, Entity, Finding, Severity

SCHEMA_FILES = {
    "catalog_meta": "catalog_meta.schema.json",
    "brand": "brand.schema.json",
    "character": "character.schema.json",
    "asset": "asset.schema.json",
    "engine": "engine.schema.json",
    "title": "title.schema.json",
    "cast": "cast.schema.json",
    "slots": "slots.schema.json",
    "bindings": "bindings.schema.json",
    "ggd": "ggd.schema.json",
    "levels": "levels.schema.json",
    "job": "job.schema.json",
}


def load_schema_registry(schemas_dir: Path) -> tuple[Registry, dict[str, Any]]:
    """Load JSON schemas and build a referencing Registry for $ref resolution."""
    resources: list[tuple[str, Resource]] = []
    raw: dict[str, Any] = {}

    for path in sorted(schemas_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        raw[path.name] = doc
        # Register under both filename and $id if present
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        resources.append((path.name, resource))
        schema_id = doc.get("$id")
        if isinstance(schema_id, str):
            resources.append((schema_id, resource))
        # Also allow common.json short ref as used in schemas: "common.json#/..."
        if path.name == "common.json":
            resources.append(("common.json", resource))

    registry = Registry()
    for uri, resource in resources:
        registry = registry.with_resource(uri, resource)

    return registry, raw


def _validator_for(
    kind: str, schemas_dir: Path, registry: Registry, cache: dict[str, Draft202012Validator]
) -> Draft202012Validator | None:
    filename = SCHEMA_FILES.get(kind)
    if not filename:
        return None
    if kind in cache:
        return cache[kind]
    path = schemas_dir / filename
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    # Resolve relative $ref like "common.json#/$defs/Status" against registry
    validator = Draft202012Validator(schema, registry=registry)
    cache[kind] = validator
    return validator


def validate_entity_schema(
    entity: Entity,
    kind: str,
    schemas_dir: Path,
    registry: Registry,
    cache: dict[str, Draft202012Validator],
) -> list[Finding]:
    findings: list[Finding] = []
    validator = _validator_for(kind, schemas_dir, registry, cache)
    if validator is None:
        findings.append(
            Finding(
                Severity.WARNING,
                "no_schema",
                f"No JSON Schema registered for kind '{kind}'",
                path=entity.path,
                entity_id=entity.entity_id,
            )
        )
        return findings

    errors = sorted(validator.iter_errors(entity.data), key=lambda e: list(e.absolute_path))
    for err in errors:
        findings.append(_schema_error_to_finding(entity, err))
    return findings


def _schema_error_to_finding(entity: Entity, err: ValidationError) -> Finding:
    path_parts = [str(p) for p in err.absolute_path]
    loc = "/".join(path_parts) if path_parts else "(root)"
    return Finding(
        Severity.ERROR,
        "schema",
        f"at {loc}: {err.message}",
        path=entity.path,
        entity_id=entity.entity_id,
    )


def validate_all_schemas(index: CatalogIndex) -> list[Finding]:
    schemas_dir = index.root / "schemas"
    findings: list[Finding] = []
    if not schemas_dir.is_dir():
        findings.append(
            Finding(
                Severity.ERROR,
                "missing_schemas",
                "schemas/ directory not found under catalog root",
                path=index.root,
            )
        )
        return findings

    try:
        registry, _ = load_schema_registry(schemas_dir)
    except Exception as e:  # noqa: BLE001
        findings.append(
            Finding(
                Severity.ERROR,
                "schema_registry",
                f"Failed to load schema registry: {e}",
                path=schemas_dir,
            )
        )
        return findings

    cache: dict[str, Draft202012Validator] = {}

    if index.meta is not None:
        meta_entity = Entity(
            kind="catalog_meta",
            path=index.root / "_meta" / "catalog.yaml",
            data=index.meta,
            entity_id=None,
        )
        findings.extend(
            validate_entity_schema(meta_entity, "catalog_meta", schemas_dir, registry, cache)
        )

    for entity in index.brands.values():
        findings.extend(validate_entity_schema(entity, "brand", schemas_dir, registry, cache))
    for entity in index.characters.values():
        findings.extend(
            validate_entity_schema(entity, "character", schemas_dir, registry, cache)
        )
    for entity in index.assets.values():
        findings.extend(validate_entity_schema(entity, "asset", schemas_dir, registry, cache))
    for entity in index.engines.values():
        findings.extend(validate_entity_schema(entity, "engine", schemas_dir, registry, cache))
    for entity in index.titles.values():
        findings.extend(validate_entity_schema(entity, "title", schemas_dir, registry, cache))
    for entity in index.jobs.values():
        findings.extend(validate_entity_schema(entity, "job", schemas_dir, registry, cache))

    for _tid, files in index.title_files.items():
        for kind, entity in files.items():
            findings.extend(
                validate_entity_schema(entity, kind, schemas_dir, registry, cache)
            )

    return findings
