from __future__ import annotations

from pathlib import Path

from lifeos.coherence_scoped import runtime_exclusion_prefix


def test_in_vault_runtime_prefix_survives_symlink_topology_change(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    external = tmp_path / "external-runtime"
    external.mkdir()
    runtime = vault / "runtime-node"
    runtime.symlink_to(external, target_is_directory=True)

    assert runtime_exclusion_prefix(vault, runtime_dir=runtime) == "runtime-node/"

    runtime.unlink()
    runtime.mkdir()

    assert runtime_exclusion_prefix(vault, runtime_dir=runtime) == "runtime-node/"
