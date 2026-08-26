"""Console entry point for first-party LifeOS setup and established commands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lifeos.bootstrap import BootstrapError, initialize_vault
from lifeos.cli import main as cli_main
from lifeos.config import ConfigError, load_config
from lifeos.registry import Registry


def _run_init(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="lifeos init",
        description="Create a new LifeOS vault without overwriting existing content.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Vault directory to create (default: current directory)",
    )
    args = parser.parse_args(argv)

    try:
        result = initialize_vault(args.path)
    except BootstrapError as error:
        print(f"Initialization error: {error}", file=sys.stderr)
        return 1

    if result.created:
        print(f"Initialized LifeOS vault at {result.vault_root}")
    else:
        print(f"LifeOS vault already initialized at {result.vault_root}; no files changed.")
    return 0


def _run_doctor(argv: Sequence[str]) -> int:
    from lifeos.doctor import collect_doctor, format_doctor_text, serialize_doctor_json
    from lifeos.status import serialize_error_json

    parser = argparse.ArgumentParser(
        prog="lifeos doctor",
        description="Check LifeOS installation and vault readiness without making repairs.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("lifeos.yml"),
        help="Path to lifeos.yml (default: lifeos.yml)",
    )
    parser.add_argument("--json", action="store_true", help="Output doctor result as JSON")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as error:
        if args.json:
            print(serialize_error_json("config-error", str(error)))
        else:
            print(f"Configuration error: {error}", file=sys.stderr)
        return 1

    result = collect_doctor(config, config_path=args.config)
    print(serialize_doctor_json(result) if args.json else format_doctor_text(result))
    return result.exit_code


def _run_scan(argv: Sequence[str]) -> int:
    """Refresh disposable registry state while preserving relocation evidence in output."""
    from lifeos.facade.errors import ToolExecutionError
    from lifeos.facade.registry_tools import refresh_registry

    parser = argparse.ArgumentParser(
        prog="lifeos scan",
        description="Refresh the disposable file and proposal registry.",
    )
    parser.add_argument(
        "--config",
        default=Path("lifeos.yml"),
        type=Path,
        help="Path to lifeos.yml (default: lifeos.yml)",
    )
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args(argv)

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
        return 0

    print(
        "Registry refreshed: "
        f"{len(result.new)} new, "
        f"{len(result.modified)} modified, "
        f"{len(result.unchanged)} unchanged, "
        f"{len(result.deleted)} deleted, "
        f"{len(result.renamed)} renamed; "
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


def _run_legacy_cli(arguments: list[str]) -> int:
    """Delegate established commands while keeping first-party setup commands discoverable."""
    try:
        return cli_main(arguments)
    except SystemExit as error:
        if arguments in (["--help"], ["-h"]) and error.code == 0:
            print(
                "\nsetup commands:\n"
                "  init [PATH]          Create a new LifeOS vault (default: current directory)\n"
                "  doctor [OPTIONS]     Check installation and vault readiness without repair"
            )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch first-party setup commands before delegating established CLI commands."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "init":
        return _run_init(arguments[1:])
    if arguments and arguments[0] == "doctor":
        return _run_doctor(arguments[1:])
    if arguments and arguments[0] == "scan":
        return _run_scan(arguments[1:])
    return _run_legacy_cli(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
