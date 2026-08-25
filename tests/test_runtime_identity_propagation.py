from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from lifeos.bridge.application import BridgeApplication
from lifeos.desktop.proposals import DesktopProposalService
from lifeos.facade.authorization import ConsequentialAction
from lifeos.facade.consequential_tools import ApplyProposalRequest
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.proposals import application as proposal_application


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


def test_apply_uses_custom_runtime_for_lock_recovery_and_transaction_state(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime_dir = tmp_path / "node-runtime"
    proposal = MagicMock()
    proposal.metadata.id = "prop-runtime"
    proposal.metadata.status = "approved"
    proposal.proposal_source_hash = "sha256:" + "0" * 64
    proposal.patch_document.operations = ()
    expected = MagicMock()
    recovery_lock = MagicMock()

    with (
        patch.object(
            proposal_application,
            "acquire_recovery_lock",
            return_value=recovery_lock,
        ) as acquire_lock,
        patch.object(
            proposal_application,
            "_recover_interrupted_applications_locked",
        ) as recover,
        patch.object(
            proposal_application,
            "_apply_proposal_locked",
            return_value=expected,
        ) as apply_locked,
    ):
        result = proposal_application.apply_proposal(
            proposal,
            vault_root=vault,
            applied_by="desktop-user",
            applied_at="2026-08-25T10:00:00Z",
            identity_runtime_dir=runtime_dir,
        )

    assert result is expected
    acquire_lock.assert_called_once_with(runtime_dir=runtime_dir)
    recover.assert_called_once_with(vault_root=vault, runtime_dir=runtime_dir)
    assert apply_locked.call_args.kwargs["runtime_dir"] == runtime_dir
    assert apply_locked.call_args.kwargs["recovery_root"] == runtime_dir / "recovery"


def test_apply_rejects_vault_root_runtime_before_recovery(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    proposal = MagicMock()
    proposal.metadata.id = "prop-runtime-root"
    proposal.metadata.status = "approved"
    proposal.proposal_source_hash = "sha256:" + "0" * 64
    proposal.patch_document.operations = ()

    with (
        patch.object(proposal_application, "acquire_recovery_lock") as acquire_lock,
        patch.object(
            proposal_application,
            "_recover_interrupted_applications_locked",
        ) as recover,
        patch.object(proposal_application, "_apply_proposal_locked") as apply_locked,
    ):
        try:
            proposal_application.apply_proposal(
                proposal,
                vault_root=vault,
                applied_by="desktop-user",
                applied_at="2026-08-25T10:00:00Z",
                identity_runtime_dir=vault,
            )
        except proposal_application.ApplicationError as error:
            assert error.code is proposal_application.ApplicationErrorCode.VALIDATION_ERROR
        else:
            raise AssertionError("vault-root runtime must be rejected")

    acquire_lock.assert_not_called()
    recover.assert_not_called()
    apply_locked.assert_not_called()
