from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lifeos.facade.exploration as exploration_facade
from lifeos.facade.registry_tools import RegistryRefreshResult
import lifeos.mcp.runtime_server as runtime_server
import lifeos.mcp.server as core_server
import lifeos.runtime_scope as runtime_scope


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


def _install_case_insensitive_runtime_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open

    def case_insensitive_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        selected = os.fspath(path)
        if dir_fd is not None and selected == "Runtime":
            try:
                return real_open(selected, flags, mode, dir_fd=dir_fd)
            except FileNotFoundError:
                return real_open("runtime", flags, mode, dir_fd=dir_fd)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(runtime_scope.os, "open", case_insensitive_open)


def test_core_refresh_excludes_case_renamed_runtime_after_prefix_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime_dir = vault / "Runtime"
    runtime_dir.mkdir()
    (runtime_dir / "export.md").write_text("runtime-only\n", encoding="utf-8")
    renamed_runtime = vault / "runtime"
    renamed = False

    def fake_refresh_registry(
        *,
        vault_root: Path,
        registry: object,
        identity_allow_path: object,
    ) -> RegistryRefreshResult:
        nonlocal renamed
        assert vault_root == vault
        assert identity_allow_path is not None
        if not renamed:
            runtime_dir.rename(renamed_runtime)
            renamed = True
        assert not identity_allow_path("runtime/export.md")  # type: ignore[operator]
        return RegistryRefreshResult((), (), (), (), 0)

    _install_case_insensitive_runtime_open(monkeypatch)
    monkeypatch.setattr(core_server, "refresh_registry", fake_refresh_registry)
    server = runtime_server.create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime_dir,
    )
    tool = server._tool_manager.get_tool("registry_refresh")

    tool.fn()

    assert renamed_runtime.is_dir()


def test_exploration_excludes_case_renamed_runtime_after_prefix_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "wiki").mkdir()
    (vault / "wiki" / "public.md").write_text("public\n", encoding="utf-8")
    runtime_dir = vault / "Runtime"
    runtime_dir.mkdir()
    (runtime_dir / "export.md").write_text("runtime-only\n", encoding="utf-8")
    renamed_runtime = vault / "runtime"
    real_iter = exploration_facade.iter_vault_markdown_paths
    renamed = False

    def rename_then_iter(*args: object, **kwargs: object) -> object:
        nonlocal renamed
        if not renamed:
            runtime_dir.rename(renamed_runtime)
            renamed = True
        return real_iter(*args, **kwargs)

    _install_case_insensitive_runtime_open(monkeypatch)
    monkeypatch.setattr(exploration_facade, "iter_vault_markdown_paths", rename_then_iter)
    server = runtime_server.create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime_dir,
    )
    tool = server._tool_manager.get_tool("vault_list")

    result = tool.fn()
    paths = {item["path"] for item in result["entries"]}

    assert "wiki/public.md" in paths
    assert "runtime/export.md" not in paths
    assert renamed_runtime.is_dir()
