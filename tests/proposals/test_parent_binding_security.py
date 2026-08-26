from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import lifeos._transaction_files as transaction_files
from lifeos._transaction_files import (
    ParentDescriptor,
    TransactionError,
    create_hardlink_backup,
    create_staging_file,
    get_target_identity,
    publish_creation,
    publish_replacement,
    remove_verified_target,
    rollback_replacement,
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


def test_replacement_syscall_never_overwrites_foreign_replacement_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    target.write_bytes(b"original\n")
    parent = _parent(canonical_parent)
    original = get_target_identity("note.md", parent)
    assert original is not None
    staging = create_staging_file("note.md", b"candidate\n", parent, 0o644)
    moved_parent = vault / "moved"
    real_replace = os.replace
    relocated = False

    def relocate_then_replace(*args: object, **kwargs: object) -> None:
        nonlocal relocated
        if not relocated:
            canonical_parent.rename(moved_parent)
            canonical_parent.mkdir()
            (canonical_parent / "note.md").write_bytes(b"foreign\n")
            relocated = True
        real_replace(*args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "replace", relocate_then_replace)
    try:
        with pytest.raises(TransactionError, match="parent directory moved"):
            publish_replacement("note.md", staging, original)

        assert (moved_parent / "note.md").read_bytes() == b"original\n"
        assert (canonical_parent / "note.md").read_bytes() == b"foreign\n"
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)


def test_staging_race_leaves_no_artifact_in_replacement_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    parent = _parent(canonical_parent)
    moved_parent = vault / "moved"
    real_open = os.open
    relocated = False

    def relocate_then_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal relocated
        selected = os.fspath(path)
        if (
            not relocated
            and isinstance(selected, str)
            and selected.startswith(".note.md.")
            and selected.endswith(".staged")
        ):
            canonical_parent.rename(moved_parent)
            canonical_parent.mkdir()
            relocated = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(transaction_files.os, "open", relocate_then_open)
    try:
        with pytest.raises(TransactionError, match="parent directory moved"):
            create_staging_file("note.md", b"candidate\n", parent, 0o644)

        assert not list(moved_parent.glob("*.staged"))
        assert not list(canonical_parent.glob("*.staged"))
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)


def test_replacement_guard_rejects_target_inode_swap_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    target.write_bytes(b"original\n")
    parent = _parent(canonical_parent)
    original = get_target_identity("note.md", parent)
    assert original is not None
    staging = create_staging_file("note.md", b"candidate\n", parent, 0o644)
    real_link = os.link
    swapped = False

    def swap_then_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped and os.fspath(dst).endswith(".replace-guard"):
            target.unlink()
            target.write_bytes(b"foreign\n")
            swapped = True
        real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "link", swap_then_link)
    try:
        with pytest.raises(TransactionError, match="unexpected target identity"):
            publish_replacement("note.md", staging, original)

        assert target.read_bytes() == b"foreign\n"
        assert not list(canonical_parent.glob("*.replace-guard"))
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)


def test_remove_guard_rejects_target_inode_swap_before_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    target.write_bytes(b"installed\n")
    parent = _parent(canonical_parent)
    expected = get_target_identity("note.md", parent)
    assert expected is not None
    real_link = os.link
    swapped = False

    def swap_then_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped and os.fspath(dst).endswith(".unlink-guard"):
            target.unlink()
            target.write_bytes(b"foreign\n")
            swapped = True
        real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "link", swap_then_link)
    try:
        with pytest.raises(TransactionError, match="unexpected target identity"):
            remove_verified_target("note.md", parent, expected)

        assert target.read_bytes() == b"foreign\n"
        assert not list(canonical_parent.glob("*.unlink-guard"))
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)


def test_rollback_guard_rejects_target_inode_swap_before_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    target.write_bytes(b"original\n")
    parent = _parent(canonical_parent)
    original = get_target_identity("note.md", parent)
    assert original is not None
    staging = create_staging_file("note.md", b"candidate\n", parent, 0o644)
    backup = create_hardlink_backup("note.md", parent, original)
    target.unlink()
    target.write_bytes(b"candidate\n")
    real_link = os.link
    swapped = False

    def swap_then_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped and os.fspath(dst).endswith(".rollback-guard"):
            target.unlink()
            target.write_bytes(b"foreign\n")
            swapped = True
        real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "link", swap_then_link)
    try:
        with pytest.raises(TransactionError, match="unexpected target identity"):
            rollback_replacement("note.md", staging, backup)

        assert target.read_bytes() == b"foreign\n"
        assert (canonical_parent / backup.name).read_bytes() == b"original\n"
        assert not list(canonical_parent.glob("*.rollback-guard"))
    finally:
        try:
            (canonical_parent / staging.name).unlink()
        except FileNotFoundError:
            pass
        try:
            (canonical_parent / backup.name).unlink()
        except FileNotFoundError:
            pass
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)