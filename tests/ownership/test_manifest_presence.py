from pathlib import Path

import pytest

from lifeos.ownership import GeneratedOwnership, PathSafetyError


def _symlink(link: Path, target: str | Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_load_if_present_distinguishes_true_missing_from_load_fallback(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    manifest_path = vault_root / "system" / "generated-ownership.json"

    assert GeneratedOwnership.load_if_present(manifest_path, vault_root) is None
    assert GeneratedOwnership.load(manifest_path, vault_root).entries == {}


def test_load_if_present_rejects_dangling_final_symlink(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "system"
    system_dir.mkdir(parents=True)
    manifest_path = system_dir / "generated-ownership.json"
    _symlink(manifest_path, "missing.json")

    with pytest.raises(PathSafetyError, match="Manifest path or parent is a symlink"):
        GeneratedOwnership.load_if_present(manifest_path, vault_root)


def test_load_if_present_rejects_symlinked_parent(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    external_system = tmp_path / "external-system"
    external_system.mkdir()
    _symlink(vault_root / "system", external_system, target_is_directory=True)
    manifest_path = vault_root / "system" / "generated-ownership.json"

    with pytest.raises(PathSafetyError, match="Manifest path or parent is a symlink"):
        GeneratedOwnership.load_if_present(manifest_path, vault_root)
