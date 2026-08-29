"""Read-only recovery-readiness diagnostics for canonical LifeOS vault data."""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import unicodedata
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


@dataclass(slots=True)
class _ScopeFilter:
    runtime: PathExclusion
    policy: RetrievalPolicy
    request: RetrievalScope
    case_insensitive: bool = False
    incomplete: bool = False

    def __call__(self, path: str) -> bool:
        try:
            if self.runtime(path):
                return True
            if _casefold_denied(path, self.policy, self.request):
                self.incomplete = True
                return True
            decision = scope_decision(
                path,
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
        raise RecoveryGitError("Could not execute Git safely") from exc
    if check and result.returncode:
        raise RecoveryGitError(
            "Git metadata query failed; repository state could not be verified safely."
        )
    return result


def _run_git_presence(
    git_executable: str,
    *,
    cwd: Path,
    arguments: Sequence[str],
) -> bool:
    """Run a metadata-only existence probe while discarding any pathname output."""
    try:
        result = subprocess.run(
            [git_executable, *arguments],
            cwd=cwd,
            shell=False,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=_git_environment(),
        )
    except OSError as exc:
        raise RecoveryGitError("Could not execute Git safely") from exc
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RecoveryGitError("Git metadata existence query could not be verified safely")


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
    del vault
    # Do not enumerate vault names merely to select privacy matching semantics.
    # macOS commonly exposes normalization- and case-insensitive volumes, so fail
    # closed there; later identity checks still prevent unrelated aliases matching.
    return sys.platform == "darwin"


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


def _scope_filter(config: LifeOSConfig) -> _ScopeFilter:
    try:
        runtime = _runtime_filter(config)
        policy = load_retrieval_policy(config.vault_root)
        case_insensitive = _vault_case_insensitive(config.vault_root)
    except (CoherenceError, RetrievalError) as exc:
        raise RecoveryGitError("Could not load recovery scope policy safely") from exc
    return _ScopeFilter(runtime, policy, RetrievalScope(), case_insensitive)


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


def _head_exists(git: str, root: Path) -> bool:
    return _head_oid(git, root) is not None


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


def _authorized_git_pathspecs(
    context: _RepoContext,
    scope: _ScopeFilter,
    config: LifeOSConfig,
) -> tuple[str, ...]:
    pathspecs = [
        _literal_pathspec(PurePosixPath(*context.prefix).as_posix())
        if context.prefix
        else "."
    ]
    denied = (*_policy_denied_prefixes(scope), *_runtime_prefixes(config))
    for relative in dict.fromkeys(denied):
        pathspecs.append(
            _literal_pathspec(
                _repo_path(relative, context.prefix),
                exclude=True,
                icase=scope.case_insensitive,
            )
        )
    return tuple(pathspecs)


def _uses_magic(pathspecs: Sequence[str]) -> bool:
    return any(path.startswith(":(") for path in pathspecs)


def _pathspec_command(
    command: str, arguments: Sequence[str], pathspec: Pathspec
) -> tuple[str, ...]:
    pathspecs = (pathspec,) if isinstance(pathspec, str) else tuple(pathspec)
    prefix = (
        ("--no-literal-pathspecs",)
        if _uses_magic(pathspecs)
        else ("--literal-pathspecs",)
    )
    return (*prefix, command, *arguments, "--", *pathspecs)


def _hidden_index_state(
    git: str,
    root: Path,
    context: _RepoContext,
    scope: _ScopeFilter,
) -> tuple[bool, ...]:
    state: list[bool] = []
    for relative in _policy_denied_prefixes(scope):
        repo_relative = _repo_path(relative, context.prefix)
        state.append(
            _run_git_presence(
                git,
                cwd=root,
                arguments=(
                    "--no-literal-pathspecs",
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    _literal_pathspec(repo_relative, icase=scope.case_insensitive),
                ),
            )
        )
    return tuple(state)


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


def _tree_root_oid(
    git: str,
    root: Path,
    head_oid: str,
    prefix: tuple[str, ...],
) -> str | None:
    if not prefix:
        return _root_tree_oid(git, root, head_oid)
    path = PurePosixPath(*prefix).as_posix()
    result = _run_git(
        git,
        cwd=root,
        arguments=("--literal-pathspecs", "ls-tree", "-z", head_oid, "--", path),
    )
    if result.stderr.strip():
        raise RecoveryGitError("Git vault tree query reported incomplete results")
    records = _parse_tree_records(result.stdout)
    exact = [record for record in records if record[3] == path]
    if not exact:
        return None
    if len(exact) != 1:
        raise RecoveryGitError("Git vault tree query returned ambiguous output")
    mode, obj_type, oid, _ = exact[0]
    if obj_type != "tree" or (mode & 0o170000) != 0o040000:
        raise RecoveryGitError("Configured vault path is not a Git tree")
    return oid


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


def _tree_entries(
    git: str,
    root: Path,
    head_oid: str | None,
    pathspec: Pathspec,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> dict[str, tuple[int, str, str]]:
    del pathspec, case_insensitive_prefix
    if head_oid is None:
        return {}
    tree_oid = _tree_root_oid(git, root, head_oid, prefix)
    if tree_oid is None:
        return {}
    return _walk_tree_entries(git, root, tree_oid, (), excluded)


def _committed_coverage(
    git: str,
    root: Path,
    pathspec: Pathspec,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    entries = _tree_entries(
        git,
        root,
        _head_oid(git, root),
        pathspec,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )
    covered = {
        path
        for path, (mode, obj_type, _oid) in entries.items()
        if obj_type == "blob" and (mode & 0o170000) == 0o100000
    }
    return tuple(sorted(covered)), tuple(sorted(set(entries) - covered))


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


def _index_flags(
    git: str,
    root: Path,
    pathspec: Pathspec,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    return _index_flags_from_raw(
        _index_flags_raw(git, root, pathspec),
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


def _working_tree_snapshot(vault: Path, excluded: PathExclusion) -> _WorkingTreeSnapshot:
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


def _visible_worktree_paths(vault: Path, excluded: PathExclusion) -> tuple[str, ...]:
    return _working_tree_snapshot(vault, excluded).paths


def _snapshot_entry_for_index_path(
    vault: Path,
    path: str,
    snapshot: _WorkingTreeSnapshot,
) -> _FsEntry | None:
    by_path = snapshot.by_path()
    exact = by_path.get(path)
    if exact is not None:
        return exact
    folded = path.casefold()
    candidates = [entry for entry in snapshot.entries if entry.path.casefold() == folded]
    if not candidates:
        return None
    observed = _lstat(vault, path)
    if observed is None:
        return None
    identity = (observed.st_dev, observed.st_ino)
    matches = [entry for entry in candidates if (entry.device, entry.inode) == identity]
    if len(matches) > 1:
        raise RecoveryGitError("Filesystem exposes ambiguous case aliases for a canonical path")
    return matches[0] if matches else None


def _compare_index_entry(
    entry: _IndexEntry,
    observed: _FsEntry,
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
    return "clean"


def _worktree_from_snapshot(
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


def _worktree(
    git: str,
    root: Path,
    vault: Path,
    pathspec: Pathspec,
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    return _worktree_from_entries(
        _index_entries(_index_debug_raw(git, root, pathspec)),
        vault,
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _ignored_paths(
    git: str,
    root: Path,
    paths: Sequence[str],
    prefix: tuple[str, ...],
    excluded: PathExclusion,
    *,
    case_insensitive_prefix: bool = False,
) -> tuple[str, ...]:
    if not paths:
        return ()
    repo_paths = tuple(f"./{_repo_path(path, prefix)}" for path in paths)
    input_bytes = (
        b"\0".join(path.encode("utf-8", errors="surrogateescape") for path in repo_paths) + b"\0"
    )
    result = _run_git(
        git,
        cwd=root,
        arguments=(
            "--no-literal-pathspecs",
            "-c",
            f"core.excludesFile={os.devnull}",
            "check-ignore",
            "--stdin",
            "-z",
        ),
        check=False,
        input_bytes=input_bytes,
    )
    if result.returncode not in {0, 1} or result.stderr.strip():
        raise RecoveryGitError("Git ignore query could not be verified safely")
    return _filter_paths(
        _nul_paths(result.stdout),
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _latest_commit(
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


def _build_report(
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


def _resolve_git_executable() -> str | None:
    discovered = shutil.which("git")
    if discovered is None:
        return None
    try:
        return str(Path(discovered).resolve(strict=True))
    except OSError as exc:
        raise RecoveryGitError("Git executable could not be resolved safely") from exc


def collect_recovery_readiness(
    config: LifeOSConfig,
    *,
    clock_fn: Callable[[], datetime] = _utc_now,
) -> RecoveryReport:
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
        context = _repo_context(git, config.vault_root)
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)))
    if context is None:
        return _fallback(config, _no_repo())

    root = context.root
    prefix = context.prefix
    case_insensitive_prefix = context.case_insensitive_prefix
    try:
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
                clock_fn,
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
    except RecoveryGitError as exc:
        return _fallback(config, _git_unknown(str(exc)), root)

    return _build_report(
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
