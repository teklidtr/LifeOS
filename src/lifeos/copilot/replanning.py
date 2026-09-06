"""Living goal and plan review loops with proposal-only consequential changes."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from lifeos.proposals.publication import (
    ProposalDocuments,
    ProposalPublicationError,
    publish_proposal_documents,
)
from lifeos.daily import load_execution_records
from lifeos.daily.service import _frontmatter_document, content_hash as raw_content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import PatchDocumentV2, PatchHumanFile, serialize_patch_json_bytes
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalRisk,
    ProposalStatus,
    generate_proposal_id,
)
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.vault import VaultAccessError, read_vault_markdown

from .contracts import PlanOption, PlanRecord, build_copilot_index

TriggerCode = Literal[
    "goal-no-active-plan",
    "plan-no-feasible-next-action",
    "milestone-completed",
    "repeated-avoidance",
    "constraints-changed",
    "assumptions-stale",
    "review-date-approaching",
]
ReplanningOutcome = Literal[
    "continue-unchanged",
    "adjust-next-wave",
    "revise-scope",
    "split",
    "merge",
    "pause",
    "supersede",
    "close",
    "return-to-experiment",
    "reopen-clarification",
]


class ReplanningError(ValueError):
    """Raised when a living review is stale, malformed, or unsafe."""


@dataclass(frozen=True, slots=True)
class ReplanningTrigger:
    trigger_id: str
    code: TriggerCode
    severity: Literal["information", "attention", "important"]
    target_kind: Literal["goal", "plan"]
    target_id: str
    target_path: str
    title: str
    detail: str
    evidence_refs: tuple[str, ...]
    evidence_fingerprint: str
    possible_outcomes: tuple[ReplanningOutcome, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    evidence_id: str
    kind: Literal[
        "execution", "correction", "review-answer", "canonical-change", "deterministic-fact"
    ]
    statement: str
    source_ref: str | None = None
    observed_at: date | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["observed_at"] = self.observed_at.isoformat() if self.observed_at else None
        return data


@dataclass(frozen=True, slots=True)
class ReplanningComparison:
    dimension: str
    original_value: str
    current_value: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReplanningReview:
    schema_version: int
    review_id: str
    target_kind: Literal["goal", "plan"]
    target_id: str
    target_path: str
    target_hash: str
    original_option_id: str | None
    triggers: tuple[ReplanningTrigger, ...]
    comparisons: tuple[ReplanningComparison, ...]
    evidence: tuple[ReviewEvidence, ...]
    outcomes: tuple[ReplanningOutcome, ...]
    recommended_outcomes: tuple[ReplanningOutcome, ...]
    questions: tuple[str, ...]
    lineage: tuple[str, ...]
    generated_as_of: date

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "triggers": [item.to_dict() for item in self.triggers],
            "comparisons": [item.to_dict() for item in self.comparisons],
            "evidence": [item.to_dict() for item in self.evidence],
            "generated_as_of": self.generated_as_of.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ReplanningProposalRequest:
    review_id: str
    target_path: str
    expected_hash: str
    outcome: ReplanningOutcome
    rationale: str
    evidence_fingerprint: str
    changes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReplanningProposalResult:
    proposal_id: str
    proposal_path: str
    target_path: str
    base_hash: str
    outcome: ReplanningOutcome

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_OUTCOMES: tuple[ReplanningOutcome, ...] = (
    "continue-unchanged",
    "adjust-next-wave",
    "revise-scope",
    "split",
    "merge",
    "pause",
    "supersede",
    "close",
    "return-to-experiment",
    "reopen-clarification",
)


def scan_replanning_triggers(
    *, vault_root: Path, runtime_dir: Path, as_of: date
) -> tuple[ReplanningTrigger, ...]:
    """Scan current canonical state. Exact rejected fingerprints stay suppressed."""
    index = build_copilot_index(vault_root)
    suppressions = _load_suppressions(runtime_dir)
    candidates: list[ReplanningTrigger] = []
    active_plans = tuple(
        plan for plan in index.plans if plan.status in {"active", "seed", "needs-review"}
    )
    plan_by_goal: dict[str, list[PlanRecord]] = {}
    for plan in active_plans:
        if plan.goal_ref:
            plan_by_goal.setdefault(_reference_id(plan.goal_ref), []).append(plan)

    for goal in index.goals:
        if goal.status in {"active", "seed", "needs-review"} and not plan_by_goal.get(goal.goal_id):
            candidates.append(
                _trigger(
                    "goal-no-active-plan",
                    "attention",
                    "goal",
                    goal.goal_id,
                    goal.path,
                    "Goal has no active plan",
                    "The goal remains active, but no current plan references it. Continuing without a plan is still a valid choice.",
                    (goal.content_hash,),
                    ("continue-unchanged", "reopen-clarification", "return-to-experiment"),
                )
            )
    for plan in active_plans:
        actionable = [
            task
            for task in plan.tasks
            if task.status in {"todo", "active", "pending"} and not task.blocked_by
        ]
        if not actionable:
            candidates.append(
                _trigger(
                    "plan-no-feasible-next-action",
                    "important",
                    "plan",
                    plan.plan_id,
                    plan.path,
                    "Plan has no feasible next action",
                    "No visible active task is both incomplete and unblocked. Review prerequisites or the next wave instead of endlessly moving dates.",
                    (plan.content_hash, *tuple(task.task_id for task in plan.tasks)),
                    (
                        "adjust-next-wave",
                        "revise-scope",
                        "pause",
                        "return-to-experiment",
                        "continue-unchanged",
                    ),
                )
            )
        completed = tuple(m for m in plan.milestones if m.status in {"done", "completed"})
        remaining = tuple(
            m for m in plan.milestones if m.status not in {"done", "completed", "cancelled"}
        )
        if completed and remaining:
            candidates.append(
                _trigger(
                    "milestone-completed",
                    "information",
                    "plan",
                    plan.plan_id,
                    plan.path,
                    "A milestone is complete; review the next wave",
                    "Completed evidence exists while later milestones remain intentionally coarse.",
                    (plan.content_hash, *tuple(item.milestone_id for item in completed)),
                    ("adjust-next-wave", "continue-unchanged", "revise-scope", "close"),
                )
            )
        if plan.review_date is not None and plan.review_date <= as_of + timedelta(days=14):
            candidates.append(
                _trigger(
                    "review-date-approaching",
                    "attention" if plan.review_date >= as_of else "important",
                    "plan",
                    plan.plan_id,
                    plan.path,
                    "Plan review date is approaching"
                    if plan.review_date >= as_of
                    else "Plan review date has passed",
                    f"The current review date is {plan.review_date.isoformat()}.",
                    (plan.content_hash, plan.review_date.isoformat()),
                    ("continue-unchanged", "adjust-next-wave", "revise-scope", "pause", "close"),
                )
            )
        if plan.assumptions and plan.review_date is not None and plan.review_date <= as_of:
            candidates.append(
                _trigger(
                    "assumptions-stale",
                    "attention",
                    "plan",
                    plan.plan_id,
                    plan.path,
                    "Plan assumptions need reconfirmation",
                    "The review date has arrived while visible assumptions still underpin the plan.",
                    (plan.content_hash, *plan.assumptions),
                    ("continue-unchanged", "revise-scope", "return-to-experiment", "pause"),
                )
            )

    try:
        records = load_execution_records(vault_root)
    except Exception:
        records = ()
    by_task: dict[tuple[str, str], list[Any]] = {}
    for record in records:
        if record.outcome in {"skipped", "deferred", "partial"}:
            by_task.setdefault((record.plan_path, record.task_id), []).append(record)
    plans_by_path = {plan.path: plan for plan in index.plans}
    for (path, task_id), events in sorted(by_task.items()):
        if len(events) < 2 or path not in plans_by_path:
            continue
        plan = plans_by_path[path]
        reasons = tuple(sorted({item.reason for item in events if item.reason}))
        detail = f"{len(events)} incomplete attempts are visible. " + (
            f"Competing explanations include: {', '.join(reasons)}."
            if reasons
            else "The reason remains unknown and should be clarified."
        )
        candidates.append(
            _trigger(
                "repeated-avoidance",
                "attention",
                "plan",
                plan.plan_id,
                path,
                f"Repeated friction around {task_id}",
                detail,
                tuple(item.event_id for item in events),
                (
                    "adjust-next-wave",
                    "revise-scope",
                    "pause",
                    "return-to-experiment",
                    "reopen-clarification",
                    "continue-unchanged",
                ),
            )
        )

    visible = [
        item
        for item in candidates
        if suppressions.get(item.trigger_id) != item.evidence_fingerprint
    ]
    return tuple(
        sorted(
            visible,
            key=lambda item: (
                _severity_rank(item.severity),
                item.target_path,
                item.code,
                item.trigger_id,
            ),
        )
    )


def build_replanning_review(
    *,
    vault_root: Path,
    runtime_dir: Path,
    target_path: str,
    as_of: date,
    original_option: PlanOption | None = None,
    corrections: Sequence[ReviewEvidence] = (),
    recent_answers: Sequence[ReviewEvidence] = (),
    expected_hash: str | None = None,
) -> ReplanningReview:
    try:
        source = read_vault_markdown(vault_root, target_path)
    except VaultAccessError as exc:
        raise ReplanningError(str(exc)) from exc
    current_hash = _hash(source.content)
    if expected_hash is not None and current_hash != expected_hash:
        raise ReplanningError("canonical source changed during replanning review")
    parsed = parse_markdown_note(source.path, content=source.content)
    fm = dict(parsed.frontmatter)
    target_kind = fm.get("type")
    if target_kind not in {"goal", "plan"} or not isinstance(fm.get("id"), str):
        raise ReplanningError("target must be a canonical goal or plan")
    all_triggers = scan_replanning_triggers(
        vault_root=vault_root, runtime_dir=runtime_dir, as_of=as_of
    )
    triggers = tuple(item for item in all_triggers if item.target_path == target_path)
    evidence = tuple(
        sorted((*corrections, *recent_answers), key=lambda item: (item.kind, item.evidence_id))
    )
    changed_dimensions = _changed_dimensions(evidence)
    if changed_dimensions:
        triggers = (
            *triggers,
            _trigger(
                "constraints-changed",
                "attention",
                target_kind,
                fm["id"],
                target_path,
                "Planning conditions changed",
                "Explicit review evidence changed: " + ", ".join(changed_dimensions) + ".",
                tuple(item.evidence_id for item in evidence),
                (
                    "continue-unchanged",
                    "adjust-next-wave",
                    "revise-scope",
                    "pause",
                    "return-to-experiment",
                ),
            ),
        )
    comparisons = _comparisons(fm, original_option, evidence)
    recommended = _recommended_outcomes(triggers, evidence)
    questions = _review_questions(triggers, evidence)
    lineage_raw = fm.get("decision_lineage", [])
    lineage = (
        tuple(
            str(item.get("decision_id"))
            for item in lineage_raw
            if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
        )
        if isinstance(lineage_raw, list)
        else ()
    )
    review_id = (
        "replan-"
        + hashlib.sha256(
            f"{target_path}\0{current_hash}\0{as_of.isoformat()}".encode()
        ).hexdigest()[:20]
    )
    return ReplanningReview(
        1,
        review_id,
        target_kind,
        fm["id"],
        target_path,
        current_hash,
        original_option.option_id if original_option else None,
        triggers,
        comparisons,
        evidence,
        _OUTCOMES,
        recommended,
        questions,
        lineage,
        as_of,
    )


def suppress_replanning_suggestion(
    *, runtime_dir: Path, trigger_id: str, evidence_fingerprint: str
) -> None:
    if not trigger_id.strip() or not evidence_fingerprint.startswith("sha256:"):
        raise ReplanningError("trigger_id and sha256 evidence fingerprint are required")
    values = _load_suppressions(runtime_dir)
    values[trigger_id] = evidence_fingerprint
    path = runtime_dir / "replanning" / "suppressed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def create_replanning_proposal(
    *,
    vault_root: Path,
    request: ReplanningProposalRequest,
    actor_id: str,
    now: datetime | None = None,
) -> ReplanningProposalResult | None:
    """Create a reviewable patch for a selected review outcome; never apply it."""
    if request.outcome == "continue-unchanged":
        return None
    if request.outcome not in _OUTCOMES:
        raise ReplanningError("unsupported replanning outcome")
    if not request.rationale.strip():
        raise ReplanningError("a visible rationale is required")
    try:
        source = read_vault_markdown(vault_root, request.target_path)
    except VaultAccessError as exc:
        raise ReplanningError(str(exc)) from exc
    base_hash = _hash(source.content)
    if base_hash != request.expected_hash:
        raise ReplanningError("replanning target changed after review")
    parsed = parse_markdown_note(source.path, content=source.content)
    fm = copy.deepcopy(dict(parsed.frontmatter))
    if fm.get("type") not in {"goal", "plan"} or not isinstance(fm.get("id"), str):
        raise ReplanningError("replanning target is not a goal or plan")
    _apply_outcome(fm, request)
    lineage = fm.get("decision_lineage", [])
    if lineage is None:
        lineage = []
    if not isinstance(lineage, list):
        raise ReplanningError("decision_lineage must be a list")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ReplanningError("proposal timestamp must be timezone-aware")
    utc = moment.astimezone(timezone.utc)
    decision_id = (
        "decision-"
        + hashlib.sha256(
            f"{request.review_id}\0{request.outcome}\0{request.evidence_fingerprint}".encode()
        ).hexdigest()[:16]
    )
    lineage.append(
        {
            "decision_id": decision_id,
            "review_id": request.review_id,
            "outcome": request.outcome,
            "rationale": request.rationale.strip(),
            "evidence_fingerprint": request.evidence_fingerprint,
            "source_hash": base_hash,
            "decided_at": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    fm["decision_lineage"] = lineage
    updated = _frontmatter_document(fm, parsed.body, preserve_body=True)
    if updated == source.content:
        raise ReplanningError("selected review outcome has no visible effect")
    suffix = hashlib.sha256(
        f"{request.review_id}\0{request.outcome}\0{base_hash}".encode()
    ).hexdigest()[:8]
    proposal_id = generate_proposal_id(lambda: utc, lambda: suffix)
    patch = PatchHumanFile(
        "op-replanning-update",
        request.target_path,
        base_hash,
        _diff(source.content, updated, request.target_path),
    )
    patch_document = PatchDocumentV2(2, proposal_id, (patch,))
    timestamp = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Replanning proposal: {request.outcome.replace('-', ' ')}",
        description=request.rationale.strip(),
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.HIGH
        if request.outcome in {"supersede", "split", "merge", "close"}
        else ProposalRisk.MEDIUM,
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
        related_goals=tuple(filter(None, (str(fm.get("goal") or fm.get("id") or ""),))),
        related_sources=(request.target_path,),
        extensions={
            "replanning": {
                "review_id": request.review_id,
                "outcome": request.outcome,
                "evidence_fingerprint": request.evidence_fingerprint,
                "decision_id": decision_id,
            }
        },
    )
    body = (
        "## Living-plan review\n\n"
        f"**Review:** `{request.review_id}`\n\n"
        f"**Selected outcome:** `{request.outcome}`\n\n"
        f"**Rationale:** {request.rationale.strip()}\n\n"
        "> Execution evidence prompted this review but did not rewrite intent automatically.\n"
    )
    _publish(
        vault_root=vault_root,
        proposal_id=proposal_id,
        proposal_markdown=serialize_proposal_markdown(metadata, body),
        patches_json=serialize_patch_json_bytes(patch_document),
    )
    return ReplanningProposalResult(
        proposal_id, f"proposals/{proposal_id}", request.target_path, base_hash, request.outcome
    )


def _apply_outcome(fm: dict[str, Any], request: ReplanningProposalRequest) -> None:
    changes = dict(request.changes)
    outcome = request.outcome
    if outcome == "adjust-next-wave":
        allowed = {"milestones", "tasks", "review_date"}
        if not changes or not set(changes) <= allowed:
            raise ReplanningError("adjust-next-wave requires milestones, tasks, or review_date")
        for key, value in changes.items():
            fm[key] = value
    elif outcome == "revise-scope":
        allowed = {"desired_outcome", "boundaries", "success_evidence", "constraints", "non_goals"}
        if not changes or not set(changes) <= allowed:
            raise ReplanningError("revise-scope contains unsupported fields")
        fm.update(changes)
    elif outcome == "split":
        targets = changes.get("split_into")
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(item, str) and item.strip() for item in targets)
        ):
            raise ReplanningError("split requires visible target plan IDs")
        fm["status"] = "superseded"
        fm["split_into"] = targets
    elif outcome == "merge":
        target = changes.get("merged_into")
        if not isinstance(target, str) or not target.strip():
            raise ReplanningError("merge requires merged_into")
        fm["status"] = "superseded"
        fm["merged_into"] = target.strip()
    elif outcome == "pause":
        fm["status"] = "paused"
    elif outcome == "supersede":
        target = changes.get("superseded_by")
        if not isinstance(target, str) or not target.strip():
            raise ReplanningError("supersede requires superseded_by")
        fm["status"] = "superseded"
        fm["superseded_by"] = target.strip()
    elif outcome == "close":
        fm["status"] = "closed"
    elif outcome == "return-to-experiment":
        fm["status"] = "paused" if fm.get("type") == "plan" else fm.get("status", "active")
        fm["planning_mode"] = "experiment"
        if "experiment_ref" in changes:
            fm["experiment_ref"] = changes["experiment_ref"]
    elif outcome == "reopen-clarification":
        if fm.get("type") == "goal":
            fm["readiness"] = "clarifying"
        else:
            fm["goal_review_requested"] = True
    else:
        raise ReplanningError("unsupported consequential outcome")


def _comparisons(
    fm: Mapping[str, Any], original: PlanOption | None, evidence: Sequence[ReviewEvidence]
) -> tuple[ReplanningComparison, ...]:
    if original is None:
        return (
            ReplanningComparison(
                "historical-option",
                "Not available",
                "Current canonical state remains authoritative.",
                tuple(item.evidence_id for item in evidence),
            ),
        )
    current_outcome = str(fm.get("desired_outcome") or "Unknown")
    current_boundaries = _render_collection(fm.get("boundaries", fm.get("non_goals", [])))
    current_review = str(fm.get("review_date") or "Open")
    return (
        ReplanningComparison(
            "desired outcome",
            original.desired_outcome,
            current_outcome,
            tuple(original.source_refs),
        ),
        ReplanningComparison(
            "scope boundaries",
            "; ".join(original.boundaries) or "None",
            current_boundaries,
            tuple(original.source_refs),
        ),
        ReplanningComparison(
            "review date",
            original.review_date.isoformat() if original.review_date else "Open",
            current_review,
            tuple(item.evidence_id for item in evidence),
        ),
        ReplanningComparison(
            "execution evidence",
            "Not part of original intent",
            f"{len([item for item in evidence if item.kind == 'execution'])} visible records",
            tuple(item.evidence_id for item in evidence if item.kind == "execution"),
        ),
    )


def _recommended_outcomes(
    triggers: Sequence[ReplanningTrigger], evidence: Sequence[ReviewEvidence]
) -> tuple[ReplanningOutcome, ...]:
    codes = {item.code for item in triggers}
    outcomes: list[ReplanningOutcome] = ["continue-unchanged"]
    if "milestone-completed" in codes or "plan-no-feasible-next-action" in codes:
        outcomes.append("adjust-next-wave")
    if (
        "repeated-avoidance" in codes
        or "assumptions-stale" in codes
        or "constraints-changed" in codes
    ):
        outcomes.extend(("revise-scope", "return-to-experiment"))
    if "goal-no-active-plan" in codes:
        outcomes.append("reopen-clarification")
    if any(item.kind == "correction" for item in evidence):
        outcomes.append("revise-scope")
    return tuple(dict.fromkeys(outcomes))


def _review_questions(
    triggers: Sequence[ReplanningTrigger], evidence: Sequence[ReviewEvidence]
) -> tuple[str, ...]:
    questions: list[str] = []
    codes = {item.code for item in triggers}
    if "repeated-avoidance" in codes:
        questions.append(
            "Is the friction caused by scope, prerequisite, timing, capacity, or loss of relevance?"
        )
    if "assumptions-stale" in codes:
        questions.append(
            "Which assumptions still hold, and which now need an experiment or correction?"
        )
    if "plan-no-feasible-next-action" in codes:
        questions.append(
            "What is the smallest unblocked action or prerequisite that would create new evidence?"
        )
    if "goal-no-active-plan" in codes:
        questions.append(
            "Does this goal need a plan now, a bounded experiment, or deliberate non-planning?"
        )
    if not questions and evidence:
        questions.append("Does the new evidence change intent, only the next wave, or neither?")
    return tuple(questions)


def _changed_dimensions(evidence: Sequence[ReviewEvidence]) -> tuple[str, ...]:
    dimensions: list[str] = []
    labels = {
        "deadline": ("deadline", "due date", "review date", "target date"),
        "scope": ("scope", "outcome", "boundary", "non-goal"),
        "capacity": ("capacity", "available time", "energy", "workload"),
        "prerequisite": ("prerequisite", "blocked", "dependency", "depends"),
        "constraint": ("constraint", "restriction", "budget"),
    }
    text = " ".join(item.statement.casefold() for item in evidence)
    for dimension, terms in labels.items():
        if any(term in text for term in terms):
            dimensions.append(dimension)
    return tuple(dimensions)


def _trigger(
    code: TriggerCode,
    severity: Literal["information", "attention", "important"],
    target_kind: Literal["goal", "plan"],
    target_id: str,
    target_path: str,
    title: str,
    detail: str,
    evidence_refs: Sequence[str],
    outcomes: Sequence[ReplanningOutcome],
) -> ReplanningTrigger:
    refs = tuple(sorted(str(item) for item in evidence_refs))
    fingerprint = (
        "sha256:" + hashlib.sha256("\0".join((code, target_path, *refs)).encode()).hexdigest()
    )
    trigger_id = "replan:" + hashlib.sha256(f"{code}\0{target_path}".encode()).hexdigest()[:20]
    return ReplanningTrigger(
        trigger_id,
        code,
        severity,
        target_kind,
        target_id,
        target_path,
        title,
        detail,
        refs,
        fingerprint,
        tuple(outcomes),
    )


def _load_suppressions(runtime_dir: Path) -> dict[str, str]:
    path = runtime_dir / "replanning" / "suppressed.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
        ):
            raise ValueError
        return dict(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ReplanningError("replanning suppression data is corrupt") from exc


def _render_collection(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or "None"
    return str(value or "None")


def _reference_id(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("[[") and cleaned.endswith("]]"):
        cleaned = cleaned[2:-2].split("|", 1)[0]
    return Path(cleaned).stem


def _hash(content: str) -> str:
    return f"sha256:{raw_content_hash(content)}"


def _diff(before: str, after: str, path: str) -> str:
    lines = tuple(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )
    result = "".join(lines[2:])
    if not result:
        raise ReplanningError("replanning patch has no effect")
    return result


def _publish(
    *, vault_root: Path, proposal_id: str, proposal_markdown: bytes, patches_json: bytes
) -> None:
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=vault_root,
        patches_json=patches_json,
    )
    try:
        publish_proposal_documents(
            vault_root=vault_root,
            proposal_id=proposal_id,
            documents=ProposalDocuments(proposal_markdown, patches_json, review_json),
        )
    except ProposalPublicationError as exc:
        raise ReplanningError(f"could not publish replanning proposal: {exc}") from exc


def _severity_rank(value: str) -> int:
    return {"important": 0, "attention": 1, "information": 2}.get(value, 3)
