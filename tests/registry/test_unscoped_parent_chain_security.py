from __future__ import annotations

import os
from pathlib import Path

import pytest

from lifeos.registry import file_tracking


def test_registry_revalidation_rejects_parent_symlink_aba(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    note = wiki / "note.md"
    note.write_text("# Stable\n", encoding="utf-8")

    absolute = Path(os.path.abspath(note))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    opened: list[int] = []
    try:
        current_fd = os.open(absolute.anchor, flags)
        opened.append(current_fd)
        chain = [file_tracking._fd_identity(current_fd)]
        for component in absolute.parts[1:-1]:
            current_fd = os.open(component, flags, dir_fd=current_fd)
            opened.append(current_fd)
            chain.append(file_tracking._fd_identity(current_fd))
        file_fd = os.open(absolute.parts[-1], file_flags, dir_fd=current_fd)
        opened.append(file_fd)
        chain.append(file_tracking._fd_identity(file_fd))
    finally:
        for fd in reversed(opened):
            os.close(fd)

    parked = vault / "wiki-parked"
    wiki.rename(parked)
    wiki.symlink_to(parked, target_is_directory=True)

    with pytest.raises(file_tracking.FileTrackingError, match="changed during hashing"):
        file_tracking._revalidate_hash_path_chain(
            absolute,
            expected_chain=tuple(chain),
            display_path=note,
        )
