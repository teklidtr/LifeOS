from pathlib import Path

import pytest

from lifeos.config import LifeOSConfig
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.status import _ownership_status


def _symlink(link: Path, target: str | Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def _config(vault_root: Path) -> LifeOSConfig:
    return LifeOSConfig(vault_root=vault_root, runtime_dir=vault_root / ".lifeos")


def test_status_true_missing_ownership_manifest_remains_absent(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    status = _ownership_status(_config(vault_root))

    assert status.state == "healthy"
    assert status.code == "ownership-absent"


def test_status_dangling_ownership_manifest_symlink_is_unsafe(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "system"
    system_dir.mkdir(parents=True)
    manifest_path = system_dir / "generated-ownership.json"
    _symlink(manifest_path, "missing.json")

    status = _ownership_status(_config(vault_root))

    assert status.state == "corrupt"
    assert status.code == "ownership-unsafe-path"


def test_status_symlinked_manifest_parent_is_unsafe(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    external_system = tmp_path / "external-system"
    external_system.mkdir()
    _symlink(vault_root / "system", external_system, target_is_directory=True)

    status = _ownership_status(_config(vault_root))

    assert status.state == "corrupt"
    assert status.code == "ownership-unsafe-path"


def test_status_regular_ownership_manifest_remains_valid(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "system"
    system_dir.mkdir(parents=True)
    manifest_path = system_dir / "generated-ownership.json"
    manifest_path.write_bytes(serialize_generated_ownership_bytes({}))

    status = _ownership_status(_config(vault_root))

    assert status.state == "healthy"
    assert status.code == "ownership-valid"
