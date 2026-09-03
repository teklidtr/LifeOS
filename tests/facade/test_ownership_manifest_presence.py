from pathlib import Path

import pytest

from lifeos.facade.errors import ToolValidationError
from lifeos.facade.proposal_tools import _load_generated_ownership
from lifeos.ownership import PathSafetyError
from lifeos.ownership.manifest import serialize_generated_ownership_bytes


def _symlink(link: Path, target: str | Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_facade_true_missing_ownership_manifest_keeps_missing_error(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    with pytest.raises(ToolValidationError, match="Generated ownership manifest is missing"):
        _load_generated_ownership(vault_root=vault_root)


def test_facade_dangling_manifest_symlink_is_invalid_not_missing(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "system"
    system_dir.mkdir(parents=True)
    manifest_path = system_dir / "generated-ownership.json"
    _symlink(manifest_path, "missing.json")

    with pytest.raises(ToolValidationError, match="Generated ownership manifest is invalid") as exc_info:
        _load_generated_ownership(vault_root=vault_root)

    assert isinstance(exc_info.value.__cause__, PathSafetyError)


def test_facade_regular_ownership_manifest_still_loads(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "system"
    system_dir.mkdir(parents=True)
    manifest_path = system_dir / "generated-ownership.json"
    manifest_path.write_bytes(serialize_generated_ownership_bytes({}))

    ownership = _load_generated_ownership(vault_root=vault_root)

    assert ownership.entries == {}
