"""Review-scoped item decisions and proposal-gated external changes."""

from __future__ import annotations

import copy
import difflib
import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import _frontmatter_document, content_hash
from lifeos.markdown.parser import FenceState, advance_fenced_code_state, parse_markdown_note
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import PatchDocumentV2, PatchHumanFile, serialize_patch_json_bytes
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus, generate_proposal_id
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate, extract_managed_block
from lifeos.reviews.contracts import DecisionKind, ReviewArtifact, ReviewItemDecision
from lifeos.vault import VaultAccessError, read_vault_markdown

ReviewProposalAction = Literal[
    "set_note_status",
    "set_review_date",
    "update_task_status",
    "append_review_reference",
]

_ITEM_ID_PATTERN = r"[a-z0-9][a-z0-9._:-]{0,191}"
_FINGERPRINT_PATTERN = r"sha256:[0-9a-f]{64}"
_ITEM_MARKER = re.compile(
    rf"<!-- lifeos:item (?P<item>{_ITEM_ID_PATTERN}) "
    rf"(?P<fingerprint>{_FINGERPRINT_PATTERN}) -->"
)
_ITEM_LINE = re.compile(
    rf"^-[ \t]+\[ \][ \t]+.+?[ \t]+<!-- lifeos:item (?P<item>{_ITEM_ID_PATTERN}) "
    rf"(?P<fingerprint>{_FINGERPRINT_PATTERN}) -->[ \t]*$"
)
_ALLOWED_NOTE_STATUS = {"inbox", "active", "paused", "completed", "cancelled", "archived", "seed"}
_ALLOWED_TASK_STATUS = {"todo", "active", "done", "cancelled", "blocked", "pending"}


class ReviewProposalError(ValueError):
    pass


class DuplicateReviewProposal(ReviewProposalError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewProposalRequest:
    review_id: str
    item_id: str
    evidence_fingerprint: str
    target_path: str
    expected_target_hash: str
    action: ReviewProposalAction
    value: str
    rationale: str
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewProposalResult:
    proposal_id: str
    proposal_path: str
    target_path: str
    base_hash: str
    review_id: str
    item_id: str
    evidence_fingerprint: str
    action: ReviewProposalAction

    def to_dict(self) -> dict[str, str]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_path": self.proposal_path,
            "target_path": self.target_path,
            "base_hash": self.base_hash,
            "review_id": self.review_id,
            "item_id": self.item_id,
            "evidence_fingerprint": self.evidence_fingerprint,
            "action": self.action,
        }


def artifact_item_fingerprints(artifact: ReviewArtifact) -> dict[str, str]:
    items = extract_managed_block(artifact.body, "items")
    result: dict[str, str] = {}
    fenced_code: FenceState = None
    for line in items.splitlines():
        previous_fence = fenced_code
        fenced_code = advance_fenced_code_state(line, fenced_code)
        if previous_fence is not None or fenced_code is not None:
            continue

        structural = _ITEM_LINE.fullmatch(line)
        if structural is None:
            continue
        markers = tuple(_ITEM_MARKER.finditer(line))
        item_id = structural.group("item")
        fingerprint = structural.group("fingerprint")
        if len(markers) != 1:
            raise DailyInteractionError(
                "duplicate_review_item",
                f"Review item {item_id} contains ambiguous marker structure.",
                "Refresh or repair the managed review items block.",
            )
        if item_id in result:
            message = (
                f"Review item {item_id} appears with multiple fingerprints."
                if result[item_id] != fingerprint
                else f"Review item {item_id} appears more than once."
            )
            raise DailyInteractionError(
                "duplicate_review_item",
                message,
                "Refresh or repair the managed review items block.",
            )
        result[item_id] = fingerprint
    return result


