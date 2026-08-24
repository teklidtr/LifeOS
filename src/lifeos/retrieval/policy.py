"""Strict fail-closed loading for optional canonical retrieval policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from lifeos.retrieval.contracts import RetrievalError, RetrievalPolicy
from lifeos.vault import VaultAccessError, read_vault_text

_ALLOWED = {
    "schema_version",
    "excluded_prefixes",
    "protected_prefixes",
    "external_allowed_prefixes",
    "max_external_characters",
}
_POLICY_PATH = "system/retrieval-policy.yml"


def load_retrieval_policy(vault_root: Path) -> RetrievalPolicy:
    try:
        source = read_vault_text(vault_root, _POLICY_PATH)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return RetrievalPolicy()
        raise RetrievalError(
            "invalid_policy",
            "Could not read retrieval policy safely.",
        ) from exc
    try:
        raw: Any = yaml.safe_load(source.content)
    except yaml.YAMLError as exc:
        raise RetrievalError("invalid_policy", "Could not parse retrieval policy.") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise RetrievalError("invalid_policy", "Retrieval policy must be a YAML mapping.")
    unknown = sorted(set(raw) - _ALLOWED)
    if unknown:
        raise RetrievalError("invalid_policy", f"Unknown retrieval policy fields: {', '.join(unknown)}")

    def strings(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = raw.get(key, list(default))
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise RetrievalError("invalid_policy", f"{key} must be a list of strings.")
        return tuple(value)

    return RetrievalPolicy(
        schema_version=raw.get("schema_version", 1),
        excluded_prefixes=strings("excluded_prefixes", ()),
        protected_prefixes=strings("protected_prefixes", RetrievalPolicy().protected_prefixes),
        external_allowed_prefixes=strings("external_allowed_prefixes", ()),
        max_external_characters=raw.get("max_external_characters", 24_000),
    )
