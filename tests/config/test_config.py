from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from lifeos.config import ConfigError, FeatureFlags, LifeOSConfig, load_config


def _write_config(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def _yaml_path(path: Path) -> str:
    return json.dumps(str(path))


def test_valid_configuration_loads_as_typed_objects(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = _write_config(
        tmp_path / "config.yml",
        (
            f"vault_root: {_yaml_path(vault)}\n"
            "runtime_dir: runtime\n"
            "features:\n"
            "  graphify: true\n"
            "  exports: true\n"
        ),
    )

    config = load_config(config_path)

    assert isinstance(config, LifeOSConfig)
    assert config.vault_root == vault.resolve()
    assert config.runtime_dir == (vault / "runtime").resolve()
    assert config.features == FeatureFlags(graphify=True, exports=True)


def test_runtime_dir_defaults_to_dot_lifeos(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(vault)}\n",
    )

    config = load_config(config_path)

    assert config.runtime_dir == (vault / ".lifeos").resolve()
    assert not config.runtime_dir.exists()


def test_relative_paths_use_config_and_vault_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "settings"
    vault = config_dir / "vault"
    vault.mkdir(parents=True)
    config_path = _write_config(
        config_dir / "config.yml",
        "vault_root: vault\nruntime_dir: state/runtime\n",
    )
    monkeypatch.chdir(tmp_path)

    config = load_config(config_path)

    assert config.vault_root == vault.resolve()
    assert config.runtime_dir == (vault / "state" / "runtime").resolve()


def test_relative_config_path_uses_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "settings"
    vault = config_dir / "vault"
    vault.mkdir(parents=True)
    _write_config(config_dir / "config.yml", "vault_root: vault\n")
    monkeypatch.chdir(tmp_path)

    config = load_config(Path("settings/config.yml"))

    assert config.vault_root == vault.resolve()


def test_absolute_paths_are_not_prefixed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "external-runtime"
    config_path = _write_config(
        tmp_path / "settings" / "config.yml",
        f"vault_root: {_yaml_path(vault)}\nruntime_dir: {_yaml_path(runtime)}\n",
    )

    config = load_config(config_path)

    assert config.vault_root == vault.resolve()
    assert config.runtime_dir == runtime.resolve()
    assert config.vault_root.is_absolute()
    assert config.runtime_dir.is_absolute()


@pytest.mark.parametrize(
    ("features_yaml", "expected"),
    [
        ("", FeatureFlags()),
        ("features: {}\n", FeatureFlags()),
        ("features:\n  graphify: true\n", FeatureFlags(graphify=True)),
        ("features:\n  exports: true\n", FeatureFlags(exports=True)),
    ],
)
def test_feature_flags_default_deterministically(
    tmp_path: Path, features_yaml: str, expected: FeatureFlags
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(vault)}\n{features_yaml}",
    )

    config = load_config(config_path)

    assert config.features == expected


def test_malformed_yaml_raises_clear_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.yml", "vault_root: [\n")

    with pytest.raises(ConfigError, match="Malformed YAML") as exc_info:
        load_config(config_path)

    assert str(config_path.resolve()) in str(exc_info.value)


def test_unsafe_yaml_tag_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "config.yml",
        "vault_root: !!python/object/apply:os.getcwd []\n",
    )

    with pytest.raises(ConfigError, match="Malformed YAML"):
        load_config(config_path)


def test_missing_vault_root_raises_clear_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.yml", "features: {}\n")

    with pytest.raises(ConfigError, match="Missing required configuration key: vault_root"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("template", "field_name"),
    [
        ("vault_root: 42\n", "vault_root"),
        ('vault_root: ""\n', "vault_root"),
        ("vault_root: <vault>\nruntime_dir: false\n", "runtime_dir"),
        ("vault_root: <vault>\nfeatures: []\n", "features"),
        (
            'vault_root: <vault>\nfeatures:\n  graphify: "false"\n',
            "features.graphify",
        ),
        ("vault_root: <vault>\nfeatures:\n  exports: 1\n", "features.exports"),
    ],
)
def test_invalid_field_types_are_rejected(tmp_path: Path, template: str, field_name: str) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    contents = template.replace("<vault>", _yaml_path(vault))
    config_path = _write_config(tmp_path / "config.yml", contents)

    with pytest.raises(ConfigError, match=re.escape(field_name)):
        load_config(config_path)


def test_configuration_root_must_be_a_mapping(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.yml", "- vault\n- runtime\n")

    with pytest.raises(ConfigError, match="YAML mapping at the top level"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("extra_yaml", "unknown_key"),
    [
        ("unexpected: true\n", "unexpected"),
        ("features:\n  unsupported: false\n", "unsupported"),
    ],
)
def test_unknown_keys_are_rejected(tmp_path: Path, extra_yaml: str, unknown_key: str) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(vault)}\n{extra_yaml}",
    )

    with pytest.raises(ConfigError, match="Unknown configuration key") as exc_info:
        load_config(config_path)

    assert unknown_key in str(exc_info.value)


def test_vault_root_must_exist(tmp_path: Path) -> None:
    missing_vault = tmp_path / "missing-vault"
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(missing_vault)}\n",
    )

    with pytest.raises(ConfigError, match="vault_root.*does not exist"):
        load_config(config_path)


def test_vault_root_must_be_a_directory(tmp_path: Path) -> None:
    vault_file = tmp_path / "not-a-vault"
    vault_file.write_text("content", encoding="utf-8")
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(vault_file)}\n",
    )

    with pytest.raises(ConfigError, match="vault_root.*not a directory"):
        load_config(config_path)


def test_existing_runtime_path_must_be_a_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime_file = vault / "runtime-file"
    runtime_file.write_text("content", encoding="utf-8")
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(vault)}\nruntime_dir: runtime-file\n",
    )

    with pytest.raises(ConfigError, match="runtime_dir.*not a directory"):
        load_config(config_path)


def test_missing_configuration_file_raises_clear_error(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yml"

    with pytest.raises(ConfigError, match="Could not read configuration file") as exc_info:
        load_config(config_path)

    assert str(config_path.resolve()) in str(exc_info.value)


def test_loading_configuration_does_not_create_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "new" / "runtime"
    config_path = _write_config(
        tmp_path / "config.yml",
        f"vault_root: {_yaml_path(vault)}\nruntime_dir: new/runtime\n",
    )
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    config = load_config(config_path)

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert config.runtime_dir == runtime.resolve()
    assert before == after
    assert not runtime.exists()
