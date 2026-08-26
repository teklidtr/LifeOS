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
    real_replace = recovery_io.os.replace
    relocated = False

    def relocate_then_replace(src: object, dst: object, *args: object, **kwargs: object) -> None:
        nonlocal relocated
        is_canonical_consume = (
            str(src) == "note.md"
            and str(dst).startswith(".note.md.")
            and str(dst).endswith(".unlink-quarantine")
        )
        if not relocated and is_canonical_consume:
            canonical_parent.rename(moved_parent)
            canonical_parent.mkdir()
            (canonical_parent / "note.md").write_bytes(b"foreign\n")
            relocated = True
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(recovery_io.os, "replace", relocate_then_replace)
    try:
        with pytest.raises(RecoveryIOUnavailableError, match="Failed to unlink target"):
            remove_installed_creation(
                target_name="note.md",
                target_parent=parent,
                expected_installed_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
                expected_installed_mode=0o640,
            )

        assert (moved_parent / "note.md").read_bytes() == content
        assert (canonical_parent / "note.md").read_bytes() == b"foreign\n"
    finally:
        os.close(parent.fd)
        assert parent.authority_fd is not None
        os.close(parent.authority_fd)
