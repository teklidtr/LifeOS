"""Symlink-safe, path-only traversal for canonical vault files."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from lifeos.vault import (
    VaultAccessError,
    _DIRECTORY_FLAGS,
    _EXCLUDED_NAMES,
    _classify_open_error,
    _open_root,
)

PathFilter = Callable[[str], bool]


def _walk_vault_paths(
    *,
    directory_fd: int,
    relative_parts: tuple[str, ...],
    suffixes: frozenset[str],
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
                yield from _walk_vault_paths(
                    directory_fd=child_fd,
                    relative_parts=child_parts,
                    suffixes=suffixes,
                    path_filter=path_filter,
                )
            finally:
                os.close(child_fd)
            continue
        if stat.S_ISREG(entry_stat.st_mode) and any(name.endswith(suffix) for suffix in suffixes):
            yield relative


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
    root_fd = _open_root(vault_root)
    try:
        paths = tuple(
            _walk_vault_paths(
                directory_fd=root_fd,
                relative_parts=(),
                suffixes=normalized,
                path_filter=path_filter,
            )
        )
    finally:
        os.close(root_fd)
    return tuple(sorted(paths))


def iter_vault_markdown_paths(
    vault_root: Path,
    *,
    path_filter: PathFilter | None = None,
) -> tuple[str, ...]:
    """Return deterministic Markdown paths without opening or decoding file contents."""
    return iter_vault_text_paths(
        vault_root,
        suffixes=(".md",),
        path_filter=path_filter,
    )
