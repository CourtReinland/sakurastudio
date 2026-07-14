from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sakura.loader import discover_catalog_root, load_catalog
from sakura.models import CatalogIndex, Finding, Severity
from sakura.validate import run_validate, summarize
from sakura.yaml_io import dump_yaml, load_yaml, order_binding

VALID_STATUSES = frozenset({"draft", "review", "approved", "deprecated", "blocked"})


@dataclass
class BindResult:
    ok: bool
    message: str
    path: Path | None = None
    previous_asset_id: str | None = None
    findings: list[Finding] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def resolve_title_id(index: CatalogIndex, title: str | None) -> str:
    if title:
        if title not in index.titles:
            raise ValueError(
                f"Unknown title '{title}'. Known: {', '.join(sorted(index.titles)) or '(none)'}"
            )
        return title
    if len(index.titles) == 1:
        return next(iter(index.titles))
    if not index.titles:
        raise ValueError("No titles found in catalog")
    raise ValueError(
        "Multiple titles found; pass --title. Known: "
        + ", ".join(sorted(index.titles))
    )


def _slot_map(index: CatalogIndex, title_id: str) -> dict[str, dict[str, Any]]:
    files = index.title_files.get(title_id, {})
    slots_ent = files.get("slots")
    if not slots_ent:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for s in slots_ent.data.get("slots") or []:
        if isinstance(s, dict) and isinstance(s.get("id"), str):
            out[s["id"]] = s
    return out


def _bindings_path(index: CatalogIndex, title_id: str) -> Path:
    files = index.title_files.get(title_id, {})
    if "bindings" in files:
        return files["bindings"].path
    # derive from title.yaml location
    title_ent = index.titles[title_id]
    content = title_ent.data.get("content_files") or {}
    name = content.get("bindings", "bindings.yaml")
    return title_ent.path.parent / str(name)


def _load_bindings_doc(path: Path, title_id: str) -> dict[str, Any]:
    if path.is_file():
        data = load_yaml(path)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError(f"bindings file is not a mapping: {path}")
        data.setdefault("title_id", title_id)
        data.setdefault("bindings", [])
        if data["bindings"] is None:
            data["bindings"] = []
        if not isinstance(data["bindings"], list):
            raise ValueError(f"bindings must be a list: {path}")
        return data
    return {"title_id": title_id, "bindings": []}


def _matching_indices(
    bindings: list[Any], slot_id: str, locale: str | None
) -> list[int]:
    matches: list[int] = []
    for i, b in enumerate(bindings):
        if not isinstance(b, dict):
            continue
        if b.get("slot_id") != slot_id:
            continue
        b_loc = b.get("locale") or None
        want = locale or None
        if b_loc == want:
            matches.append(i)
    return matches


def _check_compat(
    slot: dict[str, Any],
    asset: dict[str, Any],
    *,
    force: bool,
) -> list[str]:
    """Return hard error messages; empty if ok (or force)."""
    errors: list[str] = []
    warnings: list[str] = []

    sk = slot.get("kind")
    ak = asset.get("kind")
    if sk and ak and sk != ak:
        msg = f"kind mismatch: slot={sk} asset={ak}"
        (warnings if force else errors).append(msg)

    constraints = slot.get("constraints") or {}
    tags = set(asset.get("tags") or [])
    tags_any = constraints.get("tags_any") or []
    tags_all = constraints.get("tags_all") or []
    if tags_any and not any(t in tags for t in tags_any):
        msg = f"tags_any not satisfied: need any of {tags_any}, have {sorted(tags)}"
        (warnings if force else errors).append(msg)
    if tags_all and not all(t in tags for t in tags_all):
        msg = f"tags_all not satisfied: need {tags_all}, have {sorted(tags)}"
        (warnings if force else errors).append(msg)

    return errors


