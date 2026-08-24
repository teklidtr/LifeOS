from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from lifeos.facade.exploration import VaultListRequest
from lifeos.mcp.exploration_tools import _validated_request
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.mcp.server import _invoke_mcp_tool


def test_runtime_replaces_legacy_reads_with_policy_aware_inputs(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert "allow_protected" in tools["vault_read_markdown"].parameters["properties"]
    assert "allow_protected" in tools["vault_context"].parameters["properties"]
    assert "after" in tools["vault_list"].parameters["properties"]
    assert "offset" in tools["vault_links"].parameters["properties"]


def test_exploration_request_value_errors_are_mapped_to_argument_errors() -> None:
    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        _invoke_mcp_tool(
            lambda: _validated_request(lambda: VaultListRequest(limit=201))
        )


def test_runtime_exploration_inputs_are_type_strict(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    list_model = tools["vault_list"].fn_metadata.arg_model

    with pytest.raises(ValidationError):
        list_model.model_validate({"allow_protected": "yes"})
    with pytest.raises(ValidationError):
        list_model.model_validate({"limit": "20"})
    with pytest.raises(ValidationError):
        list_model.model_validate({"limit": True})


def test_runtime_protected_read_uses_external_disclosure_policy(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    secret = vault / "journal/private/secret.md"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret\n", encoding="utf-8")
    server = create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )

    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool("vault_read_markdown").fn(
            vault_path="journal/private/secret.md",
            allow_protected=True,
        )
