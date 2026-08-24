from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FULL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "full-validation.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fast_pr_workflow_keeps_expensive_gates_out_of_synchronize_path() -> None:
    workflow = _read(FAST_WORKFLOW)

    assert "types: [opened, synchronize, reopened]" in workflow
    assert "name: fast-checks" in workflow
    assert "uv run pytest --collect-only -q" in workflow
    assert "uv run pytest -q tests/project" in workflow
    assert "run: uv run pytest -q\n" not in workflow
    assert "run-setup-integration-docker.sh" not in workflow


def test_fast_pr_workflow_has_safe_markdown_only_path() -> None:
    workflow = _read(FAST_WORKFLOW)

    assert "docs_only=true" in workflow
    assert "*.md) ;;" in workflow
    assert 'python scripts/check_documentation_impact.py --base-ref' in workflow
    assert "python scripts/validate_manual_links.py" in workflow
    assert "if: steps.scope.outputs.docs_only != 'true'" in workflow


def test_full_validation_is_explicit_and_complete() -> None:
    workflow = _read(FULL_WORKFLOW)

    assert "types: [labeled]" in workflow
    assert "github.event.label.name == 'full-validation'" in workflow
    assert "push:\n    branches: [master]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "name: full-test" in workflow
    assert "run: uv run pytest -q\n" in workflow
    assert "run: ./scripts/run-setup-integration-docker.sh" in workflow


def test_pr_workflows_share_supersession_concurrency_group() -> None:
    fast = _read(FAST_WORKFLOW)
    full = _read(FULL_WORKFLOW)

    assert "lifeos-pr-${{ github.event.pull_request.number }}" in fast
    assert "format('lifeos-pr-{0}', github.event.pull_request.number)" in full
    assert "cancel-in-progress: true" in fast
    assert "cancel-in-progress: true" in full


def test_mypy_cache_is_toolchain_scoped_not_source_sha_scoped() -> None:
    expected_hash = "hashFiles('.python-version', 'uv.lock', 'pyproject.toml')"

    for path in (FAST_WORKFLOW, FULL_WORKFLOW):
        workflow = _read(path)
        assert "uses: actions/cache@v4" in workflow
        assert "path: .mypy_cache" in workflow
        assert expected_hash in workflow
        assert "github.sha" not in workflow
        assert "uv run mypy src" in workflow
