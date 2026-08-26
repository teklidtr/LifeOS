from __future__ import annotations

import os
from pathlib import Path

import pytest

from lifeos.coherence_scoped import runtime_exclusion_prefix
import lifeos.runtime_scope as runtime_scope
from lifeos.runtime_scope import build_runtime_exclusion_matcher


def test_in_vault_runtime_prefix_survives_symlink_topology_change(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    external = tmp_path / "external-runtime"
    external.mkdir()
    runtime = vault / "runtime-node"
    runtime.symlink_to(external, target_is_directory=True)

    assert runtime_exclusion_prefix(vault, runtime_dir=runtime) == "runtime-node/"

    runtime.unlink()
    runtime.mkdir()

    assert runtime_exclusion_prefix(vault, runtime_dir=runtime) == "runtime-node/"


def test_runtime_matcher_excludes_new_spelling_after_case_only_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "Runtime"
    runtime.mkdir()
    prefix = runtime_exclusion_prefix(vault, runtime_dir=runtime)
    assert prefix == "Runtime/"
    renamed = vault / "runtime"
    runtime.rename(renamed)
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
    matcher = build_runtime_exclusion_matcher(
        vault,
        runtime_dir=runtime,
        snapshot_prefix=prefix,
    )

    assert matcher("Runtime/old-scan.md")
    assert matcher("runtime/new-scan.md")


def test_runtime_matcher_keeps_distinct_case_sensitive_directory_in_scope(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    configured = vault / "Runtime"
    configured.mkdir()
    distinct = vault / "runtime"
    try:
        distinct.mkdir()
    except FileExistsError:
        pytest.skip("filesystem does not distinguish case-only directory names")

    matcher = build_runtime_exclusion_matcher(
        vault,
        runtime_dir=configured,
        snapshot_prefix="Runtime/",
    )

    assert matcher("Runtime/export.md")
    assert not matcher("runtime/canonical.md")


def test_runtime_matcher_allows_non_runtime_path_when_vault_root_is_absent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    matcher = build_runtime_exclusion_matcher(
        vault,
        runtime_dir=vault / ".lifeos",
        snapshot_prefix=".lifeos/",
    )

    assert matcher(".lifeos/export.md")
    assert not matcher("wiki/note.md")
