from __future__ import annotations

import os
from pathlib import Path

import pytest

import lifeos._transaction_files as transaction_files
from lifeos._transaction_files import (
    ParentDescriptor,
    TransactionError,
    create_hardlink_backup,
    create_staging_file,
    get_target_identity,
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


def _close_parent(parent: ParentDescriptor) -> None:
    os.close(parent.fd)
    assert parent.authority_fd is not None
    os.close(parent.authority_fd)


def test_replacement_quarantine_preserves_swap_after_guard_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    real_replace = os.replace
    swapped = False

    def swap_then_quarantine(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if (
            not swapped
            and os.fspath(src) == "note.md"
            and os.fspath(dst).endswith(".replace-quarantine")
        ):
            target.unlink()
            target.write_bytes(b"foreign\n")
            swapped = True
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "replace", swap_then_quarantine)
    try:
        with pytest.raises(TransactionError, match="changed during guarded mutation"):
            publish_replacement("note.md", staging, original)

        assert target.read_bytes() == b"foreign\n"
        assert (canonical_parent / staging.name).read_bytes() == b"candidate\n"
        assert not list(canonical_parent.glob(".*.replace-guard"))
        assert not list(canonical_parent.glob(".*.replace-quarantine"))
    finally:
        _close_parent(parent)


def test_remove_quarantine_preserves_swap_after_guard_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    target.write_bytes(b"installed\n")
    parent = _parent(canonical_parent)
    expected = get_target_identity("note.md", parent)
    assert expected is not None
    real_replace = os.replace
    swapped = False

    def swap_then_quarantine(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if (
            not swapped
            and os.fspath(src) == "note.md"
            and os.fspath(dst).endswith(".unlink-quarantine")
        ):
            target.unlink()
            target.write_bytes(b"foreign\n")
            swapped = True
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "replace", swap_then_quarantine)
    try:
        with pytest.raises(TransactionError, match="changed during guarded mutation"):
            remove_verified_target("note.md", parent, expected)

        assert target.read_bytes() == b"foreign\n"
        assert not list(canonical_parent.glob(".*.unlink-guard"))
        assert not list(canonical_parent.glob(".*.unlink-quarantine"))
    finally:
        _close_parent(parent)


def test_rollback_quarantine_preserves_swap_after_guard_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    real_replace = os.replace
    swapped = False

    def swap_then_quarantine(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if (
            not swapped
            and os.fspath(src) == "note.md"
            and os.fspath(dst).endswith(".rollback-quarantine")
        ):
            target.unlink()
            target.write_bytes(b"foreign\n")
            swapped = True
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "replace", swap_then_quarantine)
    try:
        with pytest.raises(TransactionError, match="changed during guarded mutation"):
            rollback_replacement("note.md", staging, backup)

        assert target.read_bytes() == b"foreign\n"
        assert (canonical_parent / backup.name).read_bytes() == b"original\n"
        assert not list(canonical_parent.glob(".*.rollback-guard"))
        assert not list(canonical_parent.glob(".*.rollback-quarantine"))
    finally:
        try:
            (canonical_parent / staging.name).unlink()
        except FileNotFoundError:
            pass
        try:
            (canonical_parent / backup.name).unlink()
        except FileNotFoundError:
            pass
        _close_parent(parent)
