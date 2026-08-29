from __future__ import annotations

import os
from pathlib import Path

import lifeos.coherence_scoped as coherence_scoped
from lifeos.runtime_scope import build_runtime_exclusion_matcher


def test_opened_component_spelling_uses_directory_entry_name(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "runtime"
    runtime.mkdir()

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(vault, flags)
    child_fd = os.open("runtime", flags, dir_fd=root_fd)
    try:
        assert coherence_scoped._opened_component_spelling(
            root_fd,
            child_fd,
            "Runtime",
        ) == "runtime"
    finally:
        os.close(child_fd)
        os.close(root_fd)


def test_runtime_prefix_uses_filesystem_selected_spelling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    monkeypatch.setattr(
        coherence_scoped,
        "_existing_runtime_spelling",
        lambda _root, _relative: "runtime",
    )

    assert coherence_scoped.runtime_exclusion_prefix(
        vault,
        runtime_dir=vault / "Runtime",
    ) == "runtime/"


def test_runtime_exclusion_preserves_filename_whitespace(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "runtime"
    runtime.mkdir()

    matcher = build_runtime_exclusion_matcher(
        vault,
        runtime_dir=runtime,
        snapshot_prefix="runtime/",
    )

    assert matcher("runtime/cache.db")
    assert not matcher(" runtime/cache.db")
    assert not matcher("runtime /cache.db")
    assert not matcher("runtime/cache.db ")
