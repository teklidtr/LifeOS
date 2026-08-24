"""Entrypoint for the LifeOS MCP server."""

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Any
from pathlib import Path

from lifeos.config import ConfigError, load_config
from lifeos.mcp.authorizer import InteractiveTtyAuthorizer
from lifeos.registry import Registry


class MCPDependencyUnavailableError(Exception):
    pass


def _load_server_factory() -> Callable[..., Any]:
    try:
        from lifeos.mcp.runtime_server import create_mcp_server
    except ModuleNotFoundError as error:
        if error.name == "mcp":
            raise MCPDependencyUnavailableError from error
        raise

    return create_mcp_server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lifeos-mcp", description="LifeOS MCP Server")
    parser.add_argument("--config", default="lifeos.yml", type=Path, help="Path to lifeos.yml")
    parser.add_argument(
        "--actor-id",
        required=True,
        help="Trusted actor identity for consequential operations",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    registry = Registry(config.runtime_dir / "registry.db")
    authorizer = InteractiveTtyAuthorizer(vault_root=config.vault_root, actor_id=args.actor_id)

    try:
        create_mcp_server = _load_server_factory()
    except MCPDependencyUnavailableError:
        print("The MCP adapter requires the optional 'mcp' dependency group.", file=sys.stderr)
        return 1

    mcp = create_mcp_server(
        vault_root=config.vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=config.runtime_dir,
    )

    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
