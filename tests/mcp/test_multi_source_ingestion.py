import hashlib
from pathlib import Path

import pytest

from lifeos.facade.errors import ToolConflictError, ToolValidationError
from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.multi_source_tools import (
    EVOLVE_WIKI_BATCH_MCP_DESCRIPTION,
    BatchSourceSnapshotMCPInput,
    BatchWikiCreateMCPInput,
    build_multi_source_ingestion_tools,
)
from lifeos.mcp.runtime_server import LIFEOS_MCP_INSTRUCTIONS
from lifeos.registry import Registry


def test_batch_tool_is_exposed_as_proposal_producing_not_read_only(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = vault_root / ".lifeos"
    vault_root.mkdir()
    runtime_dir.mkdir()
    registry = Registry(runtime_dir / "registry.db")
    registry.initialize()
    activity = MCPActivityStore(runtime_dir)

    tools = build_multi_source_ingestion_tools(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        registry=registry,
        activity=activity,
        invoke=lambda operation: operation(),
    )

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "ingestion_evolve_wiki_batch_proposal"
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False
    assert "source_snapshots" in tool.parameters["properties"]
    assert "source_paths" not in tool.parameters["properties"]


def test_batch_tool_description_documents_independent_bounds_and_no_fanout() -> None:
    assert "path/content_hash snapshots returned by vault_read_many" in (
        EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    )
    assert "64 distinct sources" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "32 distinct targets" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "2 MiB" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "without automatic fan-out" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "zero durable changes" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION


def test_runtime_instructions_describe_joint_folder_reconciliation() -> None:
    assert "Folder or multi-source ingestion is one logical batch" in LIFEOS_MCP_INSTRUCTIONS
    assert "exact path/content_hash snapshots from vault_read_many" in LIFEOS_MCP_INSTRUCTIONS
    assert "Do not loop the single-source proposal tool once per file" in LIFEOS_MCP_INSTRUCTIONS
    assert "one target-reconciled draft" in LIFEOS_MCP_INSTRUCTIONS


def test_registry_refresh_cannot_rebind_old_agent_synthesis_to_new_source_bytes(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = vault_root / ".lifeos"
    source = vault_root / "raw" / "source.md"
    source.parent.mkdir(parents=True)
    runtime_dir.mkdir()
    source.write_text("Version read by the agent.\n", encoding="utf-8")
    observed_hash = f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"

    registry = Registry(runtime_dir / "registry.db")
    registry.initialize()
    activity = MCPActivityStore(runtime_dir)
    tool = build_multi_source_ingestion_tools(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        registry=registry,
        activity=activity,
        invoke=lambda operation: operation(),
    )[0]

    # The file changes after exploration. The batch tool's own registry refresh will discover
    # this newer version, but the proposal must remain bound to the version the agent read.
    source.write_text("New version after agent synthesis.\n", encoding="utf-8")

    with pytest.raises(ToolConflictError, match="version read during exploration"):
        tool.fn(
            source_snapshots=[
                BatchSourceSnapshotMCPInput(
                    path="raw/source.md",
                    content_hash=observed_hash,
                )
            ],
            creates=[
                BatchWikiCreateMCPInput(
                    target_path="wiki/result.md",
                    title="Result",
                    body="Candidate synthesized from the older bytes.",
                    rationale="Exercise source-version binding across registry refresh.",
                    source_paths=["raw/source.md"],
                )
            ],
        )


def test_batch_tool_rejects_internal_proposal_and_conversation_sources(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = vault_root / ".lifeos"
    vault_root.mkdir()
    runtime_dir.mkdir()
    registry = Registry(runtime_dir / "registry.db")
    registry.initialize()
    activity = MCPActivityStore(runtime_dir)
    tool = build_multi_source_ingestion_tools(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        registry=registry,
        activity=activity,
        invoke=lambda operation: operation(),
    )[0]

    for source_path in (
        "proposals/prop-test/proposal.md",
        "conversations/2026/session.md",
    ):
        with pytest.raises(ToolValidationError, match="MCP batch paths are unavailable"):
            tool.fn(
                source_snapshots=[
                    BatchSourceSnapshotMCPInput(
                        path=source_path,
                        content_hash="sha256:" + "1" * 64,
                    )
                ],
                creates=[
                    BatchWikiCreateMCPInput(
                        target_path="wiki/result.md",
                        title="Result",
                        body="Body",
                        rationale="Exercise the established MCP ingestion scope boundary.",
                        source_paths=[source_path],
                    )
                ],
            )
