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
from dataclasses import dataclass, replace
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

_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_DIRECTORY_FLAGS = _FILE_FLAGS | getattr(os, "O_DIRECTORY", 0)
_ENTRY_FLAGS = _FILE_FLAGS | getattr(os, "O_NONBLOCK", 0)
_PINNED_DIRECTORY_SUPPORT = (
    bool(getattr(os, "O_NOFOLLOW", 0))
    and bool(getattr(os, "O_DIRECTORY", 0))
    and os.open in os.supports_dir_fd
    and os.scandir in os.supports_fd
)


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
    object_fd: int | None = None
    object_fd_path: str | None = None

    def close(self) -> None:
        if self.object_fd is not None:
            try:
                os.close(self.object_fd)
            except OSError:
                pass
            self.object_fd = None
        try:
            self.temporary.cleanup()
        except OSError:
            pass


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

_SECTION_RE = re.compile(
    r'^\s*\[\s*([^\]\s"]+)(?:\s+"((?:\\.|[^"\\])*)")?\s*\]\s*(?:[#;].*)?$'
)
_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z0-9.-]+)\s*(?:=\s*)?(.*?)\s*$")
_DEAD_HELPERS = (
    "_committed_coverage",
    "_head_exists",
    "_index_flags",
    "_visible_worktree_paths",
    "_worktree",
)


def _base_original(name: str) -> Any:
    sentinel = f"__lifeos_recovery_original_{name.lstrip('_')}"
    original = getattr(_base, sentinel, None)
    if original is None:
        original = getattr(_base, name)
        setattr(_base, sentinel, original)
    return original


_ORIGINAL_SCOPE_FILTER = _base_original("_scope_filter")
_ORIGINAL_WORKING_TREE_SNAPSHOT = _base_original("_working_tree_snapshot")
_ORIGINAL_WORKTREE_FROM_SNAPSHOT = _base_original("_worktree_from_snapshot")
_ORIGINAL_IGNORED_PATHS = _base_original("_ignored_paths")
_ORIGINAL_BUILD_REPORT = _base_original("_build_report")
_ORIGINAL_LATEST_COMMIT = _base_original("_latest_commit")


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
        raise _base.RecoveryGitError("Could not open Git metadata safely") from exc
    try:
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode):
            raise _base.RecoveryGitError("Git metadata uses an unsupported indirection")
        if observed.st_nlink != 1:
            raise _base.RecoveryGitError("Git metadata uses an unsupported hard link")
        if limit is not None and observed.st_size > limit:
            raise _base.RecoveryGitError("Git metadata is too large to inspect safely")
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
        if stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode):
            return root, marker
        raise _base.RecoveryGitError(
            "Indirect Git metadata layouts are not supported by recovery diagnostics"
        )
    return None


def _parse_git_bool(value: str, *, key: str) -> bool:
    folded = value.strip().casefold()
    if folded in {"", "true", "yes", "on", "1"}:
        return True
    if folded in {"false", "no", "off", "0"}:
        return False
    raise _base.RecoveryGitError(f"Git {key} configuration is malformed")


def _config_snapshot(config_path: Path) -> tuple[bytes, bool, bool, bool]:
    raw = _read_small_metadata(config_path)
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
            raise _base.RecoveryGitError("Git config section header is malformed or unsupported")
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
            raise _base.RecoveryGitError(
                "Git core.excludesFile configuration is not supported by recovery diagnostics"
            )
        elif key == "repositoryformatversion":
            try:
                repository_format = int(value.strip() or "0")
            except ValueError as exc:
                raise _base.RecoveryGitError("Git repository format is malformed") from exc
    if repository_format != 0 or extensions:
        raise _base.RecoveryGitError(
            "Extended Git repository formats cannot be inspected safely by recovery diagnostics"
        )
    return raw, contains_includes, filemode, ignorecase


