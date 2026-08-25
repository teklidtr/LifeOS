from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lifeos.mcp.runtime_server as runtime_server


def test_runtime_exclusion_spelling_is_refreshed_for_each_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime_dir = vault / "Runtime"
    runtime_dir.mkdir()
    observed: list[str] = []
    spellings = iter(("Runtime/", "runtime/"))

    def current_prefix(
        vault_root: Path,
        *,
        runtime_dir: Path | None,
    ) -> str:
        assert vault_root == vault
        assert runtime_dir == vault / "Runtime"
        value = next(spellings)
        observed.append(value)
        return value

    monkeypatch.setattr(runtime_server, "runtime_exclusion_prefix", current_prefix)
    server = runtime_server.create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime_dir,
    )
    tool = server._tool_manager.get_tool("vault_list")

    tool.fn()
    tool.fn()

    assert observed == ["Runtime/", "runtime/"]
