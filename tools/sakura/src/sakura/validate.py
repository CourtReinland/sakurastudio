from __future__ import annotations

from pathlib import Path

from sakura.cross_validate import cross_validate
from sakura.loader import discover_catalog_root, load_catalog
from sakura.models import Finding, Severity
from sakura.schema_validate import validate_all_schemas


def run_validate(
    *,
    catalog: Path | None = None,
    title: str | None = None,
    include_examples: bool = False,
    strict: bool = False,
    release: bool = False,
) -> tuple[Path, list[Finding]]:
    root = discover_catalog_root(catalog)
    index = load_catalog(root, include_examples=include_examples)

    findings: list[Finding] = []
    findings.extend(index.load_findings)
    findings.extend(validate_all_schemas(index))
    findings.extend(
        cross_validate(
            index,
            title_filter=title,
            strict_files=strict,
            release=release,
        )
    )
    return root, findings


def summarize(findings: list[Finding]) -> tuple[int, int]:
    errors = sum(1 for f in findings if f.severity == Severity.ERROR)
    warnings = sum(1 for f in findings if f.severity == Severity.WARNING)
    return errors, warnings
