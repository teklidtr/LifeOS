"""First-party LifeOS vault bootstrap contract."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lifeos.config import ConfigError, load_config

VAULT_ROOTS: tuple[str, ...] = (
    "journal",
    "raw",
    "study",
    "wiki",
    "flashcards",
    "patterns",
    "profile",
    "goals",
    "plans",
    "experiments",
    "metrics",
    "reviews",
    "proposals",
    "system",
)

BOOTSTRAP_FILES: dict[str, str] = {
    ".gitignore": ".lifeos/\n.obsidian/workspace*.json\n.DS_Store\n",
    "AGENTS.md": (
        "# LifeOS Vault Agent Bootstrap\n\n"
        "This directory is a LifeOS vault, not the LifeOS application source repository.\n\n"
        "Use the configured LifeOS MCP server for canonical search, context, proposals, and "
        "consequential mutations. Obtain universal runtime policy from the MCP server and "
        "vault-specific instructions through LifeOS. Folder names provide semantic context; "
        "do not infer permission or a universal ontology from them. Do not directly rewrite "
        "canonical LifeOS artifacts when an MCP/proposal workflow exists.\n"
    ),
    "lifeos.yml": (
        "vault_root: .\n"
        "runtime_dir: .lifeos\n"
        "features:\n"
        "  graphify: false\n"
        "  exports: false\n"
    ),
    "system/generated-ownership.json": (
        json.dumps({"owned_files": {}, "schema_version": 1}, indent=2) + "\n"
    ),
    "system/instructions.yml": "schema_version: 1\ninstructions: []\n",
}


class BootstrapError(RuntimeError):
    """Raised when a vault cannot be initialized safely."""


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Result of a non-destructive vault initialization attempt."""

    vault_root: Path
    created: bool


def is_recognized_vault(root: Path) -> bool:
    """Return whether an existing directory satisfies the current bootstrap shape."""
    git_dir = root / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        return False

    config_path = root / "lifeos.yml"
    if not config_path.is_file() or config_path.is_symlink():
        return False

    for name in VAULT_ROOTS:
        path = root / name
        if not path.is_dir() or path.is_symlink():
            return False

    for relative_path in BOOTSTRAP_FILES:
        path = root / relative_path
        if not path.is_file() or path.is_symlink():
            return False

    try:
        config = load_config(config_path)
    except ConfigError:
        return False

    try:
        resolved_root = root.resolve()
    except OSError:
        return False
    return config.vault_root == resolved_root


def initialize_vault(target: Path) -> BootstrapResult:
    """Create the canonical LifeOS vault skeleton without overwriting existing content."""
    expanded_target = target.expanduser()
    if expanded_target.is_symlink():
        raise BootstrapError(f"Refusing to initialize a symlink target: {expanded_target}")
    root = expanded_target.resolve(strict=False)

    if root.exists() and not root.is_dir():
        raise BootstrapError(f"Initialization target is not a directory: {root}")

    if root.exists():
        if is_recognized_vault(root):
            return BootstrapResult(vault_root=root, created=False)
        try:
            is_empty = next(root.iterdir(), None) is None
        except OSError as error:
            raise BootstrapError(f"Cannot inspect initialization target {root}: {error}") from error
        if not is_empty:
            raise BootstrapError(
                f"Refusing to initialize non-empty directory that is not a recognized LifeOS vault: {root}"
            )

    git_executable = shutil.which("git")
    if git_executable is None:
        raise BootstrapError("Git is required to initialize a LifeOS vault")

    try:
        root.mkdir(parents=True, exist_ok=True)
        for name in VAULT_ROOTS:
            (root / name).mkdir()
        for relative_path, content in BOOTSTRAP_FILES.items():
            (root / relative_path).write_text(content, encoding="utf-8")
        subprocess.run(
            [git_executable, "init", "-q"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        # Do not recursively roll back the target. A concurrent process may have created
        # user content after our initial emptiness check; deleting the directory would make
        # a failed bootstrap destructive. Leave the partial scaffold visible and fail closed
        # on a later rerun so the user can inspect/remove it explicitly.
        raise BootstrapError(f"Failed to initialize LifeOS vault at {root}: {error}") from error

    return BootstrapResult(vault_root=root, created=True)
