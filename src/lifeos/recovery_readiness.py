"""Read-only recovery-readiness diagnostics for canonical LifeOS vault data."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from lifeos.config import LifeOSConfig

RecoveryStatus = Literal["pass", "warning", "failure", "info", "unknown"]
RecoverySeverity = Literal["info", "warning", "error"]


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


class RecoveryGitError(RuntimeError):
    """Raised when read-only Git metadata cannot be queried deterministically."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _run_git(
    git_executable: str,
    *,
    cwd: Path,
    arguments: Sequence[str],
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            [git_executable, *arguments],
            cwd=cwd,
            shell=False,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise RecoveryGitError(f"Could not execute Git: {error}") from error
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(
            f"Git metadata query failed with exit code {result.returncode}: {detail}"
        )
    return result


def _nul_paths(raw: bytes) -> tuple[str, ...]:
    return tuple(
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0")
        if item
    )


def _runtime_relative_prefix(config: LifeOSConfig) -> tuple[str, ...] | None:
    try:
        relative = config.runtime_dir.relative_to(config.vault_root)
    except ValueError:
        return None
    return tuple(relative.parts) or None


def _canonical_vault_path(
    repo_path: str,
    *,
    vault_repo_prefix: tuple[str, ...],
    runtime_prefix: tuple[str, ...] | None,
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
    if runtime_prefix is not None and relative_parts[: len(runtime_prefix)] == runtime_prefix:
        return None
    return PurePosixPath(*relative_parts).as_posix()


def _filter_canonical_paths(
    paths: Sequence[str],
    *,
    vault_repo_prefix: tuple[str, ...],
    runtime_prefix: tuple[str, ...] | None,
) -> tuple[str, ...]:
    canonical: set[str] = set()
    for path in paths:
        candidate = _canonical_vault_path(
            path,
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
        )
        if candidate is not None:
            canonical.add(candidate)
    return tuple(sorted(canonical))


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
        return None
    raw_root = result.stdout.decode("utf-8", errors="surrogateescape").strip()
    if not raw_root:
        return None
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
    runtime_prefix: tuple[str, ...] | None,
) -> tuple[str, ...]:
    result = _run_git(git_executable, cwd=repository_root, arguments=arguments)
    return _filter_canonical_paths(
        _nul_paths(result.stdout),
        vault_repo_prefix=vault_repo_prefix,
        runtime_prefix=runtime_prefix,
    )


def _head_exists(git_executable: str, repository_root: Path) -> bool:
    result = _run_git(
        git_executable,
        cwd=repository_root,
        arguments=("rev-parse", "--verify", "HEAD"),
        check=False,
    )
    return result.returncode == 0


def _committed_canonical_paths(
    git_executable: str,
    *,
    repository_root: Path,
    pathspec: str,
    vault_repo_prefix: tuple[str, ...],
    runtime_prefix: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if not _head_exists(git_executable, repository_root):
        return ()
    return _git_paths(
        git_executable,
        repository_root=repository_root,
        arguments=("ls-tree", "-r", "--name-only", "-z", "HEAD", "--", pathspec),
        vault_repo_prefix=vault_repo_prefix,
        runtime_prefix=runtime_prefix,
    )


def _latest_canonical_commit(
    git_executable: str,
    *,
    repository_root: Path,
    pathspec: str,
    vault_repo_prefix: tuple[str, ...],
    runtime_prefix: tuple[str, ...] | None,
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
            runtime_prefix=runtime_prefix,
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
            "Install Git and verify that the configured vault is covered by local version history.",
        ),
        RecoveryDiagnostic(
            "recovery.git.last_canonical_commit",
            "unknown",
            "warning",
            "Canonical commit history could not be verified.",
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
    runtime_prefix = _runtime_relative_prefix(config)
    try:
        head_exists = _head_exists(git_executable, repository_root)
        committed_paths = _committed_canonical_paths(
            git_executable,
            repository_root=repository_root,
            pathspec=pathspec,
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
        )
        staged_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=("diff", "--cached", "--name-only", "-z", "--", pathspec),
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
        )
        unstaged_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=("diff", "--name-only", "-z", "--", pathspec),
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
        )
        deleted_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=("ls-files", "--deleted", "-z", "--", pathspec),
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
        )
        untracked_paths = _git_paths(
            git_executable,
            repository_root=repository_root,
            arguments=("ls-files", "--others", "--exclude-standard", "-z", "--", pathspec),
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
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
            runtime_prefix=runtime_prefix,
        )
        last_commit = _latest_canonical_commit(
            git_executable,
            repository_root=repository_root,
            pathspec=pathspec,
            vault_repo_prefix=vault_repo_prefix,
            runtime_prefix=runtime_prefix,
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

    if uncommitted_paths:
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
                "No tracked canonical paths have uncommitted changes.",
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
    }
