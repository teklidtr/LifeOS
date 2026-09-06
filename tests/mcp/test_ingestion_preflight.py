from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from lifeos.bootstrap import initialize_vault
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.registry_tools import RegistryRefreshResult
from lifeos.markdown.parser import parse_markdown_note
from lifeos.mcp.server import (
    EvolveWikiCreateMCPInput,
    StudyFlashcardCreateMCPInput,
    create_mcp_server,
)
from lifeos.proposals.loader import load_proposal_directory
from lifeos.registry import Registry
from lifeos.registry.file_tracking import hash_file_content


def _empty_refresh() -> RegistryRefreshResult:
    return RegistryRefreshResult(
        new=(),
        modified=(),
        unchanged=(),
        deleted=(),
        proposals_indexed=0,
    )


def _real_server(tmp_path: Path):
    vault_root = tmp_path / "vault"
    initialize_vault(vault_root)
    runtime_dir = vault_root / ".lifeos"
    runtime_dir.mkdir()
    registry = Registry(runtime_dir / "registry.db")
    server = create_mcp_server(
        vault_root=vault_root,
        registry=registry,
        authorizer=MagicMock(),
        runtime_dir=runtime_dir,
    )
    return vault_root, registry, server


def _proposal_source_hash(vault_root: Path, proposal_path: str) -> str:
    loaded = load_proposal_directory(
        vault_root / proposal_path,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    operation = loaded.patch_document.operations[0]
    assert operation.op == "create_generated_file"
    parsed = parse_markdown_note(Path(operation.target_path), content=operation.new_content)
    provenance = parsed.frontmatter["lifeos_provenance"]
    return provenance["sources"][0]["content_hash"]


def test_new_and_edited_source_are_refreshed_before_compat_ingestion(tmp_path: Path) -> None:
    vault_root, _registry, server = _real_server(tmp_path)
    source = vault_root / "raw" / "source.md"
    first = b"First durable fact.\n"
    source.write_bytes(first)

    tool = server._tool_manager.get_tool("ingestion_create_wiki_proposal")
    first_result = tool.fn(
        source_path="raw/source.md",
        target_path="wiki/source-v1.md",
        title="Source V1",
        body="First durable fact.",
    )

    assert _proposal_source_hash(vault_root, first_result["proposal_path"]) == (
        f"sha256:{hash_file_content(first)}"
    )
    assert source.read_bytes() == first
    assert not (vault_root / "wiki" / "source-v1.md").exists()

    second = b"First durable fact plus a new revision.\n"
    source.write_bytes(second)
    second_result = tool.fn(
        source_path="raw/source.md",
        target_path="wiki/source-v2.md",
        title="Source V2",
        body="First durable fact plus a new revision.",
    )

    assert _proposal_source_hash(vault_root, second_result["proposal_path"]) == (
        f"sha256:{hash_file_content(second)}"
    )
    assert source.read_bytes() == second
    assert not (vault_root / "wiki" / "source-v2.md").exists()

    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)["records"]
    second_ingestion_index = next(
        index
        for index, record in reversed(list(enumerate(activity)))
        if record["tool"] == "ingestion_create_wiki_proposal"
    )
    preflight = activity[second_ingestion_index - 1]
    assert preflight["tool"] == "ingestion_registry_preflight"
    assert preflight["source_paths"] == ["raw/source.md"]
    assert "raw/source.md" in preflight["changed_paths"]


def test_unscanned_study_source_is_refreshed_before_learning_proposal(tmp_path: Path) -> None:
    vault_root, _registry, server = _real_server(tmp_path)
    source = vault_root / "study" / "topic.md"
    source.write_text("A study fact worth retaining.\n", encoding="utf-8")

    result = server._tool_manager.get_tool("study_evolve_learning_proposal").fn(
        source_path="study/topic.md",
        wiki_creates=[
            EvolveWikiCreateMCPInput(
                target_path="wiki/topic.md",
                title="Topic",
                body="A reusable durable study fact.",
                rationale="Useful beyond the source note.",
            )
        ],
        flashcards=[
            StudyFlashcardCreateMCPInput(
                target_path="flashcards/topic.md",
                card_id="topic-fact",
                topic="Topic",
                question="What is the durable fact?",
                answer="A reusable durable study fact.",
                rationale="Useful retrieval practice.",
                learning_context="General study",
                knowledge_refs=["wiki/topic.md"],
            )
        ],
    )

    assert result["status"] == "draft"
    assert result["operation_count"] == 2
    assert not (vault_root / "wiki" / "topic.md").exists()
    assert not (vault_root / "flashcards" / "topic.md").exists()


