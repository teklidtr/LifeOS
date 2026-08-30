"""Stable recovery-readiness facade with final Git metadata hardening.

The reviewed implementation lives in ``_recovery_readiness_impl``. This thin
facade preserves the public/monkeypatch surface while tightening bounded
trust-boundary details around Git config parsing, metadata-root pinning,
object-store snapshotting, and ignore-source safety.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys as _sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from lifeos import _recovery_readiness_base as _base
from lifeos import _recovery_readiness_impl as _impl
from lifeos._recovery_readiness_impl import (
    RecoveryReport as RecoveryReport,
    collect_recovery_readiness as collect_recovery_readiness,
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


_ORIGINAL_METADATA_FINGERPRINT = _impl_original("_metadata_fingerprint")


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


def _config_snapshot(config_path: Path) -> tuple[bytes, bool, bool, bool]:
    raw = _impl._read_small_metadata(config_path)
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
        # The temporary path is rooted through metadata_fd, so clean it before
        # closing that descriptor. Object descriptors are bounded to the root.
        try:
            self.temporary.cleanup()
        except OSError:
            pass
        seen: set[int] = set()
        for fd in (self.object_fd, *self.object_fds, self.metadata_fd):
            if fd is None or fd in seen:
                continue
            seen.add(fd)
            try:
                os.close(fd)
            except OSError:
                pass
        self.object_fd = None
        self.object_fds = ()
        self.metadata_fd = None


def _discover_pinned_git_directory(
    vault: Path,
) -> tuple[Path, Path, int, os.stat_result, str] | None:
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
            pinned_path = _impl._pinned_fd_path(metadata_fd, observed)
            return root, marker, metadata_fd, observed, pinned_path
        except Exception:
            os.close(metadata_fd)
            raise
    return None


def _snapshot_object_directory(
    source_fd: int,
    destination: Path,
    *,
    relative: tuple[str, ...] = (),
) -> None:
    """Create a path-stable object-store snapshot with bounded descriptors."""

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
                _snapshot_object_directory(child_fd, target, relative=child_relative)
            finally:
                os.close(child_fd)
            continue

        if not stat.S_ISREG(observed.st_mode):
            os.close(child_fd)
            raise _base.RecoveryGitError(
                "Git object store contains an unsupported entry"
            )

        try:
            # Link by name relative to the pinned parent, then verify the linked
            # inode is the one already opened. This closes the path-swap race
            # without keeping one descriptor open for every loose/pack object.
            os.link(
                name,
                target,
                src_dir_fd=source_fd,
                follow_symlinks=False,
            )
            linked = os.stat(target, follow_symlinks=False)
            if (
                not stat.S_ISREG(linked.st_mode)
                or (linked.st_dev, linked.st_ino) != (observed.st_dev, observed.st_ino)
            ):
                try:
                    target.unlink()
                except OSError:
                    pass
                raise _base.RecoveryGitError(
                    "Git object store changed during bounded snapshot creation"
                )
        except _base.RecoveryGitError:
            raise
        except OSError as exc:
            raise _base.RecoveryGitError(
                "Could not create bounded Git object-store snapshot"
            ) from exc
        finally:
            os.close(child_fd)


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


def _metadata_fingerprint(
    git_dir: Path,
    *,
    object_state: os.stat_result | None = None,
) -> str:
    sandbox = cast(Any, _impl._ACTIVE_SANDBOX.get())
    if sandbox is not None and getattr(sandbox, "metadata_fd", None) is not None:
        metadata_fd = sandbox.metadata_fd
        metadata_fd_path = sandbox.metadata_fd_path
        assert metadata_fd is not None and metadata_fd_path is not None
        try:
            live = os.lstat(git_dir)
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
        git_dir = Path(metadata_fd_path)
    return cast(str, _ORIGINAL_METADATA_FINGERPRINT(git_dir, object_state=object_state))


def _temporary_object_snapshot(
    root: Path,
    metadata_fd_path: str,
    object_state: os.stat_result,
) -> tempfile.TemporaryDirectory[str]:
    """Create a temporary directory on the object store filesystem when possible."""

    candidate_dirs: tuple[str | None, ...] = (
        None,
        str(root.parent),
        metadata_fd_path,
    )
    last_error: OSError | None = None
    for directory in candidate_dirs:
        try:
            if directory is None:
                temporary = tempfile.TemporaryDirectory(
                    prefix="lifeos-doctor-snapshot-"
                )
            else:
                temporary = tempfile.TemporaryDirectory(
                    prefix="lifeos-doctor-snapshot-",
                    dir=directory,
                )
        except OSError as exc:
            last_error = exc
            continue
        try:
            observed = os.stat(temporary.name)
        except OSError as exc:
            last_error = exc
            try:
                temporary.cleanup()
            except OSError:
                pass
            continue
        if observed.st_dev == object_state.st_dev:
            return temporary
        try:
            temporary.cleanup()
        except OSError:
            pass
    if last_error is not None:
        raise last_error
    raise OSError("no temporary directory is available on the Git object-store filesystem")


def _build_sandbox(vault: Path) -> _GitMetadataSandbox | None:
    discovered = _discover_pinned_git_directory(vault)
    if discovered is None:
        return None
    root, git_dir, metadata_fd, _metadata_state, metadata_fd_path = discovered
    pinned_git_dir = Path(metadata_fd_path)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    object_fd: int | None = None
    try:
        _impl._reject_split_index(pinned_git_dir)
        _config_bytes, contains_includes, filemode, ignorecase = _config_snapshot(
            pinned_git_dir / "config"
        )
        _object_dir, object_fd, object_state = _open_object_store_root(pinned_git_dir)
        fingerprint = _metadata_fingerprint(pinned_git_dir, object_state=object_state)

        try:
            index_state = os.lstat(pinned_git_dir / "index")
        except FileNotFoundError:
            index_mtime_ns = None
        except OSError as exc:
            raise _base.RecoveryGitError("Could not inspect Git index metadata") from exc
        else:
            if stat.S_ISLNK(index_state.st_mode) or not stat.S_ISREG(index_state.st_mode):
                raise _base.RecoveryGitError("Git index metadata uses an unsafe entry")
            if index_state.st_nlink != 1:
                raise _base.RecoveryGitError(
                    "Git index metadata uses an unsupported hard link"
                )
            index_mtime_ns = index_state.st_mtime_ns

        try:
            temporary = _temporary_object_snapshot(
                root,
                metadata_fd_path,
                object_state,
            )
            fake = Path(temporary.name) / "git"
            fake.mkdir(parents=True)
            for name in ("HEAD", "index", "packed-refs", "shallow"):
                _impl._copy_regular_metadata(pinned_git_dir / name, fake / name)
            _impl._copy_metadata_tree(pinned_git_dir / "refs", fake / "refs")
            _impl._copy_regular_metadata(
                pinned_git_dir / "info" / "exclude",
                fake / "info" / "exclude",
            )
            fake_objects = fake / "objects"
            _snapshot_object_directory(object_fd, fake_objects)
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
            (object_fd,),
        )
    except Exception:
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
            GIT_OBJECT_DIRECTORY=sandbox.object_fd_path or str(sandbox.object_dir),
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


def _applicable_ignore_sources(
    root: Path,
    path: str,
    prefix: tuple[str, ...],
) -> tuple[Path, ...]:
    repo_path = PurePosixPath(_base._repo_path(path, prefix))
    output = [root / ".gitignore"]
    for depth in range(1, len(repo_path.parts)):
        output.append(root.joinpath(*repo_path.parts[:depth], ".gitignore"))
    return tuple(output)


def _validate_ignore_sources(root: Path, paths: Any, prefix: tuple[str, ...]) -> None:
    seen: set[Path] = set()
    for path in paths:
        for source in _applicable_ignore_sources(root, path, prefix):
            if source in seen:
                continue
            seen.add(source)
            try:
                observed = os.lstat(source)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise _base.RecoveryGitError("Could not inspect Git ignore metadata") from exc
            if (
                stat.S_ISLNK(observed.st_mode)
                or not stat.S_ISREG(observed.st_mode)
                or observed.st_nlink != 1
            ):
                raise _base.RecoveryGitError(
                    "Git ignore metadata uses an unsupported non-regular entry"
                )


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
    _validate_ignore_sources(root, paths, prefix)
    repo_paths = tuple(f"./{_base._repo_path(path, prefix)}" for path in paths)
    input_bytes = (
        b"\0".join(path.encode("utf-8", errors="surrogateescape") for path in repo_paths)
        + b"\0"
    )
    try:
        result = subprocess.run(
            [
                git,
                "--no-literal-pathspecs",
                "-c",
                f"core.excludesFile={os.devnull}",
                "check-ignore",
                "--stdin",
                "-z",
            ],
            cwd=root,
            shell=False,
            check=False,
            capture_output=True,
            env=_sandbox_environment(),
            input=input_bytes,
            pass_fds=_sandbox_pass_fds(),
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise _base.RecoveryGitError("Git ignore query exceeded its safe time bound") from exc
    except OSError as exc:
        raise _base.RecoveryGitError("Could not execute Git ignore query safely") from exc
    if result.returncode not in {0, 1} or result.stderr.strip():
        raise _base.RecoveryGitError("Git ignore query could not be verified safely")
    return _base._filter_paths(
        _base._nul_paths(result.stdout),
        prefix,
        excluded,
        case_insensitive_prefix=case_insensitive_prefix,
    )


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
}.items():
    setattr(_impl, _name, _value)

setattr(_base, "_ignored_paths", _ignored_paths)


class _RecoveryModuleProxy(types.ModuleType):
    """Keep the historical monkeypatch surface synchronized with the implementation."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if not name.startswith("__") and hasattr(_impl, name):
            setattr(_impl, name, value)


_sys.modules[__name__].__class__ = _RecoveryModuleProxy
