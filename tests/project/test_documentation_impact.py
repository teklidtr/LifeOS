from __future__ import annotations

from pathlib import Path
import runpy
import subprocess
from typing import Any, Callable

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_documentation_impact.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT))
GitFileSnapshot = _NAMESPACE["GitFileSnapshot"]
parse_documentation_impact: Callable[[str], Any] = _NAMESPACE["parse_documentation_impact"]
evaluate_documentation_impact: Callable[..., tuple[str, ...]] = _NAMESPACE[
    "evaluate_documentation_impact"
]
parse_name_status_z: Callable[[bytes], tuple[Any, ...]] = _NAMESPACE["parse_name_status_z"]
evaluate_ci_scope: Callable[[tuple[Any, ...]], tuple[bool, int]] = _NAMESPACE["evaluate_ci_scope"]
is_ci_documentation_path: Callable[[str], bool] = _NAMESPACE["is_ci_documentation_path"]
is_legacy_completed_status_only_change: Callable[[bytes, bytes], bool] = _NAMESPACE[
    "is_legacy_completed_status_only_change"
]
merge_base_from_git: Callable[[str], str] = _NAMESPACE["merge_base_from_git"]
read_git_file_snapshot: Callable[[str, str], Any] = _NAMESPACE["read_git_file_snapshot"]


def _task(status: str, reason: str | None = None) -> str:
    lines = ["# Goal", "", "Example.", "", "# Documentation impact", "", f"Status: {status}"]
    if reason is not None:
        lines.extend([f"Reason: {reason}"])
    lines.extend(["", "# Validation", "", "Done."])
    return "\n".join(lines)


def _legacy_task(
    status: str,
    *,
    task_id: str = "LIFEOS-007",
    depends_on: str = "[LIFEOS-005]",
    body: str = "Legacy body.",
    acceptance: str = "Legacy criterion.",
    final_newline: bool = True,
) -> str:
    text = (
        "---\n"
        f"id: {task_id}\n"
        "title: Legacy task\n"
        f"status: {status}\n"
        f"depends_on: {depends_on}\n"
        "---\n\n"
        "# Goal\n\n"
        f"{body}\n\n"
        "# Acceptance criteria\n\n"
        f"- {acceptance}"
    )
    return text + ("\n" if final_newline else "")


def _snapshot(
    text: str,
    *,
    mode: str = "100644",
    object_type: str = "blob",
) -> Any:
    return GitFileSnapshot(mode=mode, object_type=object_type, content=text.encode("utf-8"))


def _legacy_snapshot_reader(
    current: dict[str, str],
    base: dict[str, str],
    *,
    current_modes: dict[str, str] | None = None,
    current_types: dict[str, str] | None = None,
) -> Callable[[str], tuple[Any, Any]]:
    modes = current_modes or {}
    types = current_types or {}

    def read(path: str) -> tuple[Any, Any]:
        return (
            _snapshot(base[path]),
            _snapshot(
                current[path],
                mode=modes.get(path, "100644"),
                object_type=types.get(path, "blob"),
            ),
        )

    return read


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


def test_legacy_completed_status_reconciliation_shape_passes() -> None:
    first = "tasks/completed/007-parse-durable-note-metadata.md"
    second = "tasks/completed/1002-local-desktop-bridge.md"
    selected = "tasks/completed/1667-reconcile-historical-task-status-metadata.md"
    current = {
        first: _legacy_task("completed"),
        second: _legacy_task("completed", task_id="LIFEOS-1002"),
        selected: _task("none", "Task-state metadata only; documented behavior is unchanged."),
    }
    base = {
        first: _legacy_task("ready"),
        second: _legacy_task("backlog", task_id="LIFEOS-1002"),
    }

    errors = evaluate_documentation_impact(
        [first, second, selected],
        current.__getitem__,
        _legacy_snapshot_reader(current, base),
    )

    assert errors == ()