def test_all_mcp_ingestion_draft_entrypoints_share_registry_preflight(tmp_path: Path) -> None:
    refresh_result = _empty_refresh()
    with (
        patch("lifeos.mcp.server.refresh_registry", return_value=refresh_result) as refresh,
        patch("lifeos.mcp.server.evolve_wiki_proposal") as evolve,
        patch("lifeos.mcp.server.evolve_study_learning_proposal") as study,
        patch("lifeos.mcp.server.create_wiki_proposal") as create,
        patch("lifeos.mcp.server.update_wiki_section_proposal") as update,
        patch("lifeos.mcp.server.create_wiki_and_update_section_proposal") as compound,
    ):
        evolve.return_value = MagicMock(
            proposal_id="evolve",
            proposal_path="proposals/evolve",
            target_paths=("wiki/evolve.md",),
            operation_count=1,
            status="draft",
        )
        study.return_value = MagicMock(
            proposal_id="study",
            proposal_path="proposals/study",
            target_paths=("wiki/study.md",),
            operation_count=1,
            status="draft",
        )
        create.return_value = MagicMock(
            proposal_id="create",
            proposal_path="proposals/create",
            target_path="wiki/create.md",
            status="draft",
        )
        update.return_value = MagicMock(
            proposal_id="update",
            proposal_path="proposals/update",
            target_path="wiki/update.md",
            heading="Selected",
            status="draft",
        )
        compound.return_value = MagicMock(
            proposal_id="compound",
            proposal_path="proposals/compound",
            create_target_path="wiki/detail.md",
            update_target_path="wiki/summary.md",
            heading="Selected",
            status="draft",
        )

        server = create_mcp_server(
            vault_root=tmp_path / "vault",
            registry=MagicMock(),
            authorizer=MagicMock(),
            runtime_dir=tmp_path / "runtime",
        )
        server._tool_manager.get_tool("ingestion_evolve_wiki_proposal").fn(
            source_path="raw/source.md",
            creates=[
                EvolveWikiCreateMCPInput(
                    target_path="wiki/evolve.md",
                    title="Evolve",
                    body="Body",
                    rationale="Durable.",
                )
            ],
        )
        server._tool_manager.get_tool("study_evolve_learning_proposal").fn(
            source_path="study/source.md",
            wiki_creates=[
                EvolveWikiCreateMCPInput(
                    target_path="wiki/study.md",
                    title="Study",
                    body="Body",
                    rationale="Durable.",
                )
            ],
        )
        server._tool_manager.get_tool("ingestion_create_wiki_proposal").fn(
            source_path="raw/source.md",
            target_path="wiki/create.md",
            title="Create",
            body="Body",
        )
        server._tool_manager.get_tool("ingestion_update_wiki_section_proposal").fn(
            source_path="raw/source.md",
            target_path="wiki/update.md",
            heading="Selected",
            body="Replacement",
        )
        server._tool_manager.get_tool("ingestion_create_wiki_and_update_section_proposal").fn(
            source_path="raw/source.md",
            create_target_path="wiki/detail.md",
            create_title="Detail",
            create_body="Body",
            update_target_path="wiki/summary.md",
            update_heading="Selected",
            update_body="Replacement",
        )

    assert refresh.call_count == 5
    assert all(call.kwargs["vault_root"] == tmp_path / "vault" for call in refresh.call_args_list)


def test_refresh_failure_stops_before_proposal_facade(tmp_path: Path) -> None:
    with (
        patch(
            "lifeos.mcp.server.refresh_registry",
            side_effect=ToolExecutionError("Could not refresh the disposable registry"),
        ),
        patch("lifeos.mcp.server.evolve_wiki_proposal") as evolve,
    ):
        server = create_mcp_server(
            vault_root=tmp_path / "vault",
            registry=MagicMock(),
            authorizer=MagicMock(),
            runtime_dir=tmp_path / "runtime",
        )

        with pytest.raises(ToolError, match="Could not refresh the disposable registry"):
            server._tool_manager.get_tool("ingestion_evolve_wiki_proposal").fn(
                source_path="raw/source.md",
                creates=[
                    EvolveWikiCreateMCPInput(
                        target_path="wiki/new.md",
                        title="New",
                        body="Body",
                        rationale="Durable.",
                    )
                ],
            )

    evolve.assert_not_called()
    assert not (tmp_path / "vault" / "proposals").exists()
