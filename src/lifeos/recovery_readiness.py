"""Read-only recovery-readiness diagnostics for canonical LifeOS vault data.

Recovery inspection is implemented statically in this module. Git subprocesses run
against a bounded, descriptor-pinned metadata snapshot; protected scope is authorized
before traversal or disclosure.
"""

from __future__ import annotations

import contextvars
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

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
Pathspec = str | Sequence[str]

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_INDEX_SIZE_MAX = (1 << 32) - 1
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
        "GIT_GLOB_PATHSPECS",
        "GIT_ICASE_PATHSPECS",
        "GIT_INDEX_FILE",
        "GIT_LITERAL_PATHSPECS",
        "GIT_NAMESPACE",
        "GIT_NOGLOB_PATHSPECS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_QUARANTINE_PATH",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_DIRECTORY_FLAGS = _FILE_FLAGS | getattr(os, "O_DIRECTORY", 0)
_ENTRY_FLAGS = _FILE_FLAGS | getattr(os, "O_NONBLOCK", 0)
_PINNED_DIRECTORY_SUPPORT = (
    bool(getattr(os, "O_NOFOLLOW", 0))
    and bool(getattr(os, "O_DIRECTORY", 0))
    and os.open in os.supports_dir_fd
    and os.scandir in os.supports_fd
)
_SECTION_RE = re.compile(r'^\s*\[\s*([^\]\s"]+)(?:\s+"((?:\\.|[^"\\])*)")?\s*\]\s*(?:[#;].*)?$')
_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z0-9.-]+)\s*(?:=\s*)?(.*?)\s*$")
_DEFAULT_PINNED_OBJECT_FILES = 1024
_MAX_PINNED_OBJECT_FILES = 4096
_PINNED_OBJECT_FD_RESERVE = 64
_MAX_GIT_METADATA_BYTES = 2_000_000


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
    oid: str
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


@dataclass(frozen=True, slots=True)
class _GitSnapshot:
    head_oid: str | None
    index_debug: bytes
    index_flags: bytes


@dataclass(frozen=True, slots=True)
class _FsEntry:
    path: str
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _WorkingTreeSnapshot:
    entries: tuple[_FsEntry, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries)

    def by_path(self) -> dict[str, _FsEntry]:
        return {entry.path: entry for entry in self.entries}


class RecoveryGitError(RuntimeError):
    pass


@dataclass(slots=True)
class _ScopeFilter:
    runtime: PathExclusion
    policy: RetrievalPolicy
    request: RetrievalScope
    case_insensitive: bool = False
    incomplete: bool = False

    def __call__(self, path: str) -> bool:
        try:
            if _selects_repository_metadata(path):
                return True
            if self.runtime(path):
                return True
            if self.case_insensitive and _casefold_denied(path, self.policy, self.request):
                self.incomplete = True
                return True
            normalized_path = unicodedata.normalize("NFC", path)
            decision = scope_decision(
                normalized_path,
                scope=self.request,
                policy=self.policy,
                mode="local",
            )
        except (CoherenceError, RetrievalError) as exc:
            raise RecoveryGitError("Could not verify canonical recovery scope") from exc
        if not decision.allowed:
            self.incomplete = True
            return True
        return False


@dataclass(slots=True)
class _GitMetadataSandbox:
    temporary: tempfile.TemporaryDirectory[str]
    root: Path
    vault: Path
    git_dir: Path
    object_dir: Path
    index_mtime_ns: int | None
    fingerprint: str
    contains_includes: bool
    ignorecase: bool
    metadata_fd: int | None = None
    metadata_fd_path: str | None = None
    object_fd: int | None = None
    object_fd_path: str | None = None
    object_fds: tuple[int, ...] = ()

    def close(self) -> None:
        try:
            self.temporary.cleanup()
        except OSError:
            pass
        seen: set[int] = set()
        for fd in (*self.object_fds, self.object_fd, self.metadata_fd):
            if fd is None or fd in seen:
                continue
            seen.add(fd)
            try:
                os.close(fd)
            except OSError:
                pass
        self.object_fds = ()
        self.object_fd = None
        self.metadata_fd = None


@dataclass(frozen=True, slots=True)
class _VisibleIgnoreClassification:
    untracked: tuple[str, ...]
    ignored: tuple[str, ...]


_ACTIVE_SANDBOX: contextvars.ContextVar[_GitMetadataSandbox | None] = contextvars.ContextVar(
    "lifeos_recovery_git_metadata_sandbox", default=None
)
_ACTIVE_CONFIG: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "lifeos_recovery_active_config", default=None
)
_ACTIVE_WORKTREE_SNAPSHOT: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "lifeos_recovery_worktree_snapshot", default=None
)
_ACTIVE_GIT_EXECUTABLE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "lifeos_recovery_git_executable", default=None
)
_ACTIVE_VISIBLE_IGNORE_CLASSIFICATION: contextvars.ContextVar[
    _VisibleIgnoreClassification | None
] = contextvars.ContextVar("lifeos_recovery_visible_ignore_classification", default=None)


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
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_PAGER="",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="core.fsmonitor",
        GIT_CONFIG_VALUE_0="false",
    )
    return env


def _runtime_filter(config: LifeOSConfig) -> PathExclusion:
    try:
        relative = config.runtime_dir.relative_to(config.vault_root)
        prefix = f"{relative.as_posix().rstrip('/')}/" if relative.parts else None
    except ValueError:
        prefix = None
    configured = build_runtime_exclusion_matcher(
        config.vault_root,
        runtime_dir=config.runtime_dir,
        snapshot_prefix=prefix,
    )
    reserved = build_runtime_exclusion_matcher(
        config.vault_root,
        runtime_dir=config.vault_root / ".lifeos",
        snapshot_prefix=".lifeos/",
    )

    def excluded(path: str) -> bool:
        return bool(reserved(path) or configured(path))

    return excluded


def _vault_case_insensitive(vault: Path) -> bool:
    # Probe only fixed LifeOS metadata names; never enumerate user-owned vault names.
    for relative in (Path("lifeos.yml"), Path("system"), Path("system/retrieval-policy.yml")):
        try:
            os.lstat(vault / relative)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RecoveryGitError("Could not inspect vault case semantics safely") from exc
        return _filesystem_case_insensitive(vault, relative)
    raise RecoveryGitError("Could not determine vault filesystem case semantics safely")


def _casefold_matches_prefix(path: str, prefixes: Sequence[str]) -> bool:
    folded = unicodedata.normalize("NFC", path).casefold()
    return any(
        folded == unicodedata.normalize("NFC", prefix.rstrip("/")).casefold()
        or folded.startswith(unicodedata.normalize("NFC", prefix.rstrip("/")).casefold() + "/")
        for prefix in prefixes
    )


def _casefold_denied(
    path: str,
    policy: RetrievalPolicy,
    request: RetrievalScope,
) -> bool:
    if _casefold_matches_prefix(path, policy.excluded_prefixes):
        return True
    if _casefold_matches_prefix(path, request.excluded_paths):
        return True
    return not request.allow_protected and _casefold_matches_prefix(path, policy.protected_prefixes)


def _filesystem_case_insensitive(root: Path, relative: Path) -> bool:
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
    return tuple(part.casefold() for part in candidate) == tuple(part.casefold() for part in prefix)


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
        if not _prefix_matches(parts, prefix, case_insensitive=case_insensitive_prefix):
            return None
        parts = parts[len(prefix) :]
    if not parts or ".git" in parts:
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
        part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part
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
        raise RecoveryGitError("Git path query reported incomplete results")
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


def _decode_single_line_path(raw: bytes) -> str:
    if not raw.endswith(b"\n"):
        raise RecoveryGitError("Git repository discovery returned malformed output")
    try:
        return raw[:-1].decode("utf-8", errors="surrogateescape")
    except UnicodeError as exc:
        raise RecoveryGitError("Git repository discovery returned malformed output") from exc


def _parse_tree_records(raw: bytes) -> tuple[tuple[int, str, str, str], ...]:
    output: list[tuple[int, str, str, str]] = []
    for record in (part for part in raw.split(b"\0") if part):
        meta, tab, raw_path = record.partition(b"\t")
        fields = meta.split()
        if tab != b"\t" or len(fields) != 3:
            raise RecoveryGitError("Git tree query returned malformed output")
        raw_mode, raw_type, raw_oid = fields
        try:
            mode = int(raw_mode, 8)
            obj_type = raw_type.decode("ascii", errors="strict")
            oid = raw_oid.decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="surrogateescape")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RecoveryGitError("Git tree query returned malformed metadata") from exc
        output.append((mode, obj_type, oid, path))
    return tuple(output)


def _root_tree_oid(git: str, root: Path, head_oid: str) -> str:
    result = _run_git(
        git,
        cwd=root,
        arguments=("rev-parse", "--verify", f"{head_oid}^{{tree}}"),
    )
    if result.stderr.strip():
        raise RecoveryGitError("Git root tree query reported incomplete results")
    try:
        oid = result.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise RecoveryGitError("Git returned a malformed tree object identifier") from exc
    if not oid:
        raise RecoveryGitError("Git returned an empty tree object identifier")
    return oid


def _git_prefix_spelling(
    git: str,
    root: Path,
    prefix: tuple[str, ...],
) -> tuple[str, ...]:
    """Resolve only the configured ancestor chain, never the parent repository file inventory."""
    head = _head_oid(git, root)
    if head is None:
        return prefix
    tree_oid = _root_tree_oid(git, root, head)
    selected: list[str] = []
    for offset, requested in enumerate(prefix):
        result = _run_git(git, cwd=root, arguments=("ls-tree", "-z", tree_oid))
        if result.stderr.strip():
            raise RecoveryGitError("Git prefix query reported incomplete results")
        matches = [
            record
            for record in _parse_tree_records(result.stdout)
            if PurePosixPath(record[3]).name.casefold() == requested.casefold()
        ]
        if len(matches) > 1:
            raise RecoveryGitError(
                "Git tree contains ambiguous case variants for the configured vault"
            )
        if not matches:
            return prefix
        mode, obj_type, oid, name = matches[0]
        selected.append(PurePosixPath(name).name)
        if offset < len(prefix) - 1:
            if obj_type != "tree" or (mode & 0o170000) != 0o040000:
                return prefix
            tree_oid = oid
    return tuple(selected)


