"""Proposal-only publication of selected goal-to-plan copilot drafts."""

from __future__ import annotations

import copy
import difflib
import hashlib
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.daily.service import _frontmatter_document, content_hash as raw_content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import CreateFile, PatchDocumentV2, PatchHumanFile, serialize_patch_json_bytes
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus, generate_proposal_id
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.vault import VaultAccessError, read_vault_markdown

from .contracts import CopilotIndex, PlanOption
from .decomposition import DecompositionResult
from .sessions import PlanningSessionService, SessionConflictError

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_ALLOWED_GOAL_FIELDS = frozenset({
    "title", "why", "desired_change", "horizon", "constraints", "non_goals",
    "review_cadence", "readiness",
})


class CopilotProposalError(ValueError):
    """Raised before publishing an unsafe or stale copilot proposal."""


@dataclass(frozen=True, slots=True)
class ConflictPlanEdit:
    target_path: str
    action: Literal["pause", "supersede"]


@dataclass(frozen=True, slots=True)
class CopilotProposalRequest:
    session_id: str
    expected_session_revision: int
    goal_path: str
    expected_goal_hash: str
    plan_id: str
    plan_path: str
    plan_title: str
    desired_outcome: str
    included_milestone_ids: tuple[str, ...]
    included_action_ids: tuple[str, ...]
    milestone_edits: Mapping[str, Mapping[str, Any]]
    action_edits: Mapping[str, Mapping[str, Any]]
    goal_updates: Mapping[str, Any]
    link_goal: bool = True
    conflict_edits: tuple[ConflictPlanEdit, ...] = ()


@dataclass(frozen=True, slots=True)
class CopilotProposalResult:
    proposal_id: str
    proposal_path: str
    plan_path: str
    base_hashes: tuple[tuple[str, str], ...]
    operation_kinds: tuple[str, ...]
    selected_option_id: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def create_copilot_plan_proposal(
    *,
    vault_root: Path,
    option: PlanOption,
    decomposition: DecompositionResult,
    index: CopilotIndex,
    request: CopilotProposalRequest,
    actor_id: str,
    session_service: PlanningSessionService | None = None,
    now: datetime | None = None,
) -> CopilotProposalResult:
    """Publish a draft proposal. It never mutates canonical goal or plan files."""
    _validate_request(request, option=option, decomposition=decomposition, index=index, vault_root=vault_root)
    if not actor_id.strip():
        raise CopilotProposalError("actor_id is required")
    if session_service is not None:
        snapshot = session_service.get(request.session_id)
        session = snapshot.envelope.session
        if session.source_revision != request.expected_session_revision:
            raise SessionConflictError(
                f"session revision is stale: expected {request.expected_session_revision}, current {session.source_revision}"
            )
        if session.goal_ref != request.goal_path or session.goal_hash != request.expected_goal_hash:
            raise CopilotProposalError("planning session does not match the visible goal draft")

    try:
        goal_source = read_vault_markdown(vault_root, request.goal_path)
    except VaultAccessError as exc:
        raise CopilotProposalError(str(exc)) from exc
    goal_base = _hash(goal_source.content)
    if goal_base != request.expected_goal_hash:
        raise CopilotProposalError("goal changed after the visible draft was prepared")
    goal_parsed = parse_markdown_note(goal_source.path, content=goal_source.content)
    if any(item.severity == "error" for item in goal_parsed.findings):
        raise CopilotProposalError("goal note is structurally invalid")
    goal_id = goal_parsed.frontmatter.get("id")
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise CopilotProposalError("goal note has no stable id")

    selected_milestones = _selected_milestones(option, request)
    selected_actions = _selected_actions(decomposition, request, selected_milestones)
    conflict_ops, conflict_hashes, supersedes = _conflict_operations(
        vault_root=vault_root, request=request
    )
    plan_content = _plan_document(
        request=request,
        option=option,
        goal_id=goal_id,
        milestones=selected_milestones,
        actions=selected_actions,
        supersedes=supersedes,
    )
    operations: list[Any] = [
        CreateFile("op-create-plan", request.plan_path, "absent", plan_content)
    ]
    base_hashes: list[tuple[str, str]] = []

    updated_goal = copy.deepcopy(dict(goal_parsed.frontmatter))
    _apply_goal_updates(updated_goal, request.goal_updates)
    if request.link_goal:
        refs = updated_goal.get("active_plans", [])
        if refs is None:
            refs = []
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise CopilotProposalError("goal active_plans must be a list of strings")
        if request.plan_id not in refs:
            refs.append(request.plan_id)
        updated_goal["active_plans"] = sorted(set(refs))
    updated_goal_content = _frontmatter_document(updated_goal, goal_parsed.body)
    if updated_goal_content != goal_source.content:
        operations.append(PatchHumanFile(
            "op-update-goal", request.goal_path, goal_base,
            _diff(goal_source.content, updated_goal_content, request.goal_path),
        ))
        base_hashes.append((request.goal_path, goal_base))
    operations.extend(conflict_ops)
    base_hashes.extend(conflict_hashes)

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise CopilotProposalError("proposal timestamp must be timezone-aware")
    utc = moment.astimezone(timezone.utc)
    fingerprint = _fingerprint(request, option, plan_content, base_hashes)
    proposal_id = generate_proposal_id(lambda: utc, lambda: fingerprint[:8])
    timestamp = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    patch_doc = PatchDocumentV2(2, proposal_id, tuple(operations))
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Create plan: {request.plan_title}",
        description="Create the selected goal-to-plan draft through reviewable canonical patches.",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.HIGH if request.conflict_edits else ProposalRisk.MEDIUM,
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
        related_goals=(goal_id,),
        related_sources=tuple(dict.fromkeys((request.goal_path, *option.source_refs, *(edit.target_path for edit in request.conflict_edits)))),
        extensions={
            "goal_to_plan": {
                "session_id": request.session_id,
                "selected_option_id": option.option_id,
                "included_milestone_ids": list(request.included_milestone_ids),
                "included_action_ids": list(request.included_action_ids),
                "draft_fingerprint": fingerprint,
            }
        },
    )
    body = _proposal_body(request, option, selected_milestones, selected_actions)
    _publish(
        vault_root=vault_root,
        proposal_id=proposal_id,
        proposal_markdown=serialize_proposal_markdown(metadata, body),
        patches_json=serialize_patch_json_bytes(patch_doc),
    )
    if session_service is not None:
        session_service.attach_proposal(
            session_id=request.session_id,
            proposal_id=proposal_id,
            selected_option_id=option.option_id,
            expected_revision=request.expected_session_revision,
        )
    return CopilotProposalResult(
        proposal_id,
        f"proposals/{proposal_id}",
        request.plan_path,
        tuple(sorted(base_hashes)),
        tuple(operation.op for operation in operations),
        option.option_id,
    )


