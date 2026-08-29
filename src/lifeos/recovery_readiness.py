"""Read-only recovery-readiness diagnostics for canonical LifeOS vault data."""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from lifeos.coherence import CoherenceError
from lifeos.config import LifeOSConfig
from lifeos.retrieval.contracts import (
    RetrievalError,
    RetrievalPolicy,
    RetrievalScope,
    scope_decision,
)
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime_scope import build_runtime_exclusion_matcher

RecoveryStatus = Literal["pass", "warning", "failure", "info", "unknown"]
RecoverySeverity = Literal["info", "warning", "error"]
PathExclusion = Callable[[str], bool]

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_GIT_ENV_KEYS = frozenset(
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
    id: str
    status: RecoveryStatus
    severity: RecoverySeverity
    summary: str
    remediation: str | None = None
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalCommitEvidence:
    sha: str
    committed_at: str
    age_days: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
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
    working_tree_uncertain_paths: tuple[str, ...]
    unrecoverable_committed_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _IndexEntry:
    path: str
    mode: int
    ctime_ns: int
    mtime_ns: int
    device: int
    inode: int
    size: int


@dataclass(frozen=True, slots=True)
class _RepoContext:
    root: Path
    prefix: tuple[str, ...]
    pathspec: str
    case_insensitive_prefix: bool


@dataclass(slots=True)
class _ScopeFilter:
    runtime: PathExclusion
    policy: RetrievalPolicy
    request: RetrievalScope
    incomplete: bool = False

    def __call__(self, path: str) -> bool:
        try:
            if self.runtime(path):
                return True
            allowed = scope_decision(
                path,
                scope=self.request,
                policy=self.policy,
                mode="local",
            ).allowed
        except (CoherenceError, RetrievalError) as exc:
            raise RecoveryGitError("Could not verify canonical recovery scope") from exc
        if not allowed:
            self.incomplete = True
            return True
        return False


class RecoveryGitError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if (
            key in _GIT_ENV_KEYS
            or key.startswith("GIT_TRACE")
            or key == "GIT_CONFIG_COUNT"
            or key.startswith("GIT_CONFIG_KEY_")
            or key.startswith("GIT_CONFIG_VALUE_")
        ):
            env.pop(key, None)
    env.update(
        GIT_OPTIONAL_LOCKS="0",
        GIT_LITERAL_PATHSPECS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_PAGER="",
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="core.fsmonitor",
        GIT_CONFIG_VALUE_0="false",
    )
    return env


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
    except OSError as exc:
        raise RecoveryGitError(f"Could not execute Git: {exc}") from exc
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise RecoveryGitError(
            f"Git metadata query failed with exit code {result.returncode}{suffix}"
        )
    return result


def _runtime_filter(config: LifeOSConfig) -> PathExclusion:
    try:
        relative = config.runtime_dir.relative_to(config.vault_root)
        prefix = f"{relative.as_posix().rstrip('/')}/" if relative.parts else None
    except ValueError:
        prefix = None
    return build_runtime_exclusion_matcher(
        config.vault_root,
        runtime_dir=config.runtime_dir,
        snapshot_prefix=prefix,
    )


def _scope_filter(config: LifeOSConfig) -> _ScopeFilter:
    try:
        runtime = _runtime_filter(config)
        policy = load_retrieval_policy(config.vault_root)
    except (CoherenceError, RetrievalError) as exc:
        raise RecoveryGitError("Could not load recovery scope policy safely") from exc
    return _ScopeFilter(runtime, policy, RetrievalScope())


def _filesystem_case_insensitive(root: Path, relative: Path) -> bool:
    """Detect whether any existing component in the vault path resolves case-insensitively."""
    current = root
    for component in relative.parts:
        actual = current / component
        variant_name = component.swapcase()
        if variant_name != component:
            variant = current / variant_name
            try:
                actual_state = os.stat(actual, follow_symlinks=False)
                variant_state = os.stat(variant, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RecoveryGitError("Could not inspect Git vault path casing") from exc
            else:
                if (actual_state.st_dev, actual_state.st_ino) == (
                    variant_state.st_dev,
                    variant_state.st_ino,
                ):
                    return True
        current = actual
    return False


def _prefix_matches(
    parts: tuple[str, ...],
    prefix: tuple[str, ...],
    *,
    case_insensitive: bool,
) -> bool:
    if len(parts) < len(prefix):
        return False
    candidate = parts[: len(prefix)]
    if candidate == prefix:
        return True
    if not case_insensitive:
        return False
    return tuple(part.casefold() for part in candidate) == tuple(
        part.casefold() for part in prefix
    )


def _canonical_path(
    path: str,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> str | None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    parts = pure.parts
    if prefix:
        if not _prefix_matches(
            parts,
            prefix,
            case_insensitive=case_insensitive_prefix,
        ):
            return None
        parts = parts[len(prefix) :]
    if not parts or "__pycache__" in parts:
        return None
    relative = PurePosixPath(*parts).as_posix()
    if excluded(relative):
        return None
    return relative


def _filter_paths(
    paths: Sequence[str],
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    output = {
        _canonical_path(
            path,
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        for path in paths
    }
    return tuple(sorted(path for path in output if path is not None))


def _nul_paths(raw: bytes) -> tuple[str, ...]:
    return tuple(
        part.decode("utf-8", errors="surrogateescape")
        for part in raw.split(b"\0")
        if part
    )


def _git_paths(
    git: str,
    root: Path,
    args: Sequence[str],
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    result = _run_git(git, cwd=root, arguments=args)
    if result.stderr.strip():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(f"Git path query reported incomplete traversal: {detail}")
    return _filter_paths(
        _nul_paths(result.stdout),
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _git_marker_exists(vault: Path) -> bool:
    for directory in (vault, *vault.parents):
        try:
            os.lstat(directory / ".git")
        except FileNotFoundError:
            continue
        except OSError:
            return True
        return True
    return False


def _git_prefix_spelling(
    git: str,
    root: Path,
    prefix: tuple[str, ...],
) -> tuple[str, ...]:
    """Recover Git's tracked display spelling for a case-insensitive nested vault prefix."""
    result = _run_git(git, cwd=root, arguments=("ls-files", "-z"))
    if result.stderr.strip():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(f"Git index query reported incomplete traversal: {detail}")
    matches: set[tuple[str, ...]] = set()
    folded = tuple(part.casefold() for part in prefix)
    for path in _nul_paths(result.stdout):
        parts = PurePosixPath(path).parts
        if len(parts) < len(prefix):
            continue
        candidate = tuple(parts[: len(prefix)])
        if tuple(part.casefold() for part in candidate) == folded:
            matches.add(candidate)
    if len(matches) > 1:
        raise RecoveryGitError(
            "Git index contains ambiguous case variants for the configured vault"
        )
    return next(iter(matches)) if matches else prefix


def _repo_context(git: str, vault: Path) -> _RepoContext | None:
    result = _run_git(
        git,
        cwd=vault,
        arguments=("rev-parse", "--show-toplevel"),
        check=False,
    )
    if result.returncode:
        if _git_marker_exists(vault):
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RecoveryGitError(
                f"Git repository discovery failed: {detail or result.returncode}"
            )
        return None
    root = Path(
        result.stdout.decode("utf-8", errors="surrogateescape").strip()
    ).resolve(strict=False)
    try:
        relative = vault.relative_to(root)
    except ValueError as exc:
        raise RecoveryGitError(
            "Git repository root does not contain the configured vault"
        ) from exc
    prefix = tuple(relative.parts)
    case_insensitive = _filesystem_case_insensitive(root, relative) if prefix else False
    if prefix and case_insensitive:
        prefix = _git_prefix_spelling(git, root, prefix)
    return _RepoContext(
        root=root,
        prefix=prefix,
        pathspec=PurePosixPath(*prefix).as_posix() if prefix else ".",
        case_insensitive_prefix=case_insensitive,
    )


def _head_exists(git: str, root: Path) -> bool:
    result = _run_git(
        git,
        cwd=root,
        arguments=("rev-parse", "--verify", "HEAD"),
        check=False,
    )
    return result.returncode == 0


def _blob_matches_oid(git: str, root: Path, oid: str) -> bool:
    try:
        oid.encode("ascii")
        producer = subprocess.Popen(
            [git, "cat-file", "blob", oid],
            cwd=root,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
        )
    except UnicodeEncodeError as exc:
        raise RecoveryGitError("Git returned a non-ASCII object identifier") from exc
    except OSError as exc:
        raise RecoveryGitError(f"Could not execute Git: {exc}") from exc
    if producer.stdout is None:
        producer.kill()
        producer.wait()
        raise RecoveryGitError("Could not verify Git blob payload")
    try:
        verifier = subprocess.run(
            [git, "hash-object", "--stdin"],
            cwd=root,
            shell=False,
            check=False,
            stdin=producer.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(),
        )
    except OSError as exc:
        producer.kill()
        producer.wait()
        raise RecoveryGitError(f"Could not execute Git: {exc}") from exc
    finally:
        producer.stdout.close()
    if producer.wait() or verifier.returncode:
        return False
    try:
        return verifier.stdout.decode("ascii", errors="strict").strip() == oid
    except UnicodeDecodeError as exc:
        raise RecoveryGitError("Git returned a non-ASCII object identifier") from exc


def _committed_coverage(
    git: str,
    root: Path,
    pathspec: str,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not _head_exists(git, root):
        return (), ()
    result = _run_git(
        git,
        cwd=root,
        arguments=("ls-tree", "-r", "-z", "HEAD", "--", pathspec),
    )
    if result.stderr.strip():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(f"Git tree query reported incomplete traversal: {detail}")
    entries: list[tuple[str, str]] = []
    gaps: set[str] = set()
    for record in (part for part in result.stdout.split(b"\0") if part):
        meta, tab, raw_path = record.partition(b"\t")
        fields = meta.split()
        if tab != b"\t" or len(fields) != 3:
            raise RecoveryGitError("Git tree query returned malformed output")
        mode, obj_type, raw_oid = fields
        canonical = _canonical_path(
            raw_path.decode("utf-8", errors="surrogateescape"),
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if canonical is None:
            continue
        if obj_type != b"blob" or not mode.startswith(b"100"):
            gaps.add(canonical)
            continue
        try:
            entries.append((canonical, raw_oid.decode("ascii", errors="strict")))
        except UnicodeDecodeError as exc:
            raise RecoveryGitError("Git returned a non-ASCII object identifier") from exc
    availability = {oid: _blob_matches_oid(git, root, oid) for _, oid in entries}
    covered = {path for path, oid in entries if availability[oid]}
    gaps.update(path for path, oid in entries if not availability[oid])
    return tuple(sorted(covered)), tuple(sorted(gaps))


def _index_flags(
    git: str,
    root: Path,
    pathspec: str,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    result = _run_git(
        git,
        cwd=root,
        arguments=("ls-files", "-v", "-z", "--", pathspec),
    )
    if result.stderr.strip():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(f"Git index flag query reported incomplete traversal: {detail}")
    paths: list[str] = []
    for record in (part for part in result.stdout.split(b"\0") if part):
        if len(record) < 3 or record[1:2] != b" ":
            raise RecoveryGitError("Git index flag query returned malformed output")
        tag = chr(record[0])
        if tag == "S" or tag.islower():
            paths.append(record[2:].decode("utf-8", errors="surrogateescape"))
    return _filter_paths(
        paths,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _debug_line(raw: bytes, cursor: int) -> tuple[bytes, int]:
    end = raw.find(b"\n", cursor)
    if end < 0:
        raise RecoveryGitError("Git index metadata query returned truncated output")
    return raw[cursor:end], end + 1


def _time(line: bytes, prefix: bytes) -> int:
    if not line.startswith(prefix):
        raise RecoveryGitError("Git index metadata query returned malformed timestamps")
    values = line[len(prefix) :].split(b":", 1)
    try:
        return int(values[0]) * 1_000_000_000 + int(values[1])
    except (IndexError, ValueError) as exc:
        raise RecoveryGitError(
            "Git index metadata query returned malformed timestamps"
        ) from exc


def _pair(line: bytes, prefix: bytes, second: bytes) -> tuple[int, int]:
    if not line.startswith(prefix):
        raise RecoveryGitError("Git index metadata query returned malformed stat data")
    left, tab, right = line[len(prefix) :].partition(b"\t")
    if tab != b"\t" or not right.startswith(second):
        raise RecoveryGitError("Git index metadata query returned malformed stat data")
    try:
        return int(left), int(right[len(second) :])
    except ValueError as exc:
        raise RecoveryGitError(
            "Git index metadata query returned malformed stat data"
        ) from exc


def _index_entries(raw: bytes) -> tuple[_IndexEntry, ...]:
    entries: list[_IndexEntry] = []
    cursor = 0
    while cursor < len(raw):
        end = raw.find(b"\0", cursor)
        if end < 0:
            raise RecoveryGitError("Git index metadata query returned malformed path data")
        header, cursor = raw[cursor:end], end + 1
        ctime, cursor = _debug_line(raw, cursor)
        mtime, cursor = _debug_line(raw, cursor)
        device, cursor = _debug_line(raw, cursor)
        uid, cursor = _debug_line(raw, cursor)
        size, cursor = _debug_line(raw, cursor)
        meta, tab, raw_path = header.partition(b"\t")
        fields = meta.split()
        if tab != b"\t" or len(fields) != 3 or not uid.startswith(b"  uid: "):
            raise RecoveryGitError("Git index metadata query returned malformed entry data")
        try:
            mode, stage = int(fields[0], 8), int(fields[2])
        except ValueError as exc:
            raise RecoveryGitError(
                "Git index metadata query returned malformed entry data"
            ) from exc
        if stage:
            raise RecoveryGitError("Git index contains unmerged entries")
        dev, ino = _pair(device, b"  dev: ", b"ino: ")
        length, _ = _pair(size, b"  size: ", b"flags: ")
        entries.append(
            _IndexEntry(
                raw_path.decode("utf-8", errors="surrogateescape"),
                mode,
                _time(ctime, b"  ctime: "),
                _time(mtime, b"  mtime: "),
                dev,
                ino,
                length,
            )
        )
    return tuple(entries)


def _lstat(vault: Path, relative: str) -> os.stat_result | None:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RecoveryGitError("Canonical Git path escaped the configured vault")
    opened: list[int] = []
    try:
        current = os.open(vault, _DIR_FLAGS)
        opened.append(current)
        for part in pure.parts[:-1]:
            try:
                next_fd = os.open(part, _DIR_FLAGS, dir_fd=current)
            except FileNotFoundError:
                return None
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise RecoveryGitError(
                        "Canonical working-tree metadata traverses an unsafe parent entry"
                    ) from exc
                raise RecoveryGitError(
                    "Could not inspect canonical working-tree metadata"
                ) from exc
            opened.append(next_fd)
            current = next_fd
        try:
            return os.stat(pure.parts[-1], dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return None
    except OSError as exc:
        raise RecoveryGitError("Could not inspect canonical working-tree metadata") from exc
    finally:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass


def _worktree(
    git: str,
    root: Path,
    vault: Path,
    pathspec: str,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    result = _run_git(
        git,
        cwd=root,
        arguments=("ls-files", "--stage", "--debug", "-z", "--", pathspec),
    )
    if result.stderr.strip():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(f"Git worktree query reported incomplete traversal: {detail}")
    modified: set[str] = set()
    deleted: set[str] = set()
    uncertain: set[str] = set()
    for entry in _index_entries(result.stdout):
        path = _canonical_path(
            entry.path,
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if path is None:
            continue
        observed = _lstat(vault, path)
        if observed is None:
            deleted.add(path)
            continue
        if entry.mode not in {0o100644, 0o100755} or not stat.S_ISREG(observed.st_mode):
            modified.add(path)
            continue
        if entry.size != observed.st_size:
            modified.add(path)
            continue
        if (
            entry.mtime_ns != observed.st_mtime_ns
            or entry.ctime_ns != observed.st_ctime_ns
            or (entry.device and entry.device != (observed.st_dev & 0xFFFFFFFF))
            or (entry.inode and entry.inode != (observed.st_ino & 0xFFFFFFFF))
        ):
            uncertain.add(path)
    return tuple(sorted(modified)), tuple(sorted(deleted)), tuple(sorted(uncertain))


def _latest_commit(
    git: str,
    root: Path,
    pathspec: str,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    clock: Callable[[], datetime],
    *,
    case_insensitive_prefix: bool = False,
) -> CanonicalCommitEvidence | None:
    if not _head_exists(git, root):
        return None
    revision_result = _run_git(
        git,
        cwd=root,
        arguments=("rev-list", "HEAD", "--", pathspec),
    )
    if revision_result.stderr.strip():
        detail = revision_result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryGitError(f"Git history query reported incomplete traversal: {detail}")
    for sha in revision_result.stdout.decode("ascii", errors="strict").splitlines():
        changed = _git_paths(
            git,
            root,
            (
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
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if not changed:
            continue
        stamp_result = _run_git(
            git,
            cwd=root,
            arguments=("show", "-s", "--format=%cI", sha),
        )
        if stamp_result.stderr.strip():
            detail = stamp_result.stderr.decode("utf-8", errors="replace").strip()
            raise RecoveryGitError(f"Git commit query reported incomplete traversal: {detail}")
        stamp = stamp_result.stdout.decode("ascii", errors="strict").strip()
        try:
            committed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecoveryGitError("Git returned an invalid commit timestamp") from exc
        if committed.tzinfo is None:
            committed = committed.replace(tzinfo=timezone.utc)
        now = clock()
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age = max(
            0.0,
            (
                now.astimezone(timezone.utc) - committed.astimezone(timezone.utc)
            ).total_seconds(),
        )
        return CanonicalCommitEvidence(sha, stamp, int(age // 86_400))
    return None


def _diag(
    id_: str,
    status: RecoveryStatus,
    severity: RecoverySeverity,
    summary: str,
    remediation: str | None = None,
    paths: tuple[str, ...] = (),
) -> RecoveryDiagnostic:
    return RecoveryDiagnostic(id_, status, severity, summary, remediation, paths)


def _git_unknown(summary: str) -> tuple[RecoveryDiagnostic, ...]:
    return (
        _diag(
            "recovery.git.repository",
            "unknown",
            "error",
            summary,
            "Verify Git repository ownership, permissions, and metadata, then retry the doctor.",
        ),
        _diag(
            "recovery.git.last_canonical_commit",
            "unknown",
            "warning",
            "Canonical commit history could not be verified.",
        ),
        _diag(
            "recovery.git.canonical_objects",
            "unknown",
            "warning",
            "Local recoverability of committed canonical blobs could not be verified.",
        ),
        _diag(
            "recovery.git.uncommitted_canonical",
            "unknown",
            "warning",
            "Uncommitted canonical changes could not be verified.",
        ),
        _diag(
            "recovery.git.untracked_canonical",
            "unknown",
            "warning",
            "Untracked canonical files could not be verified.",
        ),
        _diag(
            "recovery.git.ignored_canonical",
            "unknown",
            "warning",
            "Ignored canonical files could not be verified.",
        ),
    )


def _no_repo() -> tuple[RecoveryDiagnostic, ...]:
    return (
        _diag(
            "recovery.git.repository",
            "failure",
            "error",
            "The configured vault is not covered by a Git repository.",
            (
                "Initialize version history for the canonical vault and commit the intended "
                "durable files."
            ),
        ),
        _diag(
            "recovery.git.last_canonical_commit",
            "unknown",
            "warning",
            "No canonical commit can exist until the vault is covered by Git history.",
        ),
        _diag(
            "recovery.git.canonical_objects",
            "unknown",
            "warning",
            "No committed canonical blobs can be verified without a Git repository.",
        ),
        _diag(
            "recovery.git.uncommitted_canonical",
            "unknown",
            "warning",
            "Uncommitted canonical coverage cannot be classified without a Git repository.",
        ),
        _diag(
            "recovery.git.untracked_canonical",
            "unknown",
            "warning",
            "Untracked canonical coverage cannot be classified without a Git repository.",
        ),
        _diag(
            "recovery.git.ignored_canonical",
            "unknown",
            "warning",
            "Ignored canonical coverage cannot be classified without a Git repository.",
        ),
    )


def _external() -> RecoveryDiagnostic:
    return _diag(
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


def _runtime(config: LifeOSConfig) -> RecoveryDiagnostic:
    try:
        display = config.runtime_dir.relative_to(config.vault_root).as_posix()
    except ValueError:
        display = "<external-runtime>"
    return _diag(
        "recovery.runtime.disposable",
        "info",
        "info",
        (
            f"Disposable runtime state at {display} is rebuildable and is not canonical "
            "recovery material."
        ),
        "Restore canonical vault data first, then rebuild or recreate derived runtime state.",
    )


def _fallback(
    config: LifeOSConfig,
    items: tuple[RecoveryDiagnostic, ...],
    root: Path | None = None,
) -> RecoveryReport:
    return RecoveryReport(
        (*items, _external(), _runtime(config)),
        str(root) if root else None,
        None,
        0,
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
    )


def _incomplete(subject: str) -> str:
    return (
        f"{subject} is incomplete because protected or policy-excluded canonical scope was not "
        "inspected or exposed."
    )


def collect_recovery_readiness(
    config: LifeOSConfig,
    *,
    clock_fn: Callable[[], datetime] = _utc_now,
) -> RecoveryReport:
    git = shutil.which("git")
    if git is None:
        return _fallback(
            config,
            _git_unknown("Git is unavailable, so local canonical history is unknown."),
        )
    try:
        context = _repo_context(git, config.vault_root)
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)))
    if context is None:
        return _fallback(config, _no_repo())

    root = context.root
    prefix = context.prefix
    pathspec = context.pathspec
    case_insensitive_prefix = context.case_insensitive_prefix
    try:
        scope = _scope_filter(config)
        head = _head_exists(git, root)
        committed, unrecoverable = _committed_coverage(
            git,
            root,
            pathspec,
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        staged = _git_paths(
            git,
            root,
            (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "-z",
                "--",
                pathspec,
            ),
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        unstaged, deleted, uncertain = _worktree(
            git,
            root,
            config.vault_root,
            pathspec,
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        untracked = _git_paths(
            git,
            root,
            ("ls-files", "--others", "--exclude-standard", "-z", "--", pathspec),
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        ignored = _git_paths(
            git,
            root,
            (
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
                "--",
                pathspec,
            ),
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        flags = _index_flags(
            git,
            root,
            pathspec,
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        last = _latest_commit(
            git,
            root,
            pathspec,
            prefix,
            scope,
            clock_fn,
            case_insensitive_prefix=case_insensitive_prefix,
        )
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)), root)

    incomplete = scope.incomplete
    uncommitted = tuple(sorted(set(staged) | set(unstaged) | set(deleted)))
    items: list[RecoveryDiagnostic] = [
        _diag(
            "recovery.git.repository",
            "pass",
            "info",
            "The configured vault is covered by a local Git repository.",
        )
    ]

    if not head:
        items.append(
            _diag(
                "recovery.git.last_canonical_commit",
                "failure",
                "error",
                (
                    "The Git repository has no commit yet, so no canonical vault version is "
                    "recoverable from history."
                ),
                "Create a reviewed initial commit containing the intended canonical vault files.",
            )
        )
    elif incomplete:
        items.append(
            _diag(
                "recovery.git.last_canonical_commit",
                "unknown",
                "warning",
                _incomplete("Canonical commit-history coverage"),
                (
                    "Review protected/excluded recovery scope explicitly before treating commit "
                    "coverage as complete."
                ),
            )
        )
    elif last is None:
        items.append(
            _diag(
                "recovery.git.last_canonical_commit",
                "failure",
                "error",
                "Git history exists, but no commit affecting canonical vault paths was found.",
                "Commit the intended canonical vault files before relying on Git recovery.",
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.last_canonical_commit",
                "info",
                "info",
                (
                    f"Latest canonical commit is {last.sha[:12]} from {last.committed_at} "
                    f"({last.age_days} day(s) old)."
                ),
            )
        )

    if not head:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "unknown",
                "warning",
                "Committed canonical blob availability cannot be verified before the first commit.",
            )
        )
    elif unrecoverable:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "failure",
                "error",
                (
                    f"{len(unrecoverable)} visible committed canonical path(s) are not backed by "
                    "locally hash-verified regular blob objects."
                ),
                (
                    "Repair the local Git object store or replace gitlink/symlink-style canonical "
                    "entries with ordinary recoverable vault files before relying on local history."
                ),
                unrecoverable,
            )
        )
    elif incomplete:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "unknown",
                "warning",
                _incomplete("Committed canonical object coverage"),
                (
                    "Review protected/excluded recovery scope explicitly before treating local "
                    "object coverage as complete."
                ),
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "pass",
                "info",
                (
                    "Committed canonical tree entries are backed by locally hash-verified regular "
                    "blobs."
                ),
            )
        )

    uncertain_all = tuple(sorted(set(uncertain) | set(flags)))
    all_tracked = tuple(sorted(set(uncommitted) | set(uncertain_all)))
    if uncommitted:
        suffix = (
            f" {len(uncertain_all)} additional tracked path(s) have unverified metadata state."
            if uncertain_all
            else ""
        )
        items.append(
            _diag(
                "recovery.git.uncommitted_canonical",
                "warning",
                "warning",
                (
                    f"{len(uncommitted)} tracked canonical path(s) have staged, modified, or "
                    f"deleted state not represented by the latest commit.{suffix}"
                ),
                (
                    "Review and commit intended canonical changes; inspect metadata-uncertain "
                    "paths and clear hiding index flags before treating the tree as clean."
                ),
                all_tracked,
            )
        )
    elif uncertain_all:
        items.append(
            _diag(
                "recovery.git.uncommitted_canonical",
                "unknown",
                "warning",
                (
                    f"Working-tree content equality cannot be proven for {len(uncertain_all)} "
                    "visible canonical path(s) from metadata alone."
                ),
                (
                    "Inspect the listed paths and clear assume-unchanged/skip-worktree flags where "
                    "present before treating the tree as clean."
                ),
                uncertain_all,
            )
        )
    elif incomplete:
        items.append(
            _diag(
                "recovery.git.uncommitted_canonical",
                "unknown",
                "warning",
                _incomplete("Uncommitted canonical coverage"),
                (
                    "Review protected/excluded recovery scope explicitly before treating the "
                    "working tree as clean."
                ),
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.uncommitted_canonical",
                "pass",
                "info",
                (
                    "No tracked canonical paths have proven uncommitted changes or unresolved "
                    "metadata state."
                ),
            )
        )

    if untracked:
        items.append(
            _diag(
                "recovery.git.untracked_canonical",
                "warning",
                "warning",
                (
                    f"{len(untracked)} visible canonical path(s) are untracked and absent from "
                    "committed history."
                ),
                "Review these paths and add/commit the canonical files that should be recoverable.",
                untracked,
            )
        )
    elif incomplete:
        items.append(
            _diag(
                "recovery.git.untracked_canonical",
                "unknown",
                "warning",
                _incomplete("Untracked canonical coverage"),
                (
                    "Review protected/excluded recovery scope explicitly before treating untracked "
                    "coverage as complete."
                ),
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.untracked_canonical",
                "pass",
                "info",
                "No untracked canonical paths were found.",
            )
        )

    if ignored:
        items.append(
            _diag(
                "recovery.git.ignored_canonical",
                "warning",
                "warning",
                (
                    f"{len(ignored)} visible canonical path(s) are ignored by Git and absent from "
                    "committed canonical history."
                ),
                (
                    "Review ignore rules and protect these canonical files through the intended "
                    "durable history."
                ),
                ignored,
            )
        )
    elif incomplete:
        items.append(
            _diag(
                "recovery.git.ignored_canonical",
                "unknown",
                "warning",
                _incomplete("Ignored canonical coverage"),
                (
                    "Review protected/excluded recovery scope explicitly before treating ignore "
                    "coverage as complete."
                ),
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.ignored_canonical",
                "pass",
                "info",
                "No ignored canonical paths outside committed history were found.",
            )
        )

    items.extend((_external(), _runtime(config)))
    return RecoveryReport(
        tuple(items),
        str(root),
        last,
        len(committed),
        uncommitted,
        staged,
        unstaged,
        deleted,
        untracked,
        ignored,
        flags,
        uncertain,
        unrecoverable,
    )


def _terminal_safe_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)[1:-1]


def _terminal_safe_path(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def format_recovery_text(report: RecoveryReport) -> list[str]:
    lines = ["Recovery readiness"]
    if report.repository_root is not None:
        lines.append(f"  local Git repository: {_terminal_safe_text(report.repository_root)}")
    lines.append(f"  committed canonical paths: {report.committed_canonical_count}")
    for diagnostic in report.diagnostics:
        lines.append(
            f"  {diagnostic.id}: {diagnostic.status} ({diagnostic.severity}) - "
            f"{_terminal_safe_text(diagnostic.summary)}"
        )
        lines.extend(
            f"    path: {_terminal_safe_path(path)}" for path in diagnostic.paths
        )
        if diagnostic.remediation:
            lines.append(f"    next: {_terminal_safe_text(diagnostic.remediation)}")
    return lines


def recovery_report_to_dict(report: RecoveryReport) -> dict[str, object]:
    return {
        "diagnostics": [asdict(item) for item in report.diagnostics],
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
        "working_tree_uncertain_paths": list(report.working_tree_uncertain_paths),
        "unrecoverable_committed_paths": list(report.unrecoverable_committed_paths),
    }