def bind_set(
    *,
    catalog: Path | None,
    title: str | None,
    slot_id: str,
    asset_id: str,
    status: str = "review",
    locale: str | None = None,
    bound_by: str = "cli",
    notes: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    no_validate: bool = False,
    include_examples: bool = False,
) -> BindResult:
    if status not in VALID_STATUSES:
        return BindResult(False, f"Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}")

    root = discover_catalog_root(catalog)
    index = load_catalog(root, include_examples=include_examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        return BindResult(False, str(e))

    slots = _slot_map(index, title_id)
    if slot_id not in slots:
        known = ", ".join(sorted(slots)[:20]) or "(none)"
        return BindResult(
            False,
            f"Unknown slot '{slot_id}' for {title_id}. Known slots: {known}",
        )

    if asset_id not in index.assets:
        return BindResult(False, f"Unknown asset '{asset_id}' (not in assets/library/)")

    slot = slots[slot_id]
    asset = index.assets[asset_id].data
    hard = _check_compat(slot, asset, force=force)
    if hard:
        return BindResult(
            False,
            "Compatibility check failed (use --force to override):\n  - "
            + "\n  - ".join(hard),
        )

    path = _bindings_path(index, title_id)
    doc = _load_bindings_doc(path, title_id)
    bindings: list[Any] = doc["bindings"]

    matches = _matching_indices(bindings, slot_id, locale)
    previous: str | None = None
    now = _utc_now()

    new_rec: dict[str, Any] = {
        "slot_id": slot_id,
        "asset_id": asset_id,
        "status": status,
        "bound_at": now,
        "bound_by": bound_by,
    }
    if locale:
        new_rec["locale"] = locale
    if notes is not None:
        new_rec["notes"] = notes

    if matches:
        # update first match; drop extras for same slot+locale
        i0 = matches[0]
        prev = bindings[i0]
        if isinstance(prev, dict):
            previous = prev.get("asset_id")
            # preserve notes if not provided
            if notes is None and prev.get("notes"):
                new_rec["notes"] = prev["notes"]
        bindings[i0] = order_binding(new_rec)
        for j in reversed(matches[1:]):
            del bindings[j]
        action = "update" if previous != asset_id else "refresh"
    else:
        bindings.append(order_binding(new_rec))
        action = "create"

    doc["title_id"] = title_id
    doc["bindings"] = [order_binding(b) if isinstance(b, dict) else b for b in bindings]

    if dry_run:
        return BindResult(
            True,
            f"DRY-RUN would {action} binding: {slot_id} → {asset_id}"
            + (f" (was {previous})" if previous else "")
            + f" [{status}] in {path}",
            path=path,
            previous_asset_id=previous,
        )

    dump_yaml(path, doc)

    findings: list[Finding] | None = None
    if not no_validate:
        _, findings = run_validate(
            catalog=root,
            title=title_id,
            include_examples=include_examples,
        )
        errors, _warnings = summarize(findings)
        if errors:
            return BindResult(
                False,
                f"{action.capitalize()}d binding {slot_id} → {asset_id}, "
                f"but validate reported {errors} error(s)",
                path=path,
                previous_asset_id=previous,
                findings=findings,
            )

    was = f" (was {previous})" if previous and previous != asset_id else ""
    past = {"create": "Created", "update": "Updated", "refresh": "Refreshed"}[action]
    return BindResult(
        True,
        f"{past} binding: {slot_id} → {asset_id}{was} [{status}]\n"
        f"Wrote {path}",
        path=path,
        previous_asset_id=previous,
        findings=findings,
    )



def bind_unbind(
    *,
    catalog: Path | None,
    title: str | None,
    slot_id: str,
    locale: str | None = None,
    dry_run: bool = False,
    include_examples: bool = False,
) -> BindResult:
    root = discover_catalog_root(catalog)
    index = load_catalog(root, include_examples=include_examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        return BindResult(False, str(e))

    path = _bindings_path(index, title_id)
    if not path.is_file():
        return BindResult(False, f"No bindings file at {path}")

    doc = _load_bindings_doc(path, title_id)
    bindings = doc["bindings"]
    matches = _matching_indices(bindings, slot_id, locale)
    if not matches:
        loc = f" locale={locale}" if locale else ""
        return BindResult(False, f"No binding found for {slot_id}{loc}")

    previous = None
    prev = bindings[matches[0]]
    if isinstance(prev, dict):
        previous = prev.get("asset_id")

    if dry_run:
        return BindResult(
            True,
            f"DRY-RUN would remove {len(matches)} binding(s) for {slot_id}"
            + (f" (asset {previous})" if previous else ""),
            path=path,
            previous_asset_id=previous,
        )

    for j in reversed(matches):
        del bindings[j]
    doc["bindings"] = [order_binding(b) if isinstance(b, dict) else b for b in bindings]
    dump_yaml(path, doc)
    return BindResult(
        True,
        f"Removed {len(matches)} binding(s) for {slot_id}"
        + (f" (was {previous})" if previous else "")
        + f"\nWrote {path}",
        path=path,
        previous_asset_id=previous,
    )


def bind_set_status(
    *,
    catalog: Path | None,
    title: str | None,
    slot_id: str,
    status: str,
    locale: str | None = None,
    bound_by: str = "cli",
    dry_run: bool = False,
    include_examples: bool = False,
) -> BindResult:
    if status not in VALID_STATUSES:
        return BindResult(False, f"Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}")

    root = discover_catalog_root(catalog)
    index = load_catalog(root, include_examples=include_examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        return BindResult(False, str(e))

    path = _bindings_path(index, title_id)
    if not path.is_file():
        return BindResult(False, f"No bindings file at {path}")

    doc = _load_bindings_doc(path, title_id)
    matches = _matching_indices(doc["bindings"], slot_id, locale)
    if not matches:
        return BindResult(False, f"No binding found for {slot_id}")

    now = _utc_now()
    for i in matches:
        b = doc["bindings"][i]
        if not isinstance(b, dict):
            continue
        b["status"] = status
        b["bound_at"] = now
        b["bound_by"] = bound_by
        doc["bindings"][i] = order_binding(b)

    if dry_run:
        return BindResult(
            True,
            f"DRY-RUN would set status={status} on {len(matches)} binding(s) for {slot_id}",
            path=path,
        )

    dump_yaml(path, doc)
    return BindResult(
        True,
        f"Set status={status} on {len(matches)} binding(s) for {slot_id}\nWrote {path}",
        path=path,
    )


def bind_list(
    *,
    catalog: Path | None,
    title: str | None,
    include_examples: bool = False,
    unbound_only: bool = False,
) -> tuple[bool, str]:
    root = discover_catalog_root(catalog)
    index = load_catalog(root, include_examples=include_examples)
    try:
        title_id = resolve_title_id(index, title)
    except ValueError as e:
        return False, str(e)

    slots = _slot_map(index, title_id)
    path = _bindings_path(index, title_id)
    doc = _load_bindings_doc(path, title_id) if path.is_file() else {
        "title_id": title_id,
        "bindings": [],
    }

    # map slot+locale -> binding
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for b in doc.get("bindings") or []:
        if not isinstance(b, dict):
            continue
        sid = b.get("slot_id")
        if not sid:
            continue
        by_slot.setdefault(sid, []).append(b)

    lines = [f"Bindings for {title_id} ({path if path.is_file() else 'no file yet'})", ""]

    # all known slots first
    for sid in sorted(slots):
        slot = slots[sid]
        required = slot.get("required", True)
        recs = by_slot.pop(sid, [])
        if unbound_only and recs:
            continue
        if not recs:
            flag = "REQUIRED" if required else "optional"
            lines.append(f"  {sid:40}  <unbound>  ({flag})  kind={slot.get('kind')}")
            continue
        for b in recs:
            loc = f" locale={b['locale']}" if b.get("locale") else ""
            lines.append(
                f"  {sid:40}  → {b.get('asset_id')}  [{b.get('status', '?')}]{loc}"
            )

    # orphan bindings (slot not in slots.yaml)
    for sid, recs in sorted(by_slot.items()):
        if unbound_only:
            continue
        for b in recs:
            lines.append(
                f"  {sid:40}  → {b.get('asset_id')}  [{b.get('status', '?')}]  (ORPHAN slot)"
            )

    if len(lines) == 2:
        lines.append("  (no slots or bindings)")

    return True, "\n".join(lines)
