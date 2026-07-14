from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sakura import __version__
from sakura.bind import bind_list, bind_set, bind_set_status, bind_unbind
from sakura.models import Severity
from sakura.validate import run_validate, summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sakura",
        description="Sakura Soft catalog tools",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sakura {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    _add_validate(sub)
    _add_bind(sub)
    _add_import(sub)
    _add_studio(sub)
    _add_sync(sub)
    _add_code_graph(sub)
    return parser


def _add_validate(sub: argparse._SubParsersAction) -> None:
    v = sub.add_parser(
        "validate",
        help="Validate catalog YAML against JSON Schema and cross-file rules",
    )
    v.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to catalog root (directory containing _meta/catalog.yaml)",
    )
    v.add_argument(
        "--title",
        type=str,
        default=None,
        help="Only cross-validate this title id (e.g. title.sakura_match)",
    )
    v.add_argument(
        "--examples",
        action="store_true",
        help="Include titles under titles/_examples/",
    )
    v.add_argument(
        "--strict",
        action="store_true",
        help="Treat missing asset binary files as errors",
    )
    v.add_argument(
        "--release",
        action="store_true",
        help="Enforce release gates (approved bindings / player-facing nodes)",
    )
    v.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Exit non-zero if any warnings are present",
    )
    v.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print summary line",
    )


def _add_bind(sub: argparse._SubParsersAction) -> None:
    b = sub.add_parser(
        "bind",
        help="Manage title slot → asset bindings",
        description=(
            "Rebind catalog slots without free-form 'swap image 8' chat. "
            "Primary form: sakura bind set SLOT ASSET"
        ),
    )
    b_sub = b.add_subparsers(dest="bind_command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to catalog root",
    )
    common.add_argument(
        "--title",
        type=str,
        default=None,
        help="Title id (required if more than one title)",
    )
    common.add_argument(
        "--examples",
        action="store_true",
        help="Include titles under titles/_examples/",
    )
    common.add_argument(
        "--locale",
        type=str,
        default=None,
        help="Locale-specific binding (e.g. ja)",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )

    s = b_sub.add_parser(
        "set",
        parents=[common],
        help="Bind a slot to an asset (create or update)",
    )
    s.add_argument("slot_id", help="Slot id (e.g. slot.tile.red)")
    s.add_argument("asset_id", help="Asset id (e.g. asset.tile_red_pastel_v2)")
    s.add_argument(
        "--status",
        type=str,
        default="review",
        choices=["draft", "review", "approved", "deprecated", "blocked"],
        help="Binding status (default: review)",
    )
    s.add_argument(
        "--by",
        type=str,
        default="cli",
        dest="bound_by",
        help="bound_by field (default: cli)",
    )
    s.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Optional notes (preserves existing if omitted)",
    )
    s.add_argument(
        "--force",
        action="store_true",
        help="Allow kind/tag constraint mismatches",
    )
    s.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip post-write validate",
    )

    # Shorthand: sakura bind SLOT ASSET  (same as set)
    # Implemented by also accepting a hidden top-level pattern via set only;
    # users use `bind set`. Also add alias command name `rebind`.
    r = b_sub.add_parser(
        "rebind",
        parents=[common],
        help="Alias for 'set'",
    )
    r.add_argument("slot_id")
    r.add_argument("asset_id")
    r.add_argument(
        "--status",
        type=str,
        default="review",
        choices=["draft", "review", "approved", "deprecated", "blocked"],
    )
    r.add_argument("--by", type=str, default="cli", dest="bound_by")
    r.add_argument("--notes", type=str, default=None)
    r.add_argument("--force", action="store_true")
    r.add_argument("--no-validate", action="store_true")

    lst = b_sub.add_parser(
        "list",
        parents=[common],
        help="List slots and current bindings for a title",
    )
    lst.add_argument(
        "--unbound",
        action="store_true",
        help="Only show unbound slots",
    )

    u = b_sub.add_parser(
        "unbind",
        parents=[common],
        help="Remove binding(s) for a slot",
    )
    u.add_argument("slot_id", help="Slot id to unbind")

    st = b_sub.add_parser(
        "status",
        parents=[common],
        help="Update status on an existing binding",
    )
    st.add_argument("slot_id", help="Slot id")
    st.add_argument(
        "status",
        choices=["draft", "review", "approved", "deprecated", "blocked"],
        help="New status",
    )
    st.add_argument("--by", type=str, default="cli", dest="bound_by")


def _add_import(sub: argparse._SubParsersAction) -> None:
    imp = sub.add_parser(
        "import",
        help="Import catalog bindings into a Unity title (Resources + bindings.json)",
    )
    imp.add_argument("--catalog", type=Path, default=None)
    imp.add_argument("--title", type=str, default=None, help="e.g. title.sakura_match")
    imp.add_argument(
        "--no-generate",
        action="store_true",
        help="Do not synthesize missing PNG masters",
    )
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument(
        "--examples",
        action="store_true",
        help="Include example titles when resolving --title",
    )


def _add_studio(sub: argparse._SubParsersAction) -> None:
    st = sub.add_parser(
        "studio",
        help="Launch thin Sakura Studio GUI (bind / validate / import)",
    )
    st.add_argument("--catalog", type=Path, default=None)
    st.add_argument("--host", type=str, default="127.0.0.1")
    st.add_argument("--port", type=int, default=8787)
    st.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload server on code changes (dev)",
    )


def _add_sync(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser(
        "sync-tea-house",
        help="Import dialogue + public/assets + code graph from sakura-match checkout",
    )
    s.add_argument("--catalog", type=Path, default=None)
    s.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to CourtReinland/sakura-match clone",
    )
    s.add_argument("--dry-run", action="store_true")


