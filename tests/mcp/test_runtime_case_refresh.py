from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lifeos.facade.registry_tools import RegistryRefreshResult
import lifeos.mcp.runtime_server as runtime_server
import lifeos.mcp.server as core_server


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


def test_copied_core_registry_refresh_snapshots_runtime_spelling_per_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime_dir = vault / "Runtime"
    runtime_dir.mkdir()
    observed: list[str] = []
    spellings = iter(("Runtime/", "runtime/"))
    runtime_paths = iter(
        (
            ("Runtime/export-a.md", "Runtime/export-b.md"),
            ("runtime/export-a.md", "runtime/export-b.md"),
        )
    )

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

    def fake_refresh_registry(
        *,
        vault_root: Path,
        registry: object,
        identity_allow_path: object,
    ) -> RegistryRefreshResult:
        assert vault_root == vault
        assert identity_allow_path is not None
        for path in next(runtime_paths):
            assert not identity_allow_path(path)  # type: ignore[operator]
        return RegistryRefreshResult((), (), (), (), 0)

    monkeypatch.setattr(core_server, "runtime_exclusion_prefix", current_prefix)
    monkeypatch.setattr(core_server, "refresh_registry", fake_refresh_registry)
    server = runtime_server.create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime_dir,
    )
    tool = server._tool_manager.get_tool("registry_refresh")

    tool.fn()
    tool.fn()

    assert observed == ["Runtime/", "runtime/"]