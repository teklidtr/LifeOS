import argparse
import json
import logging
import sys
from pathlib import Path

from lifeos.config import load_config
from lifeos.facade.authorization import (
    ConsequentialAuthorizer,
    AuthorizedPrincipal,
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
    AuthorizationDeniedError,
)
from lifeos.mcp.server import create_mcp_server
from lifeos.registry import Registry


class RecordingAuthorizer(ConsequentialAuthorizer):
    def __init__(self, actor_id: str, log_path: Path, deny_actions: set[ConsequentialAction]):
        self.actor_id = actor_id
        self.log_path = log_path
        self.deny_actions = deny_actions

    def authorize(self, request: ConsequentialAuthorizationRequest) -> AuthorizedPrincipal:
        record = {
            "action": request.action.value,
            "proposal_id": request.proposal_id,
            "review_digest": request.review_digest,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        if request.action in self.deny_actions:
            raise AuthorizationDeniedError(
                f"Action {request.action.value} denied by test authorizer"
            )

        return AuthorizedPrincipal(actor_id=self.actor_id)


def main() -> None:
    # We must not write to stdout, because STDIO MCP transport uses it.
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--actor-id", type=str, required=True)
    parser.add_argument("--authorization-log", type=str, required=True)
    parser.add_argument("--deny-action", type=str, action="append", default=[])
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, filename="/tmp/mcp_server_stderr.txt", filemode="a")

    try:
        config = load_config(Path(args.config))
        registry = Registry(config.runtime_dir / "registry.db")

        deny_actions = {ConsequentialAction(a) for a in args.deny_action}

        authorizer = RecordingAuthorizer(
            actor_id=args.actor_id, log_path=Path(args.authorization_log), deny_actions=deny_actions
        )

        mcp = create_mcp_server(
            vault_root=config.vault_root,
            registry=registry,
            authorizer=authorizer,
            runtime_dir=config.runtime_dir,
        )
        mcp.run(transport="stdio")
    except Exception as e:
        import traceback

        with open("/tmp/mcp_server_stderr.txt", "a") as f:
            f.write(f"Exception: {e}\n")
            traceback.print_exc(file=f)
        sys.exit(1)


if __name__ == "__main__":
    main()