def _validate_request(request: CopilotProposalRequest, *, option: PlanOption, decomposition: DecompositionResult, index: CopilotIndex, vault_root: Path) -> None:
    if decomposition.option_id != option.option_id:
        raise CopilotProposalError("decomposition does not match the selected option")
    for identifier, label in ((request.plan_id, "plan_id"), (request.session_id, "session_id")):
        if not _ID_RE.match(identifier):
            raise CopilotProposalError(f"{label} is invalid")
    if not request.plan_path.startswith("plans/") or not request.plan_path.endswith(".md") or ".." in Path(request.plan_path).parts:
        raise CopilotProposalError("plan_path must be a safe plans/*.md path")
    if (vault_root / request.plan_path).exists():
        raise CopilotProposalError("target plan already exists")
    if any(plan.plan_id == request.plan_id for plan in index.plans):
        raise CopilotProposalError(f"duplicate plan id: {request.plan_id}")
    if not request.plan_title.strip() or not request.desired_outcome.strip():
        raise CopilotProposalError("plan_title and desired_outcome are required")
    if not request.included_milestone_ids:
        raise CopilotProposalError("at least one milestone must be included")
    option_milestones = {item.milestone_id for item in option.milestones}
    if not set(request.included_milestone_ids) <= option_milestones:
        raise CopilotProposalError("included milestone id is not in the visible option")
    action_ids = {item.action.task_id for item in decomposition.actions}
    if not set(request.included_action_ids) <= action_ids:
        raise CopilotProposalError("included action id is not in the visible decomposition")
    existing_task_ids = {task.task_id for plan in index.plans for task in plan.tasks}
    duplicates = existing_task_ids & set(request.included_action_ids)
    if duplicates:
        raise CopilotProposalError(f"duplicate task ids: {', '.join(sorted(duplicates))}")
    if not set(request.goal_updates) <= _ALLOWED_GOAL_FIELDS:
        raise CopilotProposalError("goal_updates contains unsupported fields")
    if not set(request.milestone_edits) <= set(request.included_milestone_ids):
        raise CopilotProposalError("milestone edits must target included milestones")
    if not set(request.action_edits) <= set(request.included_action_ids):
        raise CopilotProposalError("action edits must target included actions")
    paths = [edit.target_path for edit in request.conflict_edits]
    if len(paths) != len(set(paths)) or request.goal_path in paths or request.plan_path in paths:
        raise CopilotProposalError("conflict edit targets must be unique and distinct")


