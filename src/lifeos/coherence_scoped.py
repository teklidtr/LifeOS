"""Policy-scoped identity snapshots that authorize paths before reading content."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path

from lifeos.coherence import (
    CoherenceError,
    IdentityDiagnostic,
    IdentitySnapshot,
    STABLE_ID_REQUIRED_ROOTS,
    StableNoteIdentity,
)
from lifeos.config import ConfigError, load_config
from lifeos.markdown.parser import parse_markdown_note
from lifeos.scanner import ScannerError, scan_vault
from lifeos.vault import VaultAccessError, read_vault_markdown

PathPredicate = Callable[[str], bool]
_IDENTITY_IGNORED_ROOTS = frozenset({"proposals"})
_IDENTITY_IGNORED_PATHS = frozenset({"AGENTS.md"})
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _opened_component_spelling(parent_fd: int, child_fd: int, requested: str) -> str:
    """Return the directory-entry spelling for an already-opened child inode."""
    child = os.fstat(child_fd)
    try:
        with os.scandir(parent_fd) as entries:
            for entry in entries:
                try:
                    observed = os.stat(entry.name, dir_fd=parent_fd, follow_symlinks=False)
                except OSError:
                    continue
                if (observed.st_dev, observed.st_ino) == (child.st_dev, child.st_ino):
                    return entry.name
    except OSError as exc:
        raise CoherenceError("Could not inspect runtime directory spelling") from exc
    return requested


def _existing_runtime_spelling(root: Path, relative: Path) -> str | None:
    """Use filesystem-resolved component spelling without weakening case-sensitive filesystems."""
    root_fd: int | None = None
    current_fd: int | None = None
    try:
        root_fd = os.open(root, _DIRECTORY_FLAGS)
        current_fd = root_fd
        actual_parts: list[str] = []
        for requested in relative.parts:
            try:
                child_fd = os.open(requested, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                return None
            except OSError as exc:
                if exc.errno in (getattr(os, "ELOOP", 40),):
                    return None
                return None
            actual_parts.append(_opened_component_spelling(current_fd, child_fd, requested))
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        return Path(*actual_parts).as_posix()
    except OSError as exc:
        raise CoherenceError("Could not inspect configured runtime directory") from exc
    finally:
        if current_fd is not None and current_fd != root_fd:
            os.close(current_fd)
        if root_fd is not None:
            os.close(root_fd)


def runtime_exclusion_prefix(
    vault_root: Path,
    *,
    runtime_dir: Path | None,
) -> str | None:
    """Return the configured in-vault runtime prefix without opening runtime content.

    The lexical configured path remains authoritative when the runtime does not yet exist or is
    unsafe to traverse. When it does exist, the returned prefix uses the directory entry spelling
    actually selected by the filesystem. This preserves case-sensitive semantics on Linux while
    preventing a differently-cased configured path from missing the same directory on a
    case-insensitive filesystem.
    """
    root = vault_root.resolve(strict=False)
    candidate = runtime_dir
    if candidate is None:
        config_path = root / "lifeos.yml"
        if config_path.exists():
            try:
                candidate = load_config(config_path).runtime_dir
            except ConfigError as exc:
                raise CoherenceError("Could not resolve configured runtime directory") from exc
        else:
            candidate = root / ".lifeos"
    elif not candidate.is_absolute():
        candidate = root / candidate

    lexical_candidate = Path(os.path.abspath(candidate))
    try:
        lexical_relative_path = lexical_candidate.relative_to(root)
        lexical_relative = lexical_relative_path.as_posix()
    except ValueError:
        lexical_relative_path = None
        lexical_relative = None

    if lexical_relative in {"", "."}:
        raise CoherenceError(
            "Runtime directory overlaps the canonical vault root; identity traversal is unsafe"
        )
    if lexical_relative_path is not None:
        actual_relative = _existing_runtime_spelling(root, lexical_relative_path)
        effective = actual_relative or lexical_relative
        return effective.rstrip("/") + "/"

    try:
        resolved = candidate.resolve(strict=False)
        relative = resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError) as exc:
        raise CoherenceError("Could not resolve runtime directory for identity traversal") from exc
    except ValueError:
        return None

    if relative in {"", "."}:
        raise CoherenceError(
            "Runtime directory overlaps the canonical vault root; identity traversal is unsafe"
        )
    return relative.rstrip("/") + "/"


# Compatibility alias for tests or internal callers that used the helper before it became the
# shared runtime-scope primitive for coherence-aware traversals.
_runtime_exclusion_prefix = runtime_exclusion_prefix


def collect_scoped_identity_snapshot(
    vault_root: Path,
    *,
    allow_path: PathPredicate,
    runtime_dir: Path | None = None,
) -> IdentitySnapshot:
    """Build identity facts only after path metadata passes the caller's policy.

    ``scan_vault`` discovers path/type metadata without opening file content. The caller's
    predicate therefore runs before any Markdown bytes are read. The configured runtime
    directory is also excluded before content access so disposable exports or indexes cannot
    participate in canonical identity. Vault bootstrap instructions such as root ``AGENTS.md``
    are control metadata rather than user notes and do not participate in note identity.
    Authorized paths are then read through the descriptor-based vault reader, which rejects
    symlink traversal and returns one byte snapshot used for both durable identity and content
    hashing.
    """
    runtime_prefix = runtime_exclusion_prefix(vault_root, runtime_dir=runtime_dir)
    try:
        entries = scan_vault(vault_root)
    except ScannerError as exc:
        raise CoherenceError(str(exc)) from exc

    notes: list[StableNoteIdentity] = []
    diagnostics: list[IdentityDiagnostic] = []
    by_id: dict[str, list[str]] = {}

    for entry in entries:
        if entry.file_type != ".md":
            continue
        relative_path = entry.path.as_posix()
        first_root = relative_path.split("/", 1)[0]
        if first_root in _IDENTITY_IGNORED_ROOTS:
            continue
        if relative_path in _IDENTITY_IGNORED_PATHS:
            continue
        if runtime_prefix is not None and relative_path.startswith(runtime_prefix):
            continue
        if not allow_path(relative_path):
            continue

        try:
            source = read_vault_markdown(vault_root, relative_path)
        except VaultAccessError as exc:
            raise CoherenceError(str(exc)) from exc
        parsed = parse_markdown_note(source.path, content=source.content)
        stable_id = parsed.durable_fields.id
        if stable_id is not None:
            stable_id = stable_id.strip() or None

        note = StableNoteIdentity(
            stable_id=stable_id,
            path=relative_path,
            content_hash=f"sha256:{hashlib.sha256(source.content_bytes).hexdigest()}",
            note_type=parsed.durable_fields.type,
            relocation_safe=stable_id is not None,
        )
        notes.append(note)
        if stable_id is not None:
            by_id.setdefault(stable_id, []).append(relative_path)
        elif first_root in STABLE_ID_REQUIRED_ROOTS:
            diagnostics.append(
                IdentityDiagnostic(
                    severity="warning",
                    code="stable-id-missing",
                    detail=(
                        "Legacy wiki note has no stable frontmatter id; it remains path-addressable "
                        "but rename/move continuity cannot be proven until an id is assigned."
                    ),
                    path=relative_path,
                )
            )

    for stable_id, paths in sorted(by_id.items()):
        if len(paths) <= 1:
            continue
        diagnostics.append(
            IdentityDiagnostic(
                severity="blocked",
                code="stable-id-ambiguous",
                detail=(
                    "Stable note id resolves to multiple policy-visible canonical paths: "
                    + ", ".join(sorted(paths))
                ),
                stable_id=stable_id,
            )
        )

    notes.sort(key=lambda item: item.path)
    diagnostics.sort(key=lambda item: (item.severity, item.code, item.path or "", item.stable_id or ""))
    return IdentitySnapshot(tuple(notes), tuple(diagnostics))
