"""Proposal-gated lifecycle builders for canonical personal patterns."""

from __future__ import annotations

import difflib
import hashlib
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypeAlias

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos._secure_io import SecureIOError, open_directory_secure
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import (
    CreateFile,
    PatchDocumentV2,
    PatchHumanFile,
    serialize_patch_json_bytes,
)
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalRisk,
    ProposalStatus,
    generate_proposal_id,
)
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import (
    PatternArtifactService,
    _validate_artifact_path,
    parse_pattern,
    serialize_pattern,
)
from .contracts import (
    PatternConfidence,
    PatternError,
    PatternEvaluation,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
)
from .evidence import compute_evidence_fingerprint

PatternProposalAction = Literal[
    "create-seed",
    "promote-active",
    "revise",
    "mark-needs-review",
    "resolve-review",
    "archive",
]
ResolvedPatternStatus = Literal["seed", "active"]


@dataclass(frozen=True, slots=True)
class CreatePatternSeedRequest:
    target_path: str
    pattern_id: str
    title: str
    description: str
    statement: str
    confidence: PatternConfidence
    origin: PatternOrigin
    evidence: tuple[PatternEvidence, ...]
    transition_reason: str
    review_due_at: str | None = None
    evaluation: PatternEvaluation | None = None


@dataclass(frozen=True, slots=True)
class PromotePatternRequest:
    target_path: str
    transition_reason: str


@dataclass(frozen=True, slots=True)
class RevisePatternRequest:
    target_path: str
    transition_reason: str
    statement: str | None = None
    evidence: tuple[PatternEvidence, ...] | None = None
    confidence: PatternConfidence | None = None


@dataclass(frozen=True, slots=True)
class MarkPatternNeedsReviewRequest:
    target_path: str
    transition_reason: str
    review_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvePatternReviewRequest:
    target_path: str
    transition_reason: str
    target_status: ResolvedPatternStatus
    confidence: PatternConfidence | None = None
    review_due_at: str | None = None


@dataclass(frozen=True, slots=True)
class ArchivePatternRequest:
    target_path: str
    transition_reason: str


PatternProposalRequest: TypeAlias = (
    CreatePatternSeedRequest
    | PromotePatternRequest
    | RevisePatternRequest
    | MarkPatternNeedsReviewRequest
    | ResolvePatternReviewRequest
    | ArchivePatternRequest
)


@dataclass(frozen=True, slots=True)
class PatternProposalPreview:
    proposal_id: str
    action: PatternProposalAction
    pattern_id: str
    target_path: str
    operation: Literal["create_file", "patch_human_file"]
    from_status: str | None
    to_status: str
    base_hash: str | None
    evidence_fingerprint: str
    transition_reason: str
    candidate_content: str

    def to_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "proposal_id",
                "action",
                "pattern_id",
                "target_path",
                "operation",
                "from_status",
                "to_status",
                "base_hash",
                "evidence_fingerprint",
                "transition_reason",
                "candidate_content",
            )
        }


