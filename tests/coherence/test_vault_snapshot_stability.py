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

    real_read_all = vault_io._read_all

    def rewrite_after_read(fd: int, relative_path: str) -> bytes:
        content = real_read_all(fd, relative_path)
        before = target.stat()
        target.write_bytes(replacement)
        # Force a distinct modification marker even on coarse/virtual filesystems.
        os.utime(
            target,
            ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
        )
        return content

    monkeypatch.setattr(vault_io, "_read_all", rewrite_after_read)

    with pytest.raises(VaultAccessError) as exc_info:
        read_vault_markdown(vault, "wiki/note.md")

    assert exc_info.value.code == "concurrent-change"
