"""Provider-neutral cross-device vault identity and coherence contracts."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from lifeos.config import LifeOSConfig
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

WriterModel = Literal["single-active-lifeos-writer"]
RuntimeLocation = Literal["inside-canonical-vault", "node-local-outside-vault"]
IdentitySeverity = Literal["warning", "blocked"]
TargetResolutionState = Literal[
    "current",
    "relocated-draft-rebase-required",
    "relocated-review-required",
    "stale-content",
    "missing",
    "ambiguous",
    "identity-changed",
]

WRITER_MODEL: WriterModel = "single-active-lifeos-writer"
STABLE_ID_REQUIRED_ROOTS = frozenset({"wiki"})
_IDENTITY_IGNORED_ROOTS = frozenset({"proposals"})


class CoherenceError(RuntimeError):
    """Raised when a vault identity or topology invariant cannot be proven."""


@dataclass(frozen=True, slots=True)
class VaultTopology:
    """Resolved operator-facing topology facts without owning sync transport."""

    canonical_vault_root: str
    runtime_dir: str
    runtime_location: RuntimeLocation
    writer_model: WriterModel
    canonical_state: tuple[str, ...]
    node_local_state: tuple[str, ...]
    required_sync_exclusions: tuple[str, ...]
    sync_transport_owner: str = "external"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdentityDiagnostic:
    severity: IdentitySeverity
    code: str
    detail: str
    path: str | None = None
    stable_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StableNoteIdentity:
    """One canonical Markdown note identity at one observed content version."""

    stable_id: str | None
    path: str
    content_hash: str
    note_type: str | None
    relocation_safe: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdentitySnapshot:
    """Disposable view rebuilt from canonical Markdown."""

    notes: tuple[StableNoteIdentity, ...]
    diagnostics: tuple[IdentityDiagnostic, ...]

    @property
    def healthy(self) -> bool:
        return not any(item.severity == "blocked" for item in self.diagnostics)

    def by_path(self, path: str) -> StableNoteIdentity | None:
        return next((item for item in self.notes if item.path == path), None)

    def by_stable_id(self, stable_id: str) -> tuple[StableNoteIdentity, ...]:
        return tuple(item for item in self.notes if item.stable_id == stable_id)


@dataclass(frozen=True, slots=True)
class TargetResolution:
    """Conservative proposal-target assessment after manual/synchronized changes."""

    state: TargetResolutionState
    reviewed_path: str
    current_path: str | None
    stable_id: str | None
    reviewed_base_hash: str
    current_content_hash: str | None
    may_apply_without_new_review: bool
    draft_rebase_allowed: bool
    requires_path_revalidation: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def describe_topology(config: LifeOSConfig) -> VaultTopology:
    """Describe canonical versus node-local state for the configured LifeOS node."""
    vault_root = config.vault_root.resolve(strict=False)
    runtime_dir = config.runtime_dir.resolve(strict=False)
    try:
        runtime_dir.relative_to(vault_root)
    except ValueError:
        location: RuntimeLocation = "node-local-outside-vault"
    else:
        location = "inside-canonical-vault"

    return VaultTopology(
        canonical_vault_root=str(vault_root),
        runtime_dir=str(runtime_dir),
        runtime_location=location,
        writer_model=WRITER_MODEL,
        canonical_state=(
            "Markdown vault content",
            "Git history on the active LifeOS node",
            "proposal review/history artifacts",
            "generated ownership and provenance artifacts",
        ),
        node_local_state=(
            "registry",
            "retrieval indexes",
            "embeddings",
            "runtime activity",
            "temporary/rebuild state",
        ),
        required_sync_exclusions=(".lifeos/", ".git/", ".obsidian/workspace*.json"),
    )


def collect_identity_snapshot(vault_root: Path) -> IdentitySnapshot:
    """Rebuild stable-id/path/hash facts directly from canonical Markdown.

    Frontmatter ``id`` is relocation-safe identity. Notes without an ID remain usable via
    their path but cannot be automatically followed across a rename. Wiki notes without an
    ID therefore produce a migration warning rather than silently treating the path as a
    permanent identity.
    """
    notes: list[StableNoteIdentity] = []
    diagnostics: list[IdentityDiagnostic] = []
    by_id: dict[str, list[str]] = {}

    try:
        sources = iter_vault_markdown(vault_root)
    except VaultAccessError as exc:
        raise CoherenceError(str(exc)) from exc

    for source in sources:
        first_root = source.relative_path.split("/", 1)[0]
        if first_root in _IDENTITY_IGNORED_ROOTS:
            continue
        parsed = parse_markdown_note(source.path, content=source.content)
        stable_id = parsed.durable_fields.id
        if stable_id is not None:
            stable_id = stable_id.strip()
            if not stable_id:
                stable_id = None
        content_hash = _prefixed_hash(source.content_bytes)
        note = StableNoteIdentity(
            stable_id=stable_id,
            path=source.relative_path,
            content_hash=content_hash,
            note_type=parsed.durable_fields.type,
            relocation_safe=stable_id is not None,
        )
        notes.append(note)
        if stable_id is not None:
            by_id.setdefault(stable_id, []).append(source.relative_path)
        elif first_root in STABLE_ID_REQUIRED_ROOTS:
            diagnostics.append(
                IdentityDiagnostic(
                    severity="warning",
                    code="stable-id-missing",
                    detail=(
                        "Legacy wiki note has no stable frontmatter id; it remains path-addressable "
                        "but rename/move continuity cannot be proven until an id is assigned."
                    ),
                    path=source.relative_path,
                )
            )

    for stable_id, paths in sorted(by_id.items()):
        if len(paths) <= 1:
            continue
        joined = ", ".join(sorted(paths))
        diagnostics.append(
            IdentityDiagnostic(
                severity="blocked",
                code="stable-id-ambiguous",
                detail=f"Stable note id resolves to multiple canonical paths: {joined}",
                stable_id=stable_id,
            )
        )

    notes.sort(key=lambda item: item.path)
    diagnostics.sort(key=lambda item: (item.severity, item.code, item.path or "", item.stable_id or ""))
    return IdentitySnapshot(tuple(notes), tuple(diagnostics))


def resolve_stable_note(snapshot: IdentitySnapshot, stable_id: str) -> StableNoteIdentity:
    """Resolve exactly one current note for a durable identity or fail closed."""
    if not stable_id.strip():
        raise CoherenceError("stable_id must be non-empty")
    matches = snapshot.by_stable_id(stable_id)
    if not matches:
        raise CoherenceError(f"Stable note id {stable_id!r} is missing from the current vault view")
    if len(matches) != 1:
        paths = ", ".join(item.path for item in matches)
        raise CoherenceError(f"Stable note id {stable_id!r} is ambiguous: {paths}")
    return matches[0]


def assess_proposal_target(
    snapshot: IdentitySnapshot,
    *,
    reviewed_path: str,
    reviewed_base_hash: str,
    stable_id: str | None,
    proposal_status: str,
) -> TargetResolution:
    """Assess an existing proposal target without weakening review or hash checks.

    A relocated draft may be deterministically rebased by a higher-level proposal workflow,
    which must regenerate its review snapshot. Pending/approved proposals never silently
    retarget: they require renewed review even when stable identity and content hash still
    match. A content hash change is always stale.
    """
    if not reviewed_path:
        raise CoherenceError("reviewed_path must be non-empty")
    if not reviewed_base_hash.startswith("sha256:"):
        raise CoherenceError("reviewed_base_hash must use the sha256: prefix")

    reviewed_note = snapshot.by_path(reviewed_path)
    current: StableNoteIdentity | None = None

    if stable_id is None:
        current = reviewed_note
        if current is None:
            return _resolution(
                "missing",
                reviewed_path,
                None,
                None,
                reviewed_base_hash,
                None,
                detail=(
                    "Legacy path-addressed target is missing. Without a stable id LifeOS cannot "
                    "prove that another path is the same note."
                ),
            )
    else:
        matches = snapshot.by_stable_id(stable_id)
        if len(matches) > 1:
            return _resolution(
                "ambiguous",
                reviewed_path,
                None,
                stable_id,
                reviewed_base_hash,
                None,
                detail="Stable target id is duplicated; mutation is blocked.",
            )
        if not matches:
            if reviewed_note is not None and reviewed_note.stable_id != stable_id:
                return _resolution(
                    "identity-changed",
                    reviewed_path,
                    reviewed_path,
                    stable_id,
                    reviewed_base_hash,
                    reviewed_note.content_hash,
                    detail="Reviewed path now identifies a different note; mutation is blocked.",
                )
            return _resolution(
                "missing",
                reviewed_path,
                None,
                stable_id,
                reviewed_base_hash,
                None,
                detail="Stable target id is missing from the current vault view.",
            )
        current = matches[0]

    if current.content_hash != reviewed_base_hash:
        return _resolution(
            "stale-content",
            reviewed_path,
            current.path,
            stable_id,
            reviewed_base_hash,
            current.content_hash,
            detail="Target content changed after review; base-hash protection remains authoritative.",
        )

    if current.path == reviewed_path:
        return TargetResolution(
            state="current",
            reviewed_path=reviewed_path,
            current_path=current.path,
            stable_id=stable_id,
            reviewed_base_hash=reviewed_base_hash,
            current_content_hash=current.content_hash,
            may_apply_without_new_review=True,
            draft_rebase_allowed=False,
            requires_path_revalidation=False,
            detail="Stable identity/path/content version still match the reviewed target.",
        )

    if proposal_status == "draft":
        return TargetResolution(
            state="relocated-draft-rebase-required",
            reviewed_path=reviewed_path,
            current_path=current.path,
            stable_id=stable_id,
            reviewed_base_hash=reviewed_base_hash,
            current_content_hash=current.content_hash,
            may_apply_without_new_review=False,
            draft_rebase_allowed=True,
            requires_path_revalidation=True,
            detail=(
                "Target relocated with the same stable id and content version. A draft may be "
                "rebased only after path-scoped policy/ownership validation and review regeneration."
            ),
        )

    return TargetResolution(
        state="relocated-review-required",
        reviewed_path=reviewed_path,
        current_path=current.path,
        stable_id=stable_id,
        reviewed_base_hash=reviewed_base_hash,
        current_content_hash=current.content_hash,
        may_apply_without_new_review=False,
        draft_rebase_allowed=False,
        requires_path_revalidation=True,
        detail=(
            "Pending/approved target relocated. LifeOS must not silently retarget it; rebuild or "
            "rebase through an explicit renewed review/approval workflow."
        ),
    )


def _resolution(
    state: TargetResolutionState,
    reviewed_path: str,
    current_path: str | None,
    stable_id: str | None,
    reviewed_base_hash: str,
    current_content_hash: str | None,
    *,
    detail: str,
) -> TargetResolution:
    return TargetResolution(
        state=state,
        reviewed_path=reviewed_path,
        current_path=current_path,
        stable_id=stable_id,
        reviewed_base_hash=reviewed_base_hash,
        current_content_hash=current_content_hash,
        may_apply_without_new_review=False,
        draft_rebase_allowed=False,
        requires_path_revalidation=current_path is not None and current_path != reviewed_path,
        detail=detail,
    )


def _prefixed_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
