from pathlib import Path

from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.multi_source_tools import (
    EVOLVE_WIKI_BATCH_MCP_DESCRIPTION,
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


def test_batch_tool_description_documents_independent_bounds_and_no_fanout() -> None:
    assert "64 distinct sources" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "32 distinct targets" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "2 MiB" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "without automatic fan-out" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION
    assert "zero durable changes" in EVOLVE_WIKI_BATCH_MCP_DESCRIPTION


def test_runtime_instructions_describe_joint_folder_reconciliation() -> None:
    assert "Folder or multi-source ingestion is one logical batch" in LIFEOS_MCP_INSTRUCTIONS
    assert "Do not loop the single-source proposal tool once per file" in LIFEOS_MCP_INSTRUCTIONS
    assert "one target-reconciled draft" in LIFEOS_MCP_INSTRUCTIONS
