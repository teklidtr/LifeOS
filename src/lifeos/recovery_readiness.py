"""Stable recovery-readiness facade with final Git metadata hardening.

The reviewed implementation lives in ``_recovery_readiness_impl``.  This thin
facade preserves the public/monkeypatch surface while tightening two bounded
trust-boundary details: Git config scalar decoding and object-store descendant
pinning.
"""

from __future__ import annotations

import os
import stat
import sys as _sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lifeos import _recovery_readiness_impl as _impl

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
                raise _impl._base.RecoveryGitError(
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
            raise _impl._base.RecoveryGitError(
                f"Git {key} configuration uses an unsupported escape"
            )
        output.append(char)
        index += 1

    if escaped or quoted:
        raise _impl._base.RecoveryGitError(f"Git {key} configuration is malformed")
    return "".join(output).strip()


def _parse_git_bool(value: str, *, key: str) -> bool:
    folded = _decode_git_config_scalar(value, key=key).casefold()
    if folded in {"", "true", "yes", "on", "1"}:
        return True
    if folded in {"false", "no", "off", "0"}:
        return False
    raise _impl._base.RecoveryGitError(f"Git {key} configuration is malformed")


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
            raise _impl._base.RecoveryGitError(
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
            raise _impl._base.RecoveryGitError(
                "Git core.excludesFile configuration is not supported by recovery diagnostics"
            )
        elif key == "repositoryformatversion":
            scalar = _decode_git_config_scalar(value, key="repositoryformatversion")
            try:
                repository_format = int(scalar or "0")
            except ValueError as exc:
                raise _impl._base.RecoveryGitError("Git repository format is malformed") from exc

    if repository_format != 0 or extensions:
        raise _impl._base.RecoveryGitError(
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
    object_fd: int | None = None
    object_fd_path: str | None = None
    object_fds: tuple[int, ...] = ()

    def close(self) -> None:
        seen: set[int] = set()
        for fd in (self.object_fd, *self.object_fds):
            if fd is None or fd in seen:
                continue
            seen.add(fd)
            try:
                os.close(fd)
            except OSError:
                pass
        self.object_fd = None
        self.object_fds = ()
        try:
            self.temporary.cleanup()
        except OSError:
            pass


def _pinned_regular_fd_path(fd: int, observed: os.stat_result) -> str:
    for root in ("/proc/self/fd", "/dev/fd"):
        candidate = f"{root}/{fd}"
        try:
            candidate_state = os.stat(candidate)
        except OSError:
            continue
        if (
            stat.S_ISREG(candidate_state.st_mode)
            and (candidate_state.st_dev, candidate_state.st_ino)
            == (observed.st_dev, observed.st_ino)
        ):
            return candidate
    raise _impl._base.RecoveryGitError(
        "Platform cannot expose pinned Git object files safely"
    )


def _snapshot_object_directory(
    source_fd: int,
    destination: Path,
    pinned_fds: list[int],
    *,
    relative: tuple[str, ...] = (),
) -> None:
    """Create an object-store pathname view backed only by pinned regular-file FDs."""

    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _impl._base.RecoveryGitError("Could not create Git object-store sandbox") from exc

    for name, expected in _impl._metadata_directory_entries(source_fd):
        child_fd, observed = _impl._open_metadata_child(source_fd, name, expected)
        child_relative = (*relative, name)
        target = destination / name
        if child_relative in {("info", "alternates"), ("info", "http-alternates")}:
            os.close(child_fd)
            raise _impl._base.RecoveryGitError(
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
            raise _impl._base.RecoveryGitError(
                "Git object store contains an unsupported entry"
            )

        try:
            target.symlink_to(_pinned_regular_fd_path(child_fd, observed))
        except OSError as exc:
            os.close(child_fd)
            raise _impl._base.RecoveryGitError(
                "Could not create pinned Git object-store view"
            ) from exc
        pinned_fds.append(child_fd)


def _open_object_store_root(git_dir: Path) -> tuple[Path, int, os.stat_result]:
    object_dir = git_dir / "objects"
    try:
        object_fd = _impl._open_metadata_directory(object_dir)
    except _impl._base.RecoveryGitError as exc:
        if "unsafe directory" in str(exc) or "open Git metadata directory" in str(exc):
            raise _impl._base.RecoveryGitError(
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
    # The object payload/pathname view used by Git is independently pinned in the
    # sandbox. Preserve the reviewed metadata fingerprint for config/index/refs
    # drift and the top-level object-store identity.
    return _ORIGINAL_METADATA_FINGERPRINT(git_dir, object_state=object_state)


def _build_sandbox(vault: Path) -> _GitMetadataSandbox | None:
    discovered = _impl._discover_git_directory(vault)
    if discovered is None:
        return None
    root, git_dir = discovered
    _impl._reject_split_index(git_dir)
    _config_bytes, contains_includes, filemode, ignorecase = _config_snapshot(
        git_dir / "config"
    )
    object_dir, object_fd, object_state = _open_object_store_root(git_dir)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    pinned_object_fds: list[int] = []
    try:
        fingerprint = _metadata_fingerprint(git_dir, object_state=object_state)
        try:
            index_state = os.lstat(git_dir / "index")
        except FileNotFoundError:
            index_mtime_ns = None
        except OSError as exc:
            raise _impl._base.RecoveryGitError("Could not inspect Git index metadata") from exc
        else:
            if stat.S_ISLNK(index_state.st_mode) or not stat.S_ISREG(index_state.st_mode):
                raise _impl._base.RecoveryGitError("Git index metadata uses an unsafe entry")
            if index_state.st_nlink != 1:
                raise _impl._base.RecoveryGitError(
                    "Git index metadata uses an unsupported hard link"
                )
            index_mtime_ns = index_state.st_mtime_ns

        try:
            temporary = tempfile.TemporaryDirectory(prefix="lifeos-doctor-git-")
            fake = Path(temporary.name) / "git"
            fake.mkdir(parents=True)
            for name in ("HEAD", "index", "packed-refs", "shallow"):
                _impl._copy_regular_metadata(git_dir / name, fake / name)
            _impl._copy_metadata_tree(git_dir / "refs", fake / "refs")
            _impl._copy_regular_metadata(
                git_dir / "info" / "exclude",
                fake / "info" / "exclude",
            )
            fake_objects = fake / "objects"
            _snapshot_object_directory(object_fd, fake_objects, pinned_object_fds)
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
            raise _impl._base.RecoveryGitError("Could not create Git metadata sandbox") from exc

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
            str(fake_objects),
            tuple(pinned_object_fds),
        )
    except Exception:
        for fd in pinned_object_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        os.close(object_fd)
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                pass
        raise


def _sandbox_environment() -> dict[str, str]:
    env = _impl._base._git_environment()
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
    for fd in (sandbox.object_fd, *getattr(sandbox, "object_fds", ())):
        if fd is not None and fd not in output:
            output.append(fd)
    return tuple(output)


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
}.items():
    setattr(_impl, _name, _value)


class _RecoveryModuleProxy(types.ModuleType):
    """Keep the historical monkeypatch surface synchronized with the implementation."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if not name.startswith("__") and hasattr(_impl, name):
            setattr(_impl, name, value)


_sys.modules[__name__].__class__ = _RecoveryModuleProxy
