from pathlib import Path
from unittest.mock import MagicMock

from lifeos.mcp.runtime_server import LIFEOS_MCP_INSTRUCTIONS, create_mcp_server


def test_runtime_server_adds_only_read_only_exploration_tools(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    exploration = {"vault_list", "vault_search", "vault_read_many", "vault_links"}
    assert exploration <= tools.keys()
    for name in exploration:
        annotations = tools[name].annotations
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is True
        assert annotations.openWorldHint is False

    assert "write_file" not in tools
    assert "delete_file" not in tools
    assert "move_file" not in tools
    assert "shell" not in tools
    assert tools["proposal_apply"].annotations.destructiveHint is True


def test_runtime_server_advertises_exploration_without_relaxing_mutation(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )

    assert server.instructions == LIFEOS_MCP_INSTRUCTIONS
    assert "Exploration is encouraged" in server.instructions
    assert "vault_list" in server.instructions
    assert "vault_search" in server.instructions
    assert "vault_read_many" in server.instructions
    assert "vault_links" in server.instructions
    assert "LifeOS constrains mutation, not exploration" in server.instructions
    assert "there is no generic vault write, delete, move, or shell surface" in server.instructions


def test_exploration_tool_schemas_are_strict_and_bounded(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools["vault_list"].parameters["properties"]) == {
        "prefix",
        "limit",
        "allow_protected",
        "after",
    }
    assert set(tools["vault_search"].parameters["properties"]) == {
        "query",
        "prefix",
        "limit",
        "allow_protected",
    }
    assert set(tools["vault_read_many"].parameters["properties"]) == {
        "paths",
        "max_characters",
        "allow_protected",
    }
    assert set(tools["vault_links"].parameters["properties"]) == {
        "path",
        "direction",
        "limit",
        "allow_protected",
    }
    assert all(tools[name].parameters["additionalProperties"] is False for name in (
        "vault_list",
        "vault_search",
        "vault_read_many",
        "vault_links",
    ))
