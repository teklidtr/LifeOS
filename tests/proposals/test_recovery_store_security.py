from __future__ import annotations

import os
from pathlib import Path

import pytest

from lifeos.proposals.recovery import RecoveryLockUnavailableError
from lifeos.proposals.recovery_store import acquire_pinned_recovery_store


def test_pinned_recovery_store_survives_runtime_path_swap(tmp_path: Path) -> None:
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


def test_pinned_recovery_store_rejects_runtime_symlink_component(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(external, target_is_directory=True)

    with pytest.raises(RecoveryLockUnavailableError):
        with acquire_pinned_recovery_store(runtime_dir=runtime):
            pytest.fail("symlinked runtime must not produce a pinned recovery store")
