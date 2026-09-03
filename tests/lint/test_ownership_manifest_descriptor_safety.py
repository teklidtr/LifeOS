import os
from pathlib import Path

import pytest

from lifeos.lint.linter import lint_vault


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_nonregular_ownership_manifest_is_reported_not_raised(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    system_dir = vault_root / "system"
    system_dir.mkdir()
    manifest_path = system_dir / "generated-ownership.json"
    os.mkfifo(manifest_path)

    result = lint_vault(vault_root, [], manifest_path)

    assert result.error_count == 1
    assert result.findings[0].code == "ownership-manifest-invalid"
    assert result.findings[0].path == Path("system/generated-ownership.json")
