from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

_IMPLEMENTATION_PREFIXES = (
    "src/",
    "packages/",
    "scripts/",
    "system/",
    "prompts/",
    ".github/workflows/",
    ".lifeos.example/",
)
_IMPLEMENTATION_FILES = {"pyproject.toml", "Dockerfile", "docker-compose.yml"}
_DOCUMENTATION_PREFIXES = ("docs/",)
_DOCUMENTATION_FILES = {"AGENTS.md", "README.md", "tasks/README.md"}
_TASK_PATTERN = re.compile(r"^tasks/(?:ready|in-progress|completed)/[^/]+\.md$")
_SECTION_PATTERN = re.compile(
    r"(?ms)^# Documentation impact\s*\n(?P<body>.*?)(?=^#\s|\Z)"
)
_STATUS_PATTERN = re.compile(r"(?mi)^Status:\s*(required|none)\s*$")
_REASON_PATTERN = re.compile(r"(?mi)^Reason:\s*(\S.*)$")


@dataclass(frozen=True)
class DocumentationImpact:
    status: str
    reason: str | None


def parse_documentation_impact(task_text: str) -> DocumentationImpact:
    section_match = _SECTION_PATTERN.search(task_text)
    if section_match is None:
        raise ValueError("missing '# Documentation impact' section")

    section = section_match.group("body")
    status_match = _STATUS_PATTERN.search(section)
    if status_match is None:
        raise ValueError("documentation impact must declare 'Status: required' or 'Status: none'")

    status = status_match.group(1).lower()
    reason_match = _REASON_PATTERN.search(section)
    reason = reason_match.group(1).strip() if reason_match is not None else None
    if status == "none" and not reason:
        raise ValueError("'Status: none' requires a non-empty 'Reason:'")

    return DocumentationImpact(status=status, reason=reason)


def is_implementation_change(path: str) -> bool:
    return path in _IMPLEMENTATION_FILES or path.startswith(_IMPLEMENTATION_PREFIXES)


def is_documentation_change(path: str) -> bool:
    return path in _DOCUMENTATION_FILES or path.startswith(_DOCUMENTATION_PREFIXES)


def evaluate_documentation_impact(
    changed_paths: Iterable[str],
    read_text: Callable[[str], str],
) -> tuple[str, ...]:
    paths = tuple(dict.fromkeys(changed_paths))
    implementation_changed = any(is_implementation_change(path) for path in paths)
    documentation_changed = any(is_documentation_change(path) for path in paths)
    task_paths = tuple(path for path in paths if _TASK_PATTERN.fullmatch(path))

    errors: list[str] = []
    if implementation_changed and len(task_paths) != 1:
        errors.append(
            "implementation-changing PRs must contain exactly one ready, in-progress, "
            "or completed task file"
        )

    declarations: list[tuple[str, DocumentationImpact]] = []
    for task_path in task_paths:
        try:
            declaration = parse_documentation_impact(read_text(task_path))
        except (OSError, ValueError) as exc:
            errors.append(f"{task_path}: {exc}")
            continue
        declarations.append((task_path, declaration))

    for task_path, declaration in declarations:
        if declaration.status == "required" and not documentation_changed:
            errors.append(
                f"{task_path}: 'Status: required' needs a documentation change in the same PR"
            )

    return tuple(errors)


def changed_paths_from_git(base_ref: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--find-renames", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the task documentation-impact contract for a pull-request diff."
    )
    parser.add_argument(
        "--base-ref",
        required=True,
        help="Git ref used as the pull-request merge base, for example origin/master.",
    )
    args = parser.parse_args()

    changed_paths = changed_paths_from_git(args.base_ref)
    errors = evaluate_documentation_impact(
        changed_paths,
        lambda path: (REPO_ROOT / path).read_text(encoding="utf-8"),
    )
    if errors:
        print("Documentation impact gate failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Documentation impact gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
