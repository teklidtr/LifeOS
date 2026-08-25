from __future__ import annotations

import json
from pathlib import Path

import pytest

import lifeos.config as config_module
from lifeos.config import ConfigError, load_config


def _write_config(path: Path, *, vault: Path, runtime: str) -> Path:
    path.write_text(
        f"vault_root: {json.dumps(str(vault))}\nruntime_dir: {runtime}\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "runtime",
    ("proposals", "proposals/node-a", "system", "system/node-a"),
)
def test_config_rejects_runtime_inside_reserved_canonical_roots(
    tmp_path: Path,
    runtime: str,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = _write_config(tmp_path / "lifeos.yml", vault=vault, runtime=runtime)

    with pytest.raises(ConfigError, match="reserved canonical subtree"):
        load_config(config_path)


def test_config_retains_lexical_runtime_when_path_changes_after_component_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "runtime"
    external = tmp_path / "external-runtime"
    external.mkdir()
    config_path = _write_config(tmp_path / "lifeos.yml", vault=vault, runtime="runtime")

    def replace_after_component_check(_runtime_dir: Path) -> None:
        runtime.symlink_to(external, target_is_directory=True)

    monkeypatch.setattr(config_module, "_validate_runtime_dir", replace_after_component_check)

    config = load_config(config_path)

    assert config.runtime_dir == runtime
    assert config.runtime_dir != external
