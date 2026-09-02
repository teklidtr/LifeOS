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
_LEGACY_COMPLETED_PREFIX = "tasks/completed/"
_LEGACY_SOURCE_STATUS_LINES = {
    b"status: backlog",
    b"status: ready",
    b"status: in-progress",
}
_LEGACY_TARGET_STATUS_LINE = b"status: completed"


@dataclass(frozen=True)
class DocumentationImpact:
    status: str
    reason: str | None


@dataclass(frozen=True)
class GitChange:
    status: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class GitFileSnapshot:
    mode: str
    object_type: str
    content: bytes

    def text(self) -> str:
        return self.content.decode("utf-8")


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


def is_ci_documentation_path(path: str) -> bool:
    """Return whether a path is safe for the dependency-free documentation-only CI path."""
    if is_implementation_change(path) or not path.endswith(".md"):
        return False
    return is_documentation_change(path) or _TASK_PATTERN.fullmatch(path) is not None


def parse_name_status_z(raw: bytes) -> tuple[GitChange, ...]:
    """Parse `git diff --name-status -z`, preserving both rename/copy endpoints."""
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()

    changes: list[GitChange] = []
    index = 0
    while index < len(tokens):
        status = tokens[index].decode("utf-8", errors="surrogateescape")
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(tokens):
            raise ValueError("truncated git --name-status -z output")
        paths = tuple(
            token.decode("utf-8", errors="surrogateescape")
            for token in tokens[index : index + path_count]
        )
        index += path_count
        changes.append(GitChange(status=status, paths=paths))
    return tuple(changes)


def evaluate_ci_scope(changes: Iterable[GitChange]) -> tuple[bool, int]:
    """Return `(docs_only, changed_entry_count)` using a conservative documentation allowlist."""
    entries = tuple(changes)
    docs_only = bool(entries) and all(
        is_ci_documentation_path(path) for change in entries for path in change.paths
    )
    return docs_only, len(entries)


def _frontmatter_end(lines: list[bytes]) -> int | None:
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip(b"\r\n") == b"---":
            return index
    return None


def _line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    if line.endswith(b"\r"):
        return b"\r"
    return b""


def is_legacy_completed_status_only_change(before: bytes, after: bytes) -> bool:
    """Return whether bytes differ only by a canonical frontmatter status transition."""
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    if len(before_lines) != len(after_lines):
        return False

    before_end = _frontmatter_end(before_lines)
    after_end = _frontmatter_end(after_lines)
    if before_end is None or before_end != after_end:
        return False

    differences = [
        index
        for index, (before_line, after_line) in enumerate(zip(before_lines, after_lines))
        if before_line != after_line
    ]
    if len(differences) != 1:
        return False

    index = differences[0]
    if not 0 < index < before_end:
        return False

    before_line = before_lines[index]
    after_line = after_lines[index]
    before_ending = _line_ending(before_line)
    after_ending = _line_ending(after_line)
    if before_ending != after_ending:
        return False

    before_core = before_line[: -len(before_ending)] if before_ending else before_line
    after_core = after_line[: -len(after_ending)] if after_ending else after_line
    return (
        before_core in _LEGACY_SOURCE_STATUS_LINES
        and after_core == _LEGACY_TARGET_STATUS_LINE
    )


def is_legacy_completed_status_only_snapshot_change(
    before: GitFileSnapshot,
    after: GitFileSnapshot,
) -> bool:
    """Require unchanged Git object type/mode plus a status-only blob-content transition."""
    if before.object_type != "blob" or after.object_type != "blob":
        return False
    if before.mode != after.mode:
        return False
    return is_legacy_completed_status_only_change(before.content, after.content)


