"""Hardened facade for read-only recovery-readiness diagnostics.

The implementation body lives in ``_recovery_readiness_base`` so this module can
apply a small, reviewable trust-boundary layer without duplicating the large
collector. Git subprocesses run against a read-only metadata snapshot whose
configuration cannot follow repository include directives.
"""

from __future__ import annotations

import contextvars
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys as _sys
import tempfile
import types
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from lifeos import _recovery_readiness_base as _base
from lifeos._recovery_readiness_base import (
    RecoveryReport as RecoveryReport,
    format_recovery_text as format_recovery_text,
    recovery_report_to_dict as recovery_report_to_dict,
)
from lifeos.coherence import CoherenceError
from lifeos.retrieval.contracts import RetrievalError, scope_decision


@dataclass(slots=True)
class _GitMetadataSandbox:
    temporary: tempfile.TemporaryDirectory[str]
    root: Path
    git_dir: Path
    object_dir: Path
    index_mtime_ns: int | None
    fingerprint: str
    contains_includes: bool

    def close(self) -> None:
        self.temporary.cleanup()


_ACTIVE_SANDBOX: contextvars.ContextVar[_GitMetadataSandbox | None] = contextvars.ContextVar(
    "lifeos_recovery_git_metadata_sandbox", default=None
)

_SECTION_RE = re.compile(r"^\s*\[\s*([^\]\s]+)", re.IGNORECASE)
_INCLUDE_SECTION_RE = re.compile(r"^\s*\[\s*include(?:if\b[^\]]*)?\]", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z0-9.-]+)\s*(?:=\s*)?(.*?)\s*$")
_DEAD_HELPERS = (
    "_committed_coverage",
    "_head_exists",
    "_index_flags",
    "_visible_worktree_paths",
    "_worktree",
)


def _read_small_metadata(path: Path, *, limit: int = 2_000_000) -> bytes:
    try:
        observed = os.lstat(path)
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise _base.RecoveryGitError("Could not inspect Git metadata safely") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise _base.RecoveryGitError("Git metadata uses an unsupported indirection")
    if observed.st_size > limit:
        raise _base.RecoveryGitError("Git metadata is too large to inspect safely")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _base.RecoveryGitError("Could not read Git metadata safely") from exc


def _discover_git_directory(vault: Path) -> tuple[Path, Path] | None:
    for root in (vault, *vault.parents):
        marker = root / ".git"
        try:
            observed = os.lstat(marker)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _base.RecoveryGitError("Could not inspect Git repository metadata") from exc
        if stat.S_ISDIR(observed.st_mode):
            return root, marker
        if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
            raise _base.RecoveryGitError("Git repository metadata uses an unsupported marker")
        raw = _read_small_metadata(marker, limit=16_384)
        try:
            text = raw.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise _base.RecoveryGitError("Git repository marker is malformed") from exc
        if not text.lower().startswith("gitdir:"):
            raise _base.RecoveryGitError("Git repository marker is malformed")
        selected = Path(text.split(":", 1)[1].strip())
        git_dir = selected if selected.is_absolute() else (root / selected)
        try:
            git_dir = git_dir.resolve(strict=True)
        except OSError as exc:
            raise _base.RecoveryGitError("Git repository metadata could not be resolved") from exc
        if not git_dir.is_dir():
            raise _base.RecoveryGitError("Git repository metadata directory is unavailable")
        if (git_dir / "commondir").exists():
            raise _base.RecoveryGitError(
                "Linked-worktree Git metadata cannot be inspected safely by recovery diagnostics"
            )
        return root, git_dir
    return None


