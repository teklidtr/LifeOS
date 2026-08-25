"""Typed, read-only LifeOS configuration loading."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

__all__ = ["ConfigError", "FeatureFlags", "LifeOSConfig", "load_config"]

_ALLOWED_ROOT_KEYS = frozenset({"vault_root", "runtime_dir", "features"})
_ALLOWED_FEATURE_KEYS = frozenset({"graphify", "exports"})
_DEFAULT_RUNTIME_DIR = ".lifeos"


class ConfigError(ValueError):
    """Raised when a LifeOS configuration cannot be read or validated."""


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    """Optional LifeOS features that are disabled by default."""

    graphify: bool = False
    exports: bool = False


@dataclass(frozen=True, slots=True)
class LifeOSConfig:
    """Resolved paths and feature flags used by deterministic LifeOS modules."""

    vault_root: Path
    runtime_dir: Path
    features: FeatureFlags = field(default_factory=FeatureFlags)


def load_config(config_path: str | Path) -> LifeOSConfig:
    """Load and validate a configuration file without modifying the filesystem."""
    source_path = _normalize_path(
        Path(config_path),
        base=Path.cwd(),
        field_name="configuration file",
    )
    document = _read_yaml(source_path)

    if document is None:
        data: Mapping[object, object] = {}
    elif isinstance(document, Mapping):
        data = document
    else:
        raise ConfigError(
            f"Configuration file {source_path} must contain a YAML mapping at the top level."
        )

    _reject_unknown_keys(data, _ALLOWED_ROOT_KEYS, location="configuration root")

    if "vault_root" not in data:
        raise ConfigError("Missing required configuration key: vault_root.")

    vault_path = _parse_path(data["vault_root"], field_name="vault_root")
    vault_root = _normalize_path(
        vault_path,
        base=source_path.parent,
        field_name="vault_root",
    )
    _validate_vault_root(vault_root)

    runtime_value = data.get("runtime_dir", _DEFAULT_RUNTIME_DIR)
    runtime_path = _parse_path(runtime_value, field_name="runtime_dir")
    runtime_candidate = _lexical_absolute_path(runtime_path, base=vault_root)
    _reject_runtime_symlink_components(runtime_candidate)
    runtime_dir = _normalize_path(
        runtime_candidate,
        base=vault_root,
        field_name="runtime_dir",
    )
    _validate_runtime_dir(runtime_dir)

    features = _parse_features(data.get("features", {}))
    return LifeOSConfig(vault_root=vault_root, runtime_dir=runtime_dir, features=features)


def _read_yaml(source_path: Path) -> object:
    try:
        contents = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Could not read configuration file {source_path}: {exc}") from exc

    try:
        document: object = yaml.safe_load(contents)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML in configuration file {source_path}: {exc}") from exc
    return document


def _parse_path(value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"Configuration field '{field_name}' must be a non-empty string path; "
            f"got {type(value).__name__}."
        )
    if "\x00" in value:
        raise ConfigError(f"Configuration field '{field_name}' contains an invalid null byte.")
    return Path(value)


def _lexical_absolute_path(path: Path, *, base: Path) -> Path:
    candidate = path if path.is_absolute() else base / path
    return Path(os.path.abspath(candidate))


def _reject_runtime_symlink_components(runtime_dir: Path) -> None:
    """Reject existing symlink components before runtime resolution loses lexical topology."""
    current = Path(runtime_dir.anchor)
    parts = runtime_dir.parts[1:] if runtime_dir.anchor else runtime_dir.parts
    for part in parts:
        current = current / part
        try:
            state = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ConfigError(
                f"Could not inspect configuration field 'runtime_dir': {exc}"
            ) from exc
        if stat.S_ISLNK(state.st_mode):
            raise ConfigError(
                f"Configuration field 'runtime_dir' contains a symlink component: {current}"
            )


def _normalize_path(path: Path, *, base: Path, field_name: str) -> Path:
    candidate = path if path.is_absolute() else base / path
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ConfigError(f"Could not resolve configuration field '{field_name}': {exc}") from exc


def _validate_vault_root(vault_root: Path) -> None:
    if not vault_root.exists():
        raise ConfigError(f"Configuration field 'vault_root' does not exist: {vault_root}")
    if not vault_root.is_dir():
        raise ConfigError(f"Configuration field 'vault_root' is not a directory: {vault_root}")


def _validate_runtime_dir(runtime_dir: Path) -> None:
    if runtime_dir.exists() and not runtime_dir.is_dir():
        raise ConfigError(f"Configuration field 'runtime_dir' is not a directory: {runtime_dir}")


def _parse_features(value: object) -> FeatureFlags:
    if not isinstance(value, Mapping):
        raise ConfigError(
            f"Configuration field 'features' must be a mapping; got {type(value).__name__}."
        )

    _reject_unknown_keys(value, _ALLOWED_FEATURE_KEYS, location="features")
    return FeatureFlags(
        graphify=_parse_bool(value, "graphify"),
        exports=_parse_bool(value, "exports"),
    )


def _parse_bool(data: Mapping[object, object], key: str) -> bool:
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(
            f"Configuration field 'features.{key}' must be a boolean; got {type(value).__name__}."
        )
    return value


def _reject_unknown_keys(
    data: Mapping[object, object],
    allowed: frozenset[str],
    *,
    location: str,
) -> None:
    unknown = sorted(
        (key for key in data if not isinstance(key, str) or key not in allowed),
        key=repr,
    )
    if not unknown:
        return

    keys = ", ".join(repr(key) for key in unknown)
    raise ConfigError(f"Unknown configuration key(s) in {location}: {keys}.")
