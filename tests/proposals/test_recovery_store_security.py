from __future__ import annotations

import os
from pathlib import Path

import pytest

from lifeos.proposals.recovery import RecoveryLockUnavailableError, RecoveryUnavailableError
from lifeos.proposals.recovery_store import acquire_pinned_recovery_store


def test_pinned_recovery_store_rejects_runtime_path_swap(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    parked = tmp_path / "runtime-pinned"

    with acquire_pinned_recovery_store(runtime_dir=runtime) as store:
        runtime.rename(parked)
        runtime.symlink_to(redirected, target_is_directory=True)
        (redirected / "recovery").mkdir()

        os.mkdir("marker", 0o700, dir_fd=store.recovery_fd)

        assert (parked / "recovery" / "marker").is_dir()
        assert not (redirected / "recovery" / "marker").exists()
        with pytest.raises(RecoveryUnavailableError, match="no longer identifies"):
            store.require_current_runtime_path()


def test_recovery_discovery_fails_if_runtime_path_was_replaced(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    parked = tmp_path / "runtime-pinned"

    with acquire_pinned_recovery_store(runtime_dir=runtime) as store:
        runtime.rename(parked)
        runtime.mkdir()

        with pytest.raises(RecoveryUnavailableError, match="no longer identifies"):
            store.discover()


def test_vault_authority_survives_runtime_leaf_replacement(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    parked = tmp_path / "runtime-pinned"

    with acquire_pinned_recovery_store(
        runtime_dir=runtime,
        authority_root=vault,
    ):
        runtime.rename(parked)
        runtime.mkdir()

        with pytest.raises(RecoveryLockUnavailableError, match="mutation authority"):
            with acquire_pinned_recovery_store(
                runtime_dir=runtime,
                authority_root=vault,
            ):
                pytest.fail("replacement runtime must not acquire an independent vault authority")


def test_pinned_recovery_store_rejects_runtime_symlink_component(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(external, target_is_directory=True)

    with pytest.raises(RecoveryLockUnavailableError):
        with acquire_pinned_recovery_store(runtime_dir=runtime):
            pytest.fail("symlinked runtime must not produce a pinned recovery store")
