from pathlib import Path

import pytest

from lifeos.lint.linter import lint_vault
from lifeos.ownership import PathSafetyError


def _symlink(link: Path, target: str | Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_missing_ownership_manifest_remains_clean(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    manifest_path = vault_root / "system" / "generated-ownership.json"

    result = lint_vault(vault_root, [], manifest_path)

    assert result.error_count == 0
    assert result.findings == ()


def test_dangling_ownership_manifest_symlink_is_not_skipped(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "system"
    system_dir.mkdir(parents=True)
    manifest_path = system_dir / "generated-ownership.json"
    _symlink(manifest_path, "missing.json")

    with pytest.raises(PathSafetyError, match="Manifest path or parent is a symlink"):
        lint_vault(vault_root, [], manifest_path)