class PatternProposalService:
    """Build and publish pattern proposals without directly mutating canonical Markdown."""

    def __init__(self, *, vault_root: Path, actor_id: str) -> None:
        actor = actor_id.strip()
        if not actor:
            raise PatternError("invalid_actor", "Pattern proposal actor_id must not be blank.")
        self.vault_root = vault_root
        self.actor_id = actor
        self.artifacts = PatternArtifactService(vault_root=vault_root)

    def preview(
        self,
        request: PatternProposalRequest,
        *,
        now: datetime | None = None,
        expected_base_hash: str | None = None,
    ) -> tuple[PatternProposalPreview, PatchDocumentV2, bytes]:
        moment = _utc_moment(now)
        reason = _transition_reason(request.transition_reason)
        if isinstance(request, CreatePatternSeedRequest):
            return self._preview_create(request, moment=moment, reason=reason)
        return self._preview_existing(
            request,
            moment=moment,
            reason=reason,
            expected_base_hash=expected_base_hash,
        )

    def publish(
        self,
        request: PatternProposalRequest,
        *,
        now: datetime | None = None,
        expected_base_hash: str | None = None,
    ) -> dict[str, object]:
        preview, patch, proposal_markdown = self.preview(
            request,
            now=now,
            expected_base_hash=expected_base_hash,
        )
        patches_json = serialize_patch_json_bytes(patch)
        review_json = build_review_snapshot_bytes_from_patches(
            vault_root=self.vault_root,
            patches_json=patches_json,
        )
        _publish_proposal(
            vault_root=self.vault_root,
            proposal_id=preview.proposal_id,
            proposal_markdown=proposal_markdown,
            patches_json=patches_json,
            review_json=review_json,
        )
        return {
            "proposal_id": preview.proposal_id,
            "proposal_path": f"proposals/{preview.proposal_id}",
            "preview": preview.to_dict(),
        }

    def _preview_create(
        self,
        request: CreatePatternSeedRequest,
        *,
        moment: datetime,
        reason: str,
    ) -> tuple[PatternProposalPreview, PatchDocumentV2, bytes]:
        target_path = _validate_artifact_path(request.target_path)
        _require_absent_target(self.vault_root, target_path)
        if any(item.metadata.pattern_id == request.pattern_id for item in self.artifacts.list()):
            raise PatternError(
                "duplicate_identity",
                "Pattern identity already exists.",
                {"pattern_id": request.pattern_id},
            )
        timestamp = _pattern_timestamp(moment)
        metadata = PatternMetadata(
            pattern_id=request.pattern_id,
            title=request.title,
            description=request.description,
            status="seed",
            confidence=request.confidence,
            review_reasons=(),
            statement=request.statement,
            origin=request.origin,
            created_at=timestamp,
            updated_at=timestamp,
            evidence_fingerprint=compute_evidence_fingerprint(request.evidence),
            evidence=request.evidence,
            review_due_at=request.review_due_at,
            evaluation=request.evaluation,
        )
        return self._build(
            action="create-seed",
            target_path=target_path,
            metadata=metadata,
            candidate=serialize_pattern(metadata),
            source=None,
            base_hash=None,
            from_status=None,
            reason=reason,
            moment=moment,
        )

    def _preview_existing(
        self,
        request: PromotePatternRequest
        | RevisePatternRequest
        | MarkPatternNeedsReviewRequest
        | ResolvePatternReviewRequest
        | ArchivePatternRequest,
        *,
        moment: datetime,
        reason: str,
        expected_base_hash: str | None,
    ) -> tuple[PatternProposalPreview, PatchDocumentV2, bytes]:
        target_path = _validate_artifact_path(request.target_path)
        try:
            source = read_vault_markdown(self.vault_root, target_path)
        except VaultAccessError as exc:
            raise PatternError(exc.code, str(exc), {"target_path": target_path}) from exc
        artifact = parse_pattern(source.path, source.relative_path, source.content)
        if artifact is None:
            raise PatternError(
                "unsupported_artifact",
                "Target Markdown does not declare a recognized personal-pattern schema.",
                {"target_path": target_path},
            )
        if expected_base_hash is not None and artifact.content_hash != expected_base_hash:
            raise PatternError(
                "stale_target",
                "The pattern changed after it was inspected. Refresh before creating a proposal.",
                {
                    "path": artifact.path,
                    "expected_hash": expected_base_hash,
                    "current_hash": artifact.content_hash,
                },
            )

        action, metadata = _transition(
            artifact.metadata,
            request,
            timestamp=_pattern_timestamp(moment),
        )
        candidate = serialize_pattern(
            metadata,
            body_prefix=artifact.body_prefix,
            body_suffix=artifact.body_suffix,
        )
        return self._build(
            action=action,
            target_path=artifact.path,
            metadata=metadata,
            candidate=candidate,
            source=source.content,
            base_hash=artifact.content_hash,
            from_status=artifact.metadata.status,
            reason=reason,
            moment=moment,
        )

    def _build(
        self,
        *,
        action: PatternProposalAction,
        target_path: str,
        metadata: PatternMetadata,
        candidate: str,
        source: str | None,
        base_hash: str | None,
        from_status: str | None,
        reason: str,
        moment: datetime,
    ) -> tuple[PatternProposalPreview, PatchDocumentV2, bytes]:
        proposal_id = _proposal_id(
            action=action,
            pattern_id=metadata.pattern_id,
            target_path=target_path,
            base_hash=base_hash,
            evidence_fingerprint=metadata.evidence_fingerprint,
            reason=reason,
            candidate=candidate,
            moment=moment,
        )
        if source is None:
            operation: CreateFile | PatchHumanFile = CreateFile(
                "op-pattern-create", target_path, "absent", candidate
            )
            operation_name: Literal["create_file", "patch_human_file"] = "create_file"
        else:
            assert base_hash is not None
            operation = PatchHumanFile(
                "op-pattern-update",
                target_path,
                base_hash,
                _diff(source, candidate, target_path),
            )
            operation_name = "patch_human_file"

        patch = PatchDocumentV2(2, proposal_id, (operation,))
        proposal_metadata = _proposal_metadata(
            proposal_id=proposal_id,
            actor_id=self.actor_id,
            action=action,
            target_path=target_path,
            pattern=metadata,
            base_hash=base_hash,
            from_status=from_status,
            reason=reason,
            moment=moment,
        )
        preview = PatternProposalPreview(
            proposal_id=proposal_id,
            action=action,
            pattern_id=metadata.pattern_id,
            target_path=target_path,
            operation=operation_name,
            from_status=from_status,
            to_status=metadata.status,
            base_hash=base_hash,
            evidence_fingerprint=metadata.evidence_fingerprint,
            transition_reason=reason,
            candidate_content=candidate,
        )
        body = _proposal_body(action, metadata, target_path, from_status, reason)
        return preview, patch, serialize_proposal_markdown(proposal_metadata, body)


