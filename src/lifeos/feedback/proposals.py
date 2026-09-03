"""Reviewable plan-improvement proposals derived from feedback."""

from __future__ import annotations

import copy
import difflib
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.daily.service import _frontmatter_document, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import PatchDocumentV2, PatchHumanFile, serialize_patch_json_bytes
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus, generate_proposal_id
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.vault import VaultAccessError, read_vault_markdown

FeedbackProposalKind = Literal[
    "update_task_estimate",
    "clarify_task",
    "decompose_task",
    "change_task_fit",
    "add_blocker",
    "resolve_blocker",
    "pause_plan",
    "resume_plan",
    "revise_review_date",
    "open_goal_review",
    "reduce_tracking",
    "disable_tracking",
]


class FeedbackProposalError(ValueError):
    pass


class DuplicateFeedbackProposal(FeedbackProposalError):
    pass


@dataclass(frozen=True, slots=True)
class FeedbackProposalRequest:
    kind: FeedbackProposalKind
    target_path: str
    evidence_fingerprint: str
    evidence_event_ids: tuple[str, ...]
    confidence: str
    expected_effect: str
    alternatives: tuple[str, ...]
    task_id: str | None = None
    changes: dict[str, Any] | None = None
    decomposition_titles: tuple[str, ...] = ()
    agent_requested: bool = False


@dataclass(frozen=True, slots=True)
class FeedbackProposalResult:
    proposal_id: str
    proposal_path: str
    target_path: str
    base_hash: str
    evidence_fingerprint: str
    operation_kind: str


