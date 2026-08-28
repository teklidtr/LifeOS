"""Command-line interface for LifeOS."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lifeos import __version__
from lifeos.config import ConfigError, load_config
from lifeos.diagnostics import DiagnosticError, serialize_diagnostic_error
from lifeos.registry import Registry


def _print_domain_error(prefix: str, error: DiagnosticError, *, json_output: bool) -> None:
    if json_output:
        print(serialize_diagnostic_error(error))
    else:
        print(f"{prefix}: {error}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lifeos",
        description=(
            "LifeOS is a private, Obsidian-native system for knowledge, study, "
            "adaptive planning, personal observation, and agent-assisted reflection."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", title="commands")
    status_parser = subparsers.add_parser(
        "status", help="Show the current status of the LifeOS vault"
    )
    status_parser.add_argument("--json", action="store_true", help="Output status as JSON")

    scan_parser = subparsers.add_parser(
        "scan", help="Refresh the disposable file and proposal registry"
    )
    scan_parser.add_argument(
        "--config",
        default="lifeos.yml",
        type=Path,
        help="Path to lifeos.yml (default: lifeos.yml)",
    )
    scan_parser.add_argument("--json", action="store_true", help="Output result as JSON")

    proposals_parser = subparsers.add_parser("proposals", help="Manage proposals")
    proposals_subparsers = proposals_parser.add_subparsers(dest="proposals_command", required=True)

    list_parser = proposals_subparsers.add_parser("list", help="List indexed proposals")
    from lifeos.proposals.schema import ProposalStatus

    list_parser.add_argument(
        "--status",
        choices=[s.value for s in ProposalStatus],
        help="Filter proposals by status",
    )

    migrate_parser = proposals_subparsers.add_parser(
        "migrate-lifecycle",
        help="Upgrade legacy proposals to lifecycle schema version 1",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report migration candidates without writing proposal files",
    )

    context_parser = subparsers.add_parser("context", help="Build inspectable context packs")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    context_build_parser = context_subparsers.add_parser(
        "build", help="Build a deterministic context pack for a question"
    )
    context_build_parser.add_argument("question", help="Question or retrieval query")
    context_build_parser.add_argument("--limit", type=int, default=8, help="Maximum source count")
    context_build_parser.add_argument(
        "--focus-path",
        action="append",
        default=[],
        help="Vault-relative Markdown path that must be included as reasoning context (repeatable)",
    )
    context_build_parser.add_argument("--json", action="store_true", help="Output JSON")

    study_parser = subparsers.add_parser("study", help="Plan study and flashcard workloads")
    study_subparsers = study_parser.add_subparsers(dest="study_command", required=True)
    review_parser = study_subparsers.add_parser("review", help="Build a due-card review workload")
    review_parser.add_argument("--date", dest="review_date", help="Review date in YYYY-MM-DD")
    review_parser.add_argument("--minutes", type=int, default=20, help="Available review minutes")
    review_parser.add_argument("--topic", help="Optional exact topic filter")
    review_parser.add_argument("--json", action="store_true", help="Output JSON")

    plan_parser = subparsers.add_parser("plan", help="Build adaptive planning menus")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)
    today_parser = plan_subparsers.add_parser("today", help="Build a proposed daily menu")
    today_parser.add_argument("--date", dest="plan_date", help="Planning date in YYYY-MM-DD")
    today_parser.add_argument("--minutes", type=int, default=120, help="Available minutes")
    today_parser.add_argument("--energy", choices=["low", "medium", "high"], required=True)
    today_parser.add_argument("--motivation", choices=["low", "medium", "high"], required=True)
    today_parser.add_argument("--mode", help="Optional exact mode filter")
    today_parser.add_argument("--json", action="store_true", help="Output JSON")

    observe_parser = subparsers.add_parser("observe", help="Analyze tentative personal patterns")
    observe_subparsers = observe_parser.add_subparsers(dest="observe_command", required=True)
    patterns_parser = observe_subparsers.add_parser(
        "patterns", help="Analyze a numeric or activity association"
    )
    patterns_parser.add_argument("--outcome", required=True, help="Outcome metric name")
    factor_group = patterns_parser.add_mutually_exclusive_group(required=True)
    factor_group.add_argument("--factor", help="Numeric factor metric name")
    factor_group.add_argument("--activity", help="Activity tag to compare")
    patterns_parser.add_argument("--min-samples", type=int, default=5)
    patterns_parser.add_argument("--json", action="store_true", help="Output JSON")

    graph_parser = subparsers.add_parser("graph", help="Build or inspect derived graph views")
    graph_subparsers = graph_parser.add_subparsers(dest="graph_command", required=True)
    for graph_command in ("build", "status"):
        graph_view_parser = graph_subparsers.add_parser(
            graph_command, help=f"{graph_command.title()} a graph view"
        )
        graph_view_parser.add_argument(
            "view", choices=["knowledge", "provenance", "personal-patterns", "system"]
        )
        graph_view_parser.add_argument("--json", action="store_true", help="Output JSON")

    export_parser = subparsers.add_parser("export", help="Build purpose-specific exports")
    export_subparsers = export_parser.add_subparsers(dest="export_command", required=True)
    for export_command in ("build", "status"):
        export_kind_parser = export_subparsers.add_parser(
            export_command,
            help=f"{export_command.title()} an export bundle",
        )
        export_kind_parser.add_argument(
            "kind",
            choices=["public-wiki", "study-bundle", "trusted-agent", "personal-review"],
        )
        export_kind_parser.add_argument("--json", action="store_true", help="Output JSON")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the LifeOS command-line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        from lifeos.facade.errors import ToolExecutionError
        from lifeos.facade.registry_tools import refresh_registry

        try:
            config = load_config(args.config)
            result = refresh_registry(
                vault_root=config.vault_root,
                registry=Registry(config.runtime_dir / "registry.db"),
            )
        except ConfigError as error:
            print(f"Configuration error: {error}", file=sys.stderr)
            return 1
        except ToolExecutionError as error:
            print(f"Scan error: {error}", file=sys.stderr)
            return 1

        payload = {
            "new": list(result.new),
            "modified": list(result.modified),
            "unchanged": list(result.unchanged),
            "deleted": list(result.deleted),
            "proposals_indexed": result.proposals_indexed,
        }
        if result.renamed:
            payload["renamed"] = [
                {"from_path": old_path, "to_path": new_path}
                for old_path, new_path in result.renamed
            ]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(
                "Registry refreshed: "
                f"{len(result.new)} new, "
                f"{len(result.modified)} modified, "
                f"{len(result.unchanged)} unchanged, "
                f"{len(result.deleted)} deleted; "
                f"{result.proposals_indexed} proposals indexed."
            )
            for label, paths in (
                ("New", result.new),
                ("Modified", result.modified),
                ("Deleted", result.deleted),
            ):
                for path in paths:
                    print(f"{label}: {path}")
            for old_path, new_path in result.renamed:
                print(f"Renamed: {old_path} -> {new_path}")
        return 0

    if args.command == "status":
        from lifeos.status import (
            collect_status,
            format_status_text,
            serialize_status_json,
            serialize_error_json,
        )

        # Load config
        config_path = Path("lifeos.yml")
        try:
            config = load_config(config_path)
        except ConfigError as e:
            if args.json:
                print(serialize_error_json("config-error", str(e)))
            else:
                print(f"Configuration error: {e}", file=sys.stderr)
            return 1

        registry = Registry(config.runtime_dir / "registry.db")

        status = collect_status(config, registry)
        if args.json:
            print(serialize_status_json(status))
        else:
            print(format_status_text(status))
        return status.exit_code

    if args.command == "proposals" and args.proposals_command == "list":
        from lifeos.proposals.schema import ProposalStatus
        from lifeos.registry.proposals import ProposalQueryError, list_proposals
        from lifeos.registry._registry import RegistryError, RegistryHistoryError, RegistryOpenError

        config_path = Path("lifeos.yml")
        try:
            config = load_config(config_path)
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1

        registry = Registry(config.runtime_dir / "registry.db")

        parsed_status = ProposalStatus(args.status) if args.status else None

        try:
            with registry.connect() as conn:
                summaries = list_proposals(conn, status=parsed_status)

            _print_proposals_table(summaries)
            return 0

        except ProposalQueryError as e:
            print(f"Query error: {e}", file=sys.stderr)
            return 1
        except RegistryHistoryError as e:
            print(f"Query error: Proposal index unavailable ({e})", file=sys.stderr)
            return 1
        except RegistryOpenError as e:
            print(f"Registry error: {e}", file=sys.stderr)
            return 1
        except RegistryError as e:
            print(f"Registry error: {e}", file=sys.stderr)
            return 1

    if args.command == "proposals" and args.proposals_command == "migrate-lifecycle":
        from lifeos.proposals.migration import (
            LegacyLifecycleMigrationError,
            migrate_legacy_lifecycle,
            plan_legacy_lifecycle_migration,
        )

        config_path = Path("lifeos.yml")
        try:
            config = load_config(config_path)
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1

        proposals_root = config.vault_root / "proposals"
        try:
            if args.dry_run:
                plan = plan_legacy_lifecycle_migration(proposals_root)
                print(
                    "Legacy lifecycle migration dry run: "
                    f"{len(plan.candidates)} candidate(s), "
                    f"{len(plan.skipped_proposal_ids)} current, "
                    f"{len(plan.warnings)} warning(s)."
                )
                for candidate in plan.candidates:
                    print(f"Would migrate {candidate.proposal_id} ({candidate.status.value}).")
                return 0

            migration_result = migrate_legacy_lifecycle(proposals_root)
            print(
                "Legacy lifecycle migration: "
                f"{len(migration_result.transitions)} migrated, "
                f"{len(migration_result.skipped_proposal_ids)} current, "
                f"{len(migration_result.warnings)} warning(s)."
            )
            for transition in migration_result.transitions:
                print(f"Migrated {transition.proposal_id} ({transition.new_status.value}).")
            return 0
        except LegacyLifecycleMigrationError as e:
            print(f"Migration error: {e}", file=sys.stderr)
            return 1

    if args.command == "export":
        from lifeos.exports import (
            ExportError,
            build_export,
            export_status,
            format_export_result,
            format_export_status,
            serialize_export_result,
            serialize_export_status,
        )

        try:
            config = load_config(Path("lifeos.yml"))
            if not config.features.exports:
                print("Export error: exports feature is disabled", file=sys.stderr)
                return 1
            if args.export_command == "build":
                export_result = build_export(
                    vault_root=config.vault_root,
                    runtime_dir=config.runtime_dir,
                    kind=args.kind,
                )
                output = (
                    serialize_export_result(export_result)
                    if args.json
                    else format_export_result(export_result)
                )
            else:
                export_state = export_status(
                    vault_root=config.vault_root,
                    runtime_dir=config.runtime_dir,
                    kind=args.kind,
                )
                output = (
                    serialize_export_status(export_state)
                    if args.json
                    else format_export_status(export_state)
                )
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        except ExportError as e:
            _print_domain_error("Export error", e, json_output=args.json)
            return 1

        print(output)
        return 0

    if args.command == "graph":
        from lifeos.graph import (
            GraphError,
            build_graph_view,
            format_graph_state,
            graph_view_status,
            serialize_graph_state,
        )

        try:
            config = load_config(Path("lifeos.yml"))
            if not config.features.graphify:
                print("Graph error: Graphify feature is disabled", file=sys.stderr)
                return 1
            if args.graph_command == "build":
                graph_state = build_graph_view(
                    vault_root=config.vault_root,
                    runtime_dir=config.runtime_dir,
                    view_name=args.view,
                )
            else:
                graph_state = graph_view_status(
                    vault_root=config.vault_root,
                    runtime_dir=config.runtime_dir,
                    view_name=args.view,
                )
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        except GraphError as e:
            _print_domain_error("Graph error", e, json_output=args.json)
            return 1

        print(serialize_graph_state(graph_state) if args.json else format_graph_state(graph_state))
        return 0

    if args.command == "observe" and args.observe_command == "patterns":
        from lifeos.observation import (
            ObservationError,
            analyze_activity_pattern,
            analyze_numeric_pattern,
            format_pattern_report,
            load_observations,
            serialize_pattern_report,
        )

        try:
            config = load_config(Path("lifeos.yml"))
            observations = load_observations(config.vault_root)
            if args.factor:
                pattern_report = analyze_numeric_pattern(
                    records=observations,
                    outcome=args.outcome,
                    factor=args.factor,
                    min_samples=args.min_samples,
                )
            else:
                pattern_report = analyze_activity_pattern(
                    records=observations,
                    outcome=args.outcome,
                    activity=args.activity,
                    min_group_size=args.min_samples,
                )
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        except ObservationError as e:
            _print_domain_error("Observation error", e, json_output=args.json)
            return 1

        print(
            serialize_pattern_report(pattern_report)
            if args.json
            else format_pattern_report(pattern_report)
        )
        return 0

    if args.command == "plan" and args.plan_command == "today":
        from datetime import date

        from lifeos.planning import (
            PlanningError,
            build_daily_menu,
            format_daily_menu,
            load_plan_actions,
            serialize_daily_menu,
        )

        try:
            config = load_config(Path("lifeos.yml"))
            plan_date = date.fromisoformat(args.plan_date) if args.plan_date else date.today()
            actions = load_plan_actions(config.vault_root)
            daily_menu = build_daily_menu(
                actions=actions,
                as_of=plan_date,
                available_minutes=args.minutes,
                energy=args.energy,
                motivation=args.motivation,
                mode=args.mode,
            )
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        except PlanningError as e:
            _print_domain_error("Planning error", e, json_output=args.json)
            return 1
        except ValueError as e:
            print(f"Planning error: invalid planning date ({e})", file=sys.stderr)
            return 1

        print(serialize_daily_menu(daily_menu) if args.json else format_daily_menu(daily_menu))
        return 0

    if args.command == "study" and args.study_command == "review":
        from datetime import date

        from lifeos.study import (
            StudyError,
            build_review_plan,
            format_review_plan,
            load_flashcards,
            serialize_review_plan,
        )

        try:
            config = load_config(Path("lifeos.yml"))
            review_date = date.fromisoformat(args.review_date) if args.review_date else date.today()
            cards = load_flashcards(config.vault_root)
            review_plan = build_review_plan(
                cards=cards,
                as_of=review_date,
                available_minutes=args.minutes,
                topic=args.topic,
            )
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        except StudyError as e:
            _print_domain_error("Study error", e, json_output=args.json)
            return 1
        except ValueError as e:
            print(f"Study error: invalid review date ({e})", file=sys.stderr)
            return 1

        print(serialize_review_plan(review_plan) if args.json else format_review_plan(review_plan))
        return 0

    if args.command == "context" and args.context_command == "build":
        from lifeos.context import (
            ContextSearchError,
            build_context_pack,
            format_context_pack,
            serialize_context_pack,
        )

        try:
            config = load_config(Path("lifeos.yml"))
            pack = build_context_pack(
                vault_root=config.vault_root,
                runtime_dir=config.runtime_dir,
                question=args.question,
                limit=args.limit,
                focus_paths=tuple(args.focus_path),
            )
        except ConfigError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1
        except ContextSearchError as e:
            _print_domain_error("Context error", e, json_output=args.json)
            return 1

        print(serialize_context_pack(pack) if args.json else format_context_pack(pack))
        return 0

    parser.print_help()
    return 1


def _print_proposals_table(summaries: Sequence[Any]) -> None:
    """Print the proposals in a left-aligned spaced table format."""
    header = ("ID", "STATUS", "UPDATED", "TITLE")

    id_width = max([len(header[0])] + [len(s.id) for s in summaries])
    status_width = max([len(header[1])] + [len(s.status.value) for s in summaries])
    updated_width = len(header[2])
    if summaries:
        updated_width = max(updated_width, max(len(s.updated_at) for s in summaries))

    def fmt(row: tuple[str, str, str, str]) -> str:
        return (
            f"{row[0]:<{id_width}}  {row[1]:<{status_width}}  {row[2]:<{updated_width}}  {row[3]}"
        )

    print(fmt(header))
    for s in summaries:
        print(fmt((s.id, s.status.value, s.updated_at, s.title)))


if __name__ == "__main__":
    raise SystemExit(main())