def _add_code_graph(sub: argparse._SubParsersAction) -> None:
    g = sub.add_parser(
        "code-graph",
        help="Build graphify-style import graph for a source tree into a title",
    )
    g.add_argument("--catalog", type=Path, default=None)
    g.add_argument("--source", type=Path, required=True, help="Repo root to scan")
    g.add_argument(
        "--title",
        type=str,
        required=True,
        help="title_id to attach (writes titles/<slug>/code_graph.json)",
    )
    g.add_argument("--repo", type=str, default=None, help="GitHub owner/name label")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "bind":
        return cmd_bind(args)
    if args.command == "import":
        return cmd_import(args)
    if args.command == "studio":
        return cmd_studio(args)
    if args.command == "sync-tea-house":
        return cmd_sync_tea_house(args)
    if args.command == "code-graph":
        return cmd_code_graph(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        root, findings = run_validate(
            catalog=args.catalog,
            title=args.title,
            include_examples=args.examples,
            strict=args.strict,
            release=args.release,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: validate failed: {e}", file=sys.stderr)
        return 2

    errors, warnings = summarize(findings)

    if not args.quiet:
        ordered = sorted(
            findings,
            key=lambda f: (
                0 if f.severity == Severity.ERROR else 1,
                str(f.path or ""),
                f.code,
                f.message,
            ),
        )
        for f in ordered:
            print(f.format(catalog_root=root))

    print(
        f"sakura validate: {errors} error(s), {warnings} warning(s) "
        f"(catalog: {root})"
    )

    if errors:
        return 1
    if args.warnings_as_errors and warnings:
        return 1
    return 0


def cmd_bind(args: argparse.Namespace) -> int:
    cmd = args.bind_command

    try:
        if cmd in ("set", "rebind"):
            result = bind_set(
                catalog=args.catalog,
                title=args.title,
                slot_id=args.slot_id,
                asset_id=args.asset_id,
                status=args.status,
                locale=args.locale,
                bound_by=args.bound_by,
                notes=args.notes,
                dry_run=args.dry_run,
                force=args.force,
                no_validate=args.no_validate,
                include_examples=args.examples,
            )
            print(result.message)
            if result.findings and not result.ok:
                for f in result.findings:
                    if f.severity == Severity.ERROR:
                        print(f.format())
            return 0 if result.ok else 1

        if cmd == "list":
            ok, message = bind_list(
                catalog=args.catalog,
                title=args.title,
                include_examples=args.examples,
                unbound_only=args.unbound,
            )
            print(message)
            return 0 if ok else 1

        if cmd == "unbind":
            result = bind_unbind(
                catalog=args.catalog,
                title=args.title,
                slot_id=args.slot_id,
                locale=args.locale,
                dry_run=args.dry_run,
                include_examples=args.examples,
            )
            print(result.message)
            return 0 if result.ok else 1

        if cmd == "status":
            result = bind_set_status(
                catalog=args.catalog,
                title=args.title,
                slot_id=args.slot_id,
                status=args.status,
                locale=args.locale,
                bound_by=args.bound_by,
                dry_run=args.dry_run,
                include_examples=args.examples,
            )
            print(result.message)
            return 0 if result.ok else 1

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: bind failed: {e}", file=sys.stderr)
        return 2

    print(f"ERROR: unknown bind command {cmd}", file=sys.stderr)
    return 2


def cmd_import(args: argparse.Namespace) -> int:
    from sakura.import_unity import import_title

    try:
        result = import_title(
            catalog=args.catalog,
            title=args.title,
            generate_missing=not args.no_generate,
            dry_run=args.dry_run,
            include_examples=args.examples,
        )
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: import failed: {e}", file=sys.stderr)
        return 2
    print(result.message)
    return 0 if result.ok else 1


def cmd_studio(args: argparse.Namespace) -> int:
    from sakura.studio_server import run_studio

    catalog = args.catalog
    if catalog is None:
        # Prefer SakuraSoft/catalog when launched from monorepo
        try:
            from sakura.loader import discover_catalog_root

            catalog = discover_catalog_root(None)
        except FileNotFoundError:
            catalog = None

    print(
        f"Sakura Studio → http://{args.host}:{args.port}/"
        + (f"  (catalog: {catalog})" if catalog else "")
    )
    try:
        run_studio(
            host=args.host,
            port=args.port,
            catalog=catalog,
            reload=args.reload,
        )
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: studio failed: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_sync_tea_house(args: argparse.Namespace) -> int:
    from sakura.loader import discover_catalog_root
    from sakura.sync_tea_house import sync_tea_house

    try:
        root = discover_catalog_root(args.catalog)
        result = sync_tea_house(
            root, args.source, dry_run=args.dry_run
        )
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: sync-tea-house failed: {e}", file=sys.stderr)
        return 2
    print(result.get("message") or result)
    if result.get("stats"):
        print("stats:", result["stats"])
    return 0 if result.get("ok") else 1


def cmd_code_graph(args: argparse.Namespace) -> int:
    from sakura.code_graph import build_code_graph, write_code_graph
    from sakura.loader import discover_catalog_root

    try:
        root = discover_catalog_root(args.catalog)
        graph = build_code_graph(
            args.source,
            title_id=args.title,
            source_repo=args.repo,
        )
        slug = args.title.replace("title.", "").replace("_", "-")
        out = root / "titles" / slug / "code_graph.json"
        write_code_graph(out, graph)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: code-graph failed: {e}", file=sys.stderr)
        return 2
    print(
        f"Wrote {out} — {graph['stats']['nodes']} nodes, "
        f"{graph['stats']['edges']} edges, "
        f"{len(graph.get('god_nodes') or [])} god nodes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
