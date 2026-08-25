from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import lifeos.registry.coherent_tracking as coherent_tracking
from lifeos.registry import FileTrackingError, Registry, register_scan
from lifeos.scanner import scan_vault


def _note(stable_id: str) -> str:
    return f"---\nid: {stable_id}\ntype: wiki\ntitle: Example\n---\nBody\n"


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def test_unscoped_registry_rejects_symlink_replacement_after_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "note.md"
    target.write_text(_note("canonical-id"), encoding="utf-8")
    entries = scan_vault(vault)

    outside = tmp_path / "outside.md"
    outside.write_text(_note("outside-id"), encoding="utf-8")
    target.unlink()
    target.symlink_to(outside)

    registry = _registry(tmp_path)
    with pytest.raises(FileTrackingError, match="safely open registry file"):
        register_scan(registry, vault, entries)

    with registry.connect_read_only() as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0


def test_scoped_registry_rejects_ctime_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "note.md"
    target.write_text(_note("canonical-id"), encoding="utf-8")
    entries = scan_vault(vault)
    registry = _registry(tmp_path)

    real_fstat = coherent_tracking.os.fstat
    regular_calls = 0

    def changed_ctime_only(fd: int):
        nonlocal regular_calls
        value = real_fstat(fd)
        if not stat.S_ISREG(value.st_mode):
            return value
        regular_calls += 1
        if regular_calls != 2:
            return value
        return SimpleNamespace(
            st_mode=value.st_mode,
            st_dev=value.st_dev,
            st_ino=value.st_ino,
            st_mtime_ns=value.st_mtime_ns,
            st_ctime_ns=value.st_ctime_ns + 1,
            st_size=value.st_size,
        )

    monkeypatch.setattr(coherent_tracking.os, "fstat", changed_ctime_only)

    with pytest.raises(FileTrackingError, match="changed during scoped hashing"):
        register_scan(
            registry,
            vault,
            entries,
            identity_allow_path=lambda _path: True,
        )
