from __future__ import annotations

from pathlib import Path
from typing import Any

from sakura.models import CatalogIndex, Finding, Severity

ACTIVE_BINDING_STATUSES = frozenset({"draft", "review", "approved"})
RELEASE_OK_STATUSES = frozenset({"approved"})


def cross_validate(
    index: CatalogIndex,
    *,
    title_filter: str | None = None,
    strict_files: bool = False,
    release: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []

    titles = index.titles
    if title_filter:
        if title_filter not in titles:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unknown_title",
                    f"Title not found: {title_filter}",
                )
            )
            return findings
        titles = {title_filter: titles[title_filter]}

    for tid, title_entity in titles.items():
        findings.extend(
            _validate_title(
                index,
                tid,
                title_entity.data,
                title_entity.path,
                strict_files=strict_files,
                release=release,
            )
        )

    # Shared entity brand refs
    for cid, ent in index.characters.items():
        brand = ent.data.get("brand_id")
        if brand and brand not in index.brands:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unresolved_ref",
                    f"brand_id '{brand}' does not exist",
                    path=ent.path,
                    entity_id=cid,
                )
            )

    for aid, ent in index.assets.items():
        brand = ent.data.get("brand_id")
        if brand and brand not in index.brands:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unresolved_ref",
                    f"brand_id '{brand}' does not exist",
                    path=ent.path,
                    entity_id=aid,
                )
            )
        for chr_id in ent.data.get("characters") or []:
            if chr_id not in index.characters:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "unresolved_ref",
                        f"characters entry '{chr_id}' does not exist",
                        path=ent.path,
                        entity_id=aid,
                    )
                )
        for var in ent.data.get("variants") or []:
            if var not in index.assets:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "unresolved_ref",
                        f"variants entry '{var}' does not exist",
                        path=ent.path,
                        entity_id=aid,
                    )
                )
        # File existence
        for i, file_rec in enumerate(ent.data.get("files") or []):
            if not isinstance(file_rec, dict):
                continue
            rel = file_rec.get("path")
            if not rel:
                continue
            full = (index.root / rel).resolve()
            # also try relative to catalog as stored
            if not full.is_file():
                # paths in assets are relative to catalog root
                alt = index.root / str(rel)
                exists = alt.is_file()
            else:
                exists = True
            if not exists:
                sev = Severity.ERROR if strict_files else Severity.WARNING
                findings.append(
                    Finding(
                        sev,
                        "missing_file",
                        f"Asset file missing: {rel}",
                        path=ent.path,
                        entity_id=aid,
                    )
                )

    # Jobs referencing titles / scope
    for jid, ent in index.jobs.items():
        data = ent.data
        jtid = data.get("title_id")
        if jtid and jtid not in index.titles:
            # examples may reference titles that exist
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unresolved_ref",
                    f"title_id '{jtid}' does not exist",
                    path=ent.path,
                    entity_id=jid,
                )
            )
        scope = data.get("scope") or {}
        if isinstance(scope, dict) and jtid and jtid in index.title_files:
            tfiles = index.title_files[jtid]
            slots_doc = (tfiles.get("slots") or None)
            slot_ids = set()
            if slots_doc:
                for s in slots_doc.data.get("slots") or []:
                    if isinstance(s, dict) and "id" in s:
                        slot_ids.add(s["id"])
            for sid in scope.get("slot_ids") or []:
                if slot_ids and sid not in slot_ids:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "job_scope",
                            f"scope.slot_ids entry '{sid}' not in title slots",
                            path=ent.path,
                            entity_id=jid,
                        )
                    )
            for aid in scope.get("asset_ids") or []:
                if aid not in index.assets:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "unresolved_ref",
                            f"scope.asset_ids entry '{aid}' does not exist",
                            path=ent.path,
                            entity_id=jid,
                        )
                    )
            ggd_doc = tfiles.get("ggd")
            node_ids = set()
            if ggd_doc:
                for n in ggd_doc.data.get("nodes") or []:
                    if isinstance(n, dict) and "id" in n:
                        node_ids.add(n["id"])
            for nid in scope.get("node_ids") or []:
                if node_ids and nid not in node_ids:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "job_scope",
                            f"scope.node_ids entry '{nid}' not in title GGD",
                            path=ent.path,
                            entity_id=jid,
                        )
                    )

    return findings


