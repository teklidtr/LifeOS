from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from lifeos.facade.exploration import VaultListRequest
from lifeos.mcp.exploration_tools import _validated_request
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.mcp.server import _invoke_mcp_tool
from lifeos.runtime import ActivityStore


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
        _invoke_mcp_tool(lambda: _validated_request(lambda: VaultListRequest(limit=201)))


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


def test_runtime_activity_refilters_protected_paths_after_explicit_read(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    secret = vault / "journal/private/secret.md"
    public = vault / "wiki/public.md"
    policy = vault / "system/retrieval-policy.yml"
    secret.parent.mkdir(parents=True)
    public.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)
    secret.write_text("secret\n", encoding="utf-8")
    public.write_text("public\n", encoding="utf-8")
    policy.write_text(
        "schema_version: 1\nexternal_allowed_prefixes:\n  - journal/private\n",
        encoding="utf-8",
    )
    server = create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )

    server._tool_manager.get_tool("vault_read_markdown").fn(
        vault_path="journal/private/secret.md",
        allow_protected=True,
    )
    server._tool_manager.get_tool("vault_read_markdown").fn(
        vault_path="wiki/public.md",
    )
    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)
    read_records = [
        record for record in activity["records"] if record["tool"] == "vault_read_markdown"
    ]

    assert any(record["source_paths"] == ["wiki/public.md"] for record in read_records)
    assert any(record["source_paths"] == [] for record in read_records)
    assert all("journal/private/secret.md" not in record["source_paths"] for record in read_records)


def test_runtime_activity_redacts_historical_instruction_ids(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / ".lifeos"
    ActivityStore(runtime).append(
        tool="vault_context",
        instruction_ids=["protected-private-rule"],
    )
    server = create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )

    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)
    context_records = [
        record for record in activity["records"] if record["tool"] == "vault_context"
    ]

    assert context_records
    assert all(record["instruction_ids"] == [] for record in context_records)
