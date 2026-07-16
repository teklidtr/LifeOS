"""Symlink-safe, descriptor-based reads of canonical vault Markdown."""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator

_EXCLUDED_NAMES = frozenset({".git", ".lifeos", "__pycache__"})
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


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


def _safe_relative_path(relative_path: str) -> tuple[str, ...]:
    if type(relative_path) is not str or not relative_path:
        raise VaultAccessError("invalid-path", "", "Vault path must be a non-empty string")
    if "\\" in relative_path or "\x00" in relative_path:
        raise VaultAccessError("invalid-path", relative_path, "Vault path contains an invalid character")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise VaultAccessError("invalid-path", relative_path, "Vault path must stay within the vault")
    return pure.parts


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


def _read_all(fd: int, relative_path: str) -> bytes:
    chunks: list[bytes] = []
    try:
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as exc:
        raise VaultAccessError(
            "filesystem-unavailable",
            relative_path,
            f"Vault file could not be read: {relative_path}",
        ) from exc
    return b"".join(chunks)


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


def _read_file_at(parent_fd: int, name: str, relative_path: str, vault_root: Path) -> VaultMarkdownFile:
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise _classify_open_error(exc, relative_path, kind="file") from exc
    try:
        try:
            before = os.fstat(fd)
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be inspected: {relative_path}",
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            raise VaultAccessError(
                "unsafe-file-type",
                relative_path,
                f"Vault entry is not a regular file: {relative_path}",
            )
        content_bytes = _read_all(fd, relative_path)
        try:
            after = os.fstat(fd)
        except OSError as exc:
            raise VaultAccessError(
                "filesystem-unavailable",
                relative_path,
                f"Vault file could not be inspected after reading: {relative_path}",
            ) from exc
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or len(content_bytes) != after.st_size
        ):
            raise VaultAccessError(
                "concurrent-change",
                relative_path,
                f"Vault file changed while it was being read: {relative_path}",
            )
    finally:
        os.close(fd)
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VaultAccessError(
            "invalid-utf8",
            relative_path,
            f"Vault file is not valid UTF-8: {relative_path}",
        ) from exc
    return VaultMarkdownFile(relative_path, vault_root / relative_path, content, content_bytes)


def read_vault_text(vault_root: Path, relative_path: str) -> VaultMarkdownFile:
    """Read one UTF-8 vault file without following any path-component symlink."""
    parts = _safe_relative_path(relative_path)
    root_fd = _open_root(vault_root)
    current_fd = root_fd
    try:
        for index, part in enumerate(parts[:-1]):
            current_relative = "/".join(parts[: index + 1])
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as exc:
                raise _classify_open_error(exc, current_relative, kind="directory") from exc
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise VaultAccessError(
                        "unsafe-file-type",
                        current_relative,
                        f"Vault entry is not a directory: {current_relative}",
                    )
            except OSError as exc:
                os.close(next_fd)
                raise VaultAccessError(
                    "filesystem-unavailable",
                    current_relative,
                    f"Vault directory could not be inspected: {current_relative}",
                ) from exc
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        return _read_file_at(current_fd, parts[-1], relative_path, vault_root)
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def read_vault_markdown(vault_root: Path, relative_path: str) -> VaultMarkdownFile:
    """Read one Markdown file without following any path-component symlink."""
    if not relative_path.endswith(".md"):
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
        if stat.S_ISREG(entry_stat.st_mode) and any(name.endswith(suffix) for suffix in suffixes):
            yield _read_file_at(directory_fd, name, relative, vault_root)


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
