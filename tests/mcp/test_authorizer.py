"""Tests for interactive TTY authorizer."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lifeos.mcp.authorizer import InteractiveTtyAuthorizer
from lifeos.facade.authorization import (
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
    AuthorizationDeniedError,
    AuthorizationUnavailableError,
)
from lifeos.proposals.loader import ProposalLoadResult, LoadedProposal
from lifeos.proposals.schema import ProposalMetadata, ProposalStatus, ProposalRisk
from lifeos.proposals.patches import PatchDocument

VALID_ID = "prop-20240101T000000Z-12345678"


def _make_meta() -> ProposalMetadata:
    return ProposalMetadata(
        id=VALID_ID,
        schema_version=1,
        patch_schema_version=1,
        lifecycle_schema_version=None,
        title="T",
        description="D",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.LOW,
        created_at="2026-07-13T00:00:00Z",
        created_by="system",
        submitted_at=None,
        submitted_by=None,
        review_digest=None,
        approved_at=None,
        approved_by=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        applied_at=None,
        applied_by=None,
        related_goals=[],
        related_sources=[],
        extensions={},
    )


def _make_proposal() -> LoadedProposal:
    return LoadedProposal(
        proposal_dir="/fake",
        proposal_path="/fake/proposal.md",
        patches_path="/fake/patches.json",
        proposal_source_hash="abcd",
        patches_source_hash="efgh",
        metadata=_make_meta(),
        patch_document=PatchDocument(schema_version=1, proposal_id=VALID_ID, operations=()),
        body="body",
    )


@pytest.fixture
def authorizer():
    return InteractiveTtyAuthorizer(vault_root=Path("/fake"), actor_id="test-actor")


def test_authorizer_validates_proposal_id_before_filesystem_access(authorizer) -> None:
    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id="invalid/id",
        review_digest=None,
    )
    with pytest.raises(
        AuthorizationUnavailableError, match="Proposal could not be loaded for authorization"
    ):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
def test_authorizer_rejects_loader_findings(mock_load, authorizer) -> None:
    mock_load.return_value = ProposalLoadResult(findings=["Finding 1"], proposal=None)
    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest=None,
    )
    with pytest.raises(
        AuthorizationUnavailableError, match="Proposal could not be loaded for authorization"
    ):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
@patch("builtins.open")
def test_authorizer_uses_metadata_body_and_patch_document_for_digest(
    mock_open, mock_load, authorizer
) -> None:
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_file.readline.return_value = "y\n"
    mock_open.return_value = mock_file

    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest=None,
    )
    res = authorizer.authorize(request)
    assert res.actor_id == "test-actor"


@patch("lifeos.mcp.authorizer.load_proposal_directory")
@patch("builtins.open")
def test_authorizer_raises_authorization_unavailable_error(
    mock_open, mock_load, authorizer
) -> None:
    mock_open.side_effect = OSError("No tty")

    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest=None,
    )
    with pytest.raises(
        AuthorizationUnavailableError, match="Interactive authorization is unavailable"
    ):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
@patch("builtins.open")
def test_authorizer_raises_authorization_denied_error(mock_open, mock_load, authorizer) -> None:
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_file.readline.return_value = "n\n"
    mock_open.return_value = mock_file

    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest=None,
    )
    with pytest.raises(
        AuthorizationDeniedError, match="Consequential operation was not authorized"
    ):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
def test_submit_authorization_requires_absent_digest(mock_load, authorizer) -> None:
    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest="some-digest",
    )
    with pytest.raises(AuthorizationDeniedError):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
def test_approve_authorization_requires_matching_digest(mock_load, authorizer) -> None:
    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.APPROVE,
        proposal_id=VALID_ID,
        review_digest="wrong-digest",
    )
    with pytest.raises(AuthorizationDeniedError):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
def test_apply_authorization_requires_matching_digest(mock_load, authorizer) -> None:
    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.APPLY,
        proposal_id=VALID_ID,
        review_digest="wrong-digest",
    )
    with pytest.raises(AuthorizationDeniedError):
        authorizer.authorize(request)


@patch("lifeos.mcp.authorizer.load_proposal_directory")
@patch("builtins.open")
def test_tty_authorizer_never_reads_protocol_stdin(mock_open, mock_load, authorizer) -> None:
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_file.readline.return_value = "y\n"
    mock_open.return_value = mock_file

    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest=None,
    )
    authorizer.authorize(request)
    mock_open.assert_called_once_with("/dev/tty", "r+", encoding="utf-8", buffering=1)
    mock_file.readline.assert_called_once()
    mock_file.write.assert_called()


@patch("lifeos.mcp.authorizer.load_proposal_directory")
@patch("builtins.open")
def test_tty_authorizer_writes_only_to_controlling_terminal(
    mock_open, mock_load, authorizer
) -> None:
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_file.readline.return_value = "y\n"
    mock_open.return_value = mock_file

    mock_load.return_value = ProposalLoadResult(findings=[], proposal=_make_proposal())

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=VALID_ID,
        review_digest=None,
    )
    authorizer.authorize(request)

    assert mock_file.write.call_count > 0


@patch("lifeos.mcp.authorizer.load_proposal_directory")
@patch("builtins.open")
@patch("lifeos.mcp.authorizer.compute_review_digest")
def test_tty_authorizer_renders_exact_patch_content(
    mock_digest, mock_open, mock_load, authorizer
) -> None:
    mock_digest.return_value = "fake-digest"
    mock_load.return_value.findings = []
    mock_load.return_value.proposal.metadata.title = "Test"
    mock_load.return_value.proposal.metadata.description = "Test"
    mock_load.return_value.proposal.body = "Body"
    from lifeos.proposals.patches import ReplaceManagedBlock

    mock_load.return_value.proposal.patch_document.operations = [
        ReplaceManagedBlock(
            id="op-1",
            target_path="some/file.md",
            base_hash="sha256:" + "a" * 64,
            block_name="my_block",
            new_content="exact candidate content",
        )
    ]

    mock_file = mock_open.return_value.__enter__.return_value
    mock_file.readline.return_value = "y\n"

    # mock_load.return_value.proposal can just be a mock, but compute_review_digest needs serializable metadata.
    # Actually, we can just mock compute_review_digest!

    request = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id="prop-20260714T000000Z-abcdef12",
        review_digest=None,
    )
    authorizer.authorize(request)

    written_content = ""
    for call in mock_open.return_value.__enter__.return_value.write.call_args_list:
        written_content += call.args[0]

    assert "Operation ID: op-1" in written_content
    assert "Type:         replace_managed_block" in written_content
    assert "Target Path:  some/file.md" in written_content
    assert "Block Name:   my_block" in written_content
    assert "Expected:     sha256:" + "a" * 64 in written_content
    assert "exact candidate content" in written_content