def test_legacy_reconciliation_requires_selected_task_declaration() -> None:
    legacy = "tasks/completed/007-parse-durable-note-metadata.md"
    current = {legacy: _legacy_task("completed")}
    base = {legacy: _legacy_task("ready")}

    errors = evaluate_documentation_impact(
        [legacy],
        current.__getitem__,
        _legacy_snapshot_reader(current, base),
    )

    assert errors == (
        "legacy completed-task status reconciliation requires exactly one changed task "
        "with a valid documentation-impact declaration",
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            _legacy_task("ready"),
            _legacy_task("completed", task_id="LIFEOS-CHANGED"),
        ),
        (
            _legacy_task("ready"),
            _legacy_task("completed", depends_on="[LIFEOS-999]"),
        ),
        (
            _legacy_task("ready"),
            _legacy_task("completed", body="Changed body."),
        ),
        (
            _legacy_task("ready"),
            _legacy_task("completed", acceptance="Changed criterion."),
        ),
        (
            _legacy_task("ready"),
            _legacy_task("completed", final_newline=False),
        ),
        (
            _legacy_task("ready"),
            _legacy_task("completed").replace("status: completed", "status:   completed"),
        ),
        (
            _legacy_task("ready"),
            _legacy_task("completed").replace("\n", "\r\n"),
        ),
    ],
)
def test_legacy_exception_rejects_substantive_or_byte_changes(
    before: str,
    after: str,
) -> None:
    legacy = "tasks/completed/007-parse-durable-note-metadata.md"
    selected = "tasks/completed/1667-reconcile-historical-task-status-metadata.md"
    current = {
        legacy: after,
        selected: _task("none", "Task-state metadata only; documented behavior is unchanged."),
    }
    base = {legacy: before}

    errors = evaluate_documentation_impact(
        [legacy, selected],
        current.__getitem__,
        _legacy_snapshot_reader(current, base),
    )

    assert errors == (f"{legacy}: missing '# Documentation impact' section",)


@pytest.mark.parametrize(
    ("mode", "object_type"),
    [
        ("100755", "blob"),
        ("120000", "blob"),
        ("100644", "commit"),
    ],
)
def test_legacy_exception_rejects_mode_or_object_type_changes(
    mode: str,
    object_type: str,
) -> None:
    legacy = "tasks/completed/007-parse-durable-note-metadata.md"
    selected = "tasks/completed/1667-reconcile-historical-task-status-metadata.md"
    current = {
        legacy: _legacy_task("completed"),
        selected: _task("none", "Task-state metadata only; documented behavior is unchanged."),
    }
    base = {legacy: _legacy_task("ready")}

    errors = evaluate_documentation_impact(
        [legacy, selected],
        current.__getitem__,
        _legacy_snapshot_reader(
            current,
            base,
            current_modes={legacy: mode},
            current_types={legacy: object_type},
        ),
    )

    assert errors == (f"{legacy}: missing '# Documentation impact' section",)


def test_legacy_status_helper_requires_transition_to_completed() -> None:
    assert is_legacy_completed_status_only_change(
        _legacy_task("backlog").encode("utf-8"),
        _legacy_task("completed").encode("utf-8"),
    )
    assert not is_legacy_completed_status_only_change(
        _legacy_task("backlog").encode("utf-8"),
        _legacy_task("ready").encode("utf-8"),
    )


def test_merge_base_reader_resolves_against_head(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> object:
        assert args == ["git", "merge-base", "origin/master", "HEAD"]
        return type("Result", (), {"stdout": "abc123\n"})()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert merge_base_from_git("origin/master") == "abc123"


def test_git_snapshot_reader_preserves_mode_and_raw_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "tasks/completed/007.md"
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> object:
        calls.append(args)
        if args[:2] == ["git", "ls-tree"]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": b"100644 blob abc123\ttasks/completed/007.md\0",
                },
            )()
        assert args == ["git", "cat-file", "blob", "abc123"]
        return type("Result", (), {"returncode": 0, "stdout": b"a\r\nb\r\n"})()

    monkeypatch.setattr(subprocess, "run", fake_run)

    snapshot = read_git_file_snapshot("merge-base", path)

    assert snapshot.mode == "100644"
    assert snapshot.object_type == "blob"
    assert snapshot.content == b"a\r\nb\r\n"
    assert calls == [
        ["git", "ls-tree", "-z", "merge-base", "--", path],
        ["git", "cat-file", "blob", "abc123"],
    ]


def test_ci_documentation_allowlist_rejects_implementation_owned_markdown() -> None:
    assert is_ci_documentation_path("README.md") is True
    assert is_ci_documentation_path("AGENTS.md") is True
    assert is_ci_documentation_path("docs/user-manual/example.md") is True
    assert is_ci_documentation_path("tasks/in-progress/999-example.md") is True
    assert is_ci_documentation_path("packages/plugin/README.md") is False
    assert is_ci_documentation_path(".github/workflows/notes.md") is False
    assert is_ci_documentation_path("src/lifeos/example.py") is False


def test_ci_scope_checks_both_rename_endpoints() -> None:
    docs_rename = parse_name_status_z(b"R100\0docs/old.md\0docs/new.md\0M\0README.md\0")
    assert evaluate_ci_scope(docs_rename) == (True, 2)

    implementation_to_docs = parse_name_status_z(b"R100\0src/lifeos/example.py\0docs/example.md\0")
    assert evaluate_ci_scope(implementation_to_docs) == (False, 1)


def test_ci_scope_rejects_empty_and_non_markdown_diffs() -> None:
    assert evaluate_ci_scope(()) == (False, 0)
    changes = parse_name_status_z(b"M\0docs/diagram.png\0")
    assert evaluate_ci_scope(changes) == (False, 1)
