from __future__ import annotations

import json
import tomllib
from pathlib import Path

from lifeos.bridge.protocol import PROTOCOL_VERSION
from lifeos.conversations import CONVERSATION_SCHEMA_VERSION
from lifeos.experiments import EXPERIMENT_SCHEMA_VERSION
from lifeos.retrieval import INDEX_SCHEMA_VERSION
from lifeos.versioning import (
    DESKTOP_RUNTIME_SCHEMA_VERSION,
    MINIMUM_PLUGIN_VERSION,
    PYTHON_PACKAGE_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
RICH_CAPTURE_TESTING = REPO_ROOT / "docs" / "rich-capture-testing.md"
RICH_CAPTURE_VALIDATOR = REPO_ROOT / "scripts" / "validate-rich-capture.sh"
RETIRED_RELEASE_SCRIPTS = (
    "build-release.sh",
    "validate-release.sh",
    "validate-first-class-reviews.sh",
    "validate-semantic-retrieval.sh",
    "validate-personal-experiments.sh",
)
SEMANTIC_PROVIDER_NEUTRAL_PATHS = (
    "src/lifeos/retrieval/contracts.py",
    "src/lifeos/retrieval/index.py",
    "src/lifeos/retrieval/search.py",
    "src/lifeos/conversations/contracts.py",
    "src/lifeos/conversations/grounding.py",
    "packages/obsidian-plugin/src/knowledge-conversation.ts",
    "packages/obsidian-plugin/src/knowledge-conversation-workspace.ts",
)
EXPERIMENT_PROVIDER_NEUTRAL_PATHS = (
    *(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src/lifeos/experiments").glob("*.py")
    ),
    "packages/obsidian-plugin/src/experiment.ts",
    "packages/obsidian-plugin/src/experiment-workspace.ts",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _joined_contract_text(paths: tuple[str, ...]) -> str:
    return "\n".join(_read(REPO_ROOT / path).casefold() for path in paths)


def test_legacy_release_chain_is_not_a_supported_entry_point() -> None:
    scripts = REPO_ROOT / "scripts"

    for filename in RETIRED_RELEASE_SCRIPTS:
        assert not (scripts / filename).exists(), filename


def test_readme_documents_the_authoritative_release_readiness_path() -> None:
    readme = _read(README)

    assert "`fast-checks` runs on ordinary PR" in readme
    assert "The separate `obsidian-plugin` PR job" in readme
    assert "A full checkpoint is requested by adding the `full-validation` label" in readme
    assert "`full-test`" in readme
    assert "`docker-setup-e2e`" in readme


def test_package_plugin_protocol_and_runtime_versions_remain_compatible() -> None:
    pyproject = tomllib.loads(_read(REPO_ROOT / "pyproject.toml"))
    package = json.loads(_read(REPO_ROOT / "packages/obsidian-plugin/package.json"))
    lock = json.loads(_read(REPO_ROOT / "packages/obsidian-plugin/package-lock.json"))
    manifest = json.loads(_read(REPO_ROOT / "packages/obsidian-plugin/manifest.json"))
    protocol_source = _read(REPO_ROOT / "packages/obsidian-plugin/src/protocol.ts")

    assert pyproject["project"]["version"] == PYTHON_PACKAGE_VERSION
    assert package["version"] == manifest["version"] == lock["version"]
    assert package["version"] == lock["packages"][""]["version"]
    assert _version_tuple(package["version"]) >= _version_tuple(MINIMUM_PLUGIN_VERSION)
    assert PROTOCOL_VERSION.split(".")[0] == "1"
    assert f'PROTOCOL_VERSION = "{PROTOCOL_VERSION}"' in protocol_source
    assert f"RUNTIME_SCHEMA_VERSION = {DESKTOP_RUNTIME_SCHEMA_VERSION}" in protocol_source
    assert DESKTOP_RUNTIME_SCHEMA_VERSION == 1


def test_historical_feature_schema_guards_remain_in_current_project_contract() -> None:
    assert INDEX_SCHEMA_VERSION == 1
    assert CONVERSATION_SCHEMA_VERSION == 1
    assert EXPERIMENT_SCHEMA_VERSION == 1


def test_historical_feature_provider_neutrality_guards_remain_in_project_contract() -> None:
    semantic = _joined_contract_text(SEMANTIC_PROVIDER_NEUTRAL_PATHS)
    experiments = _joined_contract_text(EXPERIMENT_PROVIDER_NEUTRAL_PATHS)

    for provider in ("anthropic", "claude"):
        assert provider not in semantic
    for provider in ("anthropic", "claude", "openai"):
        assert provider not in experiments


def test_rich_capture_validator_is_explicitly_focused_not_release_authority() -> None:
    testing = _read(RICH_CAPTURE_TESTING)

    assert RICH_CAPTURE_VALIDATOR.exists()
    assert "is retained as a focused local Rich Capture" in testing
    assert "It is not a repository release gate" in testing
    assert "`fast-checks`" in testing
    assert "`obsidian-plugin`" in testing
    assert "`full-validation`" in testing