class ReviewDecisionService:
    def __init__(self, artifact_service: ReviewArtifactService) -> None:
        self.artifacts = artifact_service

    def decide(
        self,
        *,
        review_id: str,
        item_id: str,
        evidence_fingerprint: str,
        decision: DecisionKind,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
        note: str | None = None,
        proposal_id: str | None = None,
    ) -> ReviewArtifact:
        artifact = self.artifacts.load_id(review_id)
        visible = artifact_item_fingerprints(artifact)
        if visible.get(item_id) != evidence_fingerprint:
            raise DailyInteractionError(
                "stale_review_item",
                "The review item no longer matches the evidence shown in the artifact.",
                "Refresh the review and decide on the current item.",
                {"item_id": item_id, "visible_fingerprint": visible.get(item_id)},
            )
        if decision == "propose_change" and not proposal_id:
            raise DailyInteractionError(
                "proposal_required",
                "A propose-change decision must reference a draft proposal.",
                "Create the review proposal before attaching the decision.",
            )
        record = ReviewItemDecision(
            item_id=item_id,
            evidence_fingerprint=evidence_fingerprint,
            decision=decision,
            decided_at=now.isoformat(),
            note=note.strip() if note and note.strip() else None,
            proposal_id=proposal_id,
        )
        decisions = [
            item
            for item in artifact.metadata.item_decisions
            if (item.item_id, item.evidence_fingerprint) != (item_id, evidence_fingerprint)
        ]
        decisions.append(record)
        decisions.sort(key=lambda item: (item.item_id, item.evidence_fingerprint))
        proposal_refs = artifact.metadata.proposal_refs
        if proposal_id and proposal_id not in proposal_refs:
            proposal_refs = (*proposal_refs, proposal_id)
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(
                item_decisions=tuple(decisions), proposal_refs=tuple(sorted(proposal_refs))
            ),
        )


def _existing_review_proposal(proposals_root: Path, fingerprint: str) -> str | None:
    if not proposals_root.exists():
        return None
    for child in sorted(proposals_root.iterdir()):
        if not child.is_dir():
            continue
        loaded = load_proposal_directory(child, proposals_root=proposals_root)
        if loaded.proposal is None:
            continue
        extensions = loaded.proposal.metadata.extensions
        review = extensions.get("review_artifact") if hasattr(extensions, "get") else None
        if review is not None and hasattr(review, "get") and review.get("evidence_fingerprint") == fingerprint:
            return loaded.proposal.metadata.id
    return None


def _apply_review_change(frontmatter: dict[str, Any], request: ReviewProposalRequest) -> None:
    if request.action == "set_note_status":
        if request.value not in _ALLOWED_NOTE_STATUS:
            raise ReviewProposalError(f"Unsupported note status: {request.value}")
        frontmatter["status"] = request.value
        return
    if request.action == "set_review_date":
        try:
            parsed = date.fromisoformat(request.value)
        except ValueError as exc:
            raise ReviewProposalError("Review date must be an ISO date.") from exc
        frontmatter["review_date"] = parsed
        return
    if request.action == "append_review_reference":
        refs = frontmatter.setdefault("review_refs", [])
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ReviewProposalError("Target review_refs must be a list of strings.")
        if request.review_id not in refs:
            refs.append(request.review_id)
        return
    if request.action == "update_task_status":
        if not request.task_id:
            raise ReviewProposalError("task_id is required for update_task_status.")
        if request.value not in _ALLOWED_TASK_STATUS:
            raise ReviewProposalError(f"Unsupported task status: {request.value}")
        tasks = frontmatter.get("tasks")
        if not isinstance(tasks, list):
            raise ReviewProposalError("Target note does not contain a task list.")
        matches = [item for item in tasks if isinstance(item, dict) and item.get("task_id") == request.task_id]
        if len(matches) != 1:
            raise ReviewProposalError("Task ID must match exactly one task in the target note.")
        matches[0]["status"] = request.value
        return
    raise ReviewProposalError(f"Unsupported review proposal action: {request.action}")


def _proposal_body(request: ReviewProposalRequest) -> str:
    return (
        "## Review origin\n\n"
        f"- Review: `{request.review_id}`\n"
        f"- Item: `{request.item_id}`\n"
        f"- Evidence fingerprint: `{request.evidence_fingerprint}`\n"
        f"- Target: `{request.target_path}`\n"
        f"- Action: `{request.action}`\n\n"
        "## Rationale\n\n"
        f"{request.rationale.strip()}\n\n"
        "## Safety\n\n"
        "This draft does not change the target until it is submitted, approved, and explicitly applied.\n"
    )