def _repo_context(git: str, vault: Path) -> _RepoContext | None:
    result = _run_git(
        git,
        cwd=vault,
        arguments=("rev-parse", "--show-toplevel"),
        check=False,
    )
    if result.returncode:
        if _git_marker_exists(vault):
            raise RecoveryGitError(
                "Git repository discovery failed; repository state could not be verified safely."
            )
        return None
    if result.stderr.strip():
        raise RecoveryGitError(
            "Git repository discovery reported incomplete results; state is unknown."
        )
    root = Path(_decode_single_line_path(result.stdout)).resolve(strict=False)
    try:
        relative = vault.relative_to(root)
    except ValueError as exc:
        raise RecoveryGitError("Git repository root does not contain the configured vault") from exc
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


def _head_oid(git: str, root: Path) -> str | None:
    result = _run_git(
        git,
        cwd=root,
        arguments=("rev-parse", "--verify", "--quiet", "HEAD"),
        check=False,
    )
    if result.returncode == 1 and not result.stderr.strip():
        return None
    if result.returncode != 0 or result.stderr.strip():
        raise RecoveryGitError("Git HEAD could not be verified safely")
    try:
        oid = result.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise RecoveryGitError("Git returned a non-ASCII HEAD object identifier") from exc
    if not oid:
        raise RecoveryGitError("Git returned an empty HEAD object identifier")
    return oid


def _policy_denied_prefixes(scope: _ScopeFilter) -> tuple[str, ...]:
    values: list[str] = [*scope.policy.excluded_prefixes, *scope.request.excluded_paths]
    if not scope.request.allow_protected:
        values.extend(scope.policy.protected_prefixes)
    normalized = {value.rstrip("/") for value in values if value.rstrip("/")}
    return tuple(sorted(normalized))


def _runtime_prefixes(config: LifeOSConfig) -> tuple[str, ...]:
    values = {".lifeos"}
    try:
        relative = config.runtime_dir.relative_to(config.vault_root)
    except ValueError:
        pass
    else:
        if relative.parts:
            values.add(relative.as_posix().rstrip("/"))
    return tuple(sorted(values))


def _repo_path(path: str, prefix: tuple[str, ...]) -> str:
    parts = (*prefix, *PurePosixPath(path).parts)
    return PurePosixPath(*parts).as_posix()


def _literal_pathspec(
    path: str,
    *,
    exclude: bool = False,
    icase: bool = False,
) -> str:
    parts = ["top"]
    if exclude:
        parts.append("exclude")
    if icase:
        parts.append("icase")
    parts.append("literal")
    return f":({','.join(parts)}){path}"


def _uses_magic(pathspecs: Sequence[str]) -> bool:
    return any(path.startswith(":(") for path in pathspecs)


def _pathspec_command(
    command: str, arguments: Sequence[str], pathspec: Pathspec
) -> tuple[str, ...]:
    pathspecs = (pathspec,) if isinstance(pathspec, str) else tuple(pathspec)
    prefix = ("--no-literal-pathspecs",) if _uses_magic(pathspecs) else ("--literal-pathspecs",)
    return (*prefix, command, *arguments, "--", *pathspecs)


def _index_debug_raw(git: str, root: Path, pathspec: Pathspec) -> bytes:
    result = _run_git(
        git,
        cwd=root,
        arguments=_pathspec_command("ls-files", ("--stage", "--debug", "-z"), pathspec),
    )
    if result.stderr.strip():
        raise RecoveryGitError("Git worktree query reported incomplete results")
    return result.stdout


def _index_flags_raw(git: str, root: Path, pathspec: Pathspec) -> bytes:
    result = _run_git(
        git,
        cwd=root,
        arguments=_pathspec_command("ls-files", ("-v", "-z"), pathspec),
    )
    if result.stderr.strip():
        raise RecoveryGitError("Git index flag query reported incomplete results")
    return result.stdout


def _git_snapshot(git: str, root: Path, pathspec: Pathspec) -> _GitSnapshot:
    return _GitSnapshot(
        _head_oid(git, root),
        _index_debug_raw(git, root, pathspec),
        _index_flags_raw(git, root, pathspec),
    )


def _walk_tree_entries(
    git: str,
    root: Path,
    tree_oid: str,
    relative_parts: tuple[str, ...],
    excluded: PathExclusion,
) -> dict[str, tuple[int, str, str]]:
    result = _run_git(git, cwd=root, arguments=("ls-tree", "-z", tree_oid))
    if result.stderr.strip():
        raise RecoveryGitError("Git tree query reported incomplete results")
    output: dict[str, tuple[int, str, str]] = {}
    for mode, obj_type, oid, name in _parse_tree_records(result.stdout):
        if "/" in name:
            raise RecoveryGitError("Git tree query returned an unexpected nested path")
        child = PurePosixPath(*relative_parts, name).as_posix()
        if excluded(child):
            continue
        if obj_type == "tree" and (mode & 0o170000) == 0o040000:
            nested = _walk_tree_entries(
                git,
                root,
                oid,
                (*relative_parts, name),
                excluded,
            )
            overlap = set(output) & set(nested)
            if overlap:
                raise RecoveryGitError("Git tree contains ambiguous canonical path aliases")
            output.update(nested)
            continue
        if child in output:
            raise RecoveryGitError("Git tree contains ambiguous canonical path aliases")
        output[child] = (mode, obj_type, oid)
    return output


