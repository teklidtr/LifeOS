from __future__ import annotations

from pathlib import Path
import runpy
from typing import Any, Callable

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_documentation_impact.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT))
parse_documentation_impact: Callable[[str], Any] = _NAMESPACE["parse_documentation_impact"]
evaluate_documentation_impact: Callable[..., tuple[str, ...]] = _NAMESPACE[
    "evaluate_documentation_impact"
]


def _task(status: str, reason: str | None = None) -> str:
    lines = ["# Goal", "", "Example.", "", "# Documentation impact", "", f"Status: {status}"]
    if reason is not None:
        lines.extend([f"Reason: {reason}"])
    lines.extend(["", "# Validation", "", "Done."])
    return "\n".join(lines)


def test_parse_required_documentation_impact() -> None:
    impact = parse_documentation_impact(_task("required"))
    assert impact.status == "required"
    assert impact.reason is None


def test_none_requires_reason() -> None:
    with pytest.raises(ValueError, match="requires a non-empty"):
        parse_documentation_impact(_task("none"))


def test_source_change_requires_exactly_one_task() -> None:
    errors = evaluate_documentation_impact(["src/lifeos/example.py"], lambda _path: "")
    assert errors == (
        "implementation-changing PRs must contain exactly one ready, in-progress, "
        "or completed task file",
    )


def test_justified_none_passes_without_docs_change() -> None:
    task_path = "tasks/completed/999-example.md"
    contents = {task_path: _task("none", "Internal refactor only; public behavior is unchanged.")}

    errors = evaluate_documentation_impact(
        ["src/lifeos/example.py", task_path],
        contents.__getitem__,
    )

    assert errors == ()


def test_required_status_needs_documentation_change() -> None:
    task_path = "tasks/completed/999-example.md"
    contents = {task_path: _task("required")}

    errors = evaluate_documentation_impact(
        ["src/lifeos/example.py", task_path],
        contents.__getitem__,
    )

    assert errors == (
        f"{task_path}: 'Status: required' needs a documentation change in the same PR",
    )


def test_required_status_passes_with_user_manual_change() -> None:
    task_path = "tasks/completed/999-example.md"
    contents = {task_path: _task("required")}

    errors = evaluate_documentation_impact(
        [
            "src/lifeos/example.py",
            "docs/user-manual/example.md",
            task_path,
        ],
        contents.__getitem__,
    )

    assert errors == ()


def test_multiple_active_task_files_fail_one_task_rule() -> None:
    first = "tasks/completed/999-first.md"
    second = "tasks/in-progress/1000-second.md"
    contents = {
        first: _task("none", "No documented behavior changed."),
        second: _task("none", "No documented behavior changed."),
    }

    errors = evaluate_documentation_impact(
        ["scripts/example.py", first, second],
        contents.__getitem__,
    )

    assert errors[0].startswith("implementation-changing PRs must contain exactly one")
