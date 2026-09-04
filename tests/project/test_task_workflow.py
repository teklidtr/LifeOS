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
    depends_on: str = "[]",
) -> Path:
    path = task_root / state / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {task_id}\n"
        "title: Example task\n"
        f"status: {status or state}\n"
        f"depends_on: {depends_on}\n"
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
    _write_task(
        task_root,
        "backlog",
        "002-follow-up.md",
        "LIFEOS-002",
        depends_on="[LIFEOS-001]",
    )

    assert validate_task_tree(task_root) == ()


def test_duplicate_task_ids_are_rejected(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-historical.md", "LIFEOS-001")
    _write_task(task_root, "backlog", "999-reused.md", "LIFEOS-001")

    assert validate_task_tree(task_root) == (
        "duplicate task id 'LIFEOS-001': "
        "tasks/backlog/999-reused.md, tasks/completed/001-historical.md",
    )


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


def test_unknown_dependency_is_rejected(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(
        task_root,
        "backlog",
        "002-follow-up.md",
        "LIFEOS-002",
        depends_on="[LIFEOS-001]",
    )

    assert validate_task_tree(task_root) == (
        "tasks/backlog/002-follow-up.md: dependency 'LIFEOS-001' does not match any task id",
    )


def test_multiline_dependencies_are_supported(tmp_path: Path) -> None:
    task_root = _task_root(tmp_path)
    _write_task(task_root, "completed", "001-base.md", "LIFEOS-001")
    path = task_root / "backlog" / "002-follow-up.md"
    path.write_text(
        "---\n"
        "id: LIFEOS-002\n"
        "title: Example task\n"
        "status: backlog\n"
        "depends_on:\n"
        "  - LIFEOS-001\n"
        "risk: low\n"
        "---\n",
        encoding="utf-8",
    )

    assert validate_task_tree(task_root) == ()
