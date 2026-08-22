"""Tests for MCP server integration and error boundaries."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp.exceptions import ToolError

from lifeos.mcp.server import LIFEOS_MCP_INSTRUCTIONS, create_mcp_server, _invoke_mcp_tool
from lifeos.facade.errors import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolUnavailableError,
    ToolValidationError,
)
from lifeos.facade.read_only import ReadMarkdownRequest
from lifeos.facade.proposal_tools import CreateWikiProposalRequest


def test_server_registers_only_approved_tools() -> None:
    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    expected_tools = {
        "vault_read_markdown",
        "ingestion_create_wiki_proposal",
        "proposal_submit",
        "proposal_approve",
        "proposal_apply",
    }

    registered = {t.name for t in server._tool_manager.list_tools()}
    assert registered == expected_tools


def test_mcp_names_are_unique() -> None:
    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)
    tools = list(server._tool_manager.list_tools())
    names = [t.name for t in tools]
    assert len(names) == len(set(names))


def test_server_advertises_safe_ingestion_workflow() -> None:
    server = create_mcp_server(
        vault_root=Path("/fake"), registry=MagicMock(), authorizer=MagicMock()
    )

    assert server.instructions == LIFEOS_MCP_INSTRUCTIONS
    assert "first call vault_read_markdown" in server.instructions
    assert "then call ingestion_create_wiki_proposal" in server.instructions
    assert "Stop after the draft proposal" in server.instructions
    assert "Never call proposal_submit, proposal_approve, or proposal_apply" in server.instructions


def test_tools_advertise_workflow_specific_descriptions() -> None:
    server = create_mcp_server(
        vault_root=Path("/fake"), registry=MagicMock(), authorizer=MagicMock()
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert all(tool.description for tool in tools.values())
    assert "before ingestion" in tools["vault_read_markdown"].description
    assert "after vault_read_markdown" in tools["ingestion_create_wiki_proposal"].description
    assert "creates a draft" in tools["ingestion_create_wiki_proposal"].description
    assert "explicitly requests" in tools["proposal_submit"].description
    assert "explicitly requests" in tools["proposal_approve"].description
    assert "changes canonical vault content" in tools["proposal_apply"].description


def test_tools_advertise_accurate_safety_annotations() -> None:
    server = create_mcp_server(
        vault_root=Path("/fake"), registry=MagicMock(), authorizer=MagicMock()
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["vault_read_markdown"].annotations.model_dump() == {
        "title": "Read vault Markdown",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tools["ingestion_create_wiki_proposal"].annotations.destructiveHint is False
    assert tools["ingestion_create_wiki_proposal"].annotations.idempotentHint is False
    assert tools["proposal_submit"].annotations.destructiveHint is False
    assert tools["proposal_approve"].annotations.destructiveHint is False
    assert tools["proposal_apply"].annotations.destructiveHint is True
    assert all(tool.annotations.openWorldHint is False for tool in tools.values())


def test_tools_map_to_expected_facade_descriptors() -> None:
    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    tool = server._tool_manager.get_tool("vault_read_markdown")
    assert "vault_path" in tool.parameters["properties"]


@patch("lifeos.mcp.server.read_markdown")
def test_read_markdown_delegates_to_facade(mock_facade) -> None:
    mock_facade.return_value = MagicMock(vault_path="test.md", markdown_body="# test")

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    tool = server._tool_manager.get_tool("vault_read_markdown")
    res = tool.fn(vault_path="test.md")

    mock_facade.assert_called_once_with(
        vault_root=Path("/fake"), request=ReadMarkdownRequest(vault_path="test.md")
    )
    assert res == {"vault_path": "test.md", "markdown_body": "# test"}


@patch("lifeos.mcp.server.create_wiki_proposal")
def test_create_wiki_proposal_delegates_to_facade(mock_facade) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop1", proposal_path="prop/path", target_path="target/path"
    )

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    tool = server._tool_manager.get_tool("ingestion_create_wiki_proposal")
    res = tool.fn(source_path="s", target_path="t", title="title", body="b")

    mock_facade.assert_called_once_with(
        vault_root=Path("/fake"),
        registry=registry,
        request=CreateWikiProposalRequest(
            source_path="s",
            target_path="t",
            title="title",
            body="b",
        ),
    )
    assert res == {
        "proposal_id": "prop1",
        "proposal_path": "prop/path",
        "target_path": "target/path",
        "status": "draft",
    }


@patch("lifeos.mcp.server.submit_proposal_tool")
def test_submit_passes_trusted_authorizer(mock_facade) -> None:
    mock_facade.return_value = MagicMock(proposal_id="prop1", review_digest="dig")

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    tool = server._tool_manager.get_tool("proposal_submit")
    res = tool.fn(proposal_id="prop1")

    from lifeos.facade.consequential_tools import SubmitProposalRequest

    mock_facade.assert_called_once_with(
        vault_root=Path("/fake"),
        authorizer=authorizer,
        request=SubmitProposalRequest(proposal_id="prop1"),
    )
    assert res == {"proposal_id": "prop1", "status": "pending", "review_digest": "dig"}


@patch("lifeos.mcp.server.approve_proposal_tool")
def test_approve_passes_trusted_authorizer(mock_facade) -> None:
    mock_facade.return_value = MagicMock(proposal_id="prop1", review_digest="dig")

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    tool = server._tool_manager.get_tool("proposal_approve")
    res = tool.fn(proposal_id="prop1")

    from lifeos.facade.consequential_tools import ApproveProposalRequest

    mock_facade.assert_called_once_with(
        vault_root=Path("/fake"),
        authorizer=authorizer,
        request=ApproveProposalRequest(proposal_id="prop1"),
    )
    assert res == {"proposal_id": "prop1", "status": "approved", "review_digest": "dig"}


@patch("lifeos.mcp.server.apply_proposal_tool")
def test_apply_passes_trusted_authorizer(mock_facade) -> None:
    mock_facade.return_value = MagicMock(proposal_id="prop1", changed_paths=["a.md"])

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(vault_root=Path("/fake"), registry=registry, authorizer=authorizer)

    tool = server._tool_manager.get_tool("proposal_apply")
    res = tool.fn(proposal_id="prop1")

    from lifeos.facade.consequential_tools import ApplyProposalRequest

    mock_facade.assert_called_once_with(
        vault_root=Path("/fake"),
        authorizer=authorizer,
        request=ApplyProposalRequest(proposal_id="prop1"),
    )
    assert res == {"proposal_id": "prop1", "status": "applied", "changed_paths": ["a.md"]}


def test_agent_cannot_supply_actor_or_digest() -> None:
    server = create_mcp_server(
        vault_root=Path("/fake"), registry=MagicMock(), authorizer=MagicMock()
    )
    submit = server._tool_manager.get_tool("proposal_submit")
    assert "actor_id" not in submit.parameters["properties"]
    assert "review_digest" not in submit.parameters["properties"]


@pytest.mark.parametrize(
    "exception, expected_msg",
    [
        (ToolValidationError("err"), "Invalid LifeOS tool arguments"),
        (ToolNotFoundError("err"), "Requested LifeOS object was not found"),
        (ToolConflictError("err"), "LifeOS operation conflicts with the current state"),
        (ToolAuthorizationError("err"), "Consequential operation was not authorized"),
        (ToolUnavailableError("err"), "Required LifeOS service is unavailable"),
        (ToolExecutionError("err"), "LifeOS operation failed: err"),
    ],
)
def test_expected_facade_error_raises_sanitized_tool_error(exception, expected_msg) -> None:
    def failing_op():
        raise exception

    with pytest.raises(ToolError) as exc_info:
        _invoke_mcp_tool(failing_op)

    assert str(exc_info.value) == expected_msg


def test_unexpected_error_is_logged_and_sanitized(caplog) -> None:
    def failing_op():
        raise ValueError("Secret absolute path /root/secret")

    with pytest.raises(ToolError) as exc_info:
        _invoke_mcp_tool(failing_op)

    assert str(exc_info.value) == "Internal LifeOS error"
    assert "Unexpected MCP tool failure" in caplog.text


def test_raw_exception_message_is_not_returned() -> None:
    def failing_op():
        raise ToolValidationError("DO NOT LEAK THIS")

    with pytest.raises(ToolError) as exc_info:
        _invoke_mcp_tool(failing_op)

    assert "DO NOT LEAK THIS" not in str(exc_info.value)


def test_error_payload_does_not_leak_absolute_paths(caplog) -> None:
    def failing_op():
        raise ToolNotFoundError("/root/absolute/path")

    with pytest.raises(ToolError) as exc_info:
        _invoke_mcp_tool(failing_op)

    assert "/root/absolute/path" not in str(exc_info.value)


def test_mcp_outputs_have_explicit_structured_schemas() -> None:
    # Ensure they are returning TypedDicts instead of plain dicts
    from lifeos.mcp.models import ReadMarkdownMCPResult

    assert ReadMarkdownMCPResult.__annotations__ == {"vault_path": str, "markdown_body": str}


def test_mcp_apply_returns_sanitized_recovery_required_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lifeos.proposals.application as application_module
    from lifeos.facade.authorization import AuthorizedPrincipal
    from lifeos.proposals.application import apply_proposal
    from tests.proposals.test_recovery_orchestration import (
        _InjectedInterruption,
        _interrupt_at,
        _load_two_target_application,
    )

    from dataclasses import replace
    from lifeos.proposals.lifecycle import compute_review_digest, serialize_proposal_markdown
    from lifeos.proposals.loader import load_proposal_directory

    _, vault_root, proposal = _load_two_target_application(tmp_path)
    digest = compute_review_digest(proposal.metadata, proposal.body, proposal.patch_document)
    proposal_dir = vault_root / "proposals" / proposal.proposal_dir
    proposal_path = proposal_dir / "proposal.md"
    proposal_path.write_bytes(
        serialize_proposal_markdown(replace(proposal.metadata, review_digest=digest), proposal.body)
    )
    reloaded = load_proposal_directory(proposal_dir, proposals_root=vault_root / "proposals")
    assert reloaded.proposal is not None
    proposal = reloaded.proposal

    _interrupt_at(monkeypatch, "after_target_install:0")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    (vault_root / "test1.txt").write_bytes(b"manual mutation")
    monkeypatch.setattr(application_module, "_application_checkpoint", lambda _name: None)

    authorizer = MagicMock()
    authorizer.authorize.return_value = AuthorizedPrincipal("admin")
    server = create_mcp_server(
        vault_root=vault_root,
        registry=MagicMock(),
        authorizer=authorizer,
    )
    tool = server._tool_manager.get_tool("proposal_apply")

    with pytest.raises(ToolError) as error_info:
        tool.fn(proposal_id=proposal.metadata.id)

    assert str(error_info.value) == (
        "LifeOS recovery is required before proposal application can continue"
    )
    assert "manual mutation" not in str(error_info.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "extra_field"),
    [
        ("proposal_submit", "review_digest"),
        ("proposal_approve", "actor_id"),
        ("proposal_apply", "approved_by"),
    ],
)
async def test_consequential_tools_reject_extra_agent_fields(
    tool_name: str,
    extra_field: str,
) -> None:
    server = create_mcp_server(
        vault_root=Path("/fake"),
        registry=MagicMock(),
        authorizer=MagicMock(),
    )
    tool = server._tool_manager.get_tool(tool_name)

    assert tool.parameters["properties"] == {
        "proposal_id": {"title": "Proposal Id", "type": "string"}
    }
    assert tool.parameters["additionalProperties"] is False

    with pytest.raises(ToolError, match="Extra inputs are not permitted"):
        await server._tool_manager.call_tool(
            tool_name,
            {
                "proposal_id": "prop-20260714T120000Z-1234abcd",
                extra_field: "agent-controlled",
            },
        )
