"""Tests for MCP server integration and error boundaries."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp.exceptions import ToolError

from lifeos.mcp.server import (
    LIFEOS_MCP_INSTRUCTIONS,
    EvolveWikiCreateMCPInput,
    EvolveWikiUpdateMCPInput,
    StudyFlashcardCreateMCPInput,
    create_mcp_server,
    _invoke_mcp_tool,
)
from lifeos.facade.errors import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolOwnershipConflictError,
    ToolUnavailableError,
    ToolValidationError,
)
from lifeos.facade.read_only import ReadMarkdownRequest, WikiSearchRequest, VaultContextRequest
from lifeos.facade.proposal_tools import (
    CompoundWikiProposalRequest,
    CreateWikiProposalRequest,
    EvolveWikiCreateRequest,
    EvolveWikiProposalRequest,
    EvolveWikiUpdateRequest,
    EvolveStudyLearningProposalRequest,
    StudyFlashcardCreateRequest,
    UpdateWikiSectionProposalRequest,
)
from lifeos.facade.registry_tools import RegistryRefreshResult


def test_server_registers_only_approved_tools(tmp_path: Path) -> None:
    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    expected_tools = {
        "registry_refresh",
        "vault_read_markdown",
        "vault_context",
        "wiki_search",
        "ingestion_evolve_wiki_proposal",
        "study_evolve_learning_proposal",
        "ingestion_create_wiki_proposal",
        "ingestion_create_wiki_and_update_section_proposal",
        "ingestion_update_wiki_section_proposal",
        "proposal_submit",
        "proposal_approve",
        "proposal_apply",
        "runtime_activity",
    }

    registered = {t.name for t in server._tool_manager.list_tools()}
    assert registered == expected_tools


def test_mcp_names_are_unique(tmp_path: Path) -> None:
    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )
    tools = list(server._tool_manager.list_tools())
    names = [t.name for t in tools]
    assert len(names) == len(set(names))


def test_server_advertises_safe_ingestion_workflow(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )

    assert server.instructions == LIFEOS_MCP_INSTRUCTIONS
    assert "Application AGENTS.md governs LifeOS development" in server.instructions
    assert "Use vault_context" in server.instructions
    assert "Folder location supplies context, not permission" in server.instructions
    assert "any registered canonical Markdown source" in server.instructions
    assert "wiki_search" in server.instructions
    assert "ingestion_evolve_wiki_proposal" in server.instructions
    assert "study_evolve_learning_proposal" in server.instructions
    assert "Do not generate flashcards from non-study sources by default" in server.instructions
    assert "create no proposal" in server.instructions
    assert "Stop after draft unless the user explicitly requests" in server.instructions
    assert "runtime_activity is read-only disposable diagnostics" in server.instructions


def test_tools_advertise_workflow_specific_descriptions(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert all(tool.description for tool in tools.values())
    assert "rebuildable registry data" in tools["registry_refresh"].description
    assert "before ingestion" in tools["vault_read_markdown"].description
    assert "restricted to wiki/" in tools["wiki_search"].description
    assert "explicit focus_paths" in tools["vault_context"].description
    assert "registered study/ source" in tools["study_evolve_learning_proposal"].description
    assert "routing/activity metadata" in tools["runtime_activity"].description
    assert "1..12 distinct" in tools["ingestion_evolve_wiki_proposal"].description
    assert "compatibility single-create tool" in tools["ingestion_create_wiki_proposal"].description
    assert (
        "both the registered source and existing target"
        in tools["ingestion_update_wiki_section_proposal"].description
    )
    assert (
        "base-hash-bound, ownership-aware draft"
        in tools["ingestion_update_wiki_section_proposal"].description
    )
    assert (
        "atomic two-operation draft"
        in tools["ingestion_create_wiki_and_update_section_proposal"].description
    )
    assert "explicitly requests" in tools["proposal_submit"].description
    assert "explicitly requests" in tools["proposal_approve"].description
    assert "changes canonical vault content" in tools["proposal_apply"].description


def test_tools_advertise_accurate_safety_annotations(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["vault_read_markdown"].annotations.model_dump() == {
        "title": "Read vault Markdown",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tools["registry_refresh"].annotations.model_dump() == {
        "title": "Refresh LifeOS registry",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tools["wiki_search"].annotations.readOnlyHint is True
    assert tools["vault_context"].annotations.readOnlyHint is True
    assert tools["study_evolve_learning_proposal"].annotations.destructiveHint is False
    assert tools["runtime_activity"].annotations.readOnlyHint is True
    assert tools["ingestion_evolve_wiki_proposal"].annotations.destructiveHint is False
    assert tools["ingestion_create_wiki_proposal"].annotations.destructiveHint is False
    assert tools["ingestion_create_wiki_proposal"].annotations.idempotentHint is False
    assert tools["ingestion_update_wiki_section_proposal"].annotations.destructiveHint is False
    assert tools["ingestion_update_wiki_section_proposal"].annotations.idempotentHint is False
    assert (
        tools["ingestion_create_wiki_and_update_section_proposal"].annotations.destructiveHint
        is False
    )
    assert (
        tools["ingestion_create_wiki_and_update_section_proposal"].annotations.idempotentHint
        is False
    )
    assert tools["proposal_submit"].annotations.destructiveHint is False
    assert tools["proposal_approve"].annotations.destructiveHint is False
    assert tools["proposal_apply"].annotations.destructiveHint is True
    assert all(tool.annotations.openWorldHint is False for tool in tools.values())


def test_tools_map_to_expected_facade_descriptors(tmp_path: Path) -> None:
    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    tool = server._tool_manager.get_tool("vault_read_markdown")
    assert "vault_path" in tool.parameters["properties"]


def test_update_ingestion_schema_exposes_only_bounded_fields(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("ingestion_update_wiki_section_proposal")

    assert set(tool.parameters["properties"]) == {
        "source_path",
        "target_path",
        "heading",
        "body",
        "tags",
        "tag_rationale",
    }
    assert tool.parameters["additionalProperties"] is False


def test_create_ingestion_schema_exposes_typed_and_legacy_routing_fields(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("ingestion_create_wiki_proposal")

    assert set(tool.parameters["properties"]) == {
        "source_path",
        "target_path",
        "title",
        "body",
        "page_kind",
        "slug",
        "tags",
        "tag_rationale",
    }
    assert tool.parameters["additionalProperties"] is False


def test_compound_ingestion_schema_exposes_only_bounded_fields(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("ingestion_create_wiki_and_update_section_proposal")

    assert set(tool.parameters["properties"]) == {
        "source_path",
        "create_target_path",
        "create_title",
        "create_body",
        "update_target_path",
        "update_heading",
        "update_body",
        "create_tags",
        "create_tag_rationale",
        "create_page_kind",
        "create_slug",
    }
    assert tool.parameters["additionalProperties"] is False


@patch("lifeos.mcp.server.refresh_registry")
def test_registry_refresh_delegates_to_facade(mock_facade: MagicMock, tmp_path: Path) -> None:
    mock_facade.return_value = RegistryRefreshResult(
        new=("study/new.md",),
        modified=(),
        unchanged=("wiki/old.md",),
        deleted=("study/old.md",),
        proposals_indexed=3,
    )
    registry = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=MagicMock()
    )

    result = server._tool_manager.get_tool("registry_refresh").fn()

    mock_facade.assert_called_once()
    kwargs = mock_facade.call_args.kwargs
    assert kwargs["vault_root"] == tmp_path / "vault"
    assert kwargs["registry"] is registry
    allow_path = kwargs["identity_allow_path"]
    assert callable(allow_path)
    assert allow_path("wiki/public.md") is True
    assert allow_path("private/hidden.md") is False
    assert allow_path("proposals/prop-1/proposal.md") is False
    assert result == {
        "new": ["study/new.md"],
        "modified": [],
        "unchanged": ["wiki/old.md"],
        "deleted": ["study/old.md"],
        "proposals_indexed": 3,
    }


@patch("lifeos.mcp.server.read_markdown")
def test_read_markdown_delegates_to_facade(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        vault_path="test.md",
        markdown_body="# test",
        source_tags=("tag",),
        source_topics=("topic",),
    )

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    tool = server._tool_manager.get_tool("vault_read_markdown")
    res = tool.fn(vault_path="test.md")

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault", request=ReadMarkdownRequest(vault_path="test.md")
    )
    assert res == {
        "vault_path": "test.md",
        "markdown_body": "# test",
        "source_tags": ["tag"],
        "source_topics": ["topic"],
    }


@patch("lifeos.mcp.server.search_wiki")
def test_wiki_search_delegates_to_scoped_facade(mock_facade: MagicMock, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        query="retrieval",
        hits=(
            MagicMock(
                path="wiki/learning.md",
                title="Learning",
                description="Durable learning notes",
                excerpt="retrieval practice",
                score=12,
            ),
        ),
    )
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )

    result = server._tool_manager.get_tool("wiki_search").fn(query="retrieval", limit=5)

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault", request=WikiSearchRequest(query="retrieval", limit=5)
    )
    assert result["hits"][0]["path"] == "wiki/learning.md"


@patch("lifeos.mcp.server.get_vault_context")
def test_vault_context_delegates_and_records_routing_metadata(
    mock_facade: MagicMock, tmp_path: Path
) -> None:
    instruction = MagicMock(
        id="driving-exam",
        text="Prioritize exam distinctions.",
        authority="system",
        scope="path",
        priority=100,
        applicable_sources=("study/driving.md",),
        applicability=("path:study/driving.md",),
    )
    source = MagicMock(
        path="study/driving.md",
        title="Driving",
        description="Exam notes",
        excerpt="right of way",
        score=0,
    )
    mock_facade.return_value = MagicMock(
        question="What matters?",
        instructions=(instruction,),
        sources=(source,),
        evidence_gaps=(),
        omissions=(),
        diagnostics=(),
    )
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )

    result = server._tool_manager.get_tool("vault_context").fn(
        question="What matters?", focus_paths=["study/driving.md"], limit=6
    )

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        request=VaultContextRequest(
            question="What matters?", focus_paths=("study/driving.md",), limit=6
        ),
    )
    assert result["instructions"][0]["id"] == "driving-exam"
    assert result["sources"][0]["path"] == "study/driving.md"
    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=5)
    assert activity["records"][-1]["tool"] == "vault_context"
    assert activity["records"][-1]["focus_paths"] == ["study/driving.md"]
    assert activity["records"][-1]["instruction_ids"] == ["driving-exam"]


@patch("lifeos.mcp.server.evolve_wiki_proposal")
def test_evolve_wiki_proposal_delegates_to_facade(mock_facade: MagicMock, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop1",
        proposal_path="proposals/prop1",
        target_paths=("wiki/learning/retrieval.md", "wiki/learning.md"),
        operation_count=2,
    )
    registry = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=MagicMock()
    )

    result = server._tool_manager.get_tool("ingestion_evolve_wiki_proposal").fn(
        source_path="raw/source.md",
        creates=[
            EvolveWikiCreateMCPInput(
                target_path="wiki/learning/retrieval.md",
                title="Retrieval",
                body="Body",
                rationale="Durable reusable concept.",
            )
        ],
        updates=[
            EvolveWikiUpdateMCPInput(
                target_path="wiki/learning.md",
                heading="Retrieval",
                body="See [[learning/retrieval]].",
                rationale="Reuse the existing hub.",
            )
        ],
    )

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        registry=registry,
        request=EvolveWikiProposalRequest(
            source_path="raw/source.md",
            creates=(
                EvolveWikiCreateRequest(
                    target_path="wiki/learning/retrieval.md",
                    title="Retrieval",
                    body="Body",
                    rationale="Durable reusable concept.",
                ),
            ),
            updates=(
                EvolveWikiUpdateRequest(
                    target_path="wiki/learning.md",
                    heading="Retrieval",
                    body="See [[learning/retrieval]].",
                    rationale="Reuse the existing hub.",
                ),
            ),
        ),
        runtime_dir=tmp_path / "vault" / ".lifeos",
    )
    assert result == {
        "proposal_id": "prop1",
        "proposal_path": "proposals/prop1",
        "target_paths": ["wiki/learning/retrieval.md", "wiki/learning.md"],
        "operation_count": 2,
        "status": "draft",
    }


@patch("lifeos.mcp.server.evolve_study_learning_proposal")
def test_study_learning_proposal_delegates_to_facade(
    mock_facade: MagicMock, tmp_path: Path
) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop-study",
        proposal_path="proposals/prop-study",
        target_paths=("wiki/traffic.md", "flashcards/driving/right-of-way.md"),
        operation_count=2,
    )
    registry = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=MagicMock()
    )
    result = server._tool_manager.get_tool("study_evolve_learning_proposal").fn(
        source_path="study/driving.md",
        wiki_creates=[
            EvolveWikiCreateMCPInput(
                target_path="wiki/traffic.md",
                title="Traffic",
                body="Body",
                rationale="Reusable durable knowledge.",
            )
        ],
        flashcards=[
            StudyFlashcardCreateMCPInput(
                target_path="flashcards/driving/right-of-way.md",
                card_id="right-of-way",
                topic="Driving",
                question="Who has priority?",
                answer="Apply the relevant right-of-way rule.",
                rationale="Exam-relevant and easy to confuse.",
                learning_context="Turkish driving licence exam",
                knowledge_refs=["wiki/traffic.md"],
                estimated_seconds=30,
            )
        ],
    )

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        registry=registry,
        request=EvolveStudyLearningProposalRequest(
            source_path="study/driving.md",
            wiki_creates=(
                EvolveWikiCreateRequest(
                    target_path="wiki/traffic.md",
                    title="Traffic",
                    body="Body",
                    rationale="Reusable durable knowledge.",
                ),
            ),
            flashcards=(
                StudyFlashcardCreateRequest(
                    target_path="flashcards/driving/right-of-way.md",
                    card_id="right-of-way",
                    topic="Driving",
                    question="Who has priority?",
                    answer="Apply the relevant right-of-way rule.",
                    rationale="Exam-relevant and easy to confuse.",
                    learning_context="Turkish driving licence exam",
                    knowledge_refs=("wiki/traffic.md",),
                    estimated_seconds=30,
                ),
            ),
        ),
        runtime_dir=tmp_path / "vault" / ".lifeos",
    )
    assert result == {
        "proposal_id": "prop-study",
        "proposal_path": "proposals/prop-study",
        "target_paths": ["wiki/traffic.md", "flashcards/driving/right-of-way.md"],
        "operation_count": 2,
        "status": "draft",
    }


@patch("lifeos.mcp.server.create_wiki_proposal")
def test_create_wiki_proposal_delegates_to_facade(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop1", proposal_path="prop/path", target_path="target/path"
    )

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    tool = server._tool_manager.get_tool("ingestion_create_wiki_proposal")
    res = tool.fn(source_path="s", target_path="wiki/t.md", title="title", body="b")

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        registry=registry,
        request=CreateWikiProposalRequest(
            source_path="s",
            target_path="wiki/t.md",
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


@patch("lifeos.mcp.server.create_wiki_proposal")
def test_create_wiki_proposal_accepts_typed_routing(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop1",
        proposal_path="prop/path",
        target_path="wiki/concepts/active-recall.md",
    )
    registry = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=MagicMock()
    )

    result = server._tool_manager.get_tool("ingestion_create_wiki_proposal").fn(
        source_path="study/source.md",
        title="Active Recall",
        body="Durable concept note.",
        page_kind="concept",
        slug="active-recall",
    )

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        registry=registry,
        request=CreateWikiProposalRequest(
            source_path="study/source.md",
            target_path=None,
            title="Active Recall",
            body="Durable concept note.",
            page_kind="concept",
            slug="active-recall",
        ),
    )
    assert result["target_path"] == "wiki/concepts/active-recall.md"


@patch("lifeos.mcp.server.update_wiki_section_proposal")
def test_update_wiki_section_proposal_delegates_to_facade(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop1",
        proposal_path="prop/path",
        target_path="wiki/target.md",
        heading="Selected",
    )
    registry = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=MagicMock()
    )

    result = server._tool_manager.get_tool("ingestion_update_wiki_section_proposal").fn(
        source_path="study/source.md",
        target_path="wiki/target.md",
        heading="Selected",
        body="Replacement",
    )

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        registry=registry,
        request=UpdateWikiSectionProposalRequest(
            source_path="study/source.md",
            target_path="wiki/target.md",
            heading="Selected",
            body="Replacement",
        ),
        runtime_dir=tmp_path / "vault" / ".lifeos",
    )
    assert result == {
        "proposal_id": "prop1",
        "proposal_path": "prop/path",
        "target_path": "wiki/target.md",
        "heading": "Selected",
        "status": "draft",
    }


@patch("lifeos.mcp.server.create_wiki_and_update_section_proposal")
def test_compound_wiki_proposal_delegates_to_facade(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(
        proposal_id="prop1",
        proposal_path="proposals/prop1",
        create_target_path="wiki/detail.md",
        update_target_path="wiki/summary.md",
        heading="Equipment notes",
    )
    registry = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=MagicMock()
    )

    result = server._tool_manager.get_tool("ingestion_create_wiki_and_update_section_proposal").fn(
        source_path="study/source.md",
        create_target_path="wiki/detail.md",
        create_title="Detail",
        create_body="Detailed body",
        update_target_path="wiki/summary.md",
        update_heading="Equipment notes",
        update_body="See [[detail]].",
    )

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        registry=registry,
        request=CompoundWikiProposalRequest(
            source_path="study/source.md",
            create_target_path="wiki/detail.md",
            create_title="Detail",
            create_body="Detailed body",
            update_target_path="wiki/summary.md",
            update_heading="Equipment notes",
            update_body="See [[detail]].",
        ),
        runtime_dir=tmp_path / "vault" / ".lifeos",
    )
    assert result == {
        "proposal_id": "prop1",
        "proposal_path": "proposals/prop1",
        "create_target_path": "wiki/detail.md",
        "update_target_path": "wiki/summary.md",
        "heading": "Equipment notes",
        "status": "draft",
    }


@patch("lifeos.mcp.server.submit_proposal_tool")
def test_submit_passes_trusted_authorizer(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(proposal_id="prop1", review_digest="dig")

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    tool = server._tool_manager.get_tool("proposal_submit")
    res = tool.fn(proposal_id="prop1")

    from lifeos.facade.consequential_tools import SubmitProposalRequest

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        authorizer=authorizer,
        request=SubmitProposalRequest(proposal_id="prop1"),
    )
    assert res == {"proposal_id": "prop1", "status": "pending", "review_digest": "dig"}


@patch("lifeos.mcp.server.approve_proposal_tool")
def test_approve_passes_trusted_authorizer(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(proposal_id="prop1", review_digest="dig")

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    tool = server._tool_manager.get_tool("proposal_approve")
    res = tool.fn(proposal_id="prop1")

    from lifeos.facade.consequential_tools import ApproveProposalRequest

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        authorizer=authorizer,
        request=ApproveProposalRequest(proposal_id="prop1"),
    )
    assert res == {"proposal_id": "prop1", "status": "approved", "review_digest": "dig"}


@patch("lifeos.mcp.server.apply_proposal_tool")
def test_apply_passes_trusted_authorizer(mock_facade, tmp_path: Path) -> None:
    mock_facade.return_value = MagicMock(proposal_id="prop1", changed_paths=["a.md"])

    registry = MagicMock()
    authorizer = MagicMock()
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=registry, authorizer=authorizer
    )

    tool = server._tool_manager.get_tool("proposal_apply")
    res = tool.fn(proposal_id="prop1")

    from lifeos.facade.consequential_tools import ApplyProposalRequest

    mock_facade.assert_called_once_with(
        vault_root=tmp_path / "vault",
        authorizer=authorizer,
        request=ApplyProposalRequest(proposal_id="prop1"),
    )
    assert res == {"proposal_id": "prop1", "status": "applied", "changed_paths": ["a.md"]}


def test_agent_cannot_supply_actor_or_digest(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
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


def test_ownership_conflict_returns_bounded_remediation() -> None:
    message = (
        "Wiki target is missing but retains generated ownership; restore the file "
        "or release ownership before creating it again"
    )

    def failing_op() -> None:
        raise ToolOwnershipConflictError(message)

    with pytest.raises(ToolError) as exc_info:
        _invoke_mcp_tool(failing_op)

    assert str(exc_info.value) == message


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
    # Ensure they are returning TypedDicts instead of plain dicts. Registry renames are an
    # additive optional extension so existing no-rename payloads keep their historical shape.
    from lifeos.mcp.models import ReadMarkdownMCPResult, RegistryRefreshMCPResult

    assert ReadMarkdownMCPResult.__annotations__ == {
        "vault_path": str,
        "markdown_body": str,
        "source_tags": list[str],
        "source_topics": list[str],
    }
    annotations = RegistryRefreshMCPResult.__annotations__
    required = {
        "new": list[str],
        "modified": list[str],
        "unchanged": list[str],
        "deleted": list[str],
        "proposals_indexed": int,
    }
    assert {key: annotations[key] for key in required} == required
    assert set(RegistryRefreshMCPResult.__required_keys__) == set(required)
    assert RegistryRefreshMCPResult.__optional_keys__ == frozenset({"renamed"})


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
    tmp_path: Path,
) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
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


def test_evolve_ingestion_schema_exposes_bounded_mutation_lists(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("ingestion_evolve_wiki_proposal")
    assert set(tool.parameters["properties"]) == {"source_path", "creates", "updates"}
    assert tool.parameters["additionalProperties"] is False


def test_wiki_search_schema_is_read_only_and_bounded(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("wiki_search")
    assert set(tool.parameters["properties"]) == {"query", "limit"}
    assert tool.annotations.readOnlyHint is True


def test_vault_context_schema_is_read_only_and_bounded(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("vault_context")
    assert set(tool.parameters["properties"]) == {"question", "focus_paths", "limit"}
    assert tool.annotations.readOnlyHint is True
    assert tool.parameters["additionalProperties"] is False


def test_study_learning_schema_exposes_only_bounded_mutation_lists(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("study_evolve_learning_proposal")
    assert set(tool.parameters["properties"]) == {
        "source_path",
        "wiki_creates",
        "wiki_updates",
        "flashcards",
    }
    assert tool.annotations.destructiveHint is False
    assert tool.parameters["additionalProperties"] is False


def test_runtime_activity_schema_is_read_only(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault", registry=MagicMock(), authorizer=MagicMock()
    )
    tool = server._tool_manager.get_tool("runtime_activity")
    assert set(tool.parameters["properties"]) == {"limit"}
    assert tool.annotations.readOnlyHint is True
    assert tool.parameters["additionalProperties"] is False
