from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    path: Path | None = None
    entity_id: str | None = None

    def format(self, catalog_root: Path | None = None) -> str:
        loc = ""
        if self.path is not None:
            try:
                rel = (
                    self.path.relative_to(catalog_root)
                    if catalog_root
                    else self.path
                )
            except ValueError:
                rel = self.path
            loc = f"{rel}: "
        eid = f"[{self.entity_id}] " if self.entity_id else ""
        return f"{self.severity.value.upper()} {self.code}: {loc}{eid}{self.message}"


@dataclass
class Entity:
    kind: str
    path: Path
    data: dict[str, Any]
    entity_id: str | None = None


@dataclass
class CatalogIndex:
    root: Path
    meta: dict[str, Any] | None = None
    brands: dict[str, Entity] = field(default_factory=dict)
    characters: dict[str, Entity] = field(default_factory=dict)
    assets: dict[str, Entity] = field(default_factory=dict)
    engines: dict[str, Entity] = field(default_factory=dict)
    titles: dict[str, Entity] = field(default_factory=dict)
    # title_id -> kind -> Entity (cast/slots/bindings/ggd/levels)
    title_files: dict[str, dict[str, Entity]] = field(default_factory=dict)
    jobs: dict[str, Entity] = field(default_factory=dict)
    schema_findings: list[Finding] = field(default_factory=list)
    load_findings: list[Finding] = field(default_factory=list)
