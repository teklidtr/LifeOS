from __future__ import annotations

from pathlib import Path
import runpy
from typing import Callable

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_tasks.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT))
validate_task_tree: Callable[[Path], tuple[str, ...]] = _NAMESPACE["validate_task_tree"]


def _write_task(
    task_root: Path,
    state: str,
    filename: str,
    task_id: str,
    *,
    status: str | None = None,
    dependency_frontmatter: str = "depends_on: []\n",
    extra_frontmatter: str = "",
) -> Path:
    path = task_root / state / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {task_id}\n"
        "title: Example task\n"
        f"status: {status or state}\n"
        f"{dependency_frontmatter}"
        f"{extra_frontmatter}"
        "---\n\n"
        "# Goal\n\n"
        "Example.\n",
        encoding="utf-8",
    )
    return path


def _task_root(tmp_path: Path) -> Path:
    task_root = tmp_path / "tasks"
    for state in ("backlog", "ready", "in-progress", "completed"):
        (task_root / state).mkdir(parents=True)
    return task_root


def test_valid_task_tree_passes(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-base.md", "LIFEOS-001")
    _write_task(task_root, "backlog", "002-follow-up.md", "LIFEOS-002")

    assert validate_task_tree(task_root) == ()


def test_duplicate_task_ids_are_rejected(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-historical.md", "LIFEOS-001")
    _write_task(task_root, "backlog", "999-reused.md", "LIFEOS-001")

    assert validate_task_tree(task_root) == (
        "duplicate task id 'LIFEOS-001': "
        "tasks/backlog/999-reused.md, tasks/completed/001-historical.md",
    )


def test_nested_duplicate_task_ids_are_rejected(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-historical.md", "LIFEOS-001")
    _write_task(task_root, "backlog", "team/999-reused.md", "LIFEOS-001")

    assert validate_task_tree(task_root) == (
        "duplicate task id 'LIFEOS-001': "
        "tasks/backlog/team/999-reused.md, tasks/completed/001-historical.md",
    )


def test_task_id_with_inline_yaml_comment_is_normalized_for_duplicate_detection(
    tmp_path: Path,
) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-historical.md", "LIFEOS-001")
    _write_task(
        task_root,
        "backlog",
        "999-commented.md",
        "LIFEOS-001 # historical identifier",
    )

    assert validate_task_tree(task_root) == (
        "duplicate task id 'LIFEOS-001': "
        "tasks/backlog/999-commented.md, tasks/completed/001-historical.md",
    )


def test_status_with_inline_yaml_comment_matches_directory(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "backlog",
        "001-commented.md",
        "LIFEOS-001",
        status="backlog # waiting",
    )

    assert validate_task_tree(task_root) == ()


def test_status_must_match_task_state_directory(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "completed",
        "001-example.md",
        "LIFEOS-001",
        status="ready",
    )

    assert validate_task_tree(task_root) == (
        "tasks/completed/001-example.md: status 'ready' does not match directory 'completed'",
    )


def test_completed_legacy_dependency_mapping_is_non_enforceable(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "completed",
        "001-legacy.md",
        "LIFEOS-001",
        dependency_frontmatter=(
            "depends_on:\n"
            "  legacy_phase: LIFEOS-DOES-NOT-EXIST\n"
            "  historical_alias: LIFEOS-300\n"
        ),
    )

    assert validate_task_tree(task_root) == ()


def test_historical_target_without_dependency_metadata_still_resolves(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "completed",
        "300-context-packs.md",
        "LIFEOS-300",
        dependency_frontmatter="",
    )
    _write_task(
        task_root,
        "completed",
        "1200-planning.md",
        "LIFEOS-1200",
        dependency_frontmatter="depends_on: [LIFEOS-300]\n",
    )

    assert validate_task_tree(task_root) == ()


def test_indented_empty_list_and_multiline_dependencies_resolve(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "completed",
        "1600-architecture.md",
        "LIFEOS-1600",
        dependency_frontmatter="depends_on:\n  []\n",
    )
    _write_task(
        task_root,
        "completed",
        "1601-artifacts.md",
        "LIFEOS-1601",
        dependency_frontmatter="depends_on:\n  - LIFEOS-1600\n",
    )
    _write_task(
        task_root,
        "backlog",
        "1602-follow-up.md",
        "LIFEOS-1602",
        dependency_frontmatter=(
            "depends_on:\n"
            "  - LIFEOS-1600\n"
            "  - LIFEOS-1601 # shipped foundation\n"
        ),
    )

    assert validate_task_tree(task_root) == ()


def test_completed_scalar_dependency_is_resolved_as_legacy_metadata(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-base.md", "LIFEOS-001")
    _write_task(
        task_root,
        "completed",
        "002-legacy.md",
        "LIFEOS-002",
        dependency_frontmatter="depends_on: LIFEOS-001\n",
    )

    assert validate_task_tree(task_root) == ()


def test_active_task_requires_yaml_dependency_list(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "backlog",
        "001-missing.md",
        "LIFEOS-001",
        dependency_frontmatter="",
    )

    assert validate_task_tree(task_root) == (
        "tasks/backlog/001-missing.md: active task 'depends_on' must be a YAML-style task-ID list",
    )


def test_unresolved_dependency_id_is_rejected(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "backlog",
        "002-follow-up.md",
        "LIFEOS-002",
        dependency_frontmatter="depends_on: [LIFEOS-404]\n",
    )

    assert validate_task_tree(task_root) == (
        "tasks/backlog/002-follow-up.md: dependency 'LIFEOS-404' does not match any task id",
    )


def test_missing_id_is_rejected(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    path = task_root / "backlog" / "001-invalid.md"
    path.write_text(
        "---\n"
        "title: Invalid task\n"
        "status: backlog\n"
        "depends_on: []\n"
        "---\n",
        encoding="utf-8",
    )

    assert validate_task_tree(task_root) == (
        "tasks/backlog/001-invalid.md: frontmatter must contain exactly one 'id' field",
    )
