from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.config import ConfigError, load_config


def test_config_rejects_existing_runtime_symlink_before_resolution(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    external = tmp_path / "external-runtime"
    external.mkdir()
    (vault / "runtime-link").symlink_to(external, target_is_directory=True)
    config_path = tmp_path / "lifeos.yml"
    config_path.write_text(
        f"vault_root: {vault}\nruntime_dir: runtime-link\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="runtime_dir.*symlink component"):
        load_config(config_path)
