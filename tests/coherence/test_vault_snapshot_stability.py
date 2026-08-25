from __future__ import annotations

import os
from pathlib import Path

import pytest

import lifeos.vault as vault_io
from lifeos.vault import VaultAccessError, read_vault_markdown


def test_descriptor_read_rejects_same_size_concurrent_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    target = vault / "wiki" / "note.md"
    target.parent.mkdir(parents=True)
    original = b"OLD-BYTES"
    replacement = b"NEW-BYTES"
    assert len(original) == len(replacement)
    target.write_bytes(original)

    real_read = vault_io.os.read
    rewritten = False

    def rewrite_after_first_read(fd: int, size: int) -> bytes:
        nonlocal rewritten
        content = real_read(fd, size)
        if content and not rewritten:
            rewritten = True
            before = target.stat()
            target.write_bytes(replacement)
            # Force a distinct modification marker even on coarse/virtual filesystems.
            os.utime(
                target,
                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
            )
        return content

    monkeypatch.setattr(vault_io.os, "read", rewrite_after_first_read)

    with pytest.raises(VaultAccessError) as exc_info:
        read_vault_markdown(vault, "wiki/note.md")

    assert exc_info.value.code == "concurrent-change"


def test_descriptor_read_revalidates_parent_chain_after_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "note.md"
    target.write_text("canonical", encoding="utf-8")

    real_read = vault_io.os.read
    swapped = False

    def swap_parent_then_read(fd: int, size: int) -> bytes:
        nonlocal swapped
        if not swapped:
            swapped = True
            wiki.rename(vault / "wiki-old")
            replacement = vault / "wiki"
            replacement.mkdir()
            (replacement / "note.md").write_text("replacement", encoding="utf-8")
        return real_read(fd, size)

    monkeypatch.setattr(vault_io.os, "read", swap_parent_then_read)

    with pytest.raises(VaultAccessError) as exc_info:
        read_vault_markdown(vault, "wiki/note.md")

    assert exc_info.value.code == "concurrent-change"


def test_descriptor_read_opens_fifo_nonblockingly_before_type_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "note.md"
    os.mkfifo(target)

    real_open = vault_io.os.open
    final_open_checked = False

    def require_nonblocking_final_open(path, flags, *args, **kwargs):
        nonlocal final_open_checked
        if path == "note.md" and kwargs.get("dir_fd") is not None:
            final_open_checked = True
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(vault_io.os, "open", require_nonblocking_final_open)

    with pytest.raises(VaultAccessError) as exc_info:
        read_vault_markdown(vault, "wiki/note.md")

    assert final_open_checked
    assert exc_info.value.code == "unsafe-file-type"
