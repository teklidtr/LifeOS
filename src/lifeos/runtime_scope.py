"""Filesystem-aware matching for configured node-local runtime paths."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from lifeos.coherence import CoherenceError

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _runtime_relative_parts(
    vault_root: Path,
    runtime_dir: Path,
) -> tuple[Path, tuple[str, ...]] | None:
    root = vault_root.resolve(strict=False)
    candidate = runtime_dir if runtime_dir.is_absolute() else root / runtime_dir
    lexical_candidate = Path(os.path.abspath(candidate))
    try:
        relative = lexical_candidate.relative_to(root)
    except ValueError:
        return None
    if relative.as_posix() in {"", "."}:
        raise CoherenceError(
            "Runtime directory overlaps the canonical vault root; runtime scope is unsafe"
        )
    return root, tuple(relative.parts)


def _candidate_parts(path: str) -> tuple[str, ...] | None:
    if not isinstance(path, str) or not path.strip() or "\\" in path or "\x00" in path:
        return None
    pure = PurePosixPath(path.strip())
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return tuple(pure.parts)


def _open_directory_chain(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for component in parts:
            next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def runtime_path_selects_configured_directory(
    vault_root: Path,
    *,
    runtime_dir: Path,
    path: str,
) -> bool:
    """Return whether ``path`` is under the filesystem-selected configured runtime inode.

    This comparison deliberately uses directory descriptors instead of display casing. On a
    case-insensitive filesystem, scanner paths captured as ``runtime/...`` therefore still match a
    configured ``Runtime`` directory even if a case-only rename happens between runtime-prefix
    capture and scanning. On a case-sensitive filesystem, differently cased directories remain
    distinct because they select different inodes.
    """
    resolved = _runtime_relative_parts(vault_root, runtime_dir)
    if resolved is None:
        return False
    root, runtime_parts = resolved
    candidate = _candidate_parts(path)
    if candidate is None or len(candidate) < len(runtime_parts):
        return False
    candidate_runtime_parts = candidate[: len(runtime_parts)]

    root_fd: int | None = None
    runtime_fd: int | None = None
    candidate_fd: int | None = None
    try:
        root_fd = os.open(root, _DIRECTORY_FLAGS)
        try:
            runtime_fd = _open_directory_chain(root_fd, runtime_parts)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise CoherenceError("Could not inspect configured runtime directory") from error
        try:
            candidate_fd = _open_directory_chain(root_fd, candidate_runtime_parts)
        except FileNotFoundError:
            return False
        except OSError:
            return False
        runtime_state = os.fstat(runtime_fd)
        candidate_state = os.fstat(candidate_fd)
        return (runtime_state.st_dev, runtime_state.st_ino) == (
            candidate_state.st_dev,
            candidate_state.st_ino,
        )
    except OSError as error:
        raise CoherenceError("Could not inspect runtime exclusion topology") from error
    finally:
        if candidate_fd is not None:
            os.close(candidate_fd)
        if runtime_fd is not None:
            os.close(runtime_fd)
        if root_fd is not None:
            os.close(root_fd)


def build_runtime_exclusion_matcher(
    vault_root: Path,
    *,
    runtime_dir: Path,
    snapshot_prefix: str | None,
) -> Callable[[str], bool]:
    """Bind one lexical spelling while also matching the live runtime inode.

    The bound string keeps paths captured before a case-only rename excluded. The descriptor
    comparison keeps paths captured after that rename excluded. The predicate therefore expands
    the exclusion boundary instead of replacing one spelling with another during an invocation.
    """
    snapshot_root = snapshot_prefix.rstrip("/") if snapshot_prefix is not None else None

    def excluded(path: str) -> bool:
        candidate = _candidate_parts(path)
        if candidate is None:
            return False
        normalized = PurePosixPath(*candidate).as_posix()
        if snapshot_prefix is not None and (
            normalized == snapshot_root or normalized.startswith(snapshot_prefix)
        ):
            return True
        return runtime_path_selects_configured_directory(
            vault_root,
            runtime_dir=runtime_dir,
            path=normalized,
        )

    return excluded