def evaluate_documentation_impact(
    changed_paths: Iterable[str],
    read_text: Callable[[str], str],
    read_legacy_snapshots: Callable[[str], tuple[GitFileSnapshot, GitFileSnapshot]] | None = None,
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
    legacy_status_reconciliations: list[str] = []
    for task_path in task_paths:
        try:
            task_text = read_text(task_path)
            declaration = parse_documentation_impact(task_text)
        except (OSError, ValueError) as exc:
            allowed_legacy_reconciliation = False
            if (
                isinstance(exc, ValueError)
                and str(exc) == "missing '# Documentation impact' section"
                and task_path.startswith(_LEGACY_COMPLETED_PREFIX)
                and read_legacy_snapshots is not None
            ):
                try:
                    before_snapshot, after_snapshot = read_legacy_snapshots(task_path)
                except OSError:
                    before_snapshot = None
                    after_snapshot = None
                if (
                    before_snapshot is not None
                    and after_snapshot is not None
                    and is_legacy_completed_status_only_snapshot_change(
                        before_snapshot,
                        after_snapshot,
                    )
                ):
                    legacy_status_reconciliations.append(task_path)
                    allowed_legacy_reconciliation = True

            if not allowed_legacy_reconciliation:
                errors.append(f"{task_path}: {exc}")
            continue
        declarations.append((task_path, declaration))

    if legacy_status_reconciliations and len(declarations) != 1:
        errors.append(
            "legacy completed-task status reconciliation requires exactly one changed task "
            "with a valid documentation-impact declaration"
        )

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


def git_changes_from_git(base_ref: str) -> tuple[GitChange, ...]:
    result = subprocess.run(
        ["git", "diff", "--name-status", "-z", "--find-renames", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return parse_name_status_z(result.stdout)


def merge_base_from_git(base_ref: str) -> str:
    result = subprocess.run(
        ["git", "merge-base", base_ref, "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def read_git_file_snapshot(ref: str, path: str) -> GitFileSnapshot:
    tree_result = subprocess.run(
        ["git", "ls-tree", "-z", ref, "--", path],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    entries = tree_result.stdout.split(b"\0")
    if entries and entries[-1] == b"":
        entries.pop()
    if len(entries) != 1:
        raise OSError(f"unable to resolve exactly one Git object for {path!r} at {ref!r}")

    metadata, separator, listed_path = entries[0].partition(b"\t")
    if separator != b"\t":
        raise OSError(f"invalid Git tree entry for {path!r} at {ref!r}")
    fields = metadata.split(b" ")
    if len(fields) != 3:
        raise OSError(f"invalid Git tree metadata for {path!r} at {ref!r}")
    mode_raw, object_type_raw, object_sha_raw = fields
    resolved_path = listed_path.decode("utf-8", errors="surrogateescape")
    if resolved_path != path:
        raise OSError(f"Git tree entry path mismatch for {path!r} at {ref!r}")

    mode = mode_raw.decode("ascii")
    object_type = object_type_raw.decode("ascii")
    if object_type != "blob":
        return GitFileSnapshot(mode=mode, object_type=object_type, content=b"")

    content_result = subprocess.run(
        ["git", "cat-file", "blob", object_sha_raw.decode("ascii")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if content_result.returncode != 0:
        raise OSError(f"unable to read Git blob for {path!r} at {ref!r}")
    return GitFileSnapshot(
        mode=mode,
        object_type=object_type,
        content=content_result.stdout,
    )


def _write_ci_scope(path: Path, *, base_ref: str) -> None:
    docs_only, changed_count = evaluate_ci_scope(git_changes_from_git(base_ref))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"docs_only={'true' if docs_only else 'false'}\n")
        handle.write(f"changed_count={changed_count}\n")
    print(f"PR scope: docs_only={str(docs_only).lower()} changed_count={changed_count}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate documentation impact and classify the pull-request diff."
    )
    parser.add_argument(
        "--base-ref",
        required=True,
        help="Git ref used as the pull-request merge base, for example origin/master.",
    )
    parser.add_argument(
        "--ci-scope-output",
        type=Path,
        help="Append docs_only/changed_count outputs for a GitHub Actions step.",
    )
    parser.add_argument(
        "--scope-only",
        action="store_true",
        help="Only classify CI scope; requires --ci-scope-output.",
    )
    args = parser.parse_args()

    if args.scope_only and args.ci_scope_output is None:
        parser.error("--scope-only requires --ci-scope-output")

    if args.ci_scope_output is not None:
        _write_ci_scope(args.ci_scope_output, base_ref=args.base_ref)
        if args.scope_only:
            return 0

    changed_paths = changed_paths_from_git(args.base_ref)
    merge_base = merge_base_from_git(args.base_ref)

    def read_head_text(path: str) -> str:
        return read_git_file_snapshot("HEAD", path).text()

    def read_legacy_snapshots(path: str) -> tuple[GitFileSnapshot, GitFileSnapshot]:
        return (
            read_git_file_snapshot(merge_base, path),
            read_git_file_snapshot("HEAD", path),
        )

    errors = evaluate_documentation_impact(
        changed_paths,
        read_head_text,
        read_legacy_snapshots,
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
