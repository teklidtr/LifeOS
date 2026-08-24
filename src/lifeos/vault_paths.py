"""Symlink-safe, path-only traversal for canonical vault Markdown."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

from lifeos.vault import (
    VaultAccessError,
    _DIRECTORY_FLAGS,
    _EXCLUDED_NAMES,
    _classify_open_error,
    _open_root,
)

PathFilter = Callable[[str], bool]


def _walk_markdown_paths(
    *,
    directory_fd: int,
    relative_parts: tuple[str, ...],
    path_filter: PathFilter | None,
) -> Iterator[str]:
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
                yield from _walk_markdown_paths(
                    directory_fd=child_fd,
                    relative_parts=child_parts,
                    path_filter=path_filter,
                )
            finally:
                os.close(child_fd)
            continue
        if stat.S_ISREG(entry_stat.st_mode) and name.endswith(".md"):
            yield relative


def iter_vault_markdown_paths(
    vault_root: Path,
    *,
    path_filter: PathFilter | None = None,
) -> tuple[str, ...]:
    """Return deterministic Markdown paths without opening or decoding file contents.

    ``path_filter`` is evaluated before ``stat``, directory descent, or file reads. Callers can
    therefore prune protected/excluded subtrees before touching their entries.
    """
    if path_filter is not None and not callable(path_filter):
        raise VaultAccessError(
            "invalid-filter",
            "",
            "path_filter must be callable or None",
        )
    root_fd = _open_root(vault_root)
    try:
        paths = tuple(
            _walk_markdown_paths(
                directory_fd=root_fd,
                relative_parts=(),
                path_filter=path_filter,
            )
        )
    finally:
        os.close(root_fd)
    return tuple(sorted(paths))
