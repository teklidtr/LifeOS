import os
from pathlib import Path
import pytest

from lifeos._atomic_write import atomic_write_file_secure, AtomicWriteError


def test_atomic_write_success(tmp_path: Path) -> None:
    target = "test.txt"
    dir_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        content = b"hello world"
        durability = atomic_write_file_secure(dir_fd, target, content)

        # Verify content
        with open(tmp_path / target, "rb") as f:
            assert f.read() == content

        # Verify no temp files left
        assert len(list(tmp_path.iterdir())) == 1

        # In testing environments, dir fsync may not be supported or allowed
        assert durability in ("confirmed", "uncertain")

    finally:
        os.close(dir_fd)


def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    target = "test.txt"
    (tmp_path / target).write_bytes(b"old content")

    dir_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        content = b"new content"
        atomic_write_file_secure(dir_fd, target, content)

        with open(tmp_path / target, "rb") as f:
            assert f.read() == content
    finally:
        os.close(dir_fd)


def test_atomic_write_bad_dir_fd() -> None:
    with pytest.raises(AtomicWriteError) as exc:
        atomic_write_file_secure(-1, "test.txt", b"content")
    assert exc.value.write_occurred is False