def _index_flags_from_raw(
    raw: bytes,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    paths: list[str] = []
    for record in (part for part in raw.split(b"\0") if part):
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


def _skip_worktree_paths_from_raw(
    raw: bytes,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    paths: list[str] = []
    for record in (part for part in raw.split(b"\0") if part):
        if len(record) < 3 or record[1:2] != b" ":
            raise RecoveryGitError("Git index flag query returned malformed output")
        if record[0:1] == b"S":
            paths.append(record[2:].decode("utf-8", errors="surrogateescape"))
    return _filter_paths(
        paths,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _core_filemode(git: str, root: Path) -> bool:
    result = _run_git(
        git,
        cwd=root,
        arguments=("config", "--bool", "--get", "core.filemode"),
        check=False,
    )
    if result.returncode == 1 and not result.stderr.strip():
        return True
    if result.returncode or result.stderr.strip():
        raise RecoveryGitError("Git file-mode configuration could not be verified safely")
    value = result.stdout.rstrip(b"\n")
    if value == b"true":
        return True
    if value == b"false":
        return False
    raise RecoveryGitError("Git returned malformed file-mode configuration")


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
        raise RecoveryGitError("Git index metadata query returned malformed timestamps") from exc


def _pair(line: bytes, prefix: bytes, second: bytes) -> tuple[int, int]:
    if not line.startswith(prefix):
        raise RecoveryGitError("Git index metadata query returned malformed stat data")
    left, tab, right = line[len(prefix) :].partition(b"\t")
    if tab != b"\t" or not right.startswith(second):
        raise RecoveryGitError("Git index metadata query returned malformed stat data")
    try:
        return int(left), int(right[len(second) :])
    except ValueError as exc:
        raise RecoveryGitError("Git index metadata query returned malformed stat data") from exc


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
            oid = fields[1].decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
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
                oid,
                _time(ctime, b"  ctime: "),
                _time(mtime, b"  mtime: "),
                dev,
                ino,
                length,
            )
        )
    return tuple(entries)


def _canonical_index_entries(
    entries: Sequence[_IndexEntry],
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> dict[str, _IndexEntry]:
    output: dict[str, _IndexEntry] = {}
    for entry in entries:
        canonical = _canonical_path(
            entry.path,
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if canonical is None:
            continue
        if canonical in output:
            raise RecoveryGitError("Git index contains ambiguous canonical path aliases")
        output[canonical] = entry
    return output


def _staged_paths(
    entries: Sequence[_IndexEntry],
    tree_entries: dict[str, tuple[int, str, str]],
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    index = _canonical_index_entries(
        entries,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )
    staged: set[str] = set()
    for path in set(index) | set(tree_entries):
        current = index.get(path)
        committed = tree_entries.get(path)
        if current is None or committed is None:
            staged.add(path)
            continue
        committed_mode, _committed_type, committed_oid = committed
        if current.mode != committed_mode or current.oid != committed_oid:
            staged.add(path)
    return tuple(sorted(staged))


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
                raise RecoveryGitError("Could not inspect canonical working-tree metadata") from exc
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


def _fs_entry(path: str, observed: os.stat_result) -> _FsEntry:
    return _FsEntry(
        path,
        observed.st_mode,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
        observed.st_dev,
        observed.st_ino,
    )


def _walk_visible_snapshot(
    directory_fd: int,
    relative_parts: tuple[str, ...],
    excluded: PathExclusion,
) -> list[_FsEntry]:
    try:
        with os.scandir(directory_fd) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        raise RecoveryGitError("Could not enumerate canonical working-tree metadata") from exc
    output: list[_FsEntry] = []
    for entry in entries:
        name = entry.name
        if name == ".git":
            continue
        child_parts = (*relative_parts, name)
        relative = PurePosixPath(*child_parts).as_posix()
        if excluded(relative):
            continue
        try:
            observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise RecoveryGitError("Could not inspect canonical working-tree metadata") from exc
        if stat.S_ISDIR(observed.st_mode):
            try:
                child_fd = os.open(name, _DIR_FLAGS, dir_fd=directory_fd)
            except OSError as exc:
                raise RecoveryGitError("Could not inspect canonical working-tree metadata") from exc
            try:
                output.extend(_walk_visible_snapshot(child_fd, child_parts, excluded))
            finally:
                os.close(child_fd)
            continue
        output.append(_fs_entry(relative, observed))
    return output


def _worktree_from_entries(
    entries: Sequence[_IndexEntry],
    vault: Path,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    index = _canonical_index_entries(
        entries,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )
    modified: set[str] = set()
    deleted: set[str] = set()
    uncertain: set[str] = set()
    for path, entry in index.items():
        observed = _lstat(vault, path)
        if observed is None:
            deleted.add(path)
            continue
        classification = _compare_index_entry(entry, _fs_entry(path, observed))
        if classification == "modified":
            modified.add(path)
        elif classification == "uncertain":
            uncertain.add(path)
    return tuple(sorted(modified)), tuple(sorted(deleted)), tuple(sorted(uncertain))


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
            "Committed canonical object payload integrity is not verified by recovery diagnostics.",
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
            "Initialize version history for the canonical vault and commit the intended durable files.",
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
            "Committed canonical object payload integrity is not inspected without Git history.",
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
        f"Disposable runtime state at {display} is rebuildable and is not canonical recovery material.",
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


def _resolve_git_executable() -> str | None:
    discovered = shutil.which("git")
    if discovered is None:
        return None
    try:
        return str(Path(discovered).resolve(strict=True))
    except OSError as exc:
        raise RecoveryGitError("Git executable could not be resolved safely") from exc


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
        lines.extend(f"    path: {_terminal_safe_path(path)}" for path in diagnostic.paths)
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


def _load_scope_filter(config: LifeOSConfig) -> _ScopeFilter:
    try:
        runtime = _runtime_filter(config)
        policy = load_retrieval_policy(config.vault_root)
        case_insensitive = _vault_case_insensitive(config.vault_root)
    except (CoherenceError, RetrievalError) as exc:
        raise RecoveryGitError("Could not load recovery scope policy safely") from exc
    return _ScopeFilter(runtime, policy, RetrievalScope(), case_insensitive)


def _scan_working_tree_snapshot(vault: Path, excluded: PathExclusion) -> _WorkingTreeSnapshot:
    try:
        root_fd = os.open(vault, _DIR_FLAGS)
    except OSError as exc:
        raise RecoveryGitError("Could not inspect canonical working-tree metadata") from exc
    try:
        entries = tuple(
            sorted(_walk_visible_snapshot(root_fd, (), excluded), key=lambda item: item.path)
        )
    finally:
        os.close(root_fd)
    return _WorkingTreeSnapshot(entries)


def _classify_worktree_snapshot(
    entries: Sequence[_IndexEntry],
    vault: Path,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    snapshot: _WorkingTreeSnapshot,
    *,
    case_insensitive_prefix: bool = False,
    skip_worktree_paths: Sequence[str] = (),
    filemode: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    index = _canonical_index_entries(
        entries,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )
    modified: set[str] = set()
    deleted: set[str] = set()
    uncertain: set[str] = set()
    matched_visible: set[str] = set()
    for path, entry in index.items():
        observed = _snapshot_entry_for_index_path(vault, path, snapshot)
        if observed is None:
            if path in skip_worktree_paths:
                uncertain.add(path)
            else:
                deleted.add(path)
            continue
        matched_visible.add(observed.path)
        classification = _compare_index_entry(entry, observed, filemode=filemode)
        if classification == "modified":
            modified.add(path)
        elif classification == "uncertain":
            uncertain.add(path)
    return (
        tuple(sorted(modified)),
        tuple(sorted(deleted)),
        tuple(sorted(uncertain)),
        tuple(sorted(matched_visible)),
    )


def _assemble_report(
    config: LifeOSConfig,
    *,
    root: Path,
    head: bool,
    incomplete: bool,
    committed: tuple[str, ...],
    unrecoverable: tuple[str, ...],
    staged: tuple[str, ...],
    unstaged: tuple[str, ...],
    deleted: tuple[str, ...],
    untracked: tuple[str, ...],
    ignored: tuple[str, ...],
    flags: tuple[str, ...],
    uncertain: tuple[str, ...],
    last: CanonicalCommitEvidence | None,
) -> RecoveryReport:
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
                "The Git repository has no commit yet, so no canonical vault version is recoverable from history.",
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
                "Review protected/excluded recovery scope explicitly before treating commit coverage as complete.",
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
                f"Latest canonical commit is {last.sha[:12]} from {last.committed_at} ({last.age_days} day(s) old).",
            )
        )

    if not head:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "unknown",
                "warning",
                "Committed canonical tree structure cannot be verified before the first commit.",
            )
        )
    elif unrecoverable:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "failure",
                "error",
                f"{len(unrecoverable)} visible committed canonical path(s) are not ordinary Git blob entries.",
                "Replace gitlink/symlink-style canonical entries with ordinary tracked vault files before relying on local history.",
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
                "Review protected/excluded recovery scope explicitly before treating local object coverage as complete.",
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.canonical_objects",
                "unknown",
                "warning",
                (
                    "Committed canonical paths are represented as regular Git blob entries, but "
                    "payload integrity is intentionally not verified because recovery diagnostics "
                    "do not read canonical note bodies."
                ),
                "Use dedicated Git integrity tooling separately if object-payload verification is required.",
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
                "Review and commit intended canonical changes; inspect metadata-uncertain paths and clear hiding index flags before treating the tree as clean.",
                all_tracked,
            )
        )
    elif uncertain_all:
        items.append(
            _diag(
                "recovery.git.uncommitted_canonical",
                "unknown",
                "warning",
                f"Working-tree content equality cannot be proven for {len(uncertain_all)} visible canonical path(s) from metadata alone.",
                "Inspect the listed paths and clear assume-unchanged/skip-worktree flags where present before treating the tree as clean.",
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
                "Review protected/excluded recovery scope explicitly before treating the working tree as clean.",
            )
        )
    else:
        items.append(
            _diag(
                "recovery.git.uncommitted_canonical",
                "pass",
                "info",
                "No tracked canonical paths have proven uncommitted changes or unresolved metadata state.",
            )
        )

    if untracked:
        items.append(
            _diag(
                "recovery.git.untracked_canonical",
                "warning",
                "warning",
                f"{len(untracked)} visible canonical path(s) are untracked and absent from committed history.",
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
                "Review protected/excluded recovery scope explicitly before treating untracked coverage as complete.",
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
                f"{len(ignored)} visible canonical path(s) are ignored by Git and absent from committed canonical history.",
                "Review ignore rules and protect these canonical files through the intended durable history.",
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
                "Review protected/excluded recovery scope explicitly before treating ignore coverage as complete.",
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


def _latest_visible_commit(
    git: str,
    root: Path,
    pathspec: Pathspec,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    clock: Callable[[], datetime],
    *,
    case_insensitive_prefix: bool = False,
    head_oid: str | None = None,
) -> CanonicalCommitEvidence | None:
    revision = head_oid if head_oid is not None else _head_oid(git, root)
    if revision is None:
        return None
    revision_result = _run_git(
        git,
        cwd=root,
        arguments=_pathspec_command("rev-list", (revision,), pathspec),
    )
    if revision_result.stderr.strip():
        raise RecoveryGitError("Git history query reported incomplete results")
    for sha in revision_result.stdout.decode("ascii", errors="strict").splitlines():
        pathspecs = (pathspec,) if isinstance(pathspec, str) else tuple(pathspec)
        prefix_args = ("--no-literal-pathspecs",) if _uses_magic(pathspecs) else ()
        changed = _git_paths(
            git,
            root,
            (
                *prefix_args,
                "diff-tree",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "-O",
                os.devnull,
                "-m",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                sha,
                "--",
                *pathspecs,
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
            arguments=(
                "-c",
                f"diff.orderFile={os.devnull}",
                "show",
                "-s",
                "--format=%cI",
                sha,
            ),
        )
        if stamp_result.stderr.strip():
            raise RecoveryGitError("Git commit query reported incomplete results")
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
            (now.astimezone(timezone.utc) - committed.astimezone(timezone.utc)).total_seconds(),
        )
        return CanonicalCommitEvidence(sha, stamp, int(age // 86_400))
    return None


def _open_regular_metadata(
    path: Path,
    *,
    limit: int | None = None,
) -> tuple[int, os.stat_result] | None:
    try:
        fd = os.open(path, _FILE_FLAGS)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RecoveryGitError("Could not open Git metadata safely") from exc
    try:
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode):
            raise RecoveryGitError("Git metadata uses an unsupported indirection")
        if observed.st_nlink != 1:
            raise RecoveryGitError("Git metadata uses an unsupported hard link")
        if limit is not None and observed.st_size > limit:
            raise RecoveryGitError("Git metadata is too large to inspect safely")
        return fd, observed
    except Exception:
        os.close(fd)
        raise


def _read_small_metadata(path: Path, *, limit: int = 2_000_000) -> bytes:
    opened = _open_regular_metadata(path, limit=limit)
    if opened is None:
        return b""
    fd, _observed = opened
    try:
        with os.fdopen(fd, "rb", closefd=True) as handle:
            return handle.read()
    except OSError as exc:
        raise RecoveryGitError("Could not read Git metadata safely") from exc


def _open_metadata_directory(source: Path, *, missing_ok: bool = False) -> int | None:
    if not _PINNED_DIRECTORY_SUPPORT:
        raise RecoveryGitError(
            "Platform cannot safely pin Git metadata directories for recovery diagnostics"
        )
    try:
        fd = os.open(source, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise RecoveryGitError("Could not open Git metadata directory safely")
    except OSError as exc:
        raise RecoveryGitError("Could not open Git metadata directory safely") from exc
    try:
        observed = os.fstat(fd)
        if not stat.S_ISDIR(observed.st_mode):
            raise RecoveryGitError("Git metadata snapshot encountered an unsafe directory")
        return fd
    except Exception:
        os.close(fd)
        raise


def _metadata_directory_entries(directory_fd: int) -> list[tuple[str, os.stat_result]]:
    try:
        with os.scandir(directory_fd) as iterator:
            entries: list[tuple[str, os.stat_result]] = []
            for entry in iterator:
                try:
                    observed = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise RecoveryGitError("Could not inspect Git metadata") from exc
                entries.append((entry.name, observed))
    except RecoveryGitError:
        raise
    except OSError as exc:
        raise RecoveryGitError("Could not enumerate Git metadata") from exc
    return sorted(entries, key=lambda item: item[0])


def _open_metadata_child(
    directory_fd: int,
    name: str,
    expected: os.stat_result,
) -> tuple[int, os.stat_result]:
    if stat.S_ISLNK(expected.st_mode):
        raise RecoveryGitError("Git metadata snapshot encountered an unsafe symlink")
    if stat.S_ISDIR(expected.st_mode):
        flags = _DIRECTORY_FLAGS
    elif stat.S_ISREG(expected.st_mode):
        flags = _ENTRY_FLAGS
    else:
        raise RecoveryGitError("Git metadata snapshot encountered an unsafe entry")
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise RecoveryGitError("Could not open Git metadata entry safely") from exc
    try:
        observed = os.fstat(fd)
        if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
            raise RecoveryGitError("Git metadata changed during safe traversal")
        if stat.S_ISDIR(expected.st_mode) != stat.S_ISDIR(observed.st_mode):
            raise RecoveryGitError("Git metadata changed during safe traversal")
        if stat.S_ISREG(expected.st_mode) != stat.S_ISREG(observed.st_mode):
            raise RecoveryGitError("Git metadata changed during safe traversal")
        if stat.S_ISREG(observed.st_mode) and observed.st_nlink != 1:
            raise RecoveryGitError("Git metadata uses an unsupported hard link")
        return fd, observed
    except Exception:
        os.close(fd)
        raise


def _copy_metadata_directory(directory_fd: int, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in _metadata_directory_entries(directory_fd):
        child_fd, observed = _open_metadata_child(directory_fd, name, expected)
        target = destination / name
        if stat.S_ISDIR(observed.st_mode):
            try:
                _copy_metadata_directory(child_fd, target)
            finally:
                os.close(child_fd)
            continue
        try:
            with os.fdopen(child_fd, "rb", closefd=True) as source_handle:
                child_fd = -1
                with target.open("wb") as destination_handle:
                    shutil.copyfileobj(source_handle, destination_handle, length=131_072)
        except OSError as exc:
            raise RecoveryGitError("Could not snapshot Git metadata") from exc
        finally:
            if child_fd >= 0:
                os.close(child_fd)


def _fingerprint_open_regular_metadata(
    digest: Any,
    label: str,
    fd: int,
    observed: os.stat_result,
) -> None:
    digest.update(label.encode("utf-8", errors="surrogateescape") + b"\0")
    digest.update(f"{observed.st_dev}:{observed.st_ino}:{observed.st_size}".encode())
    digest.update(b"\0")
    try:
        with os.fdopen(fd, "rb", closefd=True) as handle:
            fd = -1
            for block in iter(lambda: handle.read(131_072), b""):
                digest.update(block)
    except OSError as exc:
        raise RecoveryGitError("Could not fingerprint Git metadata") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    digest.update(b"\0")


def _fingerprint_metadata_directory(
    digest: Any,
    directory_fd: int,
    prefix: str,
) -> None:
    for name, expected in _metadata_directory_entries(directory_fd):
        child_fd, observed = _open_metadata_child(directory_fd, name, expected)
        label = f"{prefix}/{name}" if prefix else name
        if stat.S_ISDIR(observed.st_mode):
            try:
                _fingerprint_metadata_directory(digest, child_fd, label)
            finally:
                os.close(child_fd)
            continue
        _fingerprint_open_regular_metadata(digest, label, child_fd, observed)


def _run_git(
    git_executable: str,
    *,
    cwd: Path,
    arguments: Any,
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
            env=_sandbox_environment(),
            input=input_bytes,
            pass_fds=_sandbox_pass_fds(),
        )
    except OSError as exc:
        raise RecoveryGitError("Could not execute Git safely") from exc
    if check and result.returncode:
        raise RecoveryGitError(
            "Git metadata query failed; repository state could not be verified safely."
        )
    return result


def _policy_prefix_is_literal(value: str) -> bool:
    if value != value.strip() or value.startswith("/"):
        return False
    without_trailing = value.rstrip("/")
    if not without_trailing:
        return False
    return PurePosixPath(without_trailing).as_posix() == without_trailing


def _scope_filter(config: Any) -> Any:
    scope = _load_scope_filter(config)
    values = [*scope.policy.excluded_prefixes]
    if not scope.request.allow_protected:
        values.extend(scope.policy.protected_prefixes)
    values.extend(scope.request.excluded_paths)
    if any(not _policy_prefix_is_literal(value) for value in values):
        raise RecoveryGitError(
            "Recovery policy paths do not have an unambiguous literal POSIX spelling"
        )
    return scope


def _normalization_sensitive(value: str) -> bool:
    return unicodedata.normalize("NFC", value) != unicodedata.normalize("NFD", value)


def _runtime_exclusion_pathspecs(prefix: tuple[str, ...], scope: Any) -> tuple[str, ...]:
    config = _ACTIVE_CONFIG.get()
    if config is None:
        raise RecoveryGitError("Recovery runtime scope is unavailable for hidden Git queries")
    output: list[str] = []
    for relative in _runtime_prefixes(config):
        if _normalization_sensitive(relative):
            raise RecoveryGitError(
                "Git hidden-scope runtime normalization cannot be authorized safely"
            )
        output.append(
            _literal_pathspec(
                _repo_path(relative, prefix),
                exclude=True,
                icase=scope.case_insensitive,
            )
        )
    return tuple(output)


def _hidden_scope_pathspecs(
    relative: str,
    prefix: tuple[str, ...],
    scope: Any,
) -> tuple[str, ...]:
    if _normalization_sensitive(relative):
        raise RecoveryGitError("Git hidden-scope normalization cannot be authorized safely")
    return (
        _literal_pathspec(
            _repo_path(relative, prefix),
            icase=scope.case_insensitive,
        ),
        *_runtime_exclusion_pathspecs(prefix, scope),
    )


def _hidden_index_state(git: str, root: Path, context: Any, scope: Any) -> tuple[bool, ...]:
    state: list[bool] = []
    for relative in _policy_denied_prefixes(scope):
        result = _run_git(
            git,
            cwd=root,
            arguments=(
                "--no-literal-pathspecs",
                "ls-files",
                "-z",
                "--format=%(objectname)",
                "--",
                *_hidden_scope_pathspecs(relative, context.prefix, scope),
            ),
        )
        if result.stderr.strip():
            raise RecoveryGitError("Git hidden-index query reported incomplete results")
        state.append(bool(result.stdout))
    return tuple(state)


def _authorized_git_pathspecs(context: Any, scope: Any, config: Any) -> tuple[str, ...]:
    positive = PurePosixPath(*context.prefix).as_posix() if context.prefix else ""
    if positive and _normalization_sensitive(positive):
        raise RecoveryGitError(
            "Git vault path normalization cannot be authorized safely by recovery diagnostics"
        )
    pathspecs = [
        _literal_pathspec(
            positive,
            icase=context.case_insensitive_prefix,
        )
        if context.prefix
        else "."
    ]
    denied = (*_policy_denied_prefixes(scope), *_runtime_prefixes(config))
    for relative in dict.fromkeys(denied):
        if _normalization_sensitive(relative):
            raise RecoveryGitError("Git recovery scope normalization cannot be authorized safely")
        pathspecs.append(
            _literal_pathspec(
                _repo_path(relative, context.prefix),
                exclude=True,
                icase=scope.case_insensitive,
            )
        )
    return tuple(pathspecs)


def _git_object_type_for_mode(mode: int) -> str:
    kind = mode & 0o170000
    if kind in {0o100000, 0o120000}:
        return "blob"
    if kind == 0o160000:
        return "commit"
    raise RecoveryGitError("Git index contains an unsupported canonical entry type")


def _tree_entries(
    git: str,
    root: Path,
    head_oid: str | None,
    pathspec: Any,
    prefix: tuple[str, ...],
    excluded: Any,
    *,
    case_insensitive_prefix: bool = False,
) -> dict[str, tuple[int, str, str]]:
    """Reconstruct the authorized HEAD view without enumerating denied tree names."""
    if head_oid is None:
        return {}

    index_entries = _canonical_index_entries(
        _index_entries(_index_debug_raw(git, root, pathspec)),
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )
    output: dict[str, tuple[int, str, str]] = {
        path: (entry.mode, _git_object_type_for_mode(entry.mode), entry.oid)
        for path, entry in index_entries.items()
    }

    result = _run_git(
        git,
        cwd=root,
        arguments=_pathspec_command(
            "diff-index",
            ("--cached", "--raw", "--full-index", "-z", "--no-renames", head_oid),
            pathspec,
        ),
    )
    if result.stderr.strip():
        raise RecoveryGitError("Git staged metadata query reported incomplete results")

    raw = result.stdout
    cursor = 0
    seen: set[str] = set()
    while cursor < len(raw):
        header_end = raw.find(b"\0", cursor)
        if header_end < 0:
            raise RecoveryGitError("Git staged metadata query returned malformed output")
        header = raw[cursor:header_end]
        cursor = header_end + 1
        if not header:
            continue
        path_end = raw.find(b"\0", cursor)
        if path_end < 0:
            raise RecoveryGitError("Git staged metadata query returned malformed path data")
        raw_path = raw[cursor:path_end]
        cursor = path_end + 1
        fields = header.split()
        if len(fields) != 5 or not fields[0].startswith(b":"):
            raise RecoveryGitError("Git staged metadata query returned malformed entry data")
        try:
            old_mode = int(fields[0][1:], 8)
            old_oid = fields[2].decode("ascii", errors="strict")
            status = fields[4].decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="surrogateescape")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RecoveryGitError(
                "Git staged metadata query returned malformed entry data"
            ) from exc
        if status not in {"A", "D", "M", "T"}:
            raise RecoveryGitError("Git staged metadata query returned unsupported status")
        canonical = _canonical_path(
            path,
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if canonical is None:
            continue
        if canonical in seen:
            raise RecoveryGitError("Git staged metadata contains duplicate canonical paths")
        seen.add(canonical)
        if status == "A":
            output.pop(canonical, None)
            continue
        if old_mode == 0 or not old_oid or set(old_oid) == {"0"}:
            raise RecoveryGitError("Git staged metadata omitted the committed object")
        output[canonical] = (old_mode, _git_object_type_for_mode(old_mode), old_oid)
    return output


def _snapshot_entry_for_index_path(vault: Path, path: str, snapshot: Any) -> Any:
    by_path = snapshot.by_path()
    exact = by_path.get(path)
    if exact is not None:
        return exact
    folded = unicodedata.normalize("NFC", path).casefold()
    candidates = [
        entry
        for entry in snapshot.entries
        if unicodedata.normalize("NFC", entry.path).casefold() == folded
    ]
    if not candidates:
        return None
    observed = _lstat(vault, path)
    if observed is None:
        return None
    identity = (observed.st_dev, observed.st_ino)
    matches = [entry for entry in candidates if (entry.device, entry.inode) == identity]
    if len(matches) > 1:
        raise RecoveryGitError("Filesystem exposes ambiguous aliases for a canonical path")
    return matches[0] if matches else None


def _compare_index_entry(
    entry: Any,
    observed: Any,
    *,
    filemode: bool = False,
) -> Literal["clean", "modified", "uncertain"]:
    if entry.mode not in {0o100644, 0o100755} or not stat.S_ISREG(observed.mode):
        return "modified"
    if observed.size > _INDEX_SIZE_MAX:
        return "uncertain"
    if entry.size != observed.size:
        return "modified"
    if filemode and bool(entry.mode & 0o100) != bool(observed.mode & stat.S_IXUSR):
        return "modified"
    if (
        entry.mtime_ns != observed.mtime_ns
        or entry.ctime_ns != observed.ctime_ns
        or (entry.device and entry.device != (observed.device & 0xFFFFFFFF))
        or (entry.inode and entry.inode != (observed.inode & 0xFFFFFFFF))
    ):
        return "uncertain"
    sandbox = _ACTIVE_SANDBOX.get()
    if (
        sandbox is not None
        and sandbox.index_mtime_ns is not None
        and observed.mtime_ns >= sandbox.index_mtime_ns
    ):
        return "uncertain"
    return "clean"


def _scope_allows_without_mutation(scope: Any, path: str) -> bool:
    try:
        if scope.case_insensitive and _casefold_denied(path, scope.policy, scope.request):
            return False
        decision = scope_decision(
            unicodedata.normalize("NFC", path),
            scope=scope.request,
            policy=scope.policy,
            mode="local",
        )
    except (CoherenceError, RetrievalError) as exc:
        raise RecoveryGitError("Could not verify Git ignore metadata scope") from exc
    return decision.allowed


def _ignore_sources_authorized(path: str, scope: Any) -> bool:
    parts = PurePosixPath(path).parts
    candidates = [".gitignore"]
    for depth in range(1, len(parts)):
        candidates.append(PurePosixPath(*parts[:depth], ".gitignore").as_posix())
    return all(_scope_allows_without_mutation(scope, source) for source in candidates)


def _pinned_object_file_budget() -> int:
    """Return a bounded FD budget that leaves room for normal process activity."""

    try:
        import resource
    except ImportError:
        return _DEFAULT_PINNED_OBJECT_FILES

    try:
        soft_limit, _hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return _DEFAULT_PINNED_OBJECT_FILES
    if soft_limit == resource.RLIM_INFINITY:
        return _MAX_PINNED_OBJECT_FILES
    available = max(0, int(soft_limit) - _PINNED_OBJECT_FD_RESERVE)
    return min(_MAX_PINNED_OBJECT_FILES, available)


def _decode_git_config_scalar(value: str, *, key: str) -> str:
    """Decode the bounded Git scalar syntax used by safe ``core`` settings."""

    text = value.strip()
    if not text:
        return ""

    output: list[str] = []
    quoted = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if escaped:
            escapes = {
                "\\": "\\",
                '"': '"',
                "n": "\n",
                "t": "\t",
                "b": "\b",
            }
            replacement = escapes.get(char)
            if replacement is None:
                raise RecoveryGitError(f"Git {key} configuration uses an unsupported escape")
            output.append(replacement)
            escaped = False
            index += 1
            continue

        if quoted:
            if char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            else:
                output.append(char)
            index += 1
            continue

        if char == '"':
            quoted = True
            index += 1
            continue
        if char in "#;":
            break
        if char == "\\":
            raise RecoveryGitError(f"Git {key} configuration uses an unsupported escape")
        output.append(char)
        index += 1

    if escaped or quoted:
        raise RecoveryGitError(f"Git {key} configuration is malformed")
    return "".join(output).strip()


def _parse_git_bool(value: str, *, key: str) -> bool:
    folded = _decode_git_config_scalar(value, key=key).casefold()
    if folded in {"", "true", "yes", "on", "1"}:
        return True
    if folded in {"false", "no", "off", "0"}:
        return False
    raise RecoveryGitError(f"Git {key} configuration is malformed")


def _parse_config_snapshot(raw: bytes) -> tuple[bytes, bool, bool, bool]:
    text = raw.decode("utf-8-sig", errors="surrogateescape")
    section = ""
    subsection: str | None = None
    contains_includes = False
    filemode = True
    ignorecase = False
    repository_format = 0
    extensions = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        section_match = _SECTION_RE.match(raw_line)
        if section_match:
            section = section_match.group(1).casefold()
            subsection = section_match.group(2)
            contains_includes = contains_includes or section in {"include", "includeif"}
            extensions = extensions or (section == "extensions" and subsection is None)
            continue
        if line.startswith("["):
            raise RecoveryGitError("Git config section header is malformed or unsupported")
        if section != "core" or subsection is not None:
            continue

        pair = _KEY_VALUE_RE.match(raw_line)
        if pair is None:
            continue
        key, value = pair.group(1).casefold(), pair.group(2)
        if key == "filemode":
            filemode = _parse_git_bool(value, key="filemode")
        elif key == "ignorecase":
            ignorecase = _parse_git_bool(value, key="ignorecase")
        elif key == "excludesfile":
            raise RecoveryGitError(
                "Git core.excludesFile configuration is not supported by recovery diagnostics"
            )
        elif key == "repositoryformatversion":
            scalar = _decode_git_config_scalar(value, key="repositoryformatversion")
            try:
                repository_format = int(scalar or "0")
            except ValueError as exc:
                raise RecoveryGitError("Git repository format is malformed") from exc

    if repository_format != 0 or extensions:
        raise RecoveryGitError(
            "Extended Git repository formats cannot be inspected safely by recovery diagnostics"
        )
    return raw, contains_includes, filemode, ignorecase


def _config_snapshot(config_path: Path) -> tuple[bytes, bool, bool, bool]:
    return _parse_config_snapshot(_read_small_metadata(config_path))


def _discover_pinned_git_directory(
    vault: Path,
) -> tuple[Path, Path, int, os.stat_result, None] | None:
    for root in (vault, *vault.parents):
        marker = root / ".git"
        try:
            expected = os.lstat(marker)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RecoveryGitError("Could not inspect Git repository metadata") from exc
        if not stat.S_ISDIR(expected.st_mode) or stat.S_ISLNK(expected.st_mode):
            raise RecoveryGitError(
                "Indirect Git metadata layouts are not supported by recovery diagnostics"
            )
        metadata_fd = _open_metadata_directory(marker)
        assert metadata_fd is not None
        try:
            observed = os.fstat(metadata_fd)
            if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
                raise RecoveryGitError("Git repository metadata changed during safe root pinning")
            return root, marker, metadata_fd, observed, None
        except Exception:
            os.close(metadata_fd)
            raise
    return None


def _stat_child(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RecoveryGitError("Could not inspect Git metadata safely") from exc


def _open_named_directory(
    directory_fd: int,
    name: str,
    *,
    missing_ok: bool = False,
) -> int | None:
    expected = _stat_child(directory_fd, name)
    if expected is None:
        if missing_ok:
            return None
        raise RecoveryGitError("Could not open Git metadata directory safely")
    child_fd, observed = _open_metadata_child(directory_fd, name, expected)
    if not stat.S_ISDIR(observed.st_mode):
        os.close(child_fd)
        raise RecoveryGitError("Git metadata snapshot encountered an unsafe directory")
    return child_fd


def _same_regular_snapshot(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        stat.S_ISREG(after.st_mode)
        and before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_nlink == after.st_nlink == 1
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


def _read_named_regular_metadata(
    directory_fd: int,
    name: str,
    *,
    limit: int = _MAX_GIT_METADATA_BYTES,
) -> bytes:
    expected = _stat_child(directory_fd, name)
    if expected is None:
        return b""
    child_fd, observed = _open_metadata_child(directory_fd, name, expected)
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        os.close(child_fd)
        raise RecoveryGitError("Git metadata uses an unsupported entry")
    if observed.st_size > limit:
        os.close(child_fd)
        raise RecoveryGitError("Git metadata is too large to inspect safely")
    try:
        with os.fdopen(child_fd, "rb", closefd=True) as handle:
            child_fd = -1
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise RecoveryGitError("Could not read Git metadata safely") from exc
    finally:
        if child_fd >= 0:
            os.close(child_fd)
    if len(content) > limit or len(content) != observed.st_size:
        raise RecoveryGitError("Git metadata changed during safe snapshot")
    if not _same_regular_snapshot(observed, after):
        raise RecoveryGitError("Git metadata changed during safe snapshot")
    return content


def _copy_named_regular_metadata(
    directory_fd: int,
    name: str,
    destination: Path,
) -> None:
    expected = _stat_child(directory_fd, name)
    if expected is None:
        return
    child_fd, observed = _open_metadata_child(directory_fd, name, expected)
    try:
        _copy_pinned_regular_fd(child_fd, observed, destination)
    finally:
        os.close(child_fd)


def _copy_named_metadata_tree(
    directory_fd: int,
    name: str,
    destination: Path,
) -> None:
    child_fd = _open_named_directory(directory_fd, name, missing_ok=True)
    if child_fd is None:
        return
    try:
        _copy_metadata_directory(child_fd, destination)
    finally:
        os.close(child_fd)


def _reject_split_index_fd(metadata_fd: int) -> None:
    try:
        names = os.listdir(metadata_fd)
    except OSError as exc:
        raise RecoveryGitError("Could not inspect Git index topology") from exc
    if any(name.startswith("sharedindex.") for name in names):
        raise RecoveryGitError("Split-index Git metadata is not supported by recovery diagnostics")


def _copy_open_regular_fd(fd: int, destination: Path) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(fd, "rb", closefd=True) as source_handle:
            fd = -1
            with destination.open("wb") as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle, length=131_072)
    except OSError as exc:
        raise RecoveryGitError("Could not snapshot Git metadata") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _copy_pinned_regular_fd(
    fd: int,
    observed: os.stat_result,
    destination: Path,
) -> None:
    try:
        copy_fd = os.dup(fd)
    except OSError as exc:
        raise RecoveryGitError("Could not snapshot Git metadata") from exc
    _copy_open_regular_fd(copy_fd, destination)
    try:
        after = os.fstat(fd)
        copied = destination.stat(follow_symlinks=False)
    except OSError as exc:
        raise RecoveryGitError("Could not verify Git metadata snapshot") from exc
    if (
        not _same_regular_snapshot(observed, after)
        or not stat.S_ISREG(copied.st_mode)
        or copied.st_size != observed.st_size
    ):
        raise RecoveryGitError("Git metadata changed during safe snapshot")


def _copy_repository_exclude(metadata_fd: int, destination: Path) -> None:
    info_fd = _open_named_directory(metadata_fd, "info", missing_ok=True)
    if info_fd is None:
        return
    try:
        expected = _stat_child(info_fd, "exclude")
        if expected is None:
            return
        exclude_fd, observed = _open_metadata_child(info_fd, "exclude", expected)
        if not stat.S_ISREG(observed.st_mode):
            os.close(exclude_fd)
            raise RecoveryGitError("Git repository exclude metadata uses an unsupported entry")
        _copy_open_regular_fd(exclude_fd, destination)
    finally:
        os.close(info_fd)


def _snapshot_object_directory(
    source_fd: int,
    destination: Path,
    pinned_fds: list[int],
    *,
    relative: tuple[str, ...] = (),
) -> None:
    """Build a read-only Git-visible object view from a bounded set of pinned FDs."""

    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RecoveryGitError("Could not create Git object-store sandbox") from exc

    for name, expected in _metadata_directory_entries(source_fd):
        child_fd, observed = _open_metadata_child(source_fd, name, expected)
        child_relative = (*relative, name)
        target = destination / name
        if child_relative in {("info", "alternates"), ("info", "http-alternates")}:
            os.close(child_fd)
            raise RecoveryGitError(
                "Alternate Git object stores are not supported by recovery diagnostics"
            )

        if stat.S_ISDIR(observed.st_mode):
            try:
                _snapshot_object_directory(
                    child_fd,
                    target,
                    pinned_fds,
                    relative=child_relative,
                )
            finally:
                os.close(child_fd)
            continue

        if not stat.S_ISREG(observed.st_mode):
            os.close(child_fd)
            raise RecoveryGitError("Git object store contains an unsupported entry")
        if observed.st_nlink != 1:
            os.close(child_fd)
            raise RecoveryGitError("Git object store contains an unsupported hard link")
        if len(pinned_fds) >= _pinned_object_file_budget():
            os.close(child_fd)
            raise RecoveryGitError(
                "Git object store exceeds the safe pinned-file descriptor budget"
            )

        try:
            _copy_pinned_regular_fd(child_fd, observed, target)
        except Exception:
            os.close(child_fd)
            raise
        pinned_fds.append(child_fd)


def _open_object_store_root_fd(
    metadata_fd: int,
) -> tuple[int, os.stat_result]:
    try:
        object_fd = _open_named_directory(metadata_fd, "objects")
    except RecoveryGitError as exc:
        raise RecoveryGitError(
            "Redirected Git object stores are not supported by recovery diagnostics"
        ) from exc
    assert object_fd is not None
    try:
        return object_fd, os.fstat(object_fd)
    except Exception:
        os.close(object_fd)
        raise


def _fingerprint_named_regular(
    digest: Any,
    directory_fd: int,
    name: str,
    label: str,
) -> None:
    expected = _stat_child(directory_fd, name)
    if expected is None:
        digest.update(label.encode("utf-8", errors="surrogateescape") + b"\0missing\0")
        return
    child_fd, observed = _open_metadata_child(directory_fd, name, expected)
    if not stat.S_ISREG(observed.st_mode):
        os.close(child_fd)
        raise RecoveryGitError("Git metadata fingerprint encountered an unsafe entry")
    _fingerprint_open_regular_metadata(digest, label, child_fd, observed)


def _fingerprint_repository_exclude(digest: Any, metadata_fd: int) -> None:
    info_fd = _open_named_directory(metadata_fd, "info", missing_ok=True)
    if info_fd is None:
        digest.update(b"info/exclude\0missing\0")
        return
    try:
        _fingerprint_named_regular(digest, info_fd, "exclude", "info/exclude")
    finally:
        os.close(info_fd)


def _fingerprint_refs(digest: Any, metadata_fd: int) -> None:
    refs_fd = _open_named_directory(metadata_fd, "refs", missing_ok=True)
    if refs_fd is None:
        digest.update(b"refs\0missing-tree\0")
        return
    try:
        _fingerprint_metadata_directory(digest, refs_fd, "refs")
    finally:
        os.close(refs_fd)


def _metadata_fingerprint_from_fd(
    metadata_fd: int,
    *,
    object_state: os.stat_result | None = None,
) -> str:
    digest = hashlib.sha256()
    for name in ("config", "HEAD", "index", "packed-refs", "shallow"):
        _fingerprint_named_regular(digest, metadata_fd, name, name)
    _fingerprint_repository_exclude(digest, metadata_fd)
    _fingerprint_refs(digest, metadata_fd)
    if object_state is None:
        object_fd, object_state = _open_object_store_root_fd(metadata_fd)
        os.close(object_fd)
    digest.update(f"objects\0{object_state.st_dev}:{object_state.st_ino}\0".encode())
    return digest.hexdigest()


def _metadata_fingerprint(
    git_dir: Path,
    *,
    object_state: os.stat_result | None = None,
) -> str:
    sandbox = cast(Any, _ACTIVE_SANDBOX.get())
    if sandbox is not None and getattr(sandbox, "metadata_fd", None) is not None:
        metadata_fd = sandbox.metadata_fd
        assert metadata_fd is not None
        try:
            live = os.lstat(sandbox.root / ".git")
            pinned = os.fstat(metadata_fd)
        except OSError as exc:
            raise RecoveryGitError("Could not revalidate Git metadata root") from exc
        if (
            not stat.S_ISDIR(live.st_mode)
            or stat.S_ISLNK(live.st_mode)
            or (live.st_dev, live.st_ino) != (pinned.st_dev, pinned.st_ino)
        ):
            raise RecoveryGitError("Git repository metadata changed during recovery inspection")
        return _metadata_fingerprint_from_fd(
            metadata_fd,
            object_state=object_state,
        )

    metadata_fd = _open_metadata_directory(git_dir)
    assert metadata_fd is not None
    try:
        return _metadata_fingerprint_from_fd(
            metadata_fd,
            object_state=object_state,
        )
    finally:
        os.close(metadata_fd)


def _build_sandbox(vault: Path) -> _GitMetadataSandbox | None:
    discovered = _discover_pinned_git_directory(vault)
    if discovered is None:
        return None
    root, _git_dir, metadata_fd, _metadata_state, metadata_fd_path = discovered

    temporary: tempfile.TemporaryDirectory[str] | None = None
    object_fd: int | None = None
    pinned_object_fds: list[int] = []
    try:
        _reject_split_index_fd(metadata_fd)
        _config_bytes, contains_includes, filemode, ignorecase = _parse_config_snapshot(
            _read_named_regular_metadata(metadata_fd, "config")
        )
        object_fd, object_state = _open_object_store_root_fd(metadata_fd)
        fingerprint = _metadata_fingerprint_from_fd(
            metadata_fd,
            object_state=object_state,
        )

        index_state = _stat_child(metadata_fd, "index")
        if index_state is None:
            index_mtime_ns = None
        else:
            if stat.S_ISLNK(index_state.st_mode) or not stat.S_ISREG(index_state.st_mode):
                raise RecoveryGitError("Git index metadata uses an unsafe entry")
            if index_state.st_nlink != 1:
                raise RecoveryGitError("Git index metadata uses an unsupported hard link")
            index_mtime_ns = index_state.st_mtime_ns

        try:
            temporary = tempfile.TemporaryDirectory(prefix="lifeos-doctor-git-")
            fake = Path(temporary.name) / "git"
            fake.mkdir(parents=True)
            for name in ("HEAD", "index", "packed-refs", "shallow"):
                _copy_named_regular_metadata(metadata_fd, name, fake / name)
            _copy_named_metadata_tree(metadata_fd, "refs", fake / "refs")
            _copy_repository_exclude(
                metadata_fd,
                fake / "info" / "exclude",
            )
            fake_objects = fake / "objects"
            _snapshot_object_directory(
                object_fd,
                fake_objects,
                pinned_object_fds,
            )
            (fake / "config").write_text(
                "[core]\n"
                "\trepositoryformatversion = 0\n"
                f"\tfilemode = {'true' if filemode else 'false'}\n"
                f"\tignorecase = {'true' if ignorecase else 'false'}\n"
                "\tbare = false\n"
                "\tlogallrefupdates = false\n"
                "\tfsmonitor = false\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise RecoveryGitError("Could not create Git metadata sandbox") from exc

        return _GitMetadataSandbox(
            temporary,
            root,
            vault,
            fake,
            fake_objects,
            index_mtime_ns,
            fingerprint,
            contains_includes,
            ignorecase,
            metadata_fd,
            metadata_fd_path,
            object_fd,
            str(fake_objects),
            tuple(pinned_object_fds),
        )
    except Exception:
        for fd in pinned_object_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        if object_fd is not None:
            try:
                os.close(object_fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                pass
        try:
            os.close(metadata_fd)
        except OSError:
            pass
        raise


def _sandbox_environment() -> dict[str, str]:
    env = _git_environment()
    sandbox = _ACTIVE_SANDBOX.get()
    if sandbox is not None:
        env.update(
            GIT_DIR=str(sandbox.git_dir),
            GIT_WORK_TREE=str(sandbox.root),
            GIT_OBJECT_DIRECTORY=str(sandbox.object_dir),
        )
    return env


def _sandbox_pass_fds() -> tuple[int, ...]:
    sandbox = _ACTIVE_SANDBOX.get()
    if sandbox is None:
        return ()
    output: list[int] = []
    for fd in (
        getattr(sandbox, "metadata_fd", None),
        getattr(sandbox, "object_fd", None),
        *getattr(sandbox, "object_fds", ()),
    ):
        if fd is not None and fd not in output:
            output.append(fd)
    return tuple(output)


def _selects_repository_metadata(path: str) -> bool:
    sandbox = cast(Any, _ACTIVE_SANDBOX.get())
    if sandbox is None or getattr(sandbox, "metadata_fd", None) is None:
        return False
    pure = PurePosixPath(path)
    if not pure.parts:
        return False
    try:
        metadata_state = os.fstat(sandbox.metadata_fd)
        candidate_state = os.stat(
            sandbox.vault / pure.parts[0],
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RecoveryGitError("Could not verify repository metadata boundary") from exc
    return (metadata_state.st_dev, metadata_state.st_ino) == (
        candidate_state.st_dev,
        candidate_state.st_ino,
    )


def _applicable_ignore_source_parts(
    path: str,
    prefix: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    repo_path = PurePosixPath(_repo_path(path, prefix))
    output: list[tuple[str, ...]] = [(".gitignore",)]
    for depth in range(1, len(repo_path.parts)):
        output.append((*repo_path.parts[:depth], ".gitignore"))
    return tuple(output)


def _open_stable_directory(path: Path) -> int:
    try:
        expected = os.lstat(path)
    except OSError as exc:
        raise RecoveryGitError("Could not inspect Git ignore metadata root") from exc
    if not stat.S_ISDIR(expected.st_mode) or stat.S_ISLNK(expected.st_mode):
        raise RecoveryGitError("Git ignore metadata root uses an unsafe entry")
    try:
        fd = os.open(path, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise RecoveryGitError("Could not open Git ignore metadata root safely") from exc
    try:
        observed = os.fstat(fd)
        if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
            raise RecoveryGitError("Git ignore metadata root changed during safe pinning")
        return fd
    except Exception:
        os.close(fd)
        raise


def _copy_relative_ignore_source(
    root_fd: int,
    parts: tuple[str, ...],
    destination_root: Path,
) -> None:
    current_fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            expected = _stat_child(current_fd, component)
            if expected is None:
                return
            child_fd, observed = _open_metadata_child(
                current_fd,
                component,
                expected,
            )
            if not stat.S_ISDIR(observed.st_mode):
                os.close(child_fd)
                raise RecoveryGitError("Git ignore metadata ancestor uses an unsupported entry")
            os.close(current_fd)
            current_fd = child_fd

        expected = _stat_child(current_fd, parts[-1])
        if expected is None:
            return
        try:
            source_fd, observed = _open_metadata_child(current_fd, parts[-1], expected)
        except RecoveryGitError as exc:
            raise RecoveryGitError("Git ignore metadata uses an unsupported entry") from exc
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            os.close(source_fd)
            raise RecoveryGitError("Git ignore metadata uses an unsupported non-regular entry")
        _copy_open_regular_fd(
            source_fd,
            destination_root.joinpath(*parts),
        )
    finally:
        os.close(current_fd)


def _snapshot_ignore_worktree(
    root: Path,
    paths: Any,
    prefix: tuple[str, ...],
) -> tempfile.TemporaryDirectory[str]:
    try:
        temporary = tempfile.TemporaryDirectory(prefix="lifeos-doctor-ignore-")
    except OSError as exc:
        raise RecoveryGitError("Could not create Git ignore metadata snapshot") from exc
    destination = Path(temporary.name)
    root_fd: int | None = None
    try:
        root_fd = _open_stable_directory(root)
        sources: set[tuple[str, ...]] = set()
        for path in paths:
            repo_path = PurePosixPath(_repo_path(path, prefix))
            destination.joinpath(*repo_path.parts[:-1]).mkdir(
                parents=True,
                exist_ok=True,
            )
            sources.update(_applicable_ignore_source_parts(path, prefix))
        for parts in sorted(sources):
            _copy_relative_ignore_source(root_fd, parts, destination)
        return temporary
    except Exception:
        try:
            temporary.cleanup()
        except OSError:
            pass
        raise
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _ignored_paths(
    git: str,
    root: Path,
    paths: Any,
    prefix: tuple[str, ...],
    excluded: Any,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    if not paths:
        return ()
    if isinstance(excluded, _ScopeFilter):
        unsafe = tuple(path for path in paths if not _ignore_sources_authorized(path, excluded))
        if unsafe:
            raise RecoveryGitError("Git ignore metadata scope cannot be inspected safely")

    temporary = _snapshot_ignore_worktree(root, paths, prefix)
    shadow_root = Path(temporary.name)
    repo_paths = tuple(f"./{_repo_path(path, prefix)}" for path in paths)
    input_bytes = (
        b"\0".join(path.encode("utf-8", errors="surrogateescape") for path in repo_paths) + b"\0"
    )
    env = _sandbox_environment()
    env["GIT_WORK_TREE"] = str(shadow_root)
    try:
        result = subprocess.run(
            [
                git,
                "--no-literal-pathspecs",
                "-c",
                f"core.excludesFile={os.devnull}",
                "check-ignore",
                "--no-index",
                "--stdin",
                "-z",
            ],
            cwd=shadow_root,
            shell=False,
            check=False,
            capture_output=True,
            env=env,
            input=input_bytes,
            pass_fds=_sandbox_pass_fds(),
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise RecoveryGitError("Git ignore query exceeded its safe time bound") from exc
    except OSError as exc:
        raise RecoveryGitError("Could not execute Git ignore query safely") from exc
    finally:
        try:
            temporary.cleanup()
        except OSError:
            pass
    if result.returncode not in {0, 1} or result.stderr.strip():
        raise RecoveryGitError("Git ignore query could not be verified safely")
    return _filter_paths(
        _nul_paths(result.stdout),
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _validate_sandbox_stability(sandbox: _GitMetadataSandbox) -> bool:
    if sandbox.metadata_fd is None:
        raise RecoveryGitError("Git metadata sandbox is missing its pinned root")
    try:
        live = os.lstat(sandbox.root / ".git")
        pinned = os.fstat(sandbox.metadata_fd)
    except OSError as exc:
        raise RecoveryGitError("Could not revalidate Git metadata root") from exc
    if (
        not stat.S_ISDIR(live.st_mode)
        or stat.S_ISLNK(live.st_mode)
        or (live.st_dev, live.st_ino) != (pinned.st_dev, pinned.st_ino)
    ):
        return False

    _reject_split_index_fd(sandbox.metadata_fd)
    return _metadata_fingerprint(sandbox.root / ".git") == sandbox.fingerprint


def _working_tree_snapshot(vault: Path, excluded: Any) -> Any:
    snapshot = _scan_working_tree_snapshot(vault, excluded)
    _ACTIVE_WORKTREE_SNAPSHOT.set(snapshot)
    return snapshot


def _worktree_from_snapshot(
    entries: Any,
    vault: Path,
    prefix: tuple[str, ...],
    excluded: Any,
    snapshot: Any,
    *,
    case_insensitive_prefix: bool = False,
    skip_worktree_paths: Any = (),
    filemode: bool = False,
) -> Any:
    result = _classify_worktree_snapshot(
        entries,
        vault,
        prefix,
        excluded,
        snapshot,
        case_insensitive_prefix=case_insensitive_prefix,
        skip_worktree_paths=skip_worktree_paths,
        filemode=filemode,
    )
    _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.set(None)
    if not isinstance(excluded, _ScopeFilter) or not excluded.incomplete:
        return result

    git = _ACTIVE_GIT_EXECUTABLE.get()
    sandbox = _ACTIVE_SANDBOX.get()
    if git is None or sandbox is None:
        return result

    tracked_visible = result[3]
    untracked_candidates = tuple(sorted(set(snapshot.paths) - set(tracked_visible)))
    safe_candidates = tuple(
        path for path in untracked_candidates if _ignore_sources_authorized(path, excluded)
    )
    ignored = (
        _ignored_paths(
            git,
            sandbox.root,
            safe_candidates,
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if safe_candidates
        else ()
    )
    untracked = tuple(sorted(set(untracked_candidates) - set(ignored)))
    _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.set(
        _VisibleIgnoreClassification(untracked=untracked, ignored=ignored)
    )
    return result


def _latest_commit(
    git: str,
    root: Path,
    pathspec: Any,
    prefix: tuple[str, ...],
    excluded: Any,
    clock: Any,
    *,
    case_insensitive_prefix: bool = False,
    head_oid: str | None = None,
) -> Any:
    visible = _latest_visible_commit(
        git,
        root,
        pathspec,
        prefix,
        excluded,
        clock,
        case_insensitive_prefix=case_insensitive_prefix,
        head_oid=head_oid,
    )
    revision = head_oid if head_oid is not None else _head_oid(git, root)
    if revision is None:
        return visible
    if isinstance(excluded, _ScopeFilter):
        for relative in _policy_denied_prefixes(excluded):
            result = _run_git(
                git,
                cwd=root,
                arguments=(
                    "--no-literal-pathspecs",
                    "log",
                    "-1",
                    "--format=%H",
                    revision,
                    "--",
                    *_hidden_scope_pathspecs(relative, prefix, excluded),
                ),
            )
            if result.stderr.strip():
                raise RecoveryGitError("Git hidden-history query reported incomplete results")
            if result.stdout.strip():
                excluded.incomplete = True
                return None
    return visible


def _build_report(config: Any, **kwargs: Any) -> Any:
    classification = _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.get()
    if classification is not None:
        kwargs = dict(kwargs)
        kwargs["untracked"] = classification.untracked
        kwargs["ignored"] = classification.ignored

    report = _assemble_report(config, **kwargs)
    snapshot = _ACTIVE_WORKTREE_SNAPSHOT.get()
    effective_untracked = tuple(kwargs.get("untracked", ()))
    effective_ignored = tuple(kwargs.get("ignored", ()))
    if snapshot is None:
        return report

    by_path = snapshot.by_path()
    untracked_non_regular = tuple(
        sorted(
            path
            for path in effective_untracked
            if (entry := by_path.get(path)) is not None and not stat.S_ISREG(entry.mode)
        )
    )
    visible = tuple(sorted(set(effective_untracked) | set(effective_ignored)))
    visible_non_regular = tuple(
        sorted(
            path
            for path in visible
            if (entry := by_path.get(path)) is not None and not stat.S_ISREG(entry.mode)
        )
    )
    if not visible_non_regular:
        return report

    diagnostics = []
    for item in report.diagnostics:
        if item.id == "recovery.git.canonical_objects":
            paths = tuple(sorted(set(item.paths) | set(visible_non_regular)))
            item = replace(
                item,
                status="failure",
                severity="error",
                summary=(
                    f"{len(paths)} visible canonical path(s) use non-regular recovery entries "
                    "that do not preserve ordinary file bytes."
                ),
                remediation=(
                    "Replace symlink, gitlink, or other non-regular canonical entries with "
                    "ordinary tracked vault files before relying on Git recovery."
                ),
                paths=paths,
            )
        elif item.id == "recovery.git.untracked_canonical" and untracked_non_regular:
            item = replace(
                item,
                summary=(
                    f"{len(effective_untracked)} visible canonical path(s) are untracked and absent from "
                    f"committed history; {len(untracked_non_regular)} are non-regular recovery entries."
                ),
                remediation=(
                    "Replace non-regular paths identified by recovery.git.canonical_objects with "
                    "ordinary vault files; then add/commit intended regular untracked canonical files."
                ),
            )
        diagnostics.append(item)
    return replace(report, diagnostics=tuple(diagnostics))


def _finalize_sandbox_report(
    config: Any,
    sandbox: _GitMetadataSandbox,
    report: Any,
) -> Any:
    try:
        stable = _validate_sandbox_stability(sandbox)
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)), sandbox.root)
    if not stable:
        return _fallback(
            config,
            _git_unknown(
                "Git repository metadata changed during recovery inspection; retry for a stable snapshot."
            ),
            sandbox.root,
        )
    return report


def collect_recovery_readiness(config: Any, *, clock_fn: Any = None) -> Any:
    try:
        git = _resolve_git_executable()
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)))
    if git is None:
        return _fallback(
            config,
            _git_unknown("Git is unavailable, so local canonical history is unknown."),
        )
    try:
        sandbox = _build_sandbox(config.vault_root)
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)))
    if sandbox is None:
        return _fallback(config, _no_repo())

    sandbox_token = _ACTIVE_SANDBOX.set(cast(Any, sandbox))
    config_token = _ACTIVE_CONFIG.set(config)
    snapshot_token = _ACTIVE_WORKTREE_SNAPSHOT.set(None)
    git_token = _ACTIVE_GIT_EXECUTABLE.set(git)
    ignore_token = _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.set(None)
    try:
        if sandbox.contains_includes:
            return _fallback(
                config,
                _git_unknown(
                    "Git repository configuration contains include directives that recovery diagnostics will not follow."
                ),
                sandbox.root,
            )

        try:
            context = _repo_context(git, config.vault_root)
        except RecoveryGitError as exc:
            return _finalize_sandbox_report(
                config,
                sandbox,
                _fallback(config, _git_unknown(str(exc))),
            )
        if context is None:
            return _finalize_sandbox_report(
                config,
                sandbox,
                _fallback(config, _no_repo()),
            )
        root = context.root
        prefix = context.prefix
        case_insensitive_prefix = context.case_insensitive_prefix

        scope = _scope_filter(config)
        policy_before = scope.policy
        hidden_index_before = _hidden_index_state(git, root, context, scope)
        if any(hidden_index_before):
            scope.incomplete = True
        pathspec = _authorized_git_pathspecs(context, scope, config)
        try:
            policy_at_scan = load_retrieval_policy(config.vault_root)
        except (CoherenceError, RetrievalError) as exc:
            raise RecoveryGitError(
                "Recovery scope policy changed or could not be revalidated safely"
            ) from exc
        if policy_at_scan != policy_before:
            raise RecoveryGitError(
                "Recovery scope policy changed before recovery inspection; retry for a stable authorization snapshot."
            )

        fs_before = _working_tree_snapshot(config.vault_root, scope)
        snapshot_before = _git_snapshot(git, root, pathspec)
        head_oid = snapshot_before.head_oid
        head = head_oid is not None
        index_entries = _index_entries(snapshot_before.index_debug)
        filemode_before = _core_filemode(git, root)
        tree_entries = _tree_entries(
            git,
            root,
            head_oid,
            pathspec,
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        committed_set = {
            path
            for path, (mode, obj_type, _oid) in tree_entries.items()
            if obj_type == "blob" and (mode & 0o170000) == 0o100000
        }
        committed = tuple(sorted(committed_set))
        unrecoverable = tuple(sorted(set(tree_entries) - committed_set))
        staged = _staged_paths(
            index_entries,
            tree_entries,
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        unstaged, deleted, uncertain, tracked_visible = _worktree_from_snapshot(
            index_entries,
            config.vault_root,
            prefix,
            scope,
            fs_before,
            case_insensitive_prefix=case_insensitive_prefix,
            skip_worktree_paths=_skip_worktree_paths_from_raw(
                snapshot_before.index_flags,
                prefix,
                scope,
                case_insensitive_prefix=case_insensitive_prefix,
            ),
            filemode=filemode_before,
        )
        flags = _index_flags_from_raw(
            snapshot_before.index_flags,
            prefix,
            scope,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        untracked_candidates = tuple(sorted(set(fs_before.paths) - set(tracked_visible)))
        classification = _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.get()
        if classification is not None:
            untracked = classification.untracked
            ignored = classification.ignored
        else:
            ignored = (
                ()
                if scope.incomplete
                else _ignored_paths(
                    git,
                    root,
                    untracked_candidates,
                    prefix,
                    scope,
                    case_insensitive_prefix=case_insensitive_prefix,
                )
            )
            untracked = tuple(sorted(set(untracked_candidates) - set(ignored)))
        last = (
            _latest_commit(
                git,
                root,
                pathspec,
                prefix,
                scope,
                _utc_now if clock_fn is None else clock_fn,
                case_insensitive_prefix=case_insensitive_prefix,
                head_oid=head_oid,
            )
            if head
            else None
        )
        snapshot_after = _git_snapshot(git, root, pathspec)
        fs_after = _working_tree_snapshot(config.vault_root, scope)
        hidden_index_after = _hidden_index_state(git, root, context, scope)
        try:
            policy_after = load_retrieval_policy(config.vault_root)
        except (CoherenceError, RetrievalError) as exc:
            raise RecoveryGitError(
                "Recovery scope policy changed or could not be revalidated safely"
            ) from exc
        if policy_after != policy_before:
            raise RecoveryGitError(
                "Recovery scope policy changed during recovery inspection; retry for a stable authorization snapshot."
            )
        if _core_filemode(git, root) != filemode_before:
            raise RecoveryGitError(
                "Git file-mode configuration changed during recovery inspection; retry for a stable snapshot."
            )
        if hidden_index_after != hidden_index_before:
            raise RecoveryGitError(
                "Protected Git index scope changed during recovery inspection; retry for a stable snapshot."
            )
        if snapshot_after != snapshot_before:
            raise RecoveryGitError(
                "Git HEAD or index changed during recovery inspection; retry for a stable snapshot."
            )
        if fs_after != fs_before:
            raise RecoveryGitError(
                "Canonical working-tree metadata changed during recovery inspection; retry for a stable snapshot."
            )

        report = _build_report(
            config,
            root=root,
            head=head,
            incomplete=scope.incomplete,
            committed=committed,
            unrecoverable=unrecoverable,
            staged=staged,
            unstaged=unstaged,
            deleted=deleted,
            untracked=untracked,
            ignored=ignored,
            flags=flags,
            uncertain=uncertain,
            last=last,
        )
        return _finalize_sandbox_report(config, sandbox, report)
    except RecoveryGitError as exc:
        return _finalize_sandbox_report(
            config,
            sandbox,
            _fallback(config, _git_unknown(str(exc)), sandbox.root),
        )
    finally:
        _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.reset(ignore_token)
        _ACTIVE_GIT_EXECUTABLE.reset(git_token)
        _ACTIVE_WORKTREE_SNAPSHOT.reset(snapshot_token)
        _ACTIVE_CONFIG.reset(config_token)
        _ACTIVE_SANDBOX.reset(sandbox_token)
        sandbox.close()
