from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
        apply_tool.return_value = MagicMock(
            proposal_id="prop-1",
            status="applied",
            changed_paths=(),
        )
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


def test_mcp_update_proposal_threads_configured_runtime_to_publication(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime_dir = vault / "runtime" / "node-a"
    authorizer = MagicMock()
    registry = MagicMock()
    refresh_result = MagicMock(
        new=(),
        modified=(),
        unchanged=(),
        deleted=(),
        renamed=(),
    )

    with (
        patch("lifeos.mcp.server.refresh_registry", return_value=refresh_result),
        patch("lifeos.mcp.server.update_wiki_section_proposal") as proposal_tool,
    ):
        proposal_tool.return_value = MagicMock(
            proposal_id="prop-runtime",
            proposal_path="proposals/prop-runtime/proposal.md",
            target_path="wiki/target.md",
            heading="Target",
            status="draft",
        )
        server = create_mcp_server(
            vault_root=vault,
            registry=registry,
            authorizer=authorizer,
            runtime_dir=runtime_dir,
        )
        server._tool_manager.get_tool("ingestion_update_wiki_section_proposal").fn(
            source_path="inbox/source.md",
            target_path="wiki/target.md",
            heading="Target",
            body="Replacement",
        )

    assert proposal_tool.call_args.kwargs["runtime_dir"] == runtime_dir


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


def test_apply_uses_custom_runtime_for_pinned_recovery_and_transaction_state(
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
    recovery_store = MagicMock()
    recovery_store.recovery_root = runtime_dir / "recovery"
    pinned_context = MagicMock()
    pinned_context.__enter__.return_value = recovery_store

    with (
        patch.object(
            proposal_application,
            "acquire_pinned_recovery_store",
            return_value=pinned_context,
        ) as acquire_store,
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
    acquire_store.assert_called_once_with(
        runtime_dir=runtime_dir,
        authority_root=vault,
    )
    recover.assert_called_once_with(
        vault_root=vault,
        runtime_dir=runtime_dir,
        recovery_store=recovery_store,
    )
    assert apply_locked.call_args.kwargs["runtime_dir"] == runtime_dir
    assert apply_locked.call_args.kwargs["recovery_store"] is recovery_store


def test_apply_rejects_vault_root_runtime_before_recovery(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    proposal = MagicMock()
    proposal.metadata.id = "prop-runtime-root"
    proposal.metadata.status = "approved"
    proposal.proposal_source_hash = "sha256:" + "0" * 64
    proposal.patch_document.operations = ()

    with (
        patch.object(proposal_application, "acquire_pinned_recovery_store") as acquire_store,
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

    acquire_store.assert_not_called()
    recover.assert_not_called()
    apply_locked.assert_not_called()


@pytest.mark.parametrize(
    "runtime_relative",
    ("proposals", "proposals/node-a", "system", "system/node-a"),
)
def test_apply_rejects_reserved_canonical_runtime_before_recovery(
    tmp_path: Path,
    runtime_relative: str,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    proposal = MagicMock()
    proposal.metadata.id = "prop-reserved-runtime"
    proposal.metadata.status = "approved"
    proposal.proposal_source_hash = "sha256:" + "0" * 64
    proposal.patch_document.operations = ()

    with (
        patch.object(proposal_application, "acquire_pinned_recovery_store") as acquire_store,
        patch.object(
            proposal_application,
            "_recover_interrupted_applications_locked",
        ) as recover,
        patch.object(proposal_application, "_apply_proposal_locked") as apply_locked,
    ):
        with pytest.raises(proposal_application.ApplicationError) as exc_info:
            proposal_application.apply_proposal(
                proposal,
                vault_root=vault,
                applied_by="desktop-user",
                applied_at="2026-08-25T10:00:00Z",
                identity_runtime_dir=vault / runtime_relative,
            )

    assert exc_info.value.code is proposal_application.ApplicationErrorCode.VALIDATION_ERROR
    acquire_store.assert_not_called()
    recover.assert_not_called()
    apply_locked.assert_not_called()