def _transition(
    current: PatternMetadata,
    request: PromotePatternRequest
    | RevisePatternRequest
    | MarkPatternNeedsReviewRequest
    | ResolvePatternReviewRequest
    | ArchivePatternRequest,
    *,
    timestamp: str,
) -> tuple[PatternProposalAction, PatternMetadata]:
    if isinstance(request, PromotePatternRequest):
        _require_status(current, {"seed"}, "Only a seed pattern can be promoted to active.")
        return "promote-active", replace(
            current,
            status="active",
            review_reasons=(),
            updated_at=timestamp,
            last_reviewed_at=timestamp,
        )

    if isinstance(request, RevisePatternRequest):
        _require_status(
            current,
            {"seed", "active", "needs-review"},
            "Archived patterns cannot be revised by this lifecycle.",
        )
        if request.statement is None and request.evidence is None and request.confidence is None:
            raise PatternError(
                "empty_revision",
                "A revision must change statement, evidence, or confidence.",
            )
        evidence = current.evidence if request.evidence is None else request.evidence
        return "revise", replace(
            current,
            statement=current.statement if request.statement is None else request.statement,
            evidence=evidence,
            confidence=current.confidence if request.confidence is None else request.confidence,
            evidence_fingerprint=(
                current.evidence_fingerprint
                if request.evidence is None
                else compute_evidence_fingerprint(evidence)
            ),
            updated_at=timestamp,
        )

    if isinstance(request, MarkPatternNeedsReviewRequest):
        _require_status(
            current,
            {"seed", "active"},
            "Only seed or active patterns can be marked needs-review.",
        )
        if not request.review_reasons:
            raise PatternError(
                "missing_review_reason",
                "Marking a pattern needs-review requires at least one review reason.",
            )
        return "mark-needs-review", replace(
            current,
            status="needs-review",
            review_reasons=request.review_reasons,
            updated_at=timestamp,
        )

    if isinstance(request, ResolvePatternReviewRequest):
        _require_status(
            current,
            {"needs-review"},
            "Only a needs-review pattern can have its review resolved.",
        )
        return "resolve-review", replace(
            current,
            status=request.target_status,
            confidence=current.confidence if request.confidence is None else request.confidence,
            review_reasons=(),
            updated_at=timestamp,
            last_reviewed_at=timestamp,
            review_due_at=(
                current.review_due_at if request.review_due_at is None else request.review_due_at
            ),
        )

    if isinstance(request, ArchivePatternRequest):
        _require_status(
            current,
            {"seed", "active", "needs-review"},
            "Pattern is already archived.",
        )
        return "archive", replace(current, status="archived", updated_at=timestamp)

    raise AssertionError("Unsupported personal-pattern proposal request")


