"""Symlink-safe, path-only traversal for canonical vault files."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lifeos.vault import (
    VaultAccessError,
    _DIRECTORY_FLAGS,
    _EXCLUDED_NAMES,
    _classify_open_error,
    _open_root,
)

PathFilter = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class VaultPathMetadata:
    """Content-free filesystem identity for one safely discovered vault file."""

    relative_path: str
    size_bytes: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int


def _walk_vault_metadata(
    *,
    directory_fd: int,
    relative_parts: tuple[str, ...],
    suffixes: frozenset[str],
    path_filter: PathFilter | None,
) -> Iterator[VaultPathMetadata]:
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
        if path_filter is not None and not path_filter(relative):
            continue
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
                yield from _walk_vault_metadata(
                    directory_fd=child_fd,
                    relative_parts=child_parts,
                    suffixes=suffixes,
                    path_filter=path_filter,
                )
            finally:
                os.close(child_fd)
            continue
        folded_name = name.casefold()
        if stat.S_ISREG(entry_stat.st_mode) and any(
            folded_name.endswith(suffix.casefold()) for suffix in suffixes
        ):
            yield VaultPathMetadata(
                relative_path=relative,
                size_bytes=entry_stat.st_size,
                mtime_ns=entry_stat.st_mtime_ns,
                ctime_ns=entry_stat.st_ctime_ns,
                device=entry_stat.st_dev,
                inode=entry_stat.st_ino,
            )


def _validate_traversal_args(
    *, suffixes: Iterable[str], path_filter: PathFilter | None
) -> frozenset[str]:
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
    if path_filter is not None and not callable(path_filter):
        raise VaultAccessError(
            "invalid-filter",
            "",
            "path_filter must be callable or None",
        )
    return normalized


def iter_vault_text_metadata(
    vault_root: Path,
    *,
    suffixes: Iterable[str],
    path_filter: PathFilter | None = None,
) -> tuple[VaultPathMetadata, ...]:
    """Return deterministic file metadata without opening or decoding file contents.

    ``path_filter`` is evaluated before ``stat``, directory descent, or file reads. Callers can
    therefore prune protected/excluded subtrees before touching their entries. Metadata includes
    path, size, timestamps, device, and inode so callers can cheaply detect ordinary source-set
    changes while reserving byte reads for explicitly selected files.
    """
    normalized = _validate_traversal_args(suffixes=suffixes, path_filter=path_filter)
    root_fd = _open_root(vault_root)
    try:
        metadata = tuple(
            _walk_vault_metadata(
                directory_fd=root_fd,
                relative_parts=(),
                suffixes=normalized,
                path_filter=path_filter,
            )
        )
    finally:
        os.close(root_fd)
    return tuple(sorted(metadata, key=lambda item: item.relative_path))


def iter_vault_text_paths(
    vault_root: Path,
    *,
    suffixes: Iterable[str],
    path_filter: PathFilter | None = None,
) -> tuple[str, ...]:
    """Return deterministic matching vault paths without opening or decoding file contents.

    ``path_filter`` is evaluated before ``stat``, directory descent, or file reads. Callers can
    therefore prune protected/excluded subtrees before touching their entries.
    """
    return tuple(
        item.relative_path
        for item in iter_vault_text_metadata(
            vault_root,
            suffixes=suffixes,
            path_filter=path_filter,
        )
    )


def iter_vault_markdown_metadata(
    vault_root: Path,
    *,
    path_filter: PathFilter | None = None,
) -> tuple[VaultPathMetadata, ...]:
    """Return deterministic Markdown metadata without opening or decoding file contents."""
    return iter_vault_text_metadata(
        vault_root,
        suffixes=(".md",),
        path_filter=path_filter,
    )


def iter_vault_markdown_paths(
    vault_root: Path,
    *,
    path_filter: PathFilter | None = None,
) -> tuple[str, ...]:
    """Return deterministic Markdown paths without opening or decoding file contents."""
    return tuple(
        item.relative_path
        for item in iter_vault_markdown_metadata(
            vault_root,
            path_filter=path_filter,
        )
    )
