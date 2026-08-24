"""Policy-scoped identity snapshots that authorize paths before reading content."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from lifeos.coherence import (
    CoherenceError,
    IdentityDiagnostic,
    IdentitySnapshot,
    STABLE_ID_REQUIRED_ROOTS,
    StableNoteIdentity,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.scanner import ScannerError, scan_vault
from lifeos.vault import VaultAccessError, read_vault_markdown

PathPredicate = Callable[[str], bool]
_IDENTITY_IGNORED_ROOTS = frozenset({"proposals"})


def collect_scoped_identity_snapshot(
    vault_root: Path,
    *,
    allow_path: PathPredicate,
) -> IdentitySnapshot:
    """Build identity facts only after path metadata passes the caller's policy.

    ``scan_vault`` discovers path/type metadata without opening file content. The caller's
    predicate therefore runs before any Markdown bytes are read. Authorized paths are then read
    through the descriptor-based vault reader, which rejects symlink traversal and returns one
    byte snapshot used for both durable identity and content hashing.
    """
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
        if first_root in _IDENTITY_IGNORED_ROOTS or not allow_path(relative_path):
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
