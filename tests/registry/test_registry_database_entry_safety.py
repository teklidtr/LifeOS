from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import lifeos.registry._registry as registry_module
from lifeos.registry import Registry, RegistryOpenError


pytestmark = pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="registry inode-binding regressions require Linux /proc/self/fd",
)


def _runtime_fd(runtime: Path, descriptor_bound: bool) -> int | None:
    if not descriptor_bound:
        return None
    if os.open not in getattr(os, "supports_dir_fd", set()):
        pytest.skip("descriptor-bound regression requires dir_fd support")
    return os.open(runtime, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard-link regression requires os.link")
@pytest.mark.parametrize("descriptor_bound", [False, True])
def test_registry_rejects_hard_linked_database_before_sqlite_writes(
    tmp_path: Path,
    descriptor_bound: bool,
) -> None:
    runtime = tmp_path / ".lifeos"
    runtime.mkdir()
    canonical = tmp_path / "human-note.md"
    canonical.write_bytes(b"")
    os.link(canonical, runtime / "registry.db")

    runtime_fd = _runtime_fd(runtime, descriptor_bound)
    registry = Registry(runtime / "registry.db", directory_fd=runtime_fd)
    try:
        with pytest.raises(RegistryOpenError, match="multiple hard links"):
            registry.initialize()

        assert canonical.read_bytes() == b""
        assert (runtime / "registry.db").read_bytes() == b""
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard-link regression requires os.link")
@pytest.mark.parametrize("descriptor_bound", [False, True])
def test_registry_sqlite_open_stays_bound_to_validated_inode_during_name_swap(
    tmp_path: Path,
    descriptor_bound: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / ".lifeos"
    runtime.mkdir()
    database = runtime / "registry.db"
    database.touch()
    canonical = tmp_path / "human-note.md"
    canonical.write_bytes(b"")
    held = runtime / "registry-held.db"

    runtime_fd = _runtime_fd(runtime, descriptor_bound)
    registry = Registry(database, directory_fd=runtime_fd)
    real_connect = sqlite3.connect
    swapped = False

    def racing_connect(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            database.rename(held)
            os.link(canonical, database)
            swapped = True
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(registry_module.sqlite3, "connect", racing_connect)
    try:
        registry.initialize()

        assert swapped
        assert canonical.read_bytes() == b""
        assert database.read_bytes() == b""
        assert held.stat().st_size > 0
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard-link regression requires os.link")
@pytest.mark.parametrize("descriptor_bound", [False, True])
def test_registry_writes_do_not_touch_hard_linked_sqlite_journal_sidecar(
    tmp_path: Path,
    descriptor_bound: bool,
) -> None:
    runtime = tmp_path / ".lifeos"
    runtime.mkdir()
    canonical = tmp_path / "human-note.md"
    canonical.write_bytes(b"")
    journal = runtime / "registry.db-journal"
    os.link(canonical, journal)

    runtime_fd = _runtime_fd(runtime, descriptor_bound)
    registry = Registry(runtime / "registry.db", directory_fd=runtime_fd)
    try:
        registry.initialize()

        assert registry.schema_version > 0
        assert canonical.read_bytes() == b""
        assert journal.exists()
        assert journal.stat().st_ino == canonical.stat().st_ino
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)
