from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import lifeos._transaction_files as transaction_files
from lifeos._transaction_files import (
    ParentDescriptor,
    TransactionError,
    _remove_verified_artifact,
    create_hardlink_backup,
    create_staging_file,
    get_target_identity,
    publish_replacement,
    rollback_replacement,
)
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.recovery import RecoveryConflictError
from lifeos.proposals.recovery_service import recover_interrupted_applications
from tests.proposals.test_recovery_orchestration import (
    _InjectedInterruption,
    _load_two_target_application,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _parent(path: Path) -> ParentDescriptor:
    fd = os.open(path, _DIRECTORY_FLAGS)
    authority_fd = os.open(path, _DIRECTORY_FLAGS)
    state = os.fstat(fd)
    return ParentDescriptor(
        fd=fd,
        dev=state.st_dev,
        ino=state.st_ino,
        path=".",
        authority_fd=authority_fd,
    )


def _close_parent(parent: ParentDescriptor) -> None:
    os.close(parent.fd)
    assert parent.authority_fd is not None
    os.close(parent.authority_fd)


def test_guard_alone_does_not_authorize_restoring_later_human_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meta, vault_root, proposal = _load_two_target_application(tmp_path)
    real_quarantine = transaction_files._quarantine_verified_target
    real_best_effort_remove = transaction_files._best_effort_remove

    def interrupt_before_quarantine(
        target_name: str,
        **kwargs: object,
    ) -> str:
        if target_name == "test1.txt" and kwargs.get("suffix") == "replace":
            raise _InjectedInterruption("before replacement quarantine")
        return real_quarantine(target_name, **kwargs)

    monkeypatch.setattr(
        transaction_files,
        "_quarantine_verified_target",
        interrupt_before_quarantine,
    )
    monkeypatch.setattr(transaction_files, "_best_effort_remove", lambda *_args: None)

    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    guards = list(vault_root.glob(".test1.txt.*.replace-guard"))
    assert len(guards) == 1
    assert not list(vault_root.glob(".test1.txt.*.replace-quarantine"))
    assert (vault_root / "test1.txt").read_bytes() == b"old_content"

    # The interrupted process never consumed the canonical dirent. A later deletion therefore
    # belongs to the human/sync side of the coherence boundary, not to recovery.
    (vault_root / "test1.txt").unlink()
    monkeypatch.setattr(transaction_files, "_quarantine_verified_target", real_quarantine)
    monkeypatch.setattr(transaction_files, "_best_effort_remove", real_best_effort_remove)

    with pytest.raises(RecoveryConflictError, match="quarantine evidence"):
        recover_interrupted_applications(vault_root=vault_root)

    assert not (vault_root / "test1.txt").exists()
    assert guards[0].exists()


def test_verified_artifact_cleanup_never_unlinks_a_replacement_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    artifact = vault / ".note.md.recovery.replace-guard"
    artifact.write_bytes(b"trusted-artifact")
    artifact.chmod(0o640)
    parent = _parent(vault)
    expected = get_target_identity(artifact.name, parent)
    assert expected is not None
    real_replace = transaction_files.os.replace
    swapped = False

    def replace_after_swap(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal swapped
        if (
            not swapped
            and os.fspath(src) == artifact.name
            and os.fspath(dst).endswith(".cleanup-quarantine")
        ):
            artifact.unlink()
            artifact.write_bytes(b"foreign-artifact")
            artifact.chmod(0o640)
            swapped = True
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(transaction_files.os, "replace", replace_after_swap)
    try:
        with pytest.raises(TransactionError, match="changed"):
            _remove_verified_artifact(artifact.name, parent, expected)

        assert swapped is True
        assert artifact.read_bytes() == b"foreign-artifact"
    finally:
        _close_parent(parent)


def test_authority_bound_rollback_rejects_non_journaled_candidate_mode(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "note.md"
    target.write_bytes(b"old")
    target.chmod(0o640)
    parent = _parent(vault)
    backup = None

    try:
        original = get_target_identity(target.name, parent)
        assert original is not None
        staging = create_staging_file(target.name, b"new", parent, 0o640)
        backup = create_hardlink_backup(target.name, parent, original)
        publish_replacement(target.name, staging, original)
        assert target.read_bytes() == b"new"
        assert stat.S_IMODE(target.stat().st_mode) == 0o640

        target.chmod(0o600)

        with pytest.raises(TransactionError, match="mutated externally"):
            rollback_replacement(target.name, staging, backup)

        assert target.read_bytes() == b"new"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert not list(vault.glob(".note.md.*.rollback-guard"))
        assert not list(vault.glob(".note.md.*.rollback-quarantine"))
    finally:
        if backup is not None:
            try:
                os.unlink(backup.name, dir_fd=backup.parent.fd)
            except FileNotFoundError:
                pass
        _close_parent(parent)
