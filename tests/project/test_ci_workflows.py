from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FULL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "full-validation.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _restore_keys_block(workflow: str) -> str:
    return workflow.split("restore-keys: |", 1)[1].split("\n\n", 1)[0]


def test_fast_pr_workflow_keeps_expensive_gates_out_of_synchronize_path() -> None:
    workflow = _read(FAST_WORKFLOW)

    assert "types: [opened, synchronize, reopened]" in workflow
    assert "name: fast-checks" in workflow
    assert "uv run pytest --collect-only -q" in workflow
    assert "uv run pytest -q tests/project" in workflow
    assert "run: uv run pytest -q\n" not in workflow
    assert "run-setup-integration-docker.sh" not in workflow


def test_fast_pr_workflow_has_safe_documentation_only_path() -> None:
    workflow = _read(FAST_WORKFLOW)

    assert "--ci-scope-output \"$GITHUB_OUTPUT\"" in workflow
    assert "--scope-only" in workflow
    assert "*.md) ;;" not in workflow
    assert 'python scripts/check_documentation_impact.py --base-ref' in workflow
    assert "python scripts/validate_manual_links.py" in workflow
    assert "if: steps.scope.outputs.docs_only != 'true'" in workflow


def test_full_validation_is_explicit_complete_and_statelessly_sharded() -> None:
    workflow = _read(FULL_WORKFLOW)

    assert "types: [labeled]" in workflow
    assert "github.event.label.name == 'full-validation'" in workflow
    assert "push:\n    branches: [master]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "format('full-test-shard-{0}', matrix.group)" in workflow
    assert "group: [1, 2, 3, 4]" in workflow
    assert "pytest-split==0.11.0" in workflow
    assert "--splits 4" in workflow
    assert "--group ${{ matrix.group }}" in workflow
    assert "'full-test'" in workflow
    assert "needs: full_test_shard" in workflow
    assert "needs.full_test_shard.result" in workflow
    assert "uv run pytest --collect-only -q" not in workflow
    assert ".test_durations" not in workflow
    assert "run: ./scripts/run-setup-integration-docker.sh" in workflow


def test_unrelated_labels_cannot_emit_required_full_validation_check_names() -> None:
    workflow = _read(FULL_WORKFLOW)

    assert "full-test-not-requested" in workflow
    assert "docker-setup-e2e-not-requested" in workflow
    assert "full-test-shard-{0}-not-requested" in workflow
    assert "github.event.label.name != 'full-validation'" in workflow


def test_pr_concurrency_preserves_current_fast_check_and_supersedes_stale_full_run() -> None:
    fast = _read(FAST_WORKFLOW)
    full = _read(FULL_WORKFLOW)

    assert "lifeos-pr-${{ github.event.pull_request.number }}" in fast
    assert "format('lifeos-pr-{0}', github.event.pull_request.number)" in full
    assert "cancel-in-progress: true" in fast
    assert "cancel-in-progress: ${{ github.event_name != 'pull_request' }}" in full


def test_mypy_cache_rotates_primary_key_and_restores_compatible_state() -> None:
    expected_hash = "hashFiles('.python-version', 'uv.lock', 'pyproject.toml')"
    fast = _read(FAST_WORKFLOW)
    full = _read(FULL_WORKFLOW)

    for workflow in (fast, full):
        assert "uses: actions/cache@v4" in workflow
        assert "path: .mypy_cache" in workflow
        assert "mypy-v2-" in workflow
        assert expected_hash in workflow
        assert "${{ github.sha }}" in workflow
        assert "github.sha" not in _restore_keys_block(workflow)
        assert "uv run mypy src" in workflow

    assert "${{ github.event.pull_request.number }}-${{ github.sha }}" in fast
    assert "${{ github.event.pull_request.number }}-\n" in _restore_keys_block(fast)
    assert "${{ github.event.pull_request.number || github.ref_name }}-${{ github.sha }}" in full
    assert "${{ github.event.pull_request.number || github.ref_name }}-\n" in _restore_keys_block(full)