def _copy_regular_metadata(source: Path, destination: Path) -> None:
    opened = _open_regular_metadata(source)
    if opened is None:
        return
    fd, _observed = opened
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(fd, "rb", closefd=True) as source_handle:
            fd = -1
            with destination.open("wb") as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle, length=131_072)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not snapshot Git metadata") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _open_metadata_directory(source: Path, *, missing_ok: bool = False) -> int | None:
    if not _PINNED_DIRECTORY_SUPPORT:
        raise _base.RecoveryGitError(
            "Platform cannot safely pin Git metadata directories for recovery diagnostics"
        )
    try:
        fd = os.open(source, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise _base.RecoveryGitError("Could not open Git metadata directory safely")
    except OSError as exc:
        raise _base.RecoveryGitError("Could not open Git metadata directory safely") from exc
    try:
        observed = os.fstat(fd)
        if not stat.S_ISDIR(observed.st_mode):
            raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe directory")
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
                    raise _base.RecoveryGitError("Could not inspect Git metadata") from exc
                entries.append((entry.name, observed))
    except _base.RecoveryGitError:
        raise
    except OSError as exc:
        raise _base.RecoveryGitError("Could not enumerate Git metadata") from exc
    return sorted(entries, key=lambda item: item[0])


def _open_metadata_child(
    directory_fd: int,
    name: str,
    expected: os.stat_result,
) -> tuple[int, os.stat_result]:
    if stat.S_ISLNK(expected.st_mode):
        raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe symlink")
    if stat.S_ISDIR(expected.st_mode):
        flags = _DIRECTORY_FLAGS
    elif stat.S_ISREG(expected.st_mode):
        flags = _ENTRY_FLAGS
    else:
        raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe entry")
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not open Git metadata entry safely") from exc
    try:
        observed = os.fstat(fd)
        if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
            raise _base.RecoveryGitError("Git metadata changed during safe traversal")
        if stat.S_ISDIR(expected.st_mode) != stat.S_ISDIR(observed.st_mode):
            raise _base.RecoveryGitError("Git metadata changed during safe traversal")
        if stat.S_ISREG(expected.st_mode) != stat.S_ISREG(observed.st_mode):
            raise _base.RecoveryGitError("Git metadata changed during safe traversal")
        if stat.S_ISREG(observed.st_mode) and observed.st_nlink != 1:
            raise _base.RecoveryGitError("Git metadata uses an unsupported hard link")
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
            raise _base.RecoveryGitError("Could not snapshot Git metadata") from exc
        finally:
            if child_fd >= 0:
                os.close(child_fd)


def _copy_metadata_tree(source: Path, destination: Path) -> None:
    directory_fd = _open_metadata_directory(source, missing_ok=True)
    if directory_fd is None:
        return
    try:
        _copy_metadata_directory(directory_fd, destination)
    finally:
        os.close(directory_fd)


def _fingerprint_regular_metadata(digest: Any, label: str, path: Path) -> None:
    opened = _open_regular_metadata(path)
    if opened is None:
        digest.update(label.encode("utf-8", errors="surrogateescape") + b"\0missing\0")
        return
    fd, observed = opened
    digest.update(label.encode("utf-8", errors="surrogateescape") + b"\0")
    digest.update(f"{observed.st_dev}:{observed.st_ino}:{observed.st_size}".encode())
    digest.update(b"\0")
    try:
        with os.fdopen(fd, "rb", closefd=True) as handle:
            for block in iter(lambda: handle.read(131_072), b""):
                digest.update(block)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not fingerprint Git metadata") from exc
    digest.update(b"\0")


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
        raise _base.RecoveryGitError("Could not fingerprint Git metadata") from exc
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


def _fingerprint_metadata_tree(digest: Any, git_dir: Path, source: Path) -> None:
    label = source.relative_to(git_dir).as_posix()
    directory_fd = _open_metadata_directory(source, missing_ok=True)
    if directory_fd is None:
        digest.update(label.encode("utf-8", errors="surrogateescape") + b"\0missing-tree\0")
        return
    try:
        _fingerprint_metadata_directory(digest, directory_fd, label)
    finally:
        os.close(directory_fd)


def _reject_split_index(git_dir: Path) -> None:
    try:
        with os.scandir(git_dir) as iterator:
            if any(entry.name.startswith("sharedindex.") for entry in iterator):
                raise _base.RecoveryGitError(
                    "Split-index Git metadata is not supported by recovery diagnostics"
                )
    except _base.RecoveryGitError:
        raise
    except OSError as exc:
        raise _base.RecoveryGitError("Could not inspect Git index topology") from exc


def _pinned_fd_path(fd: int, observed: os.stat_result) -> str:
    for root in ("/proc/self/fd", "/dev/fd"):
        candidate = f"{root}/{fd}"
        try:
            candidate_state = os.stat(candidate)
        except OSError:
            continue
        if (
            stat.S_ISDIR(candidate_state.st_mode)
            and (candidate_state.st_dev, candidate_state.st_ino)
            == (observed.st_dev, observed.st_ino)
        ):
            return candidate
    raise _base.RecoveryGitError(
        "Platform cannot expose a pinned Git object directory safely"
    )


def _open_object_store(
    git_dir: Path,
) -> tuple[Path, int, os.stat_result, str]:
    object_dir = git_dir / "objects"
    object_fd = _open_metadata_directory(object_dir)
    assert object_fd is not None
    try:
        object_state = os.fstat(object_fd)
        top_entries = dict(_metadata_directory_entries(object_fd))
        info_state = top_entries.get("info")
        if info_state is not None:
            if not stat.S_ISDIR(info_state.st_mode) or stat.S_ISLNK(info_state.st_mode):
                raise _base.RecoveryGitError(
                    "Git object-store info metadata uses an unsupported entry"
                )
            info_fd, _ = _open_metadata_child(object_fd, "info", info_state)
            try:
                info_names = {name for name, _state in _metadata_directory_entries(info_fd)}
            finally:
                os.close(info_fd)
            if {"alternates", "http-alternates"} & info_names:
                raise _base.RecoveryGitError(
                    "Alternate Git object stores are not supported by recovery diagnostics"
                )
        object_fd_path = _pinned_fd_path(object_fd, object_state)
        return object_dir, object_fd, object_state, object_fd_path
    except Exception:
        os.close(object_fd)
        raise


def _validate_object_store(git_dir: Path) -> tuple[Path, os.stat_result]:
    try:
        object_dir, object_fd, object_state, _object_fd_path = _open_object_store(git_dir)
    except _base.RecoveryGitError as exc:
        if "unsafe directory" in str(exc) or "open Git metadata directory" in str(exc):
            raise _base.RecoveryGitError(
                "Redirected Git object stores are not supported by recovery diagnostics"
            ) from exc
        raise
    try:
        return object_dir, object_state
    finally:
        os.close(object_fd)


def _metadata_fingerprint(
    git_dir: Path,
    *,
    object_state: os.stat_result | None = None,
) -> str:
    digest = hashlib.sha256()
    for name in ("config", "HEAD", "index", "packed-refs", "shallow", "info/exclude"):
        _fingerprint_regular_metadata(digest, name, git_dir / name)
    _fingerprint_metadata_tree(digest, git_dir, git_dir / "refs")
    if object_state is None:
        object_dir, object_state = _validate_object_store(git_dir)
        if object_dir != git_dir / "objects":
            raise _base.RecoveryGitError("Git object-store topology changed unexpectedly")
    digest.update(f"objects\0{object_state.st_dev}:{object_state.st_ino}\0".encode())
    return digest.hexdigest()


def _build_sandbox(vault: Path) -> _GitMetadataSandbox | None:
    discovered = _discover_git_directory(vault)
    if discovered is None:
        return None
    root, git_dir = discovered
    _reject_split_index(git_dir)
    _config_bytes, contains_includes, filemode, ignorecase = _config_snapshot(git_dir / "config")
    try:
        object_dir, object_fd, object_state, object_fd_path = _open_object_store(git_dir)
    except _base.RecoveryGitError as exc:
        if "unsafe directory" in str(exc) or "open Git metadata directory" in str(exc):
            raise _base.RecoveryGitError(
                "Redirected Git object stores are not supported by recovery diagnostics"
            ) from exc
        raise

    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        fingerprint = _metadata_fingerprint(git_dir, object_state=object_state)
        try:
            index_state = os.lstat(git_dir / "index")
        except FileNotFoundError:
            index_mtime_ns = None
        except OSError as exc:
            raise _base.RecoveryGitError("Could not inspect Git index metadata") from exc
        else:
            if stat.S_ISLNK(index_state.st_mode) or not stat.S_ISREG(index_state.st_mode):
                raise _base.RecoveryGitError("Git index metadata uses an unsafe entry")
            if index_state.st_nlink != 1:
                raise _base.RecoveryGitError("Git index metadata uses an unsupported hard link")
            index_mtime_ns = index_state.st_mtime_ns

        try:
            temporary = tempfile.TemporaryDirectory(prefix="lifeos-doctor-git-")
            fake = Path(temporary.name) / "git"
            fake.mkdir(parents=True)
            for name in ("HEAD", "index", "packed-refs", "shallow"):
                _copy_regular_metadata(git_dir / name, fake / name)
            _copy_metadata_tree(git_dir / "refs", fake / "refs")
            _copy_regular_metadata(git_dir / "info" / "exclude", fake / "info" / "exclude")
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
            raise _base.RecoveryGitError("Could not create Git metadata sandbox") from exc

        return _GitMetadataSandbox(
            temporary,
            root,
            vault,
            fake,
            object_dir,
            index_mtime_ns,
            fingerprint,
            contains_includes,
            ignorecase,
            object_fd,
            object_fd_path,
        )
    except Exception:
        os.close(object_fd)
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                pass
        raise


def _sandbox_environment() -> dict[str, str]:
    env = _base._git_environment()
    sandbox = _ACTIVE_SANDBOX.get()
    if sandbox is not None:
        env.update(
            GIT_DIR=str(sandbox.git_dir),
            GIT_WORK_TREE=str(sandbox.root),
            GIT_OBJECT_DIRECTORY=sandbox.object_fd_path or str(sandbox.object_dir),
        )
    return env


def _sandbox_pass_fds() -> tuple[int, ...]:
    sandbox = _ACTIVE_SANDBOX.get()
    if sandbox is None or sandbox.object_fd is None:
        return ()
    return (sandbox.object_fd,)


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
            pass_fds=_sandbox_pass_fds(),
        )
    except OSError as exc:
        raise _base.RecoveryGitError("Could not execute Git safely") from exc
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise _base.RecoveryGitError("Git metadata existence query could not be verified safely")