def _find_task(frontmatter: dict[str, Any], task_id: str | None) -> dict[str, Any]:
    if not task_id:
        raise FeedbackProposalError("This proposal kind requires a task_id.")
    tasks = frontmatter.get("tasks")
    if not isinstance(tasks, list):
        raise FeedbackProposalError("Target plan has no valid tasks list.")
    task = next((item for item in tasks if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task is None:
        raise FeedbackProposalError(f"Task not found: {task_id}")
    return task


def _apply_change(frontmatter: dict[str, Any], request: FeedbackProposalRequest) -> None:
    changes = dict(request.changes or {})
    if request.kind == "update_task_estimate":
        task = _find_task(frontmatter, request.task_id)
        duration = changes.get("duration")
        if type(duration) is not int or not 1 <= duration <= 1440:
            raise FeedbackProposalError("Duration must be from 1 to 1440 minutes.")
        task["duration"] = duration
    elif request.kind == "clarify_task":
        task = _find_task(frontmatter, request.task_id)
        next_action = changes.get("next_action")
        if not isinstance(next_action, str) or not next_action.strip():
            raise FeedbackProposalError("Clarification requires a non-empty next_action.")
        task["next_action"] = next_action.strip()
    elif request.kind == "decompose_task":
        task = _find_task(frontmatter, request.task_id)
        if not request.decomposition_titles or any(not title.strip() for title in request.decomposition_titles):
            raise FeedbackProposalError("Decomposition requires bounded non-empty titles.")
        if len(request.decomposition_titles) > 8:
            raise FeedbackProposalError("Decomposition is limited to eight immediate actions.")
        if request.agent_requested and not changes.get("user_requested_agent", False):
            raise FeedbackProposalError("Agent decomposition requires explicit user request evidence.")
        tasks = frontmatter["tasks"]
        existing_ids = {item.get("task_id") for item in tasks if isinstance(item, dict)}
        created_ids: list[str] = []
        for index, title in enumerate(request.decomposition_titles, start=1):
            candidate = f"{request.task_id}-part-{index}"
            if candidate in existing_ids:
                raise FeedbackProposalError(f"Decomposition task already exists: {candidate}")
            created_ids.append(candidate)
            tasks.append({
                "task_id": candidate,
                "title": title.strip(),
                "status": "todo",
                "duration": changes.get("duration", max(5, int(task.get("duration", 30)) // len(request.decomposition_titles))),
                "energy": task.get("energy", "medium"),
                "motivation": task.get("motivation", "medium"),
                "mode": task.get("mode", "general"),
                "blocked_by": [],
            })
        task["status"] = "paused"
        task["decomposed_into"] = created_ids
    elif request.kind == "change_task_fit":
        task = _find_task(frontmatter, request.task_id)
        allowed = {"mode", "energy", "motivation", "duration"}
        if not changes or not set(changes) <= allowed:
            raise FeedbackProposalError("Task-fit changes must use mode, energy, motivation, or duration.")
        if "duration" in changes:
            duration = changes["duration"]
            if type(duration) is not int or not 1 <= duration <= 1440:
                raise FeedbackProposalError("Duration must be from 1 to 1440 minutes.")
        for key in ("energy", "motivation"):
            if key in changes and changes[key] not in {"low", "medium", "high"}:
                raise FeedbackProposalError(f"{key} must be low, medium, or high.")
        if "mode" in changes and (not isinstance(changes["mode"], str) or not changes["mode"].strip()):
            raise FeedbackProposalError("Mode must be a non-empty string.")
        task.update(changes)
    elif request.kind in {"add_blocker", "resolve_blocker"}:
        task = _find_task(frontmatter, request.task_id)
        blocker = changes.get("blocker")
        if not isinstance(blocker, str) or not blocker.strip():
            raise FeedbackProposalError("A non-empty blocker is required.")
        blocker = blocker.strip()
        blocked = task.setdefault("blocked_by", [])
        if not isinstance(blocked, list):
            raise FeedbackProposalError("Task blocked_by must be a list.")
        if request.kind == "add_blocker" and blocker not in blocked:
            blocked.append(blocker)
        elif request.kind == "resolve_blocker":
            if blocker not in blocked:
                raise FeedbackProposalError(f"Task blocker not found: {blocker}")
            blocked.remove(blocker)
    elif request.kind in {"pause_plan", "resume_plan"}:
        frontmatter["status"] = "paused" if request.kind == "pause_plan" else "active"
    elif request.kind == "revise_review_date":
        value = changes.get("review_date")
        if not isinstance(value, str):
            raise FeedbackProposalError("Review date must be an ISO date string.")
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise FeedbackProposalError("Review date must be an ISO date string.") from exc
        frontmatter["review_date"] = parsed_date
    elif request.kind == "open_goal_review":
        frontmatter["goal_review_requested"] = True
    elif request.kind == "reduce_tracking":
        frequency = changes.get("frequency")
        if not isinstance(frequency, str) or not frequency.strip():
            raise FeedbackProposalError("Tracking frequency must be a non-empty string.")
        frontmatter["tracking_frequency"] = frequency.strip()
    elif request.kind == "disable_tracking":
        frontmatter["tracking_status"] = "disabled"
    else:
        raise FeedbackProposalError(f"Unsupported feedback proposal kind: {request.kind}")


def _proposal_body(request: FeedbackProposalRequest) -> str:
    evidence = "\n".join(f"- `{event_id}`" for event_id in request.evidence_event_ids) or "- No event IDs supplied"
    alternatives = "\n".join(f"- {item}" for item in request.alternatives) or "- Take no action"
    return (
        "## Feedback basis\n\n"
        f"**Kind:** `{request.kind}`\n\n"
        f"**Confidence:** {request.confidence}\n\n"
        f"**Expected effect:** {request.expected_effect}\n\n"
        "### Explicit evidence\n\n"
        f"{evidence}\n\n"
        "### Alternative interpretations or actions\n\n"
        f"{alternatives}\n\n"
        "> This proposal is advisory. The statistical evidence did not modify the plan directly.\n"
    )


def _existing_fingerprint(proposals_root: Path, fingerprint: str) -> str | None:
    if not proposals_root.exists():
        return None
    for child in sorted(proposals_root.iterdir()):
        if not child.is_dir():
            continue
        loaded = load_proposal_directory(child, proposals_root=proposals_root)
        if loaded.proposal is None:
            continue
        extensions = loaded.proposal.metadata.extensions
        feedback = extensions.get("feedback") if hasattr(extensions, "get") else None
        if feedback is not None and hasattr(feedback, "get") and feedback.get("evidence_fingerprint") == fingerprint:
            return loaded.proposal.metadata.id
    return None


def create_feedback_proposal(
    *,
    vault_root: Path,
    request: FeedbackProposalRequest,
    actor_id: str,
    now: datetime | None = None,
) -> FeedbackProposalResult:
    if not request.evidence_fingerprint.strip():
        raise FeedbackProposalError("Evidence fingerprint is required.")
    if not request.evidence_event_ids or any(not item.strip() for item in request.evidence_event_ids):
        raise FeedbackProposalError("At least one explicit evidence event is required.")
    if request.confidence not in {"low", "moderate", "high"}:
        raise FeedbackProposalError("Confidence must be low, moderate, or high.")
    if not request.expected_effect.strip():
        raise FeedbackProposalError("Expected effect is required.")
    if not request.alternatives or any(not item.strip() for item in request.alternatives):
        raise FeedbackProposalError("At least one alternative interpretation or action is required.")
    if not actor_id.strip():
        raise FeedbackProposalError("Actor ID is required.")
    proposals_root = vault_root / "proposals"
    duplicate = _existing_fingerprint(proposals_root, request.evidence_fingerprint)
    if duplicate:
        raise DuplicateFeedbackProposal(f"Equivalent feedback proposal already exists: {duplicate}")
    try:
        source = read_vault_markdown(vault_root, request.target_path)
    except VaultAccessError as exc:
        raise FeedbackProposalError(str(exc)) from exc
    parsed = parse_markdown_note(source.path, content=source.content)
    if any(item.severity == "error" for item in parsed.findings):
        raise FeedbackProposalError("Target note is structurally invalid.")
    updated_frontmatter = copy.deepcopy(dict(parsed.frontmatter))
    _apply_change(updated_frontmatter, request)
    updated_content = _frontmatter_document(updated_frontmatter, parsed.body, preserve_body=True)
    if updated_content == source.content:
        raise FeedbackProposalError("The proposed change has no effect.")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise FeedbackProposalError("Proposal timestamp must be timezone-aware.")
    utc = moment.astimezone(timezone.utc)
    suffix = hashlib.sha256(request.evidence_fingerprint.encode("utf-8")).hexdigest()[:8]
    proposal_id = generate_proposal_id(lambda: utc, lambda: suffix)
    timestamp = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    base_hash = f"sha256:{content_hash(source.content)}"
    diff_lines = tuple(
        difflib.unified_diff(
            source.content.splitlines(keepends=True),
            updated_content.splitlines(keepends=True),
            fromfile=request.target_path,
            tofile=request.target_path,
        )
    )
    diff = "".join(diff_lines[2:])
    patch = PatchHumanFile("op-feedback-plan-update", request.target_path, base_hash, diff)
    patch_document = PatchDocumentV2(2, proposal_id, (patch,))
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Feedback proposal: {request.kind.replace('_', ' ')}",
        description=request.expected_effect,
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
        related_goals=tuple(filter(None, (str(parsed.frontmatter.get("goal") or ""),))),
        related_sources=(request.target_path, *request.evidence_event_ids),
        extensions={"feedback": {"kind": request.kind, "evidence_fingerprint": request.evidence_fingerprint, "confidence": request.confidence}},
    )
    proposal_markdown = serialize_proposal_markdown(metadata, _proposal_body(request))
    patches_json = serialize_patch_json_bytes(patch_document)
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=vault_root,
        patches_json=patches_json,
    )
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
        raise FeedbackProposalError(f"Could not publish feedback proposal: {exc}") from exc
    finally:
        if dir_fd >= 0:
            os.close(dir_fd)
        if created and not published:
            shutil.rmtree(proposal_dir, ignore_errors=True)
    return FeedbackProposalResult(proposal_id, f"proposals/{proposal_id}", request.target_path, base_hash, request.evidence_fingerprint, request.kind)
