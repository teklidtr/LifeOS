"""Read-only recovery-readiness diagnostics for canonical LifeOS vault data."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from lifeos.coherence import CoherenceError
from lifeos.config import LifeOSConfig
from lifeos.runtime_scope import build_runtime_exclusion_matcher

RecoveryStatus = Literal["pass", "warning", "failure", "info", "unknown"]
RecoverySeverity = Literal["info", "warning", "error"]
PathExclusion = Callable[[str], bool]

_GIT_ENVIRONMENT_SELECTION_KEYS = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_EXEC_PATH",
        "GIT_EXTERNAL_DIFF",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_QUARANTINE_PATH",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryDiagnostic:
    """One stable, privacy-conscious recovery diagnostic."""

    id: str
    status: RecoveryStatus
    severity: RecoverySeverity
    summary: str
    remediation: str | None = None
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalCommitEvidence:
    """Metadata for the latest commit that actually touched canonical vault data."""

    sha: str
    committed_at: str
    age_days: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Deterministic recovery evidence without canonical note contents."""

    diagnostics: tuple[RecoveryDiagnostic, ...]
    repository_root: str | None
    last_canonical_commit: CanonicalCommitEvidence | None
    committed_canonical_count: int
    uncommitted_paths: tuple[str, ...]
    staged_paths: tuple[str, ...]
    unstaged_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    untracked_paths: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    index_flagged_paths: tuple[str, ...]
    unrecoverable_committed_paths: tuple[str, ...]