def _selected_milestones(option: PlanOption, request: CopilotProposalRequest) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for milestone in option.milestones:
        if milestone.milestone_id not in request.included_milestone_ids:
            continue
        data = milestone.to_dict()
        edits = dict(request.milestone_edits.get(milestone.milestone_id, {}))
        if not set(edits) <= {"title", "outcome", "target_date", "wave"}:
            raise CopilotProposalError("milestone edit contains unsupported fields")
        data.update(edits)
        if not isinstance(data.get("title"), str) or not data["title"].strip() or not isinstance(data.get("outcome"), str) or not data["outcome"].strip():
            raise CopilotProposalError("edited milestone title and outcome are required")
        result.append(data)
    return tuple(result)


def _selected_actions(decomposition: DecompositionResult, request: CopilotProposalRequest, milestones: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    milestone_ids = {str(item["milestone_id"]) for item in milestones}
    result: list[dict[str, Any]] = []
    for generated in decomposition.actions:
        action = generated.action
        if action.task_id not in request.included_action_ids:
            continue
        if action.milestone_id not in milestone_ids:
            raise CopilotProposalError(f"included action {action.task_id} belongs to an excluded milestone")
        data = action.to_dict()
        data["verification"] = generated.verification
        data["kind"] = generated.kind
        edits = dict(request.action_edits.get(action.task_id, {}))
        if not set(edits) <= {"title", "duration", "energy", "motivation", "mode", "due", "blocked_by", "rationale", "verification"}:
            raise CopilotProposalError("action edit contains unsupported fields")
        data.update(edits)
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            raise CopilotProposalError("edited action title is required")
        duration = data.get("duration")
        if duration is not None and (type(duration) is not int or not 1 <= duration <= 1440):
            raise CopilotProposalError("edited action duration must be 1..1440 or unknown")
        result.append(data)
    return tuple(result)


def _plan_document(*, request: CopilotProposalRequest, option: PlanOption, goal_id: str, milestones: Sequence[Mapping[str, Any]], actions: Sequence[Mapping[str, Any]], supersedes: str | None) -> str:
    frontmatter: dict[str, Any] = {
        "copilot_schema_version": 1,
        "id": request.plan_id,
        "type": "plan",
        "title": request.plan_title.strip(),
        "status": "seed",
        "goal": goal_id,
        "desired_outcome": request.desired_outcome.strip(),
        "success_evidence": list(option.success_evidence),
        "boundaries": list(option.boundaries),
        "assumptions": [item.statement for item in option.assumptions],
        "review_date": option.review_date,
        "milestones": list(milestones),
        "tasks": list(actions),
        "rolling_wave_depth": decomposition_depth(option),
    }
    if supersedes:
        frontmatter["supersedes"] = supersedes
    body = (
        "# Plan intent\n\n"
        f"{option.strategy}\n\n"
        "## Tradeoffs\n\n"
        + ("\n".join(f"- {item}" for item in option.tradeoffs) or "- None recorded")
        + "\n\n## Unresolved questions\n\n"
        + ("\n".join(f"- {item}" for item in option.unresolved_questions) or "- None")
        + "\n"
    )
    return _frontmatter_document(frontmatter, body)


def decomposition_depth(option: PlanOption) -> int:
    return 1 if option.confidence_label == "low" else 2


def _apply_goal_updates(frontmatter: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        if key in {"constraints", "non_goals"}:
            if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in value):
                raise CopilotProposalError(f"{key} must be a list of non-empty strings")
            frontmatter[key] = list(value)
        elif value is None:
            frontmatter.pop(key, None)
        elif not isinstance(value, str) or not value.strip():
            raise CopilotProposalError(f"{key} must be a non-empty string or null")
        else:
            frontmatter[key] = value.strip()


def _conflict_operations(*, vault_root: Path, request: CopilotProposalRequest) -> tuple[list[PatchHumanFile], list[tuple[str, str]], str | None]:
    operations: list[PatchHumanFile] = []
    hashes: list[tuple[str, str]] = []
    supersedes: str | None = None
    for index, edit in enumerate(sorted(request.conflict_edits, key=lambda item: item.target_path), start=1):
        try:
            source = read_vault_markdown(vault_root, edit.target_path)
        except VaultAccessError as exc:
            raise CopilotProposalError(str(exc)) from exc
        parsed = parse_markdown_note(source.path, content=source.content)
        fm = copy.deepcopy(dict(parsed.frontmatter))
        if fm.get("type") != "plan" or not isinstance(fm.get("id"), str):
            raise CopilotProposalError(f"conflict target is not a valid plan: {edit.target_path}")
        if edit.action == "pause":
            fm["status"] = "paused"
        else:
            if supersedes is not None:
                raise CopilotProposalError("only one plan can be explicitly superseded by a new plan")
            supersedes = fm["id"]
            fm["status"] = "superseded"
            fm["superseded_by"] = request.plan_id
        updated = _frontmatter_document(fm, parsed.body)
        base = _hash(source.content)
        operations.append(PatchHumanFile(f"op-conflict-{index}", edit.target_path, base, _diff(source.content, updated, edit.target_path)))
        hashes.append((edit.target_path, base))
    return operations, hashes, supersedes


def _proposal_body(request: CopilotProposalRequest, option: PlanOption, milestones: Sequence[Mapping[str, Any]], actions: Sequence[Mapping[str, Any]]) -> str:
    milestone_lines = "\n".join(f"- `{item['milestone_id']}`: {item['title']}" for item in milestones)
    action_lines = "\n".join(f"- `{item['task_id']}`: {item['title']}" for item in actions) or "- No near-term actions selected"
    conflicts = "\n".join(f"- `{item.action}` `{item.target_path}`" for item in request.conflict_edits) or "- None"
    return (
        "## Visible draft selection\n\n"
        f"**Planning session:** `{request.session_id}`\n\n"
        f"**Selected option:** `{option.option_id}`\n\n"
        f"**Target plan:** `{request.plan_path}`\n\n"
        "### Included milestones\n\n" + milestone_lines + "\n\n"
        "### Included near-term actions\n\n" + action_lines + "\n\n"
        "### Explicit conflict edits\n\n" + conflicts + "\n\n"
        "> This draft does not change canonical Markdown until separately submitted, approved, and applied.\n"
    )


def _publish(*, vault_root: Path, proposal_id: str, proposal_markdown: bytes, patches_json: bytes) -> None:
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=vault_root,
        patches_json=patches_json,
    )
    root = vault_root / "proposals"
    root.mkdir(parents=True, exist_ok=True)
    proposal_dir = root / proposal_id
    created = False
    published = False
    fd = -1
    try:
        proposal_dir.mkdir(exist_ok=False)
        created = True
        fd = os.open(proposal_dir, os.O_RDONLY | os.O_DIRECTORY)
        atomic_write_file_secure(fd, "proposal.md", proposal_markdown)
        atomic_write_file_secure(fd, "patches.json", patches_json)
        atomic_write_file_secure(fd, "review.json", review_json)
        published = True
    except (OSError, AtomicWriteError) as exc:
        raise CopilotProposalError(f"could not publish copilot proposal: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if created and not published:
            shutil.rmtree(proposal_dir, ignore_errors=True)


def _diff(before: str, after: str, path: str) -> str:
    lines = tuple(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=path, tofile=path))
    result = "".join(lines[2:])
    if not result:
        raise CopilotProposalError(f"proposed patch has no effect: {path}")
    return result


def _hash(content: str) -> str:
    return f"sha256:{raw_content_hash(content)}"


def _fingerprint(request: CopilotProposalRequest, option: PlanOption, plan_content: str, hashes: Sequence[tuple[str, str]]) -> str:
    payload = repr((request.session_id, option.option_id, request.plan_path, plan_content, tuple(sorted(hashes)), tuple(sorted(request.goal_updates.items()))))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
