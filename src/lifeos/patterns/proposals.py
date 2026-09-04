"""Proposal-gated lifecycle builders for canonical personal patterns."""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypeAlias

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
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
            "proposal_id": self.proposal_id,
            "action": self.action,
            "pattern_id": self.pattern_id,
            "target_path": self.target_path,
            "operation": self.operation,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "base_hash": self.base_hash,
            "evidence_fingerprint": self.evidence_fingerprint,
            "transition_reason": self.transition_reason,
            "candidate_content": self.candidate_content,
        }


class PatternProposalService:
    """Build and publish draft proposals without mutating canonical pattern Markdown."""

    def __init__(self, *, vault_root: Path, actor_id: str) -> None:
        if not actor_id.strip():
            raise PatternError("invalid_actor", "Pattern proposal actor_id must not be blank.")
        self.vault_root = vault_root
        self.actor_id = actor_id
        self.artifacts = PatternArtifactService(vault_root=vault_root)

    def preview(
        self,
        request: PatternProposalRequest,
        *,
        now: datetime | None = None,
    ) -> tuple[PatternProposalPreview, PatchDocumentV2, bytes]:
        moment = _utc_moment(now)
        reason = _transition_reason(request.transition_reason)
        if isinstance(request, CreatePatternSeedRequest):
            return self._preview_create(request, moment=moment, reason=reason)
        return self._preview_existing(request, moment=moment, reason=reason)

    def publish(
        self,
        request: PatternProposalRequest,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        preview, patch, proposal_markdown = self.preview(request, now=now)
        root = self.vault_root / "proposals"
        target = root / preview.proposal_id
        patches_json = serialize_patch_json_bytes(patch)
        review_json = build_review_snapshot_bytes_from_patches(
            vault_root=self.vault_root,
            patches_json=patches_json,
        )
        root.mkdir(parents=True, exist_ok=True)
        created = False
        published = False
        fd = -1
        try:
            target.mkdir(exist_ok=False)
            created = True
            fd = os.open(
                target,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            atomic_write_file_secure(fd, "proposal.md", proposal_markdown)
            atomic_write_file_secure(fd, "patches.json", patches_json)
            atomic_write_file_secure(fd, "review.json", review_json)
            published = True
        except FileExistsError as exc:
            raise PatternError(
                "proposal_exists",
                "An equivalent personal-pattern proposal already exists.",
                {"proposal_id": preview.proposal_id},
            ) from exc
        except (OSError, AtomicWriteError) as exc:
            raise PatternError("proposal_publish_failed", str(exc)) from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if created and not published:
                shutil.rmtree(target, ignore_errors=True)

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
        try:
            os.lstat(self.vault_root / target_path)
        except FileNotFoundError:
            pass
        else:
            raise PatternError(
                "target_exists",
                "The proposed pattern target already exists.",
                {"target_path": target_path},
            )

        if any(item.metadata.pattern_id == request.pattern_id for item in self.artifacts.list()):
            raise PatternError(
                "duplicate_identity",
                "Pattern identity already exists.",
                {"pattern_id": request.pattern_id},
            )

        timestamp = _pattern_timestamp(moment)
        evidence_fingerprint = compute_evidence_fingerprint(request.evidence)
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
            evidence_fingerprint=evidence_fingerprint,
            evidence=request.evidence,
            review_due_at=request.review_due_at,
            evaluation=request.evaluation,
        )
        candidate = serialize_pattern(metadata)
        return self._build_proposal(
            action="create-seed",
            target_path=target_path,
            metadata=metadata,
            candidate_content=candidate,
            current_content=None,
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
        current = artifact.metadata
        timestamp = _pattern_timestamp(moment)

        if isinstance(request, PromotePatternRequest):
            if current.status != "seed":
                raise PatternError(
                    "invalid_transition",
                    "Only a seed pattern can be promoted to active.",
                    {"from_status": current.status, "to_status": "active"},
                )
            action: PatternProposalAction = "promote-active"
            updated = replace(
                current,
                status="active",
                review_reasons=(),
                updated_at=timestamp,
                last_reviewed_at=timestamp,
            )
        elif isinstance(request, RevisePatternRequest):
            if current.status == "archived":
                raise PatternError(
                    "invalid_transition",
                    "Archived patterns must remain archived in this lifecycle task.",
                    {"from_status": current.status},
                )
            if (
                request.statement is None
                and request.evidence is None
                and request.confidence is None
            ):
                raise PatternError(
                    "empty_revision",
                    "A revision must change statement, evidence, or confidence.",
                )
            action = "revise"
            evidence = current.evidence if request.evidence is None else request.evidence
            updated = replace(
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
        elif isinstance(request, MarkPatternNeedsReviewRequest):
            if current.status not in {"seed", "active"}:
                raise PatternError(
                    "invalid_transition",
                    "Only seed or active patterns can be marked needs-review.",
                    {"from_status": current.status, "to_status": "needs-review"},
                )
            if not request.review_reasons:
                raise PatternError(
                    "missing_review_reason",
                    "Marking a pattern needs-review requires at least one review reason.",
                )
            action = "mark-needs-review"
            updated = replace(
                current,
                status="needs-review",
                review_reasons=request.review_reasons,
                updated_at=timestamp,
            )
        elif isinstance(request, ResolvePatternReviewRequest):
            if current.status != "needs-review":
                raise PatternError(
                    "invalid_transition",
                    "Only a needs-review pattern can have its review resolved.",
                    {"from_status": current.status, "to_status": request.target_status},
                )
            action = "resolve-review"
            updated = replace(
                current,
                status=request.target_status,
                confidence=current.confidence if request.confidence is None else request.confidence,
                review_reasons=(),
                updated_at=timestamp,
                last_reviewed_at=timestamp,
                review_due_at=(
                    current.review_due_at
                    if request.review_due_at is None
                    else request.review_due_at
                ),
            )
        elif isinstance(request, ArchivePatternRequest):
            if current.status == "archived":
                raise PatternError(
                    "invalid_transition",
                    "Pattern is already archived.",
                    {"from_status": current.status, "to_status": "archived"},
                )
            action = "archive"
            updated = replace(current, status="archived", updated_at=timestamp)
        else:
            raise AssertionError("Unsupported personal-pattern proposal request")

        candidate = serialize_pattern(
            updated,
            body_prefix=artifact.body_prefix,
            body_suffix=artifact.body_suffix,
        )
        return self._build_proposal(
            action=action,
            target_path=artifact.path,
            metadata=updated,
            candidate_content=candidate,
            current_content=source.content,
            base_hash=artifact.content_hash,
            from_status=current.status,
            reason=reason,
            moment=moment,
        )

    def _build_proposal(
        self,
        *,
        action: PatternProposalAction,
        target_path: str,
        metadata: PatternMetadata,
        candidate_content: str,
        current_content: str | None,
        base_hash: str | None,
        from_status: str | None,
        reason: str,
        moment: datetime,
    ) -> tuple[PatternProposalPreview, PatchDocumentV2, bytes]:
        fingerprint_payload = "\0".join(
            (
                action,
                metadata.pattern_id,
                target_path,
                base_hash or "absent",
                metadata.evidence_fingerprint,
                reason,
                candidate_content,
            )
        )
        suffix = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()[:8]
        proposal_id = generate_proposal_id(lambda: moment, lambda: suffix)

        if current_content is None:
            operation: CreateFile | PatchHumanFile = CreateFile(
                "op-pattern-create",
                target_path,
                "absent",
                candidate_content,
            )
            operation_name: Literal["create_file", "patch_human_file"] = "create_file"
        else:
            assert base_hash is not None
            operation = PatchHumanFile(
                "op-pattern-update",
                target_path,
                base_hash,
                _diff(current_content, candidate_content, target_path),
            )
            operation_name = "patch_human_file"

        patch = PatchDocumentV2(2, proposal_id, (operation,))
        proposal_timestamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        related_sources = tuple(
            dict.fromkeys(
                (
                    *((target_path,) if current_content is not None else ()),
                    *(item.path for item in metadata.evidence),
                )
            )
        )
        proposal_metadata = ProposalMetadata(
            id=proposal_id,
            schema_version=1,
            patch_schema_version=2,
            lifecycle_schema_version=1,
            title=_proposal_title(action, metadata.title),
            description="Reviewable personal-pattern lifecycle change.",
            status=ProposalStatus.DRAFT,
            risk=ProposalRisk.HIGH,
            created_at=proposal_timestamp,
            created_by=self.actor_id,
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
                    "pattern_id": metadata.pattern_id,
                    "target_path": target_path,
                    "from_status": from_status,
                    "to_status": metadata.status,
                    "base_hash": base_hash,
                    "evidence_fingerprint": metadata.evidence_fingerprint,
                    "transition_reason": reason,
                }
            },
        )
        proposal_body = _proposal_body(
            action=action,
            metadata=metadata,
            target_path=target_path,
            from_status=from_status,
            reason=reason,
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
            candidate_content=candidate_content,
        )
        return preview, patch, serialize_proposal_markdown(proposal_metadata, proposal_body)


def _utc_moment(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PatternError(
            "invalid_timestamp",
            "Pattern proposal timestamp must include a timezone.",
        )
    return moment.astimezone(timezone.utc)


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


def _proposal_title(action: PatternProposalAction, title: str) -> str:
    labels = {
        "create-seed": "Track pattern",
        "promote-active": "Adopt pattern",
        "revise": "Revise pattern",
        "mark-needs-review": "Review pattern",
        "resolve-review": "Resolve pattern review",
        "archive": "Archive pattern",
    }
    return f"{labels[action]}: {title}"


def _proposal_body(
    *,
    action: PatternProposalAction,
    metadata: PatternMetadata,
    target_path: str,
    from_status: str | None,
    reason: str,
) -> str:
    evidence = [
        (
            f"- `{item.role}`: `{item.path}` at `{item.content_hash}`"
            + (f" (`{item.source_id}`)" if item.source_id is not None else "")
        )
        for item in metadata.evidence
    ]
    return "\n".join(
        [
            "## Personal-pattern review",
            "",
            f"- Pattern: `{metadata.pattern_id}`",
            f"- Target: `{target_path}`",
            f"- Action: `{action}`",
            f"- Lifecycle: `{from_status or 'absent'}` → `{metadata.status}`",
            f"- Confidence: `{metadata.confidence}`",
            f"- Evidence fingerprint: `{metadata.evidence_fingerprint}`",
            f"- Transition reason: {reason}",
            "",
            "## Proposed working hypothesis",
            "",
            metadata.statement,
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