def _validate_title(
    index: CatalogIndex,
    tid: str,
    title: dict[str, Any],
    title_path: Path,
    *,
    strict_files: bool,
    release: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    files = index.title_files.get(tid, {})

    brand_id = title.get("brand_id")
    if brand_id and brand_id not in index.brands:
        findings.append(
            Finding(
                Severity.ERROR,
                "unresolved_ref",
                f"brand_id '{brand_id}' does not exist",
                path=title_path,
                entity_id=tid,
            )
        )

    engine_id = title.get("engine_id")
    if engine_id and engine_id not in index.engines:
        findings.append(
            Finding(
                Severity.ERROR,
                "unresolved_ref",
                f"engine_id '{engine_id}' does not exist",
                path=title_path,
                entity_id=tid,
            )
        )

    # title_id consistency on content files
    for kind, ent in files.items():
        declared = ent.data.get("title_id")
        if declared and declared != tid:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "title_id_mismatch",
                    f"{kind}.yaml title_id '{declared}' != title id '{tid}'",
                    path=ent.path,
                    entity_id=tid,
                )
            )

    # Cast
    cast = files.get("cast")
    if cast:
        for i, entry in enumerate(cast.data.get("entries") or []):
            if not isinstance(entry, dict):
                continue
            cid = entry.get("character_id")
            if cid and cid not in index.characters:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "unresolved_ref",
                        f"cast.entries[{i}].character_id '{cid}' does not exist",
                        path=cast.path,
                        entity_id=tid,
                    )
                )

    # Slots index
    slots_ent = files.get("slots")
    slots_by_id: dict[str, dict[str, Any]] = {}
    if slots_ent:
        for i, slot in enumerate(slots_ent.data.get("slots") or []):
            if not isinstance(slot, dict):
                continue
            sid = slot.get("id")
            if not sid:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "missing_id",
                        f"slots[{i}] missing id",
                        path=slots_ent.path,
                        entity_id=tid,
                    )
                )
                continue
            if sid in slots_by_id:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate_id",
                        f"Duplicate slot id '{sid}'",
                        path=slots_ent.path,
                        entity_id=sid,
                    )
                )
            slots_by_id[sid] = slot
            for nid in slot.get("used_by") or []:
                # checked after GGD nodes known — stash for later
                pass

    # Bindings
    bindings_ent = files.get("bindings")
    bound_slots: dict[str, list[dict[str, Any]]] = {}
    if bindings_ent:
        for i, b in enumerate(bindings_ent.data.get("bindings") or []):
            if not isinstance(b, dict):
                continue
            sid = b.get("slot_id")
            aid = b.get("asset_id")
            if sid and sid not in slots_by_id:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "unresolved_ref",
                        f"bindings[{i}].slot_id '{sid}' not in slots.yaml",
                        path=bindings_ent.path,
                        entity_id=tid,
                    )
                )
            if aid and aid not in index.assets:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "unresolved_ref",
                        f"bindings[{i}].asset_id '{aid}' does not exist",
                        path=bindings_ent.path,
                        entity_id=tid,
                    )
                )
            if sid:
                bound_slots.setdefault(sid, []).append(b)

            # kind / constraint checks
            if sid in slots_by_id and aid in index.assets:
                slot = slots_by_id[sid]
                asset = index.assets[aid].data
                slot_kind = slot.get("kind")
                asset_kind = asset.get("kind")
                if slot_kind and asset_kind and slot_kind != asset_kind:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "kind_mismatch",
                            f"slot '{sid}' kind={slot_kind} but asset '{aid}' kind={asset_kind}",
                            path=bindings_ent.path,
                            entity_id=tid,
                        )
                    )
                findings.extend(
                    _check_slot_constraints(
                        slot,
                        asset,
                        index.assets[aid].path,
                        bindings_ent.path,
                        tid,
                        sid,
                        aid,
                    )
                )

            status = b.get("status", "draft")
            if release and status not in RELEASE_OK_STATUSES:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "release_gate",
                        f"bindings[{i}] status '{status}' not approved (release mode)",
                        path=bindings_ent.path,
                        entity_id=sid or tid,
                    )
                )

    # Required slots must have exactly one active binding
    for sid, slot in slots_by_id.items():
        required = slot.get("required", True)
        active = [
            b
            for b in bound_slots.get(sid, [])
            if b.get("status", "draft") in ACTIVE_BINDING_STATUSES
        ]
        # locale-specific: treat missing locale as default; multiple locales ok
        # For v1: count by (slot_id, locale or "")
        by_locale: dict[str, list] = {}
        for b in active:
            loc = b.get("locale") or ""
            by_locale.setdefault(loc, []).append(b)

        if required and not active:
            is_template = title.get("catalog_role") == "template"
            findings.append(
                Finding(
                    Severity.WARNING if is_template else Severity.ERROR,
                    "unbound_slot",
                    f"Required slot '{sid}' has no active binding"
                    + (" (template)" if is_template else ""),
                    path=bindings_ent.path if bindings_ent else title_path,
                    entity_id=sid,
                )
            )
        for loc, blist in by_locale.items():
            if len(blist) > 1:
                loc_s = f" locale={loc!r}" if loc else ""
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate_binding",
                        f"Slot '{sid}' has {len(blist)} active bindings{loc_s}",
                        path=bindings_ent.path if bindings_ent else title_path,
                        entity_id=sid,
                    )
                )

        if release and required:
            approved = [
                b
                for b in bound_slots.get(sid, [])
                if b.get("status") in RELEASE_OK_STATUSES
            ]
            if not approved:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "release_gate",
                        f"Required slot '{sid}' has no approved binding (release mode)",
                        path=bindings_ent.path if bindings_ent else title_path,
                        entity_id=sid,
                    )
                )

    # GGD
    ggd = files.get("ggd")
    node_ids: set[str] = set()
    nodes_by_id: dict[str, dict[str, Any]] = {}
    if ggd:
        for i, node in enumerate(ggd.data.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if not nid:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "missing_id",
                        f"ggd.nodes[{i}] missing id",
                        path=ggd.path,
                        entity_id=tid,
                    )
                )
                continue
            if nid in node_ids:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate_id",
                        f"Duplicate GGD node id '{nid}'",
                        path=ggd.path,
                        entity_id=nid,
                    )
                )
            node_ids.add(nid)
            nodes_by_id[nid] = node

            if release and title.get("gates", {}).get(
                "require_approved_player_facing_nodes"
            ):
                kind = node.get("kind")
                if kind in {
                    "scene",
                    "ending",
                    "cg_moment",
                    "level",
                    "ui_screen",
                }:
                    st = node.get("status", "draft")
                    if st not in RELEASE_OK_STATUSES:
                        findings.append(
                            Finding(
                                Severity.ERROR,
                                "release_gate",
                                f"Player-facing node '{nid}' status '{st}' not approved",
                                path=ggd.path,
                                entity_id=nid,
                            )
                        )

        edge_ids: set[str] = set()
        for i, edge in enumerate(ggd.data.get("edges") or []):
            if not isinstance(edge, dict):
                continue
            eid = edge.get("id")
            if eid:
                if eid in edge_ids:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "duplicate_id",
                            f"Duplicate GGD edge id '{eid}'",
                            path=ggd.path,
                            entity_id=eid,
                        )
                    )
                edge_ids.add(eid)

            fr = edge.get("from")
            to = edge.get("to")
            kind = edge.get("kind")

            if fr:
                findings.extend(
                    _resolve_endpoint(
                        fr,
                        "from",
                        i,
                        kind,
                        node_ids,
                        slots_by_id,
                        index,
                        ggd.path,
                        tid,
                    )
                )
            if to:
                findings.extend(
                    _resolve_endpoint(
                        to,
                        "to",
                        i,
                        kind,
                        node_ids,
                        slots_by_id,
                        index,
                        ggd.path,
                        tid,
                    )
                )

        # slot used_by references
        if slots_ent:
            for sid, slot in slots_by_id.items():
                for nid in slot.get("used_by") or []:
                    if nid not in node_ids:
                        findings.append(
                            Finding(
                                Severity.ERROR,
                                "unresolved_ref",
                                f"slot '{sid}' used_by node '{nid}' not in GGD",
                                path=slots_ent.path,
                                entity_id=sid,
                            )
                        )

    # Levels
    levels = files.get("levels")
    if levels:
        for i, level in enumerate(levels.data.get("levels") or []):
            if not isinstance(level, dict):
                continue
            lid = level.get("id")
            if lid and ggd and lid not in node_ids:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "unresolved_ref",
                        f"levels[{i}].id '{lid}' not present in GGD nodes",
                        path=levels.path,
                        entity_id=lid,
                    )
                )
            elif lid and ggd and lid in nodes_by_id:
                nkind = nodes_by_id[lid].get("kind")
                if nkind and nkind != "level":
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "level_kind",
                            f"levels[{i}].id '{lid}' GGD node kind is '{nkind}', expected 'level'",
                            path=levels.path,
                            entity_id=lid,
                        )
                    )
            for sid in level.get("tile_pool") or []:
                if sid not in slots_by_id:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "unresolved_ref",
                            f"levels[{i}] tile_pool slot '{sid}' not in slots.yaml",
                            path=levels.path,
                            entity_id=lid or tid,
                        )
                    )
            for g in level.get("goals") or []:
                if not isinstance(g, dict):
                    continue
                gsid = g.get("slot_id")
                if gsid and gsid not in slots_by_id:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "unresolved_ref",
                            f"levels[{i}] goal slot_id '{gsid}' not in slots.yaml",
                            path=levels.path,
                            entity_id=lid or tid,
                        )
                    )

    return findings


