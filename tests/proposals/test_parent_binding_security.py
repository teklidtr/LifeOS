from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from lifeos._transaction_files import (
    ParentDescriptor,
    TransactionError,
    create_staging_file,
    get_target_identity,
    publish_creation,
    publish_replacement,
)


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)


def _parent(path: Path) -> ParentDescriptor:
    fd = os.open(path, _DIRECTORY_FLAGS)
    authority_fd = os.open(path.parent, _DIRECTORY_FLAGS)
    state = os.fstat(fd)
    return ParentDescriptor(
        fd=fd,
        dev=state.st_dev,
        ino=state.st_ino,
        path="wiki",
        authority_fd=authority_fd,
    )


def test_creation_publish_rejects_parent_relocation_after_staging(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    parent = _parent(canonical_parent)
    try:
        staging = create_staging_file("note.md", b"candidate\n", parent, 0o644)
        moved_parent = vault / "system"
        canonical_parent.rename(moved_parent)
        canonical_parent.mkdir()

        with pytest.raises(TransactionError, match="parent directory moved"):
            publish_creation("note.md", staging)

        assert not (moved_parent / "note.md").exists()
        assert not (canonical_parent / "note.md").exists()
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)


def test_replacement_publish_rejects_parent_relocation_after_staging(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    target.write_bytes(b"original\n")
    parent = _parent(canonical_parent)
    try:
        original = get_target_identity("note.md", parent)
        assert original is not None
        assert stat.S_ISREG(original.mode)
        staging = create_staging_file("note.md", b"candidate\n", parent, 0o644)
        moved_parent = vault / "system"
        canonical_parent.rename(moved_parent)
        canonical_parent.mkdir()

        with pytest.raises(TransactionError, match="parent directory moved"):
            publish_replacement("note.md", staging, original)

        assert (moved_parent / "note.md").read_bytes() == b"original\n"
        assert not (canonical_parent / "note.md").exists()
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)


def test_creation_syscall_selects_live_reviewed_path_after_final_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    parent = _parent(canonical_parent)
    staging = create_staging_file("note.md", b"candidate\n", parent, 0o644)
    real_link = os.link

    def relocate_then_link(*args: object, **kwargs: object) -> None:
        canonical_parent.rename(vault / "moved")
        canonical_parent.mkdir()
        real_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", relocate_then_link)
    try:
        with pytest.raises(TransactionError, match="parent directory moved"):
            publish_creation("note.md", staging)
        assert not (vault / "moved" / "note.md").exists()
        assert not canonical_parent.joinpath("note.md").exists()
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)
