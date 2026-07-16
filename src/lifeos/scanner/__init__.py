"""Deterministic read-only vault scanner."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ScannerError", "VaultFile", "scan_vault"]

_SUPPORTED_EXTENSIONS = frozenset(
    {
        # Markdown
        ".md",
        # Documents
        ".pdf",
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        # Audio
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".flac",
    }
)

_IGNORED_DIRS = frozenset(
    {
        ".lifeos",
        ".git",
        ".trash",
        "__pycache__",
    }
)


class ScannerError(ValueError):
    """Raised when the scanner cannot read the vault."""


@dataclass(frozen=True, slots=True)
class VaultFile:
    """A supported file found in the vault."""

    path: Path
    file_type: str
    size_bytes: int


def scan_vault(vault_root: str | Path) -> list[VaultFile]:
    """
    Scan the configured vault for supported files without mutating it.

    Returns a deterministically sorted list of VaultFile objects with vault-relative paths.
    """
    root_path = Path(vault_root)

    if not root_path.exists():
        raise ScannerError(f"Vault root does not exist: {root_path}")
    if not root_path.is_dir():
        raise ScannerError(f"Vault root is not a directory: {root_path}")

    found_files: list[VaultFile] = []

    # os.walk does not follow symlinks by default, but we check explicitly to be safe
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        current_dir = Path(dirpath)

        # Determine if current dir is a symlink (should be skipped)
        if current_dir.is_symlink():
            dirnames.clear()
            continue

        # Filter directories in-place to avoid traversing into ignored ones
        dirs_to_keep = []
        for d in dirnames:
            d_path = current_dir / d
            if d_path.is_symlink():
                continue
            if d in _IGNORED_DIRS:
                continue
            dirs_to_keep.append(d)

        dirnames[:] = dirs_to_keep

        for f in filenames:
            file_path = current_dir / f

            # Skip symlinks
            if file_path.is_symlink():
                continue

            # Ignore specific files
            if f == ".DS_Store" or f.endswith(".pyc"):
                continue

            # Ignore transient Obsidian workspace files
            if ".obsidian" in file_path.parts and f.startswith("workspace"):
                continue

            ext = file_path.suffix.lower()
            if ext in _SUPPORTED_EXTENSIONS:
                rel_path = file_path.relative_to(root_path)
                try:
                    size = file_path.stat().st_size
                except OSError:
                    continue

                found_files.append(VaultFile(path=rel_path, file_type=ext, size_bytes=size))

    # Sort deterministically by path
    found_files.sort(key=lambda x: x.path)
    return found_files
