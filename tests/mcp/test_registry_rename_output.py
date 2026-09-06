from pathlib import Path
from unittest.mock import MagicMock

import lifeos.mcp.server as server_module
from lifeos.facade.registry_tools import RegistryRefreshResult


def test_registry_refresh_exposes_pure_rename_and_activity_paths(
    tmp_path: Path, monkeypatch
) -> None:
    result = RegistryRefreshResult(
        new=(),
        modified=(),
        unchanged=(),
        deleted=(),
        proposals_indexed=0,
        renamed=(("wiki/old.md", "wiki/new.md"),),
    )
    monkeypatch.setattr(server_module, "refresh_registry", lambda **_kwargs: result)
    runtime = tmp_path / "runtime"
    server = server_module.create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )

    payload = server._tool_manager.get_tool("registry_refresh").fn()

    assert payload["new"] == []
    assert payload["deleted"] == []
    assert payload["renamed"] == [{"from_path": "wiki/old.md", "to_path": "wiki/new.md"}]
    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=5)
    assert activity["records"][-1]["changed_paths"] == [
        "wiki/old.md",
        "wiki/new.md",
    ]


def test_registry_refresh_omits_empty_rename_extension(tmp_path: Path, monkeypatch) -> None:
    result = RegistryRefreshResult(
        new=("study/new.md",),
        modified=(),
        unchanged=(),
        deleted=(),
        proposals_indexed=0,
    )
    monkeypatch.setattr(server_module, "refresh_registry", lambda **_kwargs: result)
    server = server_module.create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / "runtime",
    )

    payload = server._tool_manager.get_tool("registry_refresh").fn()

    assert "renamed" not in payload
