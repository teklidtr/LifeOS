from __future__ import annotations

from pathlib import Path


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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def test_rich_capture_validator_is_explicitly_focused_not_release_authority() -> None:
    testing = _read(RICH_CAPTURE_TESTING)

    assert RICH_CAPTURE_VALIDATOR.exists()
    assert "is retained as a focused local Rich Capture" in testing
    assert "It is not a repository release gate" in testing
    assert "`fast-checks`" in testing
    assert "`obsidian-plugin`" in testing
    assert "`full-validation`" in testing