def _require_status(
    current: PatternMetadata,
    allowed: set[str],
    message: str,
) -> None:
    if current.status not in allowed:
        raise PatternError(
            "invalid_transition",
            message,
            {"from_status": current.status},
        )


def _proposal_metadata(
    *,
    proposal_id: str,
    actor_id: str,
    action: PatternProposalAction,
    target_path: str,
    pattern: PatternMetadata,
    base_hash: str | None,
    from_status: str | None,
    reason: str,
    moment: datetime,
) -> ProposalMetadata:
    related_sources = tuple(
        dict.fromkeys(
            (
                *((target_path,) if base_hash is not None else ()),
                *(item.path for item in pattern.evidence),
            )
        )
    )
    return ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"{_ACTION_TITLES[action]}: {pattern.title}",
        description="Reviewable personal-pattern lifecycle change.",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.HIGH,
        created_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        created_by=actor_id,
        submitted_at=None,
        submitted_by=None,
        review_digest=None,
        approved_at=None,
        approved_by=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        applied_at=None,
        applied_by=None,
        related_goals=(),
        related_sources=related_sources,
        extensions={
            "personal_pattern": {
                "action": action,
                "pattern_id": pattern.pattern_id,
                "target_path": target_path,
                "from_status": from_status,
                "to_status": pattern.status,
                "base_hash": base_hash,
                "evidence_fingerprint": pattern.evidence_fingerprint,
                "transition_reason": reason,
            }
        },
    )


_ACTION_TITLES: dict[PatternProposalAction, str] = {
    "create-seed": "Track pattern",
    "promote-active": "Adopt pattern",
    "revise": "Revise pattern",
    "mark-needs-review": "Review pattern",
    "resolve-review": "Resolve pattern review",
    "archive": "Archive pattern",
}


def _proposal_id(
    *,
    action: PatternProposalAction,
    pattern_id: str,
    target_path: str,
    base_hash: str | None,
    evidence_fingerprint: str,
    reason: str,
    candidate: str,
    moment: datetime,
) -> str:
    payload = "\0".join(
        (
            action,
            pattern_id,
            target_path,
            base_hash or "absent",
            evidence_fingerprint,
            reason,
            candidate,
        )
    )
    suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return generate_proposal_id(lambda: moment, lambda: suffix)


def _proposal_body(
    action: PatternProposalAction,
    pattern: PatternMetadata,
    target_path: str,
    from_status: str | None,
    reason: str,
) -> str:
    evidence = [
        (
            f"- `{item.role}`: `{item.path}` at `{item.content_hash}`"
            + (f" (`{item.source_id}`)" if item.source_id is not None else "")
        )
        for item in pattern.evidence
    ]
    return "\n".join(
        [
            "## Personal-pattern review",
            "",
            f"- Pattern: `{pattern.pattern_id}`",
            f"- Target: `{target_path}`",
            f"- Action: `{action}`",
            f"- Lifecycle: `{from_status or 'absent'}` → `{pattern.status}`",
            f"- Confidence: `{pattern.confidence}`",
            f"- Evidence fingerprint: `{pattern.evidence_fingerprint}`",
            f"- Transition reason: {reason}",
            "",
            "## Proposed working hypothesis",
            "",
            pattern.statement,
            "",
            "## Reviewed evidence",
            "",
            *(evidence or ["- No evidence references recorded."]),
            "",
            (
                "This is a reviewable working hypothesis. Applying the proposal changes "
                "canonical human-owned Markdown only after trusted approval and application."
            ),
        ]
    )


