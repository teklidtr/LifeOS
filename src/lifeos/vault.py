"""Symlink-safe, descriptor-based reads of canonical vault Markdown."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Iterable, Iterator

_EXCLUDED_NAMES = frozenset({".git", ".lifeos", "__pycache__"})
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


class VaultAccessError(RuntimeError):
    """Raised when canonical vault content cannot be read safely."""

    def __init__(self, code: str, relative_path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.relative_path = relative_path


@dataclass(frozen=True, slots=True)
class VaultMarkdownFile:
    """A safely read canonical Markdown snapshot."""

    relative_path: str
    path: Path
    content: str
    content_bytes: bytes


@dataclass(frozen=True, slots=True)
class VaultFileObservation:
    """One descriptor-stable vault file observation with optional bounded byte capture."""

    content_hash: str
    size_bytes: int
    mtime_ns: int
    captured_bytes: bytes
    capture_complete: bool


def is_markdown_path(relative_path: str) -> bool:
    """Return whether a vault path uses the scanner-supported Markdown extension contract."""
    return isinstance(relative_path, str) and relative_path.casefold().endswith(".md")


def validate_vault_relative_path(relative_path: str) -> str:
    """Validate and return one canonical, portable vault-relative path."""
    if type(relative_path) is not str or not relative_path:
        raise VaultAccessError("invalid-path", "", "Vault path must be a non-empty string")
    if "\\" in relative_path or "\x00" in relative_path:
        raise VaultAccessError("invalid-path", relative_path, "Vault path contains an invalid character")
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or PureWindowsPath(relative_path).drive
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative_path
    ):
        raise VaultAccessError("invalid-path", relative_path, "Vault path must stay within the vault")
    return relative_path


def _safe_relative_path(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(validate_vault_relative_path(relative_path)).parts


def _classify_open_error(exc: OSError, relative_path: str, *, kind: str) -> VaultAccessError:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        return VaultAccessError(
            "unsafe-symlink",
            relative_path,
            f"Unsafe {kind} entry was rejected: {relative_path}",
        )
    if exc.errno == errno.ENOENT:
        return VaultAccessError("not-found", relative_path, f"Vault entry was not found: {relative_path}")
    return VaultAccessError("filesystem-unavailable", relative_path, f"Vault entry could not be read: {relative_path}")


def _open_root(vault_root: Path) -> int:
    if not isinstance(vault_root, Path):
        raise VaultAccessError("invalid-root", "", "vault_root must be a Path")
    try:
        fd = os.open(vault_root, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise _classify_open_error(exc, ".", kind="vault root") from exc
    try:
        root_stat = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise VaultAccessError("filesystem-unavailable", ".", "Vault root could not be inspected") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        os.close(fd)
        raise VaultAccessError("invalid-root", ".", "Vault root is not a directory")
    return fd


def _close_fds(fds: list[int]) -> None:
    for fd in reversed(fds):
        try:
            os.close(fd)
        except OSError:
            pass


def _descriptor_identity(fd: int) -> tuple[int, int]:
    observed = os.fstat(fd)
    return observed.st_dev, observed.st_ino


def _open_file_chain(
    vault_root: Path,
    parts: tuple[str, ...],
    relative_path: str,
) -> tuple[list[int], os.stat_result, tuple[tuple[int, int], ...]]:
    """Open root, parents, and final regular file without following symlinks."""
    opened: list[int] = []
    try:
        root_fd = _open_root(vault_root)
        opened.append(root_fd)
        current_fd = root_fd
        identities = [_descriptor_identity(root_fd)]

        for index, part in enumerate(parts[:-1]):
            current_relative = "/".join(parts[: index + 1])
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as exc:
                raise _classify_open_error(exc, current_relative, kind="directory") from exc
            opened.append(next_fd)
            try:
                next_stat = os.fstat(next_fd)
            except OSError as exc:
                raise VaultAccessError(
                    "filesystem-unavailable",
                    current_relative,
                    f"Vault directory could not be inspected: {current_relative}",
                ) from exc
            if not stat.S_ISDIR(next_stat.st_mode):
                raise VaultAccessError(
                    "unsafe-file-type",
                    current_relative,
                    f"Vault entry is not a directory: {current_relative}",
                )
            identities.append((next_stat.st_dev, next_stat.st_ino))
            current_fd = next_fd

        try:
            file_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=current_fd)
        except OSError as exc:
            raise _classify_open_error(exc, relative_path, kind="file") from exc
        opened.append(file_fd)
        try:
            file_stat = os.fstat(file_fd)
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be inspected: {relative_path}",
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise VaultAccessError(
                "unsafe-file-type",
                relative_path,
                f"Vault entry is not a regular file: {relative_path}",
            )
        identities.append((file_stat.st_dev, file_stat.st_ino))
        return opened, file_stat, tuple(identities)
    except Exception:
        _close_fds(opened)
        raise


def _concurrent_change(relative_path: str) -> VaultAccessError:
    return VaultAccessError(
        "concurrent-change",
        relative_path,
        f"Vault file changed while it was being read: {relative_path}",
    )


def _revalidate_file_chain(
    vault_root: Path,
    parts: tuple[str, ...],
    relative_path: str,
    expected_chain: tuple[tuple[int, int], ...],
) -> None:
    """Prove the current path still names the root/parent/final chain that supplied the bytes."""
    opened: list[int] = []
    try:
        try:
            opened, _file_stat, observed_chain = _open_file_chain(
                vault_root,
                parts,
                relative_path,
            )
        except VaultAccessError as exc:
            raise _concurrent_change(relative_path) from exc
        if observed_chain != expected_chain:
            raise _concurrent_change(relative_path)
    finally:
        _close_fds(opened)


def observe_vault_file(
    vault_root: Path,
    relative_path: str,
    *,
    capture_limit: int | None = None,
) -> VaultFileObservation:
    """Stream one stable vault file while hashing all bytes and optionally retaining a prefix.

    ``capture_limit=None`` retains the complete file. A non-negative integer retains at most that
    many leading bytes while the full file continues to be streamed into the SHA-256 hash. The
    path is re-opened after the read and the complete root/parent/final descriptor identity chain
    must still match before the observation is accepted.
    """
    if capture_limit is not None and (type(capture_limit) is not int or capture_limit < 0):
        raise ValueError("capture_limit must be a non-negative integer or None")

    parts = _safe_relative_path(relative_path)
    opened, before, identity_chain = _open_file_chain(vault_root, parts, relative_path)
    file_fd = opened[-1]
    hasher = hashlib.sha256()
    captured = bytearray()
    total_bytes = 0
    try:
        try:
            while True:
                chunk = os.read(file_fd, 65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                hasher.update(chunk)
                if capture_limit is None:
                    captured.extend(chunk)
                elif len(captured) < capture_limit:
                    captured.extend(chunk[: capture_limit - len(captured)])
            after = os.fstat(file_fd)
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be read: {relative_path}",
            ) from exc

        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_size != after.st_size
            or total_bytes != after.st_size
        ):
            raise _concurrent_change(relative_path)

        _revalidate_file_chain(
            vault_root,
            parts,
            relative_path,
            identity_chain,
        )
        return VaultFileObservation(
            content_hash=hasher.hexdigest(),
            size_bytes=after.st_size,
            mtime_ns=after.st_mtime_ns,
            captured_bytes=bytes(captured),
            capture_complete=capture_limit is None or total_bytes <= capture_limit,
        )
    finally:
        _close_fds(opened)


@contextmanager
def open_vault_file(vault_root: Path, relative_path: str) -> Iterator[BinaryIO]:
    """Yield one descriptor-pinned binary vault file and reject path or byte races."""
    parts = _safe_relative_path(relative_path)
    opened, before, identity_chain = _open_file_chain(vault_root, parts, relative_path)
    duplicate_fd = -1
    try:
        try:
            duplicate_fd = os.dup(opened[-1])
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be opened: {relative_path}",
            ) from exc
        with os.fdopen(duplicate_fd, "rb", closefd=True) as source:
            duplicate_fd = -1
            yield source
        try:
            after = os.fstat(opened[-1])
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be inspected: {relative_path}",
            ) from exc
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_size != after.st_size
        ):
            raise _concurrent_change(relative_path)
        _revalidate_file_chain(vault_root, parts, relative_path, identity_chain)
    finally:
        if duplicate_fd >= 0:
            os.close(duplicate_fd)
        _close_fds(opened)


@contextmanager
def open_or_create_vault_directory(
    vault_root: Path, relative_path: str, *, create_missing: bool = True
) -> Iterator[int]:
    """Yield a vault directory descriptor, optionally creating missing directories safely."""
    parts = _safe_relative_path(relative_path)
    opened: list[int] = []
    try:
        root_fd = _open_root(vault_root)
        opened.append(root_fd)
        current_fd = root_fd
        for index, part in enumerate(parts):
            current_relative = "/".join(parts[: index + 1])
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create_missing:
                    raise VaultAccessError(
                        "not-found",
                        current_relative,
                        f"Vault directory does not exist: {current_relative}",
                    ) from None
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise VaultAccessError(
                        "filesystem-unavailable",
                        current_relative,
                        f"Vault directory could not be created: {current_relative}",
                    ) from exc
                try:
                    next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
                except OSError as exc:
                    raise _classify_open_error(
                        exc,
                        current_relative,
                        kind="directory",
                    ) from exc
            except OSError as exc:
                raise _classify_open_error(
                    exc,
                    current_relative,
                    kind="directory",
                ) from exc
            opened.append(next_fd)
            current_fd = next_fd
        yield current_fd
    finally:
        _close_fds(opened)


def unlink_vault_file(vault_root: Path, relative_path: str, *, missing_ok: bool = False) -> bool:
    """Unlink one regular vault file through a symlink-safe parent descriptor."""
    parts = _safe_relative_path(relative_path)
    opened: list[int] = []
    try:
        try:
            opened, _file_stat, _identity_chain = _open_file_chain(
                vault_root,
                parts,
                relative_path,
            )
        except VaultAccessError as exc:
            if missing_ok and exc.code == "not-found":
                return False
            raise
        try:
            os.unlink(parts[-1], dir_fd=opened[-2])
        except FileNotFoundError:
            if missing_ok:
                return False
            raise VaultAccessError(
                "not-found",
                relative_path,
                f"Vault entry was not found: {relative_path}",
            ) from None
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be deleted: {relative_path}",
            ) from exc
        return True
    finally:
        _close_fds(opened)


def _decode_snapshot(
    *,
    vault_root: Path,
    relative_path: str,
    content_bytes: bytes,
) -> VaultMarkdownFile:
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VaultAccessError(
            "invalid-utf8",
            relative_path,
            f"Vault file is not valid UTF-8: {relative_path}",
        ) from exc
    return VaultMarkdownFile(relative_path, vault_root / relative_path, content, content_bytes)


def read_vault_bytes(vault_root: Path, relative_path: str) -> bytes:
    """Read one vault file as bytes through the stable descriptor observation boundary."""
    return observe_vault_file(vault_root, relative_path).captured_bytes


def read_vault_text(vault_root: Path, relative_path: str) -> VaultMarkdownFile:
    """Read one UTF-8 vault file without following any path-component symlink."""
    return _decode_snapshot(
        vault_root=vault_root,
        relative_path=relative_path,
        content_bytes=read_vault_bytes(vault_root, relative_path),
    )


def read_vault_markdown(vault_root: Path, relative_path: str) -> VaultMarkdownFile:
    """Read one Markdown file without following any path-component symlink."""
    if not is_markdown_path(relative_path):
        raise VaultAccessError("invalid-extension", relative_path, "Vault file must have a .md extension")
    return read_vault_text(vault_root, relative_path)


def _walk_directory(
    *,
    directory_fd: int,
    relative_parts: tuple[str, ...],
    vault_root: Path,
    suffixes: frozenset[str],
) -> Iterator[VaultMarkdownFile]:
    try:
        with os.scandir(directory_fd) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        relative = "/".join(relative_parts) or "."
        raise VaultAccessError(
            "filesystem-unavailable",
            relative,
            f"Vault directory could not be listed: {relative}",
        ) from exc

    for entry in entries:
        name = entry.name
        if name in _EXCLUDED_NAMES or name.startswith("."):
            continue
        child_parts = (*relative_parts, name)
        relative = "/".join(child_parts)
        try:
            entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise _classify_open_error(exc, relative, kind="entry") from exc
        if stat.S_ISLNK(entry_stat.st_mode):
            raise VaultAccessError(
                "unsafe-symlink",
                relative,
                f"Unsafe symlink was rejected: {relative}",
            )
        if stat.S_ISDIR(entry_stat.st_mode):
            try:
                child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            except OSError as exc:
                raise _classify_open_error(exc, relative, kind="directory") from exc
            try:
                yield from _walk_directory(
                    directory_fd=child_fd,
                    relative_parts=child_parts,
                    vault_root=vault_root,
                    suffixes=suffixes,
                )
            finally:
                os.close(child_fd)
            continue
        folded_name = name.casefold()
        if stat.S_ISREG(entry_stat.st_mode) and any(
            folded_name.endswith(suffix.casefold()) for suffix in suffixes
        ):
            yield read_vault_text(vault_root, relative)


def iter_vault_markdown(
    vault_root: Path,
    *,
    roots: Iterable[str] | None = None,
) -> tuple[VaultMarkdownFile, ...]:
    """Return deterministic Markdown snapshots below selected vault roots."""
    root_fd = _open_root(vault_root)
    try:
        if roots is None:
            files = tuple(
                _walk_directory(
                    directory_fd=root_fd,
                    relative_parts=(),
                    vault_root=vault_root,
                    suffixes=frozenset({".md"}),
                )
            )
        else:
            collected: list[VaultMarkdownFile] = []
            for root_name in sorted(set(roots)):
                parts = _safe_relative_path(root_name)
                if len(parts) != 1:
                    raise VaultAccessError("invalid-root", root_name, "Traversal roots must be top-level names")
                try:
                    sub_fd = os.open(root_name, _DIRECTORY_FLAGS, dir_fd=root_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise _classify_open_error(exc, root_name, kind="directory") from exc
                try:
                    collected.extend(
                        _walk_directory(
                            directory_fd=sub_fd,
                            relative_parts=(root_name,),
                            vault_root=vault_root,
                            suffixes=frozenset({".md"}),
                        )
                    )
                finally:
                    os.close(sub_fd)
            files = tuple(collected)
    finally:
        os.close(root_fd)
    return tuple(sorted(files, key=lambda item: item.relative_path))


def iter_vault_text_files(
    vault_root: Path,
    *,
    suffixes: Iterable[str],
) -> tuple[VaultMarkdownFile, ...]:
    """Return deterministic UTF-8 snapshots for an explicit suffix allowlist."""
    normalized = frozenset(suffixes)
    if not normalized or any(
        type(suffix) is not str
        or not suffix.startswith(".")
        or len(suffix) < 2
        or "/" in suffix
        or "\\" in suffix
        or "\x00" in suffix
        for suffix in normalized
    ):
        raise VaultAccessError(
            "invalid-extension",
            "",
            "Vault suffixes must be non-empty file extensions",
        )
    root_fd = _open_root(vault_root)
    try:
        files = tuple(
            _walk_directory(
                directory_fd=root_fd,
                relative_parts=(),
                vault_root=vault_root,
                suffixes=normalized,
            )
        )
    finally:
        os.close(root_fd)
    return tuple(sorted(files, key=lambda item: item.relative_path))
