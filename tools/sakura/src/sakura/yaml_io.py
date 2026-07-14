from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class _LiteralStr(str):
    """Marker for multi-line strings (folded block if needed)."""


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.Node:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _dict_representer(dumper: yaml.Dumper, data: dict) -> yaml.Node:
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


class _CatalogDumper(yaml.SafeDumper):
    pass


_CatalogDumper.add_representer(str, _str_representer)
_CatalogDumper.add_representer(dict, _dict_representer)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_yaml(path: Path, data: Any) -> None:
    """Write YAML with stable key order and a trailing newline."""
    text = yaml.dump(
        data,
        Dumper=_CatalogDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# Preferred field order for binding records
BINDING_KEY_ORDER = (
    "slot_id",
    "asset_id",
    "status",
    "bound_at",
    "bound_by",
    "locale",
    "notes",
)


def order_binding(binding: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in BINDING_KEY_ORDER:
        if key in binding and binding[key] is not None:
            ordered[key] = binding[key]
    for key, value in binding.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return ordered