def _config_snapshot(config_path: Path) -> tuple[bytes, bool, bool]:
    raw = _read_small_metadata(config_path)
    text = raw.decode("utf-8", errors="surrogateescape")
    contains_includes = any(
        _INCLUDE_SECTION_RE.match(line) is not None for line in text.splitlines()
    )
    section = ""
    filemode = True
    repository_format = 0
    extensions = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        section_match = _SECTION_RE.match(raw_line)
        if section_match:
            section = section_match.group(1).casefold()
            extensions = extensions or section == "extensions"
            continue
        if section != "core":
            continue
        pair = _KEY_VALUE_RE.match(raw_line)
        if pair is None:
            continue
        key, value = pair.group(1).casefold(), pair.group(2).strip().casefold()
        if key == "filemode":
            if value in {"true", "yes", "on", "1"}:
                filemode = True
            elif value in {"false", "no", "off", "0"}:
                filemode = False
        elif key == "repositoryformatversion":
            try:
                repository_format = int(value or "0")
            except ValueError as exc:
                raise _base.RecoveryGitError("Git repository format is malformed") from exc
    if repository_format != 0 or extensions:
        raise _base.RecoveryGitError(
            "Extended Git repository formats cannot be inspected safely by recovery diagnostics"
        )
    return raw, contains_includes, filemode


def _copy_regular_metadata(source: Path, destination: Path) -> None:
    try:
        observed = os.lstat(source)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _base.RecoveryGitError("Could not snapshot Git metadata") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe entry")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, destination)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not snapshot Git metadata") from exc


def _copy_metadata_tree(source: Path, destination: Path) -> None:
    try:
        observed = os.lstat(source)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _base.RecoveryGitError("Could not snapshot Git metadata") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe directory")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with os.scandir(source) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not enumerate Git metadata") from exc
    for entry in entries:
        src = source / entry.name
        dst = destination / entry.name
        try:
            entry_state = os.lstat(src)
        except OSError as exc:
            raise _base.RecoveryGitError("Could not inspect Git metadata") from exc
        if stat.S_ISLNK(entry_state.st_mode):
            raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe symlink")
        if stat.S_ISDIR(entry_state.st_mode):
            _copy_metadata_tree(src, dst)
        elif stat.S_ISREG(entry_state.st_mode):
            _copy_regular_metadata(src, dst)
        else:
            raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe entry")


def _metadata_fingerprint(git_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ("config", "HEAD", "index", "packed-refs", "shallow"):
        path = git_dir / name
        try:
            observed = os.lstat(path)
        except FileNotFoundError:
            digest.update(name.encode() + b"\0missing\0")
            continue
        except OSError as exc:
            raise _base.RecoveryGitError("Could not fingerprint Git metadata") from exc
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise _base.RecoveryGitError("Git metadata fingerprint encountered an unsafe entry")
        digest.update(name.encode() + b"\0")
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(131_072), b""):
                    digest.update(block)
        except OSError as exc:
            raise _base.RecoveryGitError("Could not fingerprint Git metadata") from exc
        digest.update(b"\0")
    refs = git_dir / "refs"
    if refs.exists():
        try:
            with os.scandir(refs) as _:
                pass
        except OSError as exc:
            raise _base.RecoveryGitError("Could not fingerprint Git refs") from exc
        for directory, dirnames, filenames in os.walk(refs, followlinks=False):
            dirnames.sort()
            filenames.sort()
            relative_dir = Path(directory).relative_to(git_dir).as_posix()
            for filename in filenames:
                path = Path(directory) / filename
                observed = os.lstat(path)
                if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
                    raise _base.RecoveryGitError("Git refs contain an unsafe entry")
                digest.update(
                    f"{relative_dir}/{filename}".encode("utf-8", errors="surrogateescape")
                )
                digest.update(b"\0")
                try:
                    digest.update(path.read_bytes())
                except OSError as exc:
                    raise _base.RecoveryGitError("Could not fingerprint Git refs") from exc
                digest.update(b"\0")
    return digest.hexdigest()