def create_review_proposal(
    *,
    vault_root: Path,
    request: ReviewProposalRequest,
    actor_id: str,
    now: datetime | None = None,
) -> ReviewProposalResult:
    if not request.rationale.strip():
        raise ReviewProposalError("Rationale is required.")
    if not request.evidence_fingerprint.startswith("sha256:"):
        raise ReviewProposalError("Evidence fingerprint must be a SHA-256 fingerprint.")
    if not actor_id.strip():
        raise ReviewProposalError("Actor ID is required.")
    duplicate = _existing_review_proposal(vault_root / "proposals", request.evidence_fingerprint)
    if duplicate:
        raise DuplicateReviewProposal(f"Equivalent review proposal already exists: {duplicate}")
    try:
        source = read_vault_markdown(vault_root, request.target_path)
    except VaultAccessError as exc:
        raise ReviewProposalError(str(exc)) from exc
    actual_hash = "sha256:" + content_hash(source.content)
    expected_hash = request.expected_target_hash
    if not expected_hash.startswith("sha256:"):
        expected_hash = "sha256:" + expected_hash
    if actual_hash != expected_hash:
        raise ReviewProposalError("Target changed after the review item was inspected.")
    parsed = parse_markdown_note(source.path, content=source.content)
    if any(item.severity == "error" for item in parsed.findings):
        raise ReviewProposalError("Target note is structurally invalid.")
    updated_frontmatter = copy.deepcopy(dict(parsed.frontmatter))
    _apply_review_change(updated_frontmatter, request)
    updated_content = _frontmatter_document(updated_frontmatter, parsed.body)
    if updated_content == source.content:
        raise ReviewProposalError("The proposed change has no effect.")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ReviewProposalError("Proposal timestamp must be timezone-aware.")
    utc = moment.astimezone(timezone.utc)
    suffix = hashlib.sha256(
        f"{request.review_id}\0{request.item_id}\0{request.evidence_fingerprint}\0{request.action}".encode()
    ).hexdigest()[:8]
    proposal_id = generate_proposal_id(lambda: utc, lambda: suffix)
    timestamp = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    diff_lines = tuple(
        difflib.unified_diff(
            source.content.splitlines(keepends=True),
            updated_content.splitlines(keepends=True),
            fromfile=request.target_path,
            tofile=request.target_path,
        )
    )
    diff = "".join(diff_lines[2:])
    patch = PatchHumanFile("op-review-artifact-change", request.target_path, actual_hash, diff)
    patch_document = PatchDocumentV2(2, proposal_id, (patch,))
    goal = str(parsed.frontmatter.get("goal") or "").strip()
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Review proposal: {request.action.replace('_', ' ')}",
        description=request.rationale.strip(),
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.MEDIUM,
        created_at=timestamp,
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
        related_goals=(goal,) if goal else (),
        related_sources=(request.target_path,),
        extensions={
            "review_artifact": {
                "review_id": request.review_id,
                "item_id": request.item_id,
                "evidence_fingerprint": request.evidence_fingerprint,
                "action": request.action,
            }
        },
    )
    proposal_markdown = serialize_proposal_markdown(metadata, _proposal_body(request))
    patches_json = serialize_patch_json_bytes(patch_document)
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=vault_root,
        patches_json=patches_json,
    )
    proposals_root = vault_root / "proposals"
    proposal_dir = proposals_root / proposal_id
    proposals_root.mkdir(parents=True, exist_ok=True)
    created = False
    published = False
    dir_fd = -1
    try:
        proposal_dir.mkdir(exist_ok=False)
        created = True
        dir_fd = os.open(proposal_dir, os.O_RDONLY | os.O_DIRECTORY)
        atomic_write_file_secure(dir_fd, "proposal.md", proposal_markdown)
        atomic_write_file_secure(dir_fd, "patches.json", patches_json)
        atomic_write_file_secure(dir_fd, "review.json", review_json)
        published = True
    except (OSError, AtomicWriteError) as exc:
        raise ReviewProposalError(f"Could not publish review proposal: {exc}") from exc
    finally:
        if dir_fd >= 0:
            os.close(dir_fd)
        if created and not published:
            shutil.rmtree(proposal_dir, ignore_errors=True)
    return ReviewProposalResult(
        proposal_id,
        f"proposals/{proposal_id}",
        request.target_path,
        actual_hash,
        request.review_id,
        request.item_id,
        request.evidence_fingerprint,
        request.action,
    )
