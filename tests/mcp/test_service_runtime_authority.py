from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.config import LifeOSConfig
from lifeos.mcp.service import ServiceReadiness
from lifeos.registry import Registry
from lifeos.runtime import ActivityStore
from lifeos.runtime.activity import (
    push_activity_runtime_dir_fd,
    reset_activity_runtime_dir_fd,
)
from lifeos.runtime.authority import RuntimeDirectoryAuthority

pytestmark = pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="home-node descriptor-bound registry storage requires Linux /proc/self/fd",
)


def _service_fixture(tmp_path: Path) -> tuple[LifeOSConfig, Path, Path]:
    vault = tmp_path / "vault"
    (vault / "proposals").mkdir(parents=True)
    wiki = vault / "wiki"
    wiki.mkdir()
    runtime = vault / ".lifeos"
    runtime.mkdir()
    return LifeOSConfig(vault_root=vault, runtime_dir=runtime), runtime, wiki


def _replace_runtime_with_symlink(runtime: Path, target: Path) -> Path:
    held_runtime = runtime.with_name(".lifeos-held")
    runtime.rename(held_runtime)
    runtime.symlink_to(target, target_is_directory=True)
    return held_runtime


def test_service_readiness_rejects_runtime_symlink_swap(tmp_path: Path) -> None:
    config, runtime, wiki = _service_fixture(tmp_path)
    authority = RuntimeDirectoryAuthority.open(runtime)
    try:
        readiness = ServiceReadiness(
            config,
            config.vault_root / "lifeos.yml",
            runtime_authority=authority,
        )
        assert readiness.ready()

        _replace_runtime_with_symlink(runtime, wiki)

        assert not readiness.ready()
    finally:
        authority.close()


def test_activity_store_remains_bound_to_original_runtime_inode(tmp_path: Path) -> None:
    config, runtime, wiki = _service_fixture(tmp_path)
    authority = RuntimeDirectoryAuthority.open(runtime)
    try:
        store = ActivityStore(config.runtime_dir, runtime_dir_fd=authority.fd)
        held_runtime = _replace_runtime_with_symlink(runtime, wiki)

        store.append(tool="vault_list")

        assert (held_runtime / "activity" / "mcp.jsonl").is_file()
        assert not (wiki / "activity" / "mcp.jsonl").exists()
    finally:
        authority.close()


def test_activity_store_inherits_bound_runtime_authority(tmp_path: Path) -> None:
    config, runtime, wiki = _service_fixture(tmp_path)
    authority = RuntimeDirectoryAuthority.open(runtime)
    try:
        token = push_activity_runtime_dir_fd(authority.fd)
        try:
            store = ActivityStore(config.runtime_dir)
        finally:
            reset_activity_runtime_dir_fd(token)
        held_runtime = _replace_runtime_with_symlink(runtime, wiki)

        store.append(tool="proposal_submit")

        assert (held_runtime / "activity" / "mcp.jsonl").is_file()
        assert not (wiki / "activity" / "mcp.jsonl").exists()
    finally:
        authority.close()


def test_registry_remains_bound_to_original_runtime_inode(tmp_path: Path) -> None:
    config, runtime, wiki = _service_fixture(tmp_path)
    authority = RuntimeDirectoryAuthority.open(runtime)
    try:
        registry = Registry(config.runtime_dir / "registry.db", directory_fd=authority.fd)
        held_runtime = _replace_runtime_with_symlink(runtime, wiki)

        registry.initialize()

        assert (held_runtime / "registry.db").is_file()
        assert registry.schema_version > 0
        assert not (wiki / "registry.db").exists()
    finally:
        authority.close()