def _build_sandbox(vault: Path) -> _GitMetadataSandbox | None:
    discovered = _discover_git_directory(vault)
    if discovered is None:
        return None
    root, git_dir = discovered
    _config_bytes, contains_includes, filemode = _config_snapshot(git_dir / "config")
    fingerprint = _metadata_fingerprint(git_dir)
    try:
        index_state = os.lstat(git_dir / "index")
    except FileNotFoundError:
        index_mtime_ns = None
    except OSError as exc:
        raise _base.RecoveryGitError("Could not inspect Git index metadata") from exc
    else:
        if stat.S_ISLNK(index_state.st_mode) or not stat.S_ISREG(index_state.st_mode):
            raise _base.RecoveryGitError("Git index metadata uses an unsafe entry")
        index_mtime_ns = index_state.st_mtime_ns

    temporary = tempfile.TemporaryDirectory(prefix="lifeos-doctor-git-")
    fake = Path(temporary.name) / "git"
    fake.mkdir(parents=True)
    try:
        for name in ("HEAD", "index", "packed-refs", "shallow"):
            _copy_regular_metadata(git_dir / name, fake / name)
        _copy_metadata_tree(git_dir / "refs", fake / "refs")
        info_exclude = git_dir / "info" / "exclude"
        _copy_regular_metadata(info_exclude, fake / "info" / "exclude")
        (fake / "config").write_text(
            "[core]\n"
            "\trepositoryformatversion = 0\n"
            f"\tfilemode = {'true' if filemode else 'false'}\n"
            "\tbare = false\n"
            "\tlogallrefupdates = false\n"
            "\tfsmonitor = false\n",
            encoding="utf-8",
        )
        object_dir = (git_dir / "objects").resolve(strict=True)
        if not object_dir.is_dir():
            raise _base.RecoveryGitError("Git object directory is unavailable")
    except Exception:
        temporary.cleanup()
        raise
    return _GitMetadataSandbox(
        temporary,
        root,
        fake,
        object_dir,
        index_mtime_ns,
        fingerprint,
        contains_includes,
    )


def _sandbox_environment() -> dict[str, str]:
    env = _base._git_environment()
    sandbox = _ACTIVE_SANDBOX.get()
    if sandbox is not None:
        env.update(
            GIT_DIR=str(sandbox.git_dir),
            GIT_WORK_TREE=str(sandbox.root),
            GIT_OBJECT_DIRECTORY=str(sandbox.object_dir),
        )
    return env


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
        )
    except OSError as exc:
        raise _base.RecoveryGitError("Could not execute Git safely") from exc
    if check and result.returncode:
        raise _base.RecoveryGitError(
            "Git metadata query failed; repository state could not be verified safely."
        )
    return result


def _run_git_presence(
    git_executable: str,
    *,
    cwd: Path,
    arguments: Any,
) -> bool:
    try:
        result = subprocess.run(
            [git_executable, *arguments],
            cwd=cwd,
            shell=False,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=_sandbox_environment(),
        )
    except OSError as exc:
        raise _base.RecoveryGitError("Could not execute Git safely") from exc
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise _base.RecoveryGitError("Git metadata existence query could not be verified safely")


def _scope_filter_call(self: Any, path: str) -> bool:
    try:
        if self.runtime(path):
            return True
        if self.case_insensitive and _base._casefold_denied(path, self.policy, self.request):
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
        raise _base.RecoveryGitError("Could not verify canonical recovery scope") from exc
    if not decision.allowed:
        self.incomplete = True
        return True
    return False


def _authorized_git_pathspecs(context: Any, scope: Any, config: Any) -> tuple[str, ...]:
    pathspecs = [
        _base._literal_pathspec(
            PurePosixPath(*context.prefix).as_posix(),
            icase=context.case_insensitive_prefix,
        )
        if context.prefix
        else "."
    ]
    denied = (*_base._policy_denied_prefixes(scope), *_base._runtime_prefixes(config))
    for relative in dict.fromkeys(denied):
        pathspecs.append(
            _base._literal_pathspec(
                _base._repo_path(relative, context.prefix),
                exclude=True,
                icase=scope.case_insensitive,
            )
        )
    return tuple(pathspecs)


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
    observed = _base._lstat(vault, path)
    if observed is None:
        return None
    identity = (observed.st_dev, observed.st_ino)
    matches = [entry for entry in candidates if (entry.device, entry.inode) == identity]
    if len(matches) > 1:
        raise _base.RecoveryGitError("Filesystem exposes ambiguous aliases for a canonical path")
    return matches[0] if matches else None


def _compare_index_entry(
    entry: Any,
    observed: Any,
    *,
    filemode: bool = False,
) -> Literal["clean", "modified", "uncertain"]:
    if entry.mode not in {0o100644, 0o100755} or not stat.S_ISREG(observed.mode):
        return "modified"
    if observed.size > _base._INDEX_SIZE_MAX:
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


