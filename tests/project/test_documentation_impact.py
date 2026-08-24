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
parse_name_status_z: Callable[[bytes], tuple[Any, ...]] = _NAMESPACE["parse_name_status_z"]
evaluate_ci_scope: Callable[[tuple[Any, ...]], tuple[bool, int]] = _NAMESPACE["evaluate_ci_scope"]
is_ci_documentation_path: Callable[[str], bool] = _NAMESPACE["is_ci_documentation_path"]


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


def test_ci_documentation_allowlist_rejects_implementation_owned_markdown() -> None:
    assert is_ci_documentation_path("README.md") is True
    assert is_ci_documentation_path("AGENTS.md") is True
    assert is_ci_documentation_path("docs/user-manual/example.md") is True
    assert is_ci_documentation_path("tasks/in-progress/999-example.md") is True
    assert is_ci_documentation_path("prompts/system.md") is False
    assert is_ci_documentation_path("packages/plugin/README.md") is False
    assert is_ci_documentation_path(".github/workflows/notes.md") is False
    assert is_ci_documentation_path("src/lifeos/example.py") is False


def test_ci_scope_checks_both_rename_endpoints() -> None:
    docs_rename = parse_name_status_z(
        b"R100\0docs/old.md\0docs/new.md\0M\0README.md\0"
    )
    assert evaluate_ci_scope(docs_rename) == (True, 2)

    implementation_to_docs = parse_name_status_z(
        b"R100\0src/lifeos/example.py\0docs/example.md\0"
    )
    assert evaluate_ci_scope(implementation_to_docs) == (False, 1)


def test_ci_scope_rejects_empty_and_non_markdown_diffs() -> None:
    assert evaluate_ci_scope(()) == (False, 0)
    changes = parse_name_status_z(b"M\0docs/diagram.png\0")
    assert evaluate_ci_scope(changes) == (False, 1)
