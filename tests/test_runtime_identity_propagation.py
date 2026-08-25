from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from lifeos.bridge.application import BridgeApplication
from lifeos.desktop.proposals import DesktopProposalService
from lifeos.facade.authorization import ConsequentialAction
from lifeos.facade.consequential_tools import ApplyProposalRequest
from lifeos.mcp.runtime_server import create_mcp_server


def test_mcp_apply_threads_custom_runtime_into_identity_preflight(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime_dir = vault / "runtime" / "node-a"
    authorizer = MagicMock()
    registry = MagicMock()

    with patch("lifeos.mcp.server.apply_proposal_tool") as apply_tool:
        apply_tool.return_value = MagicMock(proposal_id="prop-1", changed_paths=())
        server = create_mcp_server(
            vault_root=vault,
            registry=registry,
            authorizer=authorizer,
            runtime_dir=runtime_dir,
        )
        server._tool_manager.get_tool("proposal_apply").fn(proposal_id="prop-1")

    assert apply_tool.call_args.kwargs == {
        "vault_root": vault,
        "authorizer": authorizer,
        "request": ApplyProposalRequest(proposal_id="prop-1"),
        "identity_runtime_dir": runtime_dir,
    }


def test_desktop_apply_threads_custom_runtime_into_identity_preflight(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime_dir = vault / "runtime" / "node-a"
    service = DesktopProposalService(
        vault_root=vault,
        actor_id="desktop-user",
        identity_runtime_dir=runtime_dir,
    )
    token = service.authorizer.issue(
        action=ConsequentialAction.APPLY,
        proposal_id="prop-2",
        review_digest=None,
    )

    with (
        patch("lifeos.desktop.proposals.apply_proposal_tool") as apply_tool,
        patch("lifeos.desktop.proposals.asdict", return_value={}),
    ):
        service.execute(proposal_id="prop-2", action="apply", token=token)

    assert apply_tool.call_args.kwargs["identity_runtime_dir"] == runtime_dir


def test_desktop_accept_threads_custom_runtime_into_identity_preflight(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime_dir = vault / "runtime" / "node-a"
    service = DesktopProposalService(
        vault_root=vault,
        actor_id="desktop-user",
        identity_runtime_dir=runtime_dir,
    )
    token = service.authorizer.issue(
        action=ConsequentialAction.APPLY,
        proposal_id="prop-3",
        review_digest=None,
    )

    with (
        patch("lifeos.desktop.proposals.accept_proposal_tool") as accept_tool,
        patch("lifeos.desktop.proposals.asdict", return_value={}),
    ):
        service.execute(proposal_id="prop-3", action="accept", token=token)

    assert accept_tool.call_args.kwargs["identity_runtime_dir"] == runtime_dir


def test_bridge_threads_runtime_into_desktop_proposals(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime_dir = vault / "runtime" / "node-a"

    application = BridgeApplication(
        vault_root=vault,
        runtime_dir=runtime_dir,
        actor_id="desktop-user",
    )

    assert application.proposals.identity_runtime_dir == runtime_dir
