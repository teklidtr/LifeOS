"""Stable recovery-readiness facade with final Git metadata hardening.

The reviewed implementation lives in ``_recovery_readiness_impl``. This thin
facade preserves the public/monkeypatch surface while tightening bounded
trust-boundary details around Git config parsing, pinned repository metadata,
read-only object-store views, and snapshotted ignore sources.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys as _sys
import tempfile
import types
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, cast

from lifeos import _recovery_readiness_base as _base
from lifeos import _recovery_readiness_impl as _impl
from lifeos._recovery_readiness_impl import (
    RecoveryReport as RecoveryReport,
    format_recovery_text as format_recovery_text,
    recovery_report_to_dict as recovery_report_to_dict,
)

# Preserve the existing public surface before overriding the final hardening seams.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


def _impl_original(name: str) -> Any:
    sentinel = f"__lifeos_recovery_final_original_{name.lstrip('_')}"
    original = getattr(_impl, sentinel, None)
    if original is None:
        original = getattr(_impl, name)
        setattr(_impl, sentinel, original)
    return original


_PREVIOUS_BUILD_REPORT = _impl_original("_build_report")

_DEFAULT_PINNED_OBJECT_FILES = 1024
_MAX_PINNED_OBJECT_FILES = 4096
_PINNED_OBJECT_FD_RESERVE = 64
_MAX_GIT_METADATA_BYTES = 2_000_000


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
                raise _base.RecoveryGitError(
                    f"Git {key} configuration uses an unsupported escape"
                )
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
            raise _base.RecoveryGitError(
                f"Git {key} configuration uses an unsupported escape"
            )
        output.append(char)
        index += 1

    if escaped or quoted:
        raise _base.RecoveryGitError(f"Git {key} configuration is malformed")
    return "".join(output).strip()


def _parse_git_bool(value: str, *, key: str) -> bool:
    folded = _decode_git_config_scalar(value, key=key).casefold()
    if folded in {"", "true", "yes", "on", "1"}:
        return True
    if folded in {"false", "no", "off", "0"}:
        return False
    raise _base.RecoveryGitError(f"Git {key} configuration is malformed")


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
        section_match = _impl._SECTION_RE.match(raw_line)
        if section_match:
            section = section_match.group(1).casefold()
            subsection = section_match.group(2)
            contains_includes = contains_includes or section in {"include", "includeif"}
            extensions = extensions or (section == "extensions" and subsection is None)
            continue
        if line.startswith("["):
            raise _base.RecoveryGitError(
                "Git config section header is malformed or unsupported"
            )
        if section != "core" or subsection is not None:
            continue

        pair = _impl._KEY_VALUE_RE.match(raw_line)
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
            scalar = _decode_git_config_scalar(value, key="repositoryformatversion")
            try:
                repository_format = int(scalar or "0")
            except ValueError as exc:
                raise _base.RecoveryGitError("Git repository format is malformed") from exc

    if repository_format != 0 or extensions:
        raise _base.RecoveryGitError(
            "Extended Git repository formats cannot be inspected safely by recovery diagnostics"
        )
    return raw, contains_includes, filemode, ignorecase


def _config_snapshot(config_path: Path) -> tuple[bytes, bool, bool, bool]:
    return _parse_config_snapshot(_impl._read_small_metadata(config_path))


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
            raise _base.RecoveryGitError("Could not inspect Git repository metadata") from exc
        if not stat.S_ISDIR(expected.st_mode) or stat.S_ISLNK(expected.st_mode):
            raise _base.RecoveryGitError(
                "Indirect Git metadata layouts are not supported by recovery diagnostics"
            )
        metadata_fd = _impl._open_metadata_directory(marker)
        assert metadata_fd is not None
        try:
            observed = os.fstat(metadata_fd)
            if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
                raise _base.RecoveryGitError(
                    "Git repository metadata changed during safe root pinning"
                )
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
        raise _base.RecoveryGitError("Could not inspect Git metadata safely") from exc


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
        raise _base.RecoveryGitError("Could not open Git metadata directory safely")
    child_fd, observed = _impl._open_metadata_child(directory_fd, name, expected)
    if not stat.S_ISDIR(observed.st_mode):
        os.close(child_fd)
        raise _base.RecoveryGitError("Git metadata snapshot encountered an unsafe directory")
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
    child_fd, observed = _impl._open_metadata_child(directory_fd, name, expected)
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        os.close(child_fd)
        raise _base.RecoveryGitError("Git metadata uses an unsupported entry")
    if observed.st_size > limit:
        os.close(child_fd)
        raise _base.RecoveryGitError("Git metadata is too large to inspect safely")
    try:
        with os.fdopen(child_fd, "rb", closefd=True) as handle:
            child_fd = -1
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise _base.RecoveryGitError("Could not read Git metadata safely") from exc
    finally:
        if child_fd >= 0:
            os.close(child_fd)
    if len(content) > limit or len(content) != observed.st_size:
        raise _base.RecoveryGitError("Git metadata changed during safe snapshot")
    if not _same_regular_snapshot(observed, after):
        raise _base.RecoveryGitError("Git metadata changed during safe snapshot")
    return content


def _copy_named_regular_metadata(
    directory_fd: int,
    name: str,
    destination: Path,
) -> None:
    expected = _stat_child(directory_fd, name)
    if expected is None:
        return
    child_fd, observed = _impl._open_metadata_child(directory_fd, name, expected)
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
        _impl._copy_metadata_directory(child_fd, destination)
    finally:
        os.close(child_fd)


def _reject_split_index_fd(metadata_fd: int) -> None:
    try:
        names = os.listdir(metadata_fd)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not inspect Git index topology") from exc
    if any(name.startswith("sharedindex.") for name in names):
        raise _base.RecoveryGitError(
            "Split-index Git metadata is not supported by recovery diagnostics"
        )


def _copy_open_regular_fd(fd: int, destination: Path) -> None:
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


def _copy_pinned_regular_fd(
    fd: int,
    observed: os.stat_result,
    destination: Path,
) -> None:
    try:
        copy_fd = os.dup(fd)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not snapshot Git metadata") from exc
    _copy_open_regular_fd(copy_fd, destination)
    try:
        after = os.fstat(fd)
        copied = destination.stat(follow_symlinks=False)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not verify Git metadata snapshot") from exc
    if (
        not _same_regular_snapshot(observed, after)
        or not stat.S_ISREG(copied.st_mode)
        or copied.st_size != observed.st_size
    ):
        raise _base.RecoveryGitError("Git metadata changed during safe snapshot")


def _copy_repository_exclude(metadata_fd: int, destination: Path) -> None:
    info_fd = _open_named_directory(metadata_fd, "info", missing_ok=True)
    if info_fd is None:
        return
    try:
        expected = _stat_child(info_fd, "exclude")
        if expected is None:
            return
        exclude_fd, observed = _impl._open_metadata_child(info_fd, "exclude", expected)
        if not stat.S_ISREG(observed.st_mode):
            os.close(exclude_fd)
            raise _base.RecoveryGitError(
                "Git repository exclude metadata uses an unsupported entry"
            )
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
        raise _base.RecoveryGitError("Could not create Git object-store sandbox") from exc

    for name, expected in _impl._metadata_directory_entries(source_fd):
        child_fd, observed = _impl._open_metadata_child(source_fd, name, expected)
        child_relative = (*relative, name)
        target = destination / name
        if child_relative in {("info", "alternates"), ("info", "http-alternates")}:
            os.close(child_fd)
            raise _base.RecoveryGitError(
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
            raise _base.RecoveryGitError(
                "Git object store contains an unsupported entry"
            )
        if observed.st_nlink != 1:
            os.close(child_fd)
            raise _base.RecoveryGitError(
                "Git object store contains an unsupported hard link"
            )
        if len(pinned_fds) >= _pinned_object_file_budget():
            os.close(child_fd)
            raise _base.RecoveryGitError(
                "Git object store exceeds the safe pinned-file descriptor budget"
            )

        try:
            _copy_pinned_regular_fd(child_fd, observed, target)
        except Exception:
            os.close(child_fd)
            raise
        pinned_fds.append(child_fd)


def _open_object_store_root(git_dir: Path) -> tuple[Path, int, os.stat_result]:
    object_dir = git_dir / "objects"
    try:
        object_fd = _impl._open_metadata_directory(object_dir)
    except _base.RecoveryGitError as exc:
        if "unsafe directory" in str(exc) or "open Git metadata directory" in str(exc):
            raise _base.RecoveryGitError(
                "Redirected Git object stores are not supported by recovery diagnostics"
            ) from exc
        raise
    assert object_fd is not None
    try:
        return object_dir, object_fd, os.fstat(object_fd)
    except Exception:
        os.close(object_fd)
        raise


def _open_object_store_root_fd(
    metadata_fd: int,
) -> tuple[int, os.stat_result]:
    try:
        object_fd = _open_named_directory(metadata_fd, "objects")
    except _base.RecoveryGitError as exc:
        raise _base.RecoveryGitError(
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
    child_fd, observed = _impl._open_metadata_child(directory_fd, name, expected)
    if not stat.S_ISREG(observed.st_mode):
        os.close(child_fd)
        raise _base.RecoveryGitError("Git metadata fingerprint encountered an unsafe entry")
    _impl._fingerprint_open_regular_metadata(digest, label, child_fd, observed)


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
        _impl._fingerprint_metadata_directory(digest, refs_fd, "refs")
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
    sandbox = cast(Any, _impl._ACTIVE_SANDBOX.get())
    if sandbox is not None and getattr(sandbox, "metadata_fd", None) is not None:
        metadata_fd = sandbox.metadata_fd
        assert metadata_fd is not None
        try:
            live = os.lstat(sandbox.root / ".git")
            pinned = os.fstat(metadata_fd)
        except OSError as exc:
            raise _base.RecoveryGitError("Could not revalidate Git metadata root") from exc
        if (
            not stat.S_ISDIR(live.st_mode)
            or stat.S_ISLNK(live.st_mode)
            or (live.st_dev, live.st_ino) != (pinned.st_dev, pinned.st_ino)
        ):
            raise _base.RecoveryGitError(
                "Git repository metadata changed during recovery inspection"
            )
        return _metadata_fingerprint_from_fd(
            metadata_fd,
            object_state=object_state,
        )

    metadata_fd = _impl._open_metadata_directory(git_dir)
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
                raise _base.RecoveryGitError("Git index metadata uses an unsafe entry")
            if index_state.st_nlink != 1:
                raise _base.RecoveryGitError(
                    "Git index metadata uses an unsupported hard link"
                )
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
            raise _base.RecoveryGitError("Could not create Git metadata sandbox") from exc

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
    env = _base._git_environment()
    sandbox = _impl._ACTIVE_SANDBOX.get()
    if sandbox is not None:
        env.update(
            GIT_DIR=str(sandbox.git_dir),
            GIT_WORK_TREE=str(sandbox.root),
            GIT_OBJECT_DIRECTORY=str(sandbox.object_dir),
        )
    return env


def _sandbox_pass_fds() -> tuple[int, ...]:
    sandbox = _impl._ACTIVE_SANDBOX.get()
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
    sandbox = cast(Any, _impl._ACTIVE_SANDBOX.get())
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
        raise _base.RecoveryGitError("Could not verify repository metadata boundary") from exc
    return (metadata_state.st_dev, metadata_state.st_ino) == (
        candidate_state.st_dev,
        candidate_state.st_ino,
    )


def _applicable_ignore_source_parts(
    path: str,
    prefix: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    repo_path = PurePosixPath(_base._repo_path(path, prefix))
    output: list[tuple[str, ...]] = [(".gitignore",)]
    for depth in range(1, len(repo_path.parts)):
        output.append((*repo_path.parts[:depth], ".gitignore"))
    return tuple(output)


def _open_stable_directory(path: Path) -> int:
    try:
        expected = os.lstat(path)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not inspect Git ignore metadata root") from exc
    if not stat.S_ISDIR(expected.st_mode) or stat.S_ISLNK(expected.st_mode):
        raise _base.RecoveryGitError("Git ignore metadata root uses an unsafe entry")
    try:
        fd = os.open(path, _impl._DIRECTORY_FLAGS)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not open Git ignore metadata root safely") from exc
    try:
        observed = os.fstat(fd)
        if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
            raise _base.RecoveryGitError(
                "Git ignore metadata root changed during safe pinning"
            )
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
            child_fd, observed = _impl._open_metadata_child(
                current_fd,
                component,
                expected,
            )
            if not stat.S_ISDIR(observed.st_mode):
                os.close(child_fd)
                raise _base.RecoveryGitError(
                    "Git ignore metadata ancestor uses an unsupported entry"
                )
            os.close(current_fd)
            current_fd = child_fd

        expected = _stat_child(current_fd, parts[-1])
        if expected is None:
            return
        try:
            source_fd, observed = _impl._open_metadata_child(
                current_fd, parts[-1], expected
            )
        except _base.RecoveryGitError as exc:
            raise _base.RecoveryGitError(
                "Git ignore metadata uses an unsupported entry"
            ) from exc
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            os.close(source_fd)
            raise _base.RecoveryGitError(
                "Git ignore metadata uses an unsupported non-regular entry"
            )
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
        raise _base.RecoveryGitError("Could not create Git ignore metadata snapshot") from exc
    destination = Path(temporary.name)
    root_fd: int | None = None
    try:
        root_fd = _open_stable_directory(root)
        sources: set[tuple[str, ...]] = set()
        for path in paths:
            repo_path = PurePosixPath(_base._repo_path(path, prefix))
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
    if isinstance(excluded, _base._ScopeFilter):
        unsafe = tuple(
            path
            for path in paths
            if not _impl._ignore_sources_authorized(path, excluded)
        )
        if unsafe:
            raise _base.RecoveryGitError(
                "Git ignore metadata scope cannot be inspected safely"
            )

    temporary = _snapshot_ignore_worktree(root, paths, prefix)
    shadow_root = Path(temporary.name)
    repo_paths = tuple(f"./{_base._repo_path(path, prefix)}" for path in paths)
    input_bytes = (
        b"\0".join(path.encode("utf-8", errors="surrogateescape") for path in repo_paths)
        + b"\0"
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
        raise _base.RecoveryGitError("Git ignore query exceeded its safe time bound") from exc
    except OSError as exc:
        raise _base.RecoveryGitError("Could not execute Git ignore query safely") from exc
    finally:
        try:
            temporary.cleanup()
        except OSError:
            pass
    if result.returncode not in {0, 1} or result.stderr.strip():
        raise _base.RecoveryGitError("Git ignore query could not be verified safely")
    return _base._filter_paths(
        _base._nul_paths(result.stdout),
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


def _build_report(config: Any, **kwargs: Any) -> Any:
    classification = _impl._ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.get()
    effective_untracked = tuple(kwargs.get("untracked", ()))
    effective_ignored = tuple(kwargs.get("ignored", ()))
    if classification is not None:
        effective_untracked = classification.untracked
        effective_ignored = classification.ignored

    report = _PREVIOUS_BUILD_REPORT(config, **kwargs)
    snapshot = _impl._ACTIVE_WORKTREE_SNAPSHOT.get()
    visible = tuple(sorted(set(effective_untracked) | set(effective_ignored)))
    if snapshot is None or not visible:
        return report

    by_path = snapshot.by_path()
    non_regular = tuple(
        sorted(
            path
            for path in visible
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
        diagnostics.append(item)
    return replace(report, diagnostics=tuple(diagnostics))


def _validate_sandbox_stability(sandbox: _GitMetadataSandbox) -> bool:
    if sandbox.metadata_fd is None:
        raise _base.RecoveryGitError("Git metadata sandbox is missing its pinned root")
    try:
        live = os.lstat(sandbox.root / ".git")
        pinned = os.fstat(sandbox.metadata_fd)
    except OSError as exc:
        raise _base.RecoveryGitError("Could not revalidate Git metadata root") from exc
    if (
        not stat.S_ISDIR(live.st_mode)
        or stat.S_ISLNK(live.st_mode)
        or (live.st_dev, live.st_ino) != (pinned.st_dev, pinned.st_ino)
    ):
        return False

    _reject_split_index_fd(sandbox.metadata_fd)
    return _metadata_fingerprint(sandbox.root / ".git") == sandbox.fingerprint


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

    sandbox_token = _impl._ACTIVE_SANDBOX.set(cast(Any, sandbox))
    config_token = _impl._ACTIVE_CONFIG.set(config)
    snapshot_token = _impl._ACTIVE_WORKTREE_SNAPSHOT.set(None)
    git_token = _impl._ACTIVE_GIT_EXECUTABLE.set(git)
    ignore_token = _impl._ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.set(None)
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
        if not _validate_sandbox_stability(sandbox):
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
        _impl._ACTIVE_VISIBLE_IGNORE_CLASSIFICATION.reset(ignore_token)
        _impl._ACTIVE_GIT_EXECUTABLE.reset(git_token)
        _impl._ACTIVE_WORKTREE_SNAPSHOT.reset(snapshot_token)
        _impl._ACTIVE_CONFIG.reset(config_token)
        _impl._ACTIVE_SANDBOX.reset(sandbox_token)
        sandbox.close()


# Install the bounded fixes into the reviewed implementation module. Its existing
# functions keep their original globals, so updating these names also updates the
# code paths used by collect_recovery_readiness and the base collector.
for _name, _value in {
    "_GitMetadataSandbox": _GitMetadataSandbox,
    "_parse_git_bool": _parse_git_bool,
    "_config_snapshot": _config_snapshot,
    "_metadata_fingerprint": _metadata_fingerprint,
    "_build_sandbox": _build_sandbox,
    "_sandbox_environment": _sandbox_environment,
    "_sandbox_pass_fds": _sandbox_pass_fds,
    "_selects_repository_metadata": _selects_repository_metadata,
    "_ignored_paths": _ignored_paths,
    "_build_report": _build_report,
    "collect_recovery_readiness": collect_recovery_readiness,
}.items():
    # ``_impl`` is itself a compatibility proxy whose ``__setattr__`` forwards
    # names that also exist in ``_base``.  Installing the facade through that
    # hook would replace the base collector with this wrapper and recurse on
    # the first real report.  Update the implementation namespace directly;
    # the explicitly shared base seams are installed just below.
    _impl.__dict__[_name] = _value

setattr(_base, "_ignored_paths", _ignored_paths)
setattr(_base, "_build_report", _build_report)
setattr(_base, "_run_git", _impl._run_git)
setattr(_base, "_run_git_presence", _impl._run_git_presence)


class _RecoveryModuleProxy(types.ModuleType):
    """Keep the historical monkeypatch surface synchronized with the implementation."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if not name.startswith("__") and hasattr(_impl, name):
            _impl.__dict__[name] = value
        # Tests and integrations historically monkeypatch helper seams on this
        # facade.  Keep those base call sites synchronized without ever
        # forwarding the public collector wrapper itself.
        if name != "collect_recovery_readiness" and hasattr(_base, name):
            _base.__dict__[name] = value


_module = _sys.modules[__name__]
if not isinstance(_module, _RecoveryModuleProxy):
    _module.__class__ = _RecoveryModuleProxy
