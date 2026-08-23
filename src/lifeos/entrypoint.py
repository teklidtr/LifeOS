"""Console entry point for LifeOS, including first-party vault initialization."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from lifeos.bootstrap import BootstrapError, initialize_vault
from lifeos.cli import main as cli_main


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


def _run_legacy_cli(arguments: list[str]) -> int:
    """Delegate established commands while keeping the new bootstrap discoverable."""
    try:
        return cli_main(arguments)
    except SystemExit as error:
        if arguments in (["--help"], ["-h"]) and error.code == 0:
            print(
                "\nbootstrap command:\n"
                "  init [PATH]          Create a new LifeOS vault (default: current directory)"
            )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch first-party bootstrap before delegating established CLI commands."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "init":
        return _run_init(arguments[1:])
    return _run_legacy_cli(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