def _selects_repository_metadata(path: str) -> bool:
    sandbox = _ACTIVE_SANDBOX.get()
    if sandbox is None:
        return False
    pure = PurePosixPath(path)
    if not pure.parts:
        return False
    try:
        metadata_state = os.stat(sandbox.vault / ".git", follow_symlinks=False)
        candidate_state = os.stat(sandbox.vault / pure.parts[0], follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _base.RecoveryGitError("Could not verify repository metadata boundary") from exc
    return (metadata_state.st_dev, metadata_state.st_ino) == (
        candidate_state.st_dev,
        candidate_state.st_ino,
    )


def _policy_prefix_is_literal(value: str) -> bool:
    if value != value.strip() or value.startswith("/"):
        return False
    without_trailing = value.rstrip("/")
    if not without_trailing:
        return False
    return PurePosixPath(without_trailing).as_posix() == without_trailing


def _scope_filter(config: Any) -> Any:
    scope = _ORIGINAL_SCOPE_FILTER(config)
    values = [*scope.policy.excluded_prefixes]
    if not scope.request.allow_protected:
        values.extend(scope.policy.protected_prefixes)
    values.extend(scope.request.excluded_paths)
    if any(not _policy_prefix_is_literal(value) for value in values):
        raise _base.RecoveryGitError(
            "Recovery policy paths do not have an unambiguous literal POSIX spelling"
        )
    return scope


def _scope_filter_call(self: Any, path: str) -> bool:
    try:
        if _selects_repository_metadata(path):
            return True
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


def _normalization_sensitive(value: str) -> bool:
    return unicodedata.normalize("NFC", value) != unicodedata.normalize("NFD", value)


def _runtime_exclusion_pathspecs(prefix: tuple[str, ...], scope: Any) -> tuple[str, ...]:
    config = _ACTIVE_CONFIG.get()
    if config is None:
        raise _base.RecoveryGitError("Recovery runtime scope is unavailable for hidden Git queries")
    output: list[str] = []
    for relative in _base._runtime_prefixes(config):
        if _normalization_sensitive(relative):
            raise _base.RecoveryGitError(
                "Git hidden-scope runtime normalization cannot be authorized safely"
            )
        output.append(
            _base._literal_pathspec(
                _base._repo_path(relative, prefix),
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
        raise _base.RecoveryGitError("Git hidden-scope normalization cannot be authorized safely")
    return (
        _base._literal_pathspec(
            _base._repo_path(relative, prefix),
            icase=scope.case_insensitive,
        ),
        *_runtime_exclusion_pathspecs(prefix, scope),
    )


def _hidden_index_state(git: str, root: Path, context: Any, scope: Any) -> tuple[bool, ...]:
    state: list[bool] = []
    for relative in _base._policy_denied_prefixes(scope):
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
            raise _base.RecoveryGitError("Git hidden-index query reported incomplete results")
        state.append(bool(result.stdout))
    return tuple(state)


def _authorized_git_pathspecs(context: Any, scope: Any, config: Any) -> tuple[str, ...]:
    positive = PurePosixPath(*context.prefix).as_posix() if context.prefix else ""
    if positive and _normalization_sensitive(positive):
        raise _base.RecoveryGitError(
            "Git vault path normalization cannot be authorized safely by recovery diagnostics"
        )
    pathspecs = [
        _base._literal_pathspec(
            positive,
            icase=context.case_insensitive_prefix,
        )
        if context.prefix
        else "."
    ]
    denied = (*_base._policy_denied_prefixes(scope), *_base._runtime_prefixes(config))
    for relative in dict.fromkeys(denied):
        if _normalization_sensitive(relative):
            raise _base.RecoveryGitError(
                "Git recovery scope normalization cannot be authorized safely"
            )
        pathspecs.append(
            _base._literal_pathspec(
                _base._repo_path(relative, context.prefix),
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
    raise _base.RecoveryGitError("Git index contains an unsupported canonical entry type")


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

    index_entries = _base._canonical_index_entries(
        _base._index_entries(_base._index_debug_raw(git, root, pathspec)),
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
        arguments=_base._pathspec_command(
            "diff-index",
            ("--cached", "--raw", "--full-index", "-z", "--no-renames", head_oid),
            pathspec,
        ),
    )
    if result.stderr.strip():
        raise _base.RecoveryGitError("Git staged metadata query reported incomplete results")

    raw = result.stdout
    cursor = 0
    seen: set[str] = set()
    while cursor < len(raw):
        header_end = raw.find(b"\0", cursor)
        if header_end < 0:
            raise _base.RecoveryGitError("Git staged metadata query returned malformed output")
        header = raw[cursor:header_end]
        cursor = header_end + 1
        if not header:
            continue
        path_end = raw.find(b"\0", cursor)
        if path_end < 0:
            raise _base.RecoveryGitError("Git staged metadata query returned malformed path data")
        raw_path = raw[cursor:path_end]
        cursor = path_end + 1
        fields = header.split()
        if len(fields) != 5 or not fields[0].startswith(b":"):
            raise _base.RecoveryGitError("Git staged metadata query returned malformed entry data")
        try:
            old_mode = int(fields[0][1:], 8)
            old_oid = fields[2].decode("ascii", errors="strict")
            status = fields[4].decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="surrogateescape")
        except (UnicodeDecodeError, ValueError) as exc:
            raise _base.RecoveryGitError(
                "Git staged metadata query returned malformed entry data"
            ) from exc
        if status not in {"A", "D", "M", "T"}:
            raise _base.RecoveryGitError("Git staged metadata query returned unsupported status")
        canonical = _base._canonical_path(
            path,
            prefix,
            excluded,
            case_insensitive_prefix=case_insensitive_prefix,
        )
        if canonical is None:
            continue
        if canonical in seen:
            raise _base.RecoveryGitError("Git staged metadata contains duplicate canonical paths")
        seen.add(canonical)
        if status == "A":
            output.pop(canonical, None)
            continue
        if old_mode == 0 or not old_oid or set(old_oid) == {"0"}:
            raise _base.RecoveryGitError("Git staged metadata omitted the committed object")
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


def _working_tree_snapshot(vault: Path, excluded: Any) -> Any:
    snapshot = _ORIGINAL_WORKING_TREE_SNAPSHOT(vault, excluded)
    _ACTIVE_WORKTREE_SNAPSHOT.set(snapshot)
    return snapshot


def _scope_allows_without_mutation(scope: Any, path: str) -> bool:
    try:
        if scope.case_insensitive and _base._casefold_denied(path, scope.policy, scope.request):
            return False
        decision = scope_decision(
            unicodedata.normalize("NFC", path),
            scope=scope.request,
            policy=scope.policy,
            mode="local",
        )
    except (CoherenceError, RetrievalError) as exc:
        raise _base.RecoveryGitError("Could not verify Git ignore metadata scope") from exc
    return decision.allowed


def _ignore_sources_authorized(path: str, scope: Any) -> bool:
    parts = PurePosixPath(path).parts
    candidates = [".gitignore"]
    for depth in range(1, len(parts)):
        candidates.append(PurePosixPath(*parts[:depth], ".gitignore").as_posix())
    return all(_scope_allows_without_mutation(scope, source) for source in candidates)


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
    result = _ORIGINAL_WORKTREE_FROM_SNAPSHOT(
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
    if not isinstance(excluded, _base._ScopeFilter) or not excluded.incomplete:
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
        _base._ignored_paths(
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


def _build_report(config: Any, **kwargs: Any) -> Any:
    classification = _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.get()
    if classification is not None:
        kwargs = dict(kwargs)
        kwargs["untracked"] = classification.untracked
        kwargs["ignored"] = classification.ignored

    report = _ORIGINAL_BUILD_REPORT(config, **kwargs)
    snapshot = _ACTIVE_WORKTREE_SNAPSHOT.get()
    untracked = tuple(kwargs.get("untracked", ()))
    if snapshot is None or not untracked:
        return report
    by_path = snapshot.by_path()
    non_regular = tuple(
        sorted(
            path
            for path in untracked
            if (entry := by_path.get(path)) is not None and not stat.S_ISREG(entry.mode)
        )
    )
    if not non_regular:
        return report

    diagnostics = []
    for item in report.diagnostics:
        if item.id == "recovery.git.canonical_objects":
            paths = tuple(sorted(set(item.paths) | set(non_regular)))
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
        elif item.id == "recovery.git.untracked_canonical":
            item = replace(
                item,
                summary=(
                    f"{len(untracked)} visible canonical path(s) are untracked and absent from "
                    f"committed history; {len(non_regular)} are non-regular recovery entries."
                ),
                remediation=(
                    "Replace non-regular paths identified by recovery.git.canonical_objects with "
                    "ordinary vault files; then add/commit intended regular untracked canonical files."
                ),
            )
        diagnostics.append(item)
    return replace(report, diagnostics=tuple(diagnostics))


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
        return _base._fallback(config, _base._no_repo())

    sandbox_token = _ACTIVE_SANDBOX.set(sandbox)
    config_token = _ACTIVE_CONFIG.set(config)
    snapshot_token = _ACTIVE_WORKTREE_SNAPSHOT.set(None)
    git_token = _ACTIVE_GIT_EXECUTABLE.set(git)
    ignore_token = _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.set(None)
    try:
        if sandbox.contains_includes:
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
        if discovered is None or discovered[1] != sandbox.root / ".git":
            return _base._fallback(
                config,
                _base._git_unknown(
                    "Git repository metadata changed during recovery inspection; retry for a stable snapshot."
                ),
                sandbox.root,
            )
        _reject_split_index(discovered[1])
        if _metadata_fingerprint(discovered[1]) != sandbox.fingerprint:
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
        _ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.reset(ignore_token)
        _ACTIVE_GIT_EXECUTABLE.reset(git_token)
        _ACTIVE_WORKTREE_SNAPSHOT.reset(snapshot_token)
        _ACTIVE_CONFIG.reset(config_token)
        _ACTIVE_SANDBOX.reset(sandbox_token)
        sandbox.close()


setattr(_base, "_run_git", _run_git)
setattr(_base, "_run_git_presence", _run_git_presence)
setattr(_base, "_scope_filter", _scope_filter)
setattr(_base._ScopeFilter, "__call__", _scope_filter_call)
setattr(_base, "_hidden_index_state", _hidden_index_state)
setattr(_base, "_authorized_git_pathspecs", _authorized_git_pathspecs)
setattr(_base, "_tree_entries", _tree_entries)
setattr(_base, "_snapshot_entry_for_index_path", _snapshot_entry_for_index_path)
setattr(_base, "_compare_index_entry", _compare_index_entry)
setattr(_base, "_working_tree_snapshot", _working_tree_snapshot)
setattr(_base, "_worktree_from_snapshot", _worktree_from_snapshot)
setattr(_base, "_build_report", _build_report)
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
        if not name.startswith("__") and hasattr(_base, name):
            setattr(_base, name, value)


_sys.modules[__name__].__class__ = _RecoveryModuleProxy
