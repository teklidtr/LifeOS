from __future__ import annotations

import os
from pathlib import Path

import pytest

from lifeos.registry import Registry, RegistryOpenError


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard-link regression requires os.link")
@pytest.mark.parametrize("descriptor_bound", [False, True])
def test_registry_rejects_hard_linked_database_before_sqlite_writes(
    tmp_path: Path,
    descriptor_bound: bool,
) -> None:
    if descriptor_bound:
        if os.open not in getattr(os, "supports_dir_fd", set()):
            pytest.skip("descriptor-bound regression requires dir_fd support")
        if not Path("/proc/self/fd").is_dir():
            pytest.skip("descriptor-bound registry storage requires Linux /proc/self/fd")

    runtime = tmp_path / ".lifeos"
    runtime.mkdir()
    canonical = tmp_path / "human-note.md"
    canonical.write_bytes(b"")
    os.link(canonical, runtime / "registry.db")

    runtime_fd: int | None = None
    if descriptor_bound:
        runtime_fd = os.open(
            runtime,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )

    registry = Registry(runtime / "registry.db", directory_fd=runtime_fd)
    try:
        with pytest.raises(RegistryOpenError, match="multiple hard links"):
            registry.initialize()

        assert canonical.read_bytes() == b""
        assert (runtime / "registry.db").read_bytes() == b""
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)
