"""Git-tracked proposal discovery scanner."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

__all__ = ["GitScannerError", "git_tracked_proposal_paths", "git_tracked_markdown_paths"]


class GitScannerError(RuntimeError):
    """Raised when the git scanner fails or encounters an invalid path."""


_PROPOSAL_PATH_PATTERN = re.compile(r"^proposals/prop-\d{8}T\d{6}Z-[a-f0-9]{8}/proposal\.md$")


def _git_ls_files(vault_root: Path, pathspec: str) -> tuple[Path, ...]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", pathspec],
            cwd=vault_root,
            shell=False,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitScannerError(
            f"Git execution failed with exit code {e.returncode}: {e.stderr.decode(errors='replace')}"
        ) from e
    except OSError as e:
        raise GitScannerError(f"Could not execute git: {e}") from e

    raw_output = result.stdout
    if not raw_output:
        return ()

    raw_paths = [p.decode(errors="replace") for p in raw_output.split(b"\0") if p]
    valid_paths: list[Path] = []

    for raw_path in raw_paths:
        if "\x00" in raw_path or ".." in raw_path.split("/") or raw_path.startswith("/"):
            raise GitScannerError(f"Unsafe path returned by git: {raw_path}")
        valid_paths.append(Path(raw_path))

    return tuple(valid_paths)


def git_tracked_proposal_paths(vault_root: Path) -> tuple[Path, ...]:
    """
    Discover all Git-tracked canonical proposal paths within the vault root.
    Returns a deterministically sorted tuple of vault-relative Path objects.
    """
    valid_paths: list[Path] = []
    for path in _git_ls_files(vault_root, "proposals"):
        if _PROPOSAL_PATH_PATTERN.match(str(path)):
            valid_paths.append(path)
    return tuple(sorted(valid_paths))


def git_tracked_markdown_paths(vault_root: Path) -> tuple[Path, ...]:
    """
    Discover all Git-tracked Markdown files within the vault root.
    Returns a deterministically sorted tuple of vault-relative Path objects.
    """
    valid_paths: list[Path] = []
    for path in _git_ls_files(vault_root, "*.md"):
        if str(path).endswith(".md"):
            valid_paths.append(path)
    return tuple(sorted(valid_paths))