def _resolve_endpoint(
    ref: str,
    field: str,
    edge_index: int,
    edge_kind: str | None,
    node_ids: set[str],
    slots_by_id: dict[str, Any],
    index: CatalogIndex,
    path: Path,
    tid: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if ref.startswith("node."):
        if ref not in node_ids:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unresolved_ref",
                    f"edges[{edge_index}].{field} '{ref}' not in GGD nodes",
                    path=path,
                    entity_id=tid,
                )
            )
    elif ref.startswith("slot."):
        if ref not in slots_by_id:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unresolved_ref",
                    f"edges[{edge_index}].{field} '{ref}' not in slots.yaml",
                    path=path,
                    entity_id=tid,
                )
            )
    elif ref.startswith("chr."):
        if ref not in index.characters:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unresolved_ref",
                    f"edges[{edge_index}].{field} '{ref}' character does not exist",
                    path=path,
                    entity_id=tid,
                )
            )
    elif ref.startswith("str."):
        # localization tables not fully indexed in v1 — soft warning
        findings.append(
            Finding(
                Severity.WARNING,
                "str_ref_unchecked",
                f"edges[{edge_index}].{field} '{ref}' string key not verified (no locale index yet)",
                path=path,
                entity_id=tid,
            )
        )
    else:
        findings.append(
            Finding(
                Severity.ERROR,
                "bad_ref_prefix",
                f"edges[{edge_index}].{field} '{ref}' has unknown id prefix",
                path=path,
                entity_id=tid,
            )
        )
    return findings