class RecoveryGitError(RuntimeError):
    """Raised when read-only Git metadata cannot be queried deterministically."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in tuple(env):
        if name in _GIT_ENVIRONMENT_SELECTION_KEYS or name.startswith("GIT_TRACE"):
            env.pop(name, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    env["GIT_NO_LAZY_FETCH"] = "1"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_PAGER"] = ""
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "core.fsmonitor"
    env["GIT_CONFIG_VALUE_0"] = "false"
    return env


def _result_error(
    result: subprocess.CompletedProcess[bytes],
    *,
    operation: str,
) -> RecoveryGitError:
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    suffix = f": {detail}" if detail else ""
    return RecoveryGitError(
        f"{operation} failed with exit code {result.returncode}{suffix}"
    )


def _run_git(
    git_executable: str,
    *,
    cwd: Path,
    arguments: Sequence[str],
    check: bool = True,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            [git_executable, *arguments],
            cwd=cwd,
            shell=False,
            check=False,
            capture_output=True,
            env=_git_environment(),
            input=input_bytes,
        )
    except OSError as error:
        raise RecoveryGitError(f"Could not execute Git: {error}") from error
    if check and result.returncode != 0:
        raise _result_error(result, operation="Git metadata query")
    return result


def _nul_paths(raw: bytes) -> tuple[str, ...]:
    return tuple(
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0")
        if item
    )


def _runtime_snapshot_prefix(config: LifeOSConfig) -> str | None:
    try:
        relative = config.runtime_dir.relative_to(config.vault_root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return f"{relative.as_posix().rstrip('/')}/"


def _runtime_exclusion_matcher(config: LifeOSConfig) -> PathExclusion:
    return build_runtime_exclusion_matcher(
        config.vault_root,
        runtime_dir=config.runtime_dir,
        snapshot_prefix=_runtime_snapshot_prefix(config),
    )


def _canonical_vault_path(
    repo_path: str,
    *,
    vault_repo_prefix: tuple[str, ...],
    runtime_excluded: PathExclusion,
) -> str | None:
    pure = PurePosixPath(repo_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    repo_parts = pure.parts
    if vault_repo_prefix:
        if repo_parts[: len(vault_repo_prefix)] != vault_repo_prefix:
            return None
        relative_parts = repo_parts[len(vault_repo_prefix) :]
    else:
        relative_parts = repo_parts
    if not relative_parts:
        return None
    if any(part.startswith(".") or part == "__pycache__" for part in relative_parts):
        return None
    relative_path = PurePosixPath(*relative_parts).as_posix()
    try:
        if runtime_excluded(relative_path):
            return None
    except CoherenceError as error:
        raise RecoveryGitError("Could not verify configured runtime exclusion") from error
    return relative_path


def _filter_canonical_paths(
    paths: Sequence[str],
    *,
    vault_repo_prefix: tuple[str, ...],
    runtime_excluded: PathExclusion,
) -> tuple[str, ...]:
    canonical: set[str] = set()
    for path in paths:
        candidate = _canonical_vault_path(
            path,
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        if candidate is not None:
            canonical.add(candidate)
    return tuple(sorted(canonical))


def _git_marker_exists(vault_root: Path) -> bool:
    for directory in (vault_root, *vault_root.parents):
        marker = directory / ".git"
        try:
            os.lstat(marker)
        except FileNotFoundError:
            continue
        except OSError:
            return True
        return True
    return False


def _vault_repo_context(
    git_executable: str,
    vault_root: Path,
) -> tuple[Path, tuple[str, ...], str] | None:
    result = _run_git(
        git_executable,
        cwd=vault_root,
        arguments=("rev-parse", "--show-toplevel"),
        check=False,
    )
    if result.returncode != 0:
        if _git_marker_exists(vault_root):
            raise _result_error(result, operation="Git repository discovery")
        return None
    raw_root = result.stdout.decode("utf-8", errors="surrogateescape").strip()
    if not raw_root:
        raise RecoveryGitError("Git repository discovery returned an empty repository root")
    repository_root = Path(raw_root).resolve(strict=False)
    try:
        vault_relative = vault_root.relative_to(repository_root)
    except ValueError as error:
        raise RecoveryGitError("Git repository root does not contain the configured vault") from error
    prefix = tuple(vault_relative.parts)
    pathspec = vault_relative.as_posix() if prefix else "."
    return repository_root, prefix, pathspec


def _git_paths(
    git_executable: str,
    *,
    repository_root: Path,
    arguments: Sequence[str],
    vault_repo_prefix: tuple[str, ...],
    runtime_excluded: PathExclusion,
) -> tuple[str, ...]:
    result = _run_git(git_executable, cwd=repository_root, arguments=arguments)
    return _filter_canonical_paths(
        _nul_paths(result.stdout),
        vault_repo_prefix=vault_repo_prefix,
        runtime_excluded=runtime_excluded,
    )


def _head_exists(git_executable: str, repository_root: Path) -> bool:
    result = _run_git(
        git_executable,
        cwd=repository_root,
        arguments=("rev-parse", "--verify", "HEAD"),
        check=False,
    )
    return result.returncode == 0


def _available_blob_oids(
    git_executable: str,
    *,
    repository_root: Path,
    object_ids: Sequence[str],
) -> frozenset[str]:
    unique = tuple(sorted(set(object_ids)))
    if not unique:
        return frozenset()
    try:
        payload = "".join(f"{object_id}\n" for object_id in unique).encode("ascii")
    except UnicodeEncodeError as error:
        raise RecoveryGitError("Git returned a non-ASCII object identifier") from error
    result = _run_git(
        git_executable,
        cwd=repository_root,
        arguments=("cat-file", "--batch-check=%(objectname) %(objecttype)"),
        input_bytes=payload,
    )
    lines = result.stdout.splitlines()
    if len(lines) != len(unique):
        raise RecoveryGitError("Git object verification returned an unexpected result count")
    available: set[str] = set()
    for expected, line in zip(unique, lines, strict=True):
        parts = line.split()
        if len(parts) != 2:
            raise RecoveryGitError("Git object verification returned malformed output")
        observed = parts[0].decode("ascii", errors="strict")
        if observed != expected:
            raise RecoveryGitError("Git object verification returned an unexpected object")
        if parts[1] == b"blob":
            available.add(expected)
        elif parts[1] != b"missing":
            raise RecoveryGitError("Git tree entry did not resolve to a blob object")
    return frozenset(available)


def _committed_canonical_coverage(
    git_executable: str,
    *,
    repository_root: Path,
    pathspec: str,
    vault_repo_prefix: tuple[str, ...],
    runtime_excluded: PathExclusion,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not _head_exists(git_executable, repository_root):
        return (), ()
    result = _run_git(
        git_executable,
        cwd=repository_root,
        arguments=("ls-tree", "-r", "-z", "HEAD", "--", pathspec),
    )
    regular_entries: list[tuple[str, str]] = []
    gaps: set[str] = set()
    for record in (item for item in result.stdout.split(b"\0") if item):
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if separator != b"\t" or len(fields) != 3:
            raise RecoveryGitError("Git tree query returned malformed output")
        mode, object_type, raw_object_id = fields
        path = raw_path.decode("utf-8", errors="surrogateescape")
        canonical = _canonical_vault_path(
            path,
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        if canonical is None:
            continue
        if object_type != b"blob" or not mode.startswith(b"100"):
            gaps.add(canonical)
            continue
        try:
            object_id = raw_object_id.decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise RecoveryGitError("Git returned a non-ASCII object identifier") from error
        regular_entries.append((canonical, object_id))

    available = _available_blob_oids(
        git_executable,
        repository_root=repository_root,
        object_ids=tuple(object_id for _, object_id in regular_entries),
    )
    covered: set[str] = set()
    for path, object_id in regular_entries:
        if object_id in available:
            covered.add(path)
        else:
            gaps.add(path)
    return tuple(sorted(covered)), tuple(sorted(gaps))


def _index_flagged_paths(
    git_executable: str,
    *,
    repository_root: Path,
    pathspec: str,
    vault_repo_prefix: tuple[str, ...],
    runtime_excluded: PathExclusion,
) -> tuple[str, ...]:
    result = _run_git(
        git_executable,
        cwd=repository_root,
        arguments=("ls-files", "-v", "-z", "--", pathspec),
    )
    paths: list[str] = []
    for record in (item for item in result.stdout.split(b"\0") if item):
        if len(record) < 3 or record[1:2] != b" ":
            raise RecoveryGitError("Git index flag query returned malformed output")
        tag = chr(record[0])
        if tag == "S" or tag.islower():
            paths.append(record[2:].decode("utf-8", errors="surrogateescape"))
    return _filter_canonical_paths(
        paths,
        vault_repo_prefix=vault_repo_prefix,
        runtime_excluded=runtime_excluded,
    )


def _latest_canonical_commit(
    git_executable: str,
    *,
    repository_root: Path,
    pathspec: str,
    vault_repo_prefix: tuple[str, ...],
    runtime_excluded: PathExclusion,
    clock_fn: Callable[[], datetime],
) -> CanonicalCommitEvidence | None:
    if not _head_exists(git_executable, repository_root):
        return None
    revision_result = _run_git(
        git_executable,
        cwd=repository_root,
        arguments=("rev-list", "HEAD", "--", pathspec),
    )
    for sha in revision_result.stdout.decode("ascii", errors="strict").splitlines():
        changed = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=(
                "diff-tree",
                "--no-ext-diff",
                "--no-textconv",
                "-m",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                sha,
                "--",
                pathspec,
            ),
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        if not changed:
            continue
        timestamp_result = _run_git(
            git_executable,
            cwd=repository_root,
            arguments=("show", "-s", "--format=%cI", sha),
        )
        committed_at = timestamp_result.stdout.decode("ascii", errors="strict").strip()
        try:
            committed = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise RecoveryGitError("Git returned an invalid commit timestamp") from error
        if committed.tzinfo is None:
            committed = committed.replace(tzinfo=timezone.utc)
        now = clock_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (now.astimezone(timezone.utc) - committed).total_seconds())
        return CanonicalCommitEvidence(
            sha=sha,
            committed_at=committed_at,
            age_days=int(age_seconds // 86_400),
        )
    return None


def _unknown_git_diagnostics(summary: str) -> tuple[RecoveryDiagnostic, ...]:
    return (
        RecoveryDiagnostic(
            "recovery.git.repository",
            "unknown",
            "error",
            summary,
            "Verify Git repository ownership, permissions, and metadata, then retry the doctor.",
        ),
        RecoveryDiagnostic(
            "recovery.git.last_canonical_commit",
            "unknown",
            "warning",
            "Canonical commit history could not be verified.",
        ),
        RecoveryDiagnostic(
            "recovery.git.canonical_objects",
            "unknown",
            "warning",
            "Local recoverability of committed canonical blobs could not be verified.",
        ),
        RecoveryDiagnostic(
            "recovery.git.uncommitted_canonical",
            "unknown",
            "warning",
            "Uncommitted canonical changes could not be verified.",
        ),
        RecoveryDiagnostic(
            "recovery.git.untracked_canonical",
            "unknown",
            "warning",
            "Untracked canonical files could not be verified.",
        ),
        RecoveryDiagnostic(
            "recovery.git.ignored_canonical",
            "unknown",
            "warning",
            "Ignored canonical files could not be verified.",
        ),
    )


def _non_repository_diagnostics() -> tuple[RecoveryDiagnostic, ...]:
    return (
        RecoveryDiagnostic(
            "recovery.git.repository",
            "failure",
            "error",
            "The configured vault is not covered by a Git repository.",
            "Initialize version history for the canonical vault and commit the intended durable files.",
        ),
        RecoveryDiagnostic(
            "recovery.git.last_canonical_commit",
            "unknown",
            "warning",
            "No canonical commit can exist until the vault is covered by Git history.",
        ),
        RecoveryDiagnostic(
            "recovery.git.canonical_objects",
            "unknown",
            "warning",
            "No committed canonical blobs can be verified without a Git repository.",
        ),
        RecoveryDiagnostic(
            "recovery.git.uncommitted_canonical",
            "unknown",
            "warning",
            "Uncommitted canonical coverage cannot be classified without a Git repository.",
        ),
        RecoveryDiagnostic(
            "recovery.git.untracked_canonical",
            "unknown",
            "warning",
            "Untracked canonical coverage cannot be classified without a Git repository.",
        ),
        RecoveryDiagnostic(
            "recovery.git.ignored_canonical",
            "unknown",
            "warning",
            "Ignored canonical coverage cannot be classified without a Git repository.",
        ),
    )


def _external_backup_diagnostic() -> RecoveryDiagnostic:
    return RecoveryDiagnostic(
        "recovery.backup.external",
        "unknown",
        "warning",
        (
            "Independent backup or snapshot protection is not deterministically verified. "
            "Local Git history or a configured remote alone is not proof of an off-device backup."
        ),
        (
            "Use an independent backup or snapshot system and verify its current, restorable copy "
            "outside this local working tree."
        ),
    )


def _runtime_diagnostic(config: LifeOSConfig) -> RecoveryDiagnostic:
    try:
        runtime_display = config.runtime_dir.relative_to(config.vault_root).as_posix()
    except ValueError:
        runtime_display = "<external-runtime>"
    return RecoveryDiagnostic(
        "recovery.runtime.disposable",
        "info",
        "info",
        (
            f"Disposable runtime state at {runtime_display} is rebuildable and is not canonical "
            "recovery material."
        ),
        "Restore canonical vault data first, then rebuild or recreate derived runtime state.",
    )


def _fallback_report(
    config: LifeOSConfig,
    git_diagnostics: tuple[RecoveryDiagnostic, ...],
    *,
    repository_root: Path | None = None,
) -> RecoveryReport:
    return RecoveryReport(
        diagnostics=(
            *git_diagnostics,
            _external_backup_diagnostic(),
            _runtime_diagnostic(config),
        ),
        repository_root=str(repository_root) if repository_root is not None else None,
        last_canonical_commit=None,
        committed_canonical_count=0,
        uncommitted_paths=(),
        staged_paths=(),
        unstaged_paths=(),
        deleted_paths=(),
        untracked_paths=(),
        ignored_paths=(),
        index_flagged_paths=(),
        unrecoverable_committed_paths=(),
    )


def collect_recovery_readiness(
    config: LifeOSConfig,
    *,
    clock_fn: Callable[[], datetime] = _utc_now,
) -> RecoveryReport:
    """Collect structural recovery evidence without reading canonical file contents or mutating Git."""
    git_executable = shutil.which("git")
    if git_executable is None:
        return _fallback_report(
            config,
            _unknown_git_diagnostics("Git is unavailable, so local canonical history is unknown."),
        )

    try:
        context = _vault_repo_context(git_executable, config.vault_root)
    except RecoveryGitError as error:
        return _fallback_report(config, _unknown_git_diagnostics(str(error)))
    if context is None:
        return _fallback_report(config, _non_repository_diagnostics())

    repository_root, vault_repo_prefix, pathspec = context
    runtime_excluded = _runtime_exclusion_matcher(config)
    try:
        head_exists = _head_exists(git_executable, repository_root)
        committed_paths, unrecoverable_paths = _committed_canonical_coverage(
            git_executable,
            repository_root=repository_root,
            pathspec=pathspec,
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        staged_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=(
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "-z",
                "--",
                pathspec,
            ),
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        unstaged_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=(
                "diff-files",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "-z",
                "--",
                pathspec,
            ),
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        deleted_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=("ls-files", "--deleted", "-z", "--", pathspec),
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        untracked_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=("ls-files", "--others", "--exclude-standard", "-z", "--", pathspec),
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        ignored_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=(
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
                "--",
                pathspec,
            ),
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        index_flagged_paths = _index_flagged_paths(
            git_executable,
            repository_root=repository_root,
            pathspec=pathspec,
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
        )
        last_commit = _latest_canonical_commit(
            git_executable,
            repository_root=repository_root,
            pathspec=pathspec,
            vault_repo_prefix=vault_repo_prefix,
            runtime_excluded=runtime_excluded,
            clock_fn=clock_fn,
        )
    except RecoveryGitError as error:
        return _fallback_report(
            config,
            _unknown_git_diagnostics(str(error)),
            repository_root=repository_root,
        )

    uncommitted_paths = tuple(sorted(set(staged_paths) | set(unstaged_paths) | set(deleted_paths)))
    diagnostic_items: list[RecoveryDiagnostic] = [
        RecoveryDiagnostic(
            "recovery.git.repository",
            "pass",
            "info",
            "The configured vault is covered by a local Git repository.",
        )
    ]
    if not head_exists:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.last_canonical_commit",
                "failure",
                "error",
                "The Git repository has no commit yet, so no canonical vault version is recoverable from history.",
                "Create a reviewed initial commit containing the intended canonical vault files.",
            )
        )
    elif last_commit is None:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.last_canonical_commit",
                "failure",
                "error",
                "Git history exists, but no commit affecting canonical vault paths was found.",
                "Commit the intended canonical vault files before relying on Git recovery.",
            )
        )
    else:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.last_canonical_commit",
                "info",
                "info",
                (
                    f"Latest canonical commit is {last_commit.sha[:12]} from "
                    f"{last_commit.committed_at} ({last_commit.age_days} day(s) old)."
                ),
            )
        )

    if not head_exists:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.canonical_objects",
                "unknown",
                "warning",
                "Committed canonical blob availability cannot be verified before the first commit.",
            )
        )
    elif unrecoverable_paths:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.canonical_objects",
                "failure",
                "error",
                (
                    f"{len(unrecoverable_paths)} committed canonical path(s) are not backed by "
                    "locally available regular blob objects."
                ),
                (
                    "Repair the local Git object store or replace gitlink/symlink-style canonical "
                    "entries with ordinary recoverable vault files before relying on local history."
                ),
                unrecoverable_paths,
            )
        )
    else:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.canonical_objects",
                "pass",
                "info",
                "Committed canonical tree entries are backed by locally available regular blobs.",
            )
        )

    if index_flagged_paths:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.uncommitted_canonical",
                "unknown",
                "warning",
                (
                    f"Working-tree cleanliness cannot be proven for {len(index_flagged_paths)} "
                    "canonical path(s) marked assume-unchanged or skip-worktree."
                ),
                (
                    "Clear assume-unchanged/skip-worktree on canonical paths, then rerun the doctor "
                    "and review any staged, modified, or deleted changes."
                ),
                tuple(sorted(set(uncommitted_paths) | set(index_flagged_paths))),
            )
        )
    elif uncommitted_paths:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.uncommitted_canonical",
                "warning",
                "warning",
                (
                    f"{len(uncommitted_paths)} tracked canonical path(s) have staged, modified, "
                    "or deleted state not represented by the latest commit."
                ),
                "Review and commit the intended canonical changes; staging alone is not durable history.",
                uncommitted_paths,
            )
        )
    else:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.uncommitted_canonical",
                "pass",
                "info",
                "No tracked canonical paths have uncommitted changes or hiding index flags.",
            )
        )

    if untracked_paths:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.untracked_canonical",
                "warning",
                "warning",
                f"{len(untracked_paths)} canonical path(s) are untracked and absent from committed history.",
                "Review these paths and add/commit the canonical files that should be recoverable.",
                untracked_paths,
            )
        )
    else:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.untracked_canonical",
                "pass",
                "info",
                "No untracked canonical paths were found.",
            )
        )

    if ignored_paths:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.ignored_canonical",
                "warning",
                "warning",
                (
                    f"{len(ignored_paths)} canonical path(s) are ignored by Git and are not present "
                    "in committed canonical history."
                ),
                "Review ignore rules and protect these canonical files through the intended durable history.",
                ignored_paths,
            )
        )
    else:
        diagnostic_items.append(
            RecoveryDiagnostic(
                "recovery.git.ignored_canonical",
                "pass",
                "info",
                "No ignored canonical paths outside committed history were found.",
            )
        )

    diagnostic_items.extend((_external_backup_diagnostic(), _runtime_diagnostic(config)))
    return RecoveryReport(
        diagnostics=tuple(diagnostic_items),
        repository_root=str(repository_root),
        last_canonical_commit=last_commit,
        committed_canonical_count=len(committed_paths),
        uncommitted_paths=uncommitted_paths,
        staged_paths=staged_paths,
        unstaged_paths=unstaged_paths,
        deleted_paths=deleted_paths,
        untracked_paths=untracked_paths,
        ignored_paths=ignored_paths,
        index_flagged_paths=index_flagged_paths,
        unrecoverable_committed_paths=unrecoverable_paths,
    )


def format_recovery_text(report: RecoveryReport) -> list[str]:
    """Format recovery evidence for inclusion in the human-readable doctor report."""
    lines = ["Recovery readiness"]
    if report.repository_root is not None:
        lines.append(f"  local Git repository: {report.repository_root}")
    lines.append(f"  committed canonical paths: {report.committed_canonical_count}")
    for diagnostic in report.diagnostics:
        lines.append(
            f"  {diagnostic.id}: {diagnostic.status} ({diagnostic.severity}) - {diagnostic.summary}"
        )
        for path in diagnostic.paths:
            lines.append(f"    path: {path}")
        if diagnostic.remediation:
            lines.append(f"    next: {diagnostic.remediation}")
    return lines


def recovery_report_to_dict(report: RecoveryReport) -> dict[str, object]:
    """Return a stable JSON-ready recovery report shape."""
    return {
        "diagnostics": [asdict(diagnostic) for diagnostic in report.diagnostics],
        "repository_root": report.repository_root,
        "last_canonical_commit": (
            asdict(report.last_canonical_commit) if report.last_canonical_commit else None
        ),
        "committed_canonical_count": report.committed_canonical_count,
        "uncommitted_paths": list(report.uncommitted_paths),
        "staged_paths": list(report.staged_paths),
        "unstaged_paths": list(report.unstaged_paths),
        "deleted_paths": list(report.deleted_paths),
        "untracked_paths": list(report.untracked_paths),
        "ignored_paths": list(report.ignored_paths),
        "index_flagged_paths": list(report.index_flagged_paths),
        "unrecoverable_committed_paths": list(report.unrecoverable_committed_paths),
    }