_ORIGINAL_LATEST_COMMIT = _base._latest_commit


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
    visible = _ORIGINAL_LATEST_COMMIT(
        git,
        root,
        pathspec,
        prefix,
        excluded,
        clock,
        case_insensitive_prefix=case_insensitive_prefix,
        head_oid=head_oid,
    )
    revision = head_oid if head_oid is not None else _base._head_oid(git, root)
    if revision is None:
        return visible
    if isinstance(excluded, _base._ScopeFilter):
        for relative in _base._policy_denied_prefixes(excluded):
            repo_relative = _base._repo_path(relative, prefix)
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
                    _base._literal_pathspec(
                        repo_relative,
                        icase=excluded.case_insensitive,
                    ),
                ),
            )
            if result.stderr.strip():
                raise _base.RecoveryGitError("Git hidden-history query reported incomplete results")
            if result.stdout.strip():
                excluded.incomplete = True
                return None
    return visible


def _reject_repository_config_includes(_git: str, _vault: Path) -> None:
    return None


def collect_recovery_readiness(config: Any, *, clock_fn: Any = None) -> Any:
    try:
        git = _base._resolve_git_executable()
    except _base.RecoveryGitError as exc:
        return _base._fallback(config, _base._git_unknown(str(exc)))
    if git is None:
        return _base._fallback(
            config,
            _base._git_unknown("Git is unavailable, so local canonical history is unknown."),
        )
    try:
        sandbox = _build_sandbox(config.vault_root)
    except _base.RecoveryGitError as exc:
        return _base._fallback(config, _base._git_unknown(str(exc)))
    if sandbox is None:
        return _base.collect_recovery_readiness(
            config,
            **({} if clock_fn is None else {"clock_fn": clock_fn}),
        )

    token = _ACTIVE_SANDBOX.set(sandbox)
    try:
        if sandbox.contains_includes:
            _base._run_git(
                git,
                cwd=config.vault_root,
                arguments=(
                    "config",
                    "--no-includes",
                    "--name-only",
                    "--get-regexp",
                    r"^include(if)?\.",
                ),
                check=False,
            )
            return _base._fallback(
                config,
                _base._git_unknown(
                    "Git repository configuration contains include directives that recovery diagnostics will not follow."
                ),
                sandbox.root,
            )
        report = _base.collect_recovery_readiness(
            config,
            **({} if clock_fn is None else {"clock_fn": clock_fn}),
        )
        discovered = _discover_git_directory(config.vault_root)
        if discovered is None or _metadata_fingerprint(discovered[1]) != sandbox.fingerprint:
            return _base._fallback(
                config,
                _base._git_unknown(
                    "Git repository metadata changed during recovery inspection; retry for a stable snapshot."
                ),
                sandbox.root,
            )
        return report
    except _base.RecoveryGitError as exc:
        return _base._fallback(config, _base._git_unknown(str(exc)), sandbox.root)
    finally:
        _ACTIVE_SANDBOX.reset(token)
        sandbox.close()


setattr(_base, "_run_git", _run_git)
setattr(_base, "_run_git_presence", _run_git_presence)
setattr(_base._ScopeFilter, "__call__", _scope_filter_call)
setattr(_base, "_authorized_git_pathspecs", _authorized_git_pathspecs)
setattr(_base, "_snapshot_entry_for_index_path", _snapshot_entry_for_index_path)
setattr(_base, "_compare_index_entry", _compare_index_entry)
setattr(_base, "_latest_commit", _latest_commit)
setattr(_base, "_reject_repository_config_includes", _reject_repository_config_includes)
for _dead_helper in _DEAD_HELPERS:
    _base.__dict__.pop(_dead_helper, None)

for _name in dir(_base):
    if not _name.startswith("__") and _name not in globals():
        globals()[_name] = getattr(_base, _name)


class _RecoveryModuleProxy(types.ModuleType):
    """Propagate monkeypatched helper assignments into the implementation module."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if hasattr(_base, name):
            setattr(_base, name, value)


_sys.modules[__name__].__class__ = _RecoveryModuleProxy
