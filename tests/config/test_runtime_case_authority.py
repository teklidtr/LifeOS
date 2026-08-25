from __future__ import annotations

import os
from pathlib import Path

import pytest

import lifeos.config as config_module
from lifeos.config import runtime_overlaps_reserved_canonical


def test_case_insensitive_selection_rejects_case_variant_reserved_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "proposals").mkdir(parents=True)
    real_open = os.open

    def case_insensitive_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        selected = os.fspath(path)
        if dir_fd is not None and selected == "Proposals":
            selected = "proposals"
        return real_open(selected, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(config_module.os, "open", case_insensitive_open)

    assert runtime_overlaps_reserved_canonical(vault, vault / "Proposals" / "node-a")


def test_case_sensitive_distinct_runtime_name_is_not_reserved(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "proposals").mkdir(parents=True)
    try:
        (vault / "Proposals").mkdir()
    except FileExistsError:
        pytest.skip("filesystem does not support distinct case-sensitive directory entries")

    assert not runtime_overlaps_reserved_canonical(vault, vault / "Proposals" / "node-a")
