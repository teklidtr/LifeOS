from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import lifeos._recovery_io as recovery_io
from lifeos._recovery_io import RecoveryIOUnavailableError, remove_installed_creation
from lifeos._transaction_files import ParentDescriptor


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


def test_recovery_creation_rollback_unlinks_through_live_canonical_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    canonical_parent = vault / "wiki"
    canonical_parent.mkdir(parents=True)
    target = canonical_parent / "note.md"
    content = b"installed\n"
    target.write_bytes(content)
    target.chmod(0o640)
    parent = _parent(canonical_parent)
    moved_parent = vault / "moved"
    real_unlink = recovery_io.os.unlink
    relocated = False

    def relocate_then_unlink(path: object, *args: object, **kwargs: object) -> None:
        nonlocal relocated
        if not relocated:
            canonical_parent.rename(moved_parent)
            canonical_parent.mkdir()
            relocated = True
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(recovery_io.os, "unlink", relocate_then_unlink)
    try:
        with pytest.raises(RecoveryIOUnavailableError, match="Failed to unlink target"):
            remove_installed_creation(
                target_name="note.md",
                target_parent=parent,
                expected_installed_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
                expected_installed_mode=0o640,
            )

        assert (moved_parent / "note.md").read_bytes() == content
        assert not (canonical_parent / "note.md").exists()
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)
