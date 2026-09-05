from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FULL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "full-validation.yml"
HOME_NODE_DOCKERFILE = REPO_ROOT / "deploy" / "home-node" / "Dockerfile"
SETUP_DOCKERFILE = REPO_ROOT / "tests" / "integration" / "docker" / "Dockerfile.setup"
ARM64_VALIDATION_SCRIPT = REPO_ROOT / "scripts" / "validate-home-node-arm64-docker.sh"


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


def test_pr_workflow_has_explicit_obsidian_plugin_checkpoint() -> None:
    workflow = _read(FAST_WORKFLOW)
    plugin_job = workflow.split("\n  obsidian-plugin:\n", 1)[1]

    assert "name: obsidian-plugin" in plugin_job
    assert "uses: actions/setup-node@v4" in plugin_job
    assert 'node-version: "24"' in plugin_job
    assert "cache: npm" in plugin_job
    assert "cache-dependency-path: packages/obsidian-plugin/package-lock.json" in plugin_job
    assert "npm --prefix packages/obsidian-plugin ci" in plugin_job
    assert "npm --prefix packages/obsidian-plugin run lint" in plugin_job
    assert "npm --prefix packages/obsidian-plugin run typecheck" in plugin_job
    assert "npm --prefix packages/obsidian-plugin test" in plugin_job
    assert "npm --prefix packages/obsidian-plugin run build" in plugin_job
    assert "if: steps.scope.outputs.docs_only != 'true'" in plugin_job
    assert "if: steps.scope.outputs.docs_only == 'true'" in plugin_job
    assert "Obsidian plugin validation skipped" in plugin_job


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


def test_full_validation_keeps_native_docker_gates_before_arm64_setup() -> None:
    workflow = _read(FULL_WORKFLOW)

    setup_gate = workflow.index("run: ./scripts/run-setup-integration-docker.sh")
    home_node_gate = workflow.index("run: bash scripts/run-home-node-integration-docker.sh")
    qemu_setup = workflow.index("- name: Set up QEMU")
    buildx_setup = workflow.index("- name: Set up Docker Buildx")
    arm64_build = workflow.index("- name: Build ARM64 home-node image with reusable layers")

    assert setup_gate < home_node_gate < qemu_setup < buildx_setup < arm64_build
    assert "platforms: arm64" in workflow


def test_arm64_build_uses_disposable_bounded_gha_layers_and_cold_fallback() -> None:
    workflow = _read(FULL_WORKFLOW)

    assert "docker/build-push-action@" in workflow
    assert "platforms: linux/arm64" in workflow
    assert "outputs: type=cacheonly" in workflow
    assert (
        "cache-from: type=gha,scope=lifeos-home-node-arm64,timeout=1m"
        in workflow
    )
    assert (
        "cache-to: type=gha,mode=max,scope=lifeos-home-node-arm64,"
        "ignore-error=true,timeout=1m"
        in workflow
    )
    assert "continue-on-error: true" in workflow
    assert "if: steps.arm64-build.outcome == 'failure'" in workflow
    assert "no-cache: true" in workflow
    assert "validate-home-node-arm64-docker.sh" not in workflow


def test_arm64_local_validation_build_does_not_export_image_to_daemon() -> None:
    script = _read(ARM64_VALIDATION_SCRIPT)

    assert "--platform linux/arm64" in script
    assert "--output type=cacheonly" in script
    assert "--load" not in script
    assert "docker image inspect" not in script


def test_docker_images_share_system_package_layer_without_ca_upgrade() -> None:
    setup = _read(SETUP_DOCKERFILE)
    home_node = _read(HOME_NODE_DOCKERFILE)
    expected = (
        "RUN apt-get update \\\n"
        "    && apt-get install -y --no-install-recommends --no-upgrade ca-certificates git \\\n"
        "    && test -s /etc/ssl/certs/ca-certificates.crt \\\n"
        "    && rm -rf /var/lib/apt/lists/*"
    )

    assert expected in setup
    assert expected in home_node


def test_home_node_dockerfile_separates_dependencies_from_project_source() -> None:
    dockerfile = _read(HOME_NODE_DOCKERFILE)

    metadata_copy = dockerfile.index("COPY pyproject.toml uv.lock README.md /app/")
    dependency_sync = dockerfile.index(
        "RUN uv sync --frozen --no-dev --extra mcp --no-install-project"
    )
    source_copy = dockerfile.index("COPY src /app/src")
    project_sync = dockerfile.index("RUN uv sync --frozen --no-dev --extra mcp\n")

    assert metadata_copy < dependency_sync < source_copy < project_sync


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
    assert (
        "${{ github.event.pull_request.number || github.ref_name }}-\n"
        in _restore_keys_block(full)
    )