def _check_slot_constraints(
    slot: dict[str, Any],
    asset: dict[str, Any],
    asset_path: Path,
    binding_path: Path,
    tid: str,
    sid: str,
    aid: str,
) -> list[Finding]:
    findings: list[Finding] = []
    constraints = slot.get("constraints") or {}
    if not constraints:
        return findings

    tags = set(asset.get("tags") or [])
    tags_any = constraints.get("tags_any") or []
    tags_all = constraints.get("tags_all") or []
    if tags_any and not any(t in tags for t in tags_any):
        findings.append(
            Finding(
                Severity.ERROR,
                "constraint",
                f"asset '{aid}' tags {sorted(tags)} miss tags_any {tags_any} for slot '{sid}'",
                path=binding_path,
                entity_id=tid,
            )
        )
    if tags_all and not all(t in tags for t in tags_all):
        findings.append(
            Finding(
                Severity.ERROR,
                "constraint",
                f"asset '{aid}' tags {sorted(tags)} miss tags_all {tags_all} for slot '{sid}'",
                path=binding_path,
                entity_id=tid,
            )
        )

    files = asset.get("files") or []
    master = None
    for f in files:
        if isinstance(f, dict) and f.get("role") == "master":
            master = f
            break
    if master is None and files and isinstance(files[0], dict):
        master = files[0]

    if master:
        w = master.get("width")
        h = master.get("height")
        max_w = constraints.get("max_width")
        max_h = constraints.get("max_height")
        min_w = constraints.get("min_width")
        min_h = constraints.get("min_height")
        if max_w is not None and w is not None and w > max_w:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "constraint",
                    f"asset '{aid}' width {w} > max_width {max_w} for slot '{sid}'",
                    path=binding_path,
                    entity_id=tid,
                )
            )
        if max_h is not None and h is not None and h > max_h:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "constraint",
                    f"asset '{aid}' height {h} > max_height {max_h} for slot '{sid}'",
                    path=binding_path,
                    entity_id=tid,
                )
            )
        if min_w is not None and w is not None and w < min_w:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "constraint",
                    f"asset '{aid}' width {w} < min_width {min_w} for slot '{sid}'",
                    path=binding_path,
                    entity_id=tid,
                )
            )
        if min_h is not None and h is not None and h < min_h:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "constraint",
                    f"asset '{aid}' height {h} < min_height {min_h} for slot '{sid}'",
                    path=binding_path,
                    entity_id=tid,
                )
            )

        mime_any = constraints.get("mime_any") or []
        mime = master.get("mime")
        if mime_any and mime and mime not in mime_any:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "constraint",
                    f"asset '{aid}' mime {mime} not in mime_any {mime_any} for slot '{sid}'",
                    path=binding_path,
                    entity_id=tid,
                )
            )

        aspect = constraints.get("aspect_ratio")
        if aspect and w and h:
            # "1:1" or "16:9"
            if ":" in str(aspect):
                a, b = str(aspect).split(":", 1)
                try:
                    ar = float(a) / float(b)
                    actual = w / h
                    if abs(ar - actual) > 0.02:
                        findings.append(
                            Finding(
                                Severity.WARNING,
                                "constraint",
                                f"asset '{aid}' aspect {w}:{h} != slot constraint {aspect}",
                                path=binding_path,
                                entity_id=tid,
                            )
                        )
                except ValueError:
                    pass

    return findings