def _require_absent_target(vault_root: Path, target_path: str) -> None:
    try:
        read_vault_markdown(vault_root, target_path)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return
        raise PatternError(exc.code, str(exc), {"target_path": target_path}) from exc
    raise PatternError(
        "target_exists",
        "The proposed pattern target already exists.",
        {"target_path": target_path},
    )


def _publish_proposal(
    *,
    vault_root: Path,
    proposal_id: str,
    proposal_markdown: bytes,
    patches_json: bytes,
    review_json: bytes,
) -> None:
    proposals_fd = proposal_fd = -1
    created = complete = False
    try:
        proposals_fd = _open_proposals_root(vault_root)
        try:
            os.mkdir(proposal_id, mode=0o755, dir_fd=proposals_fd)
            created = True
        except FileExistsError as exc:
            raise PatternError(
                "proposal_exists",
                "An equivalent personal-pattern proposal already exists.",
                {"proposal_id": proposal_id},
            ) from exc
        proposal_fd = open_directory_secure(Path(proposal_id), dir_fd=proposals_fd)
        atomic_write_file_secure(proposal_fd, "proposal.md", proposal_markdown)
        atomic_write_file_secure(proposal_fd, "patches.json", patches_json)
        atomic_write_file_secure(proposal_fd, "review.json", review_json)
        complete = True
    except PatternError:
        raise
    except (OSError, AtomicWriteError, SecureIOError) as exc:
        raise PatternError("proposal_publish_failed", str(exc)) from exc
    finally:
        if created and not complete:
            if proposal_fd >= 0:
                for filename in ("proposal.md", "patches.json", "review.json"):
                    try:
                        os.unlink(filename, dir_fd=proposal_fd)
                    except OSError:
                        pass
            if proposals_fd >= 0:
                try:
                    os.rmdir(proposal_id, dir_fd=proposals_fd)
                except OSError:
                    pass
        if proposal_fd >= 0:
            os.close(proposal_fd)
        if proposals_fd >= 0:
            os.close(proposals_fd)


def _open_proposals_root(vault_root: Path) -> int:
    vault_fd = -1
    try:
        vault_fd = open_directory_secure(vault_root)
        try:
            os.mkdir("proposals", mode=0o755, dir_fd=vault_fd)
        except FileExistsError:
            pass
        return open_directory_secure(Path("proposals"), dir_fd=vault_fd)
    except SecureIOError as exc:
        raise PatternError(
            "unsafe_proposals_root",
            "Proposal root is not a safe directory.",
        ) from exc
    except OSError as exc:
        raise PatternError("proposal_publish_failed", str(exc)) from exc
    finally:
        if vault_fd >= 0:
            os.close(vault_fd)


def _utc_moment(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PatternError(
            "invalid_timestamp",
            "Pattern proposal timestamp must include a timezone.",
        )
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def _pattern_timestamp(moment: datetime) -> str:
    return moment.isoformat().removesuffix("+00:00") + "Z"


def _transition_reason(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise PatternError(
            "missing_transition_reason",
            "Every personal-pattern lifecycle proposal requires a transition reason.",
        )
    return " ".join(value.split())


def _diff(current: str, candidate: str, target_path: str) -> str:
    lines = tuple(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=target_path,
            tofile=target_path,
        )
    )
    unified = "".join(lines[2:])
    if not unified:
        raise PatternError("no_change", "Pattern proposal would not change the target.")
    return unified
