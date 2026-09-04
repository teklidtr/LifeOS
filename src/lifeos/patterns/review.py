"""Deterministic personal-pattern re-evaluation and review recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Mapping, cast

from lifeos.observation import (
    CandidatePattern,
    ObservationRecord,
    PatternReport,
    analyze_activity_pattern,
    analyze_numeric_pattern,
    load_observations,
)
from lifeos.registry import Registry

from .artifact import PatternArtifactService
from .contracts import PatternArtifact, PatternError, PatternEvaluation
from .evidence import (
    EvidencePathPredicate,
    PatternEvidenceDiagnostic,
    compute_evidence_fingerprint,
    resolve_evidence_states,
)
from .proposals import MarkPatternNeedsReviewRequest, PatternProposalService

ReviewRecommendation = Literal["none", "review"]
ReviewReasonCode = Literal[
    "evidence-fingerprint-changed",
    "materially-new-evidence",
    "changed-evidence",
    "moved-evidence",
    "missing-evidence",
    "deleted-evidence",
    "ambiguous-evidence",
    "weaker-evidence",
    "direction-reversal",
    "new-counter-evidence",
    "stale-evidence",
    "review-due",
]
SupportedEvaluationKind = Literal[
    "numeric-metric-association",
    "activity-outcome-comparison",
]

_SUPPORTED_EVALUATIONS = frozenset(
    {"numeric-metric-association", "activity-outcome-comparison"}
)
_STRENGTH_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True, slots=True)
class PatternReviewReason:
    """One inspectable factual reason that a pattern may deserve review."""

    code: ReviewReasonCode
    summary: str
    evidence_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PatternReviewAssessment:
    """Read-only review assessment scoped to one exact canonical pattern version."""

    pattern_id: str
    pattern_path: str
    pattern_content_hash: str
    reviewed_evidence_fingerprint: str
    declared_evidence_fingerprint: str
    recommendation: ReviewRecommendation
    reasons: tuple[PatternReviewReason, ...]
    reviewed_analysis: PatternReport | None
    current_analysis: PatternReport | None

    @property
    def needs_review(self) -> bool:
        return self.recommendation == "review"


@dataclass(frozen=True, slots=True)
class _EvaluationRecipe:
    kind: SupportedEvaluationKind
    outcome: str
    factor: str
    min_samples: int
    stale_after_days: int | None


def _aware_now(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PatternError(
            "invalid_timestamp",
            "Pattern re-evaluation time must include a timezone.",
            {"field": "now"},
        )
    return moment


def _nonblank_parameter(parameters: Mapping[str, object], key: str) -> str:
    value = parameters.get(key)
    if type(value) is not str or not value.strip():
        raise PatternError(
            "invalid_evaluation",
            f"evaluation.parameters.{key} must be a non-blank string.",
            {"field": f"evaluation.parameters.{key}"},
        )
    return value.strip()


def _integer_parameter(
    parameters: Mapping[str, object],
    key: str,
    *,
    default: int | None,
    minimum: int,
) -> int | None:
    value = parameters.get(key, default)
    if value is None:
        return None
    if type(value) is not int or value < minimum:
        raise PatternError(
            "invalid_evaluation",
            f"evaluation.parameters.{key} must be an integer of at least {minimum}.",
            {"field": f"evaluation.parameters.{key}"},
        )
    return value


def _evaluation_recipe(evaluation: PatternEvaluation) -> _EvaluationRecipe:
    if evaluation.kind not in _SUPPORTED_EVALUATIONS:
        raise PatternError(
            "unsupported_evaluation",
            "Pattern evaluation recipe is not supported for deterministic re-evaluation.",
            {"kind": evaluation.kind},
        )
    parameters = dict(evaluation.parameters)
    if evaluation.kind == "numeric-metric-association":
        allowed = {"outcome", "factor", "min_samples", "stale_after_days"}
        factor_key = "factor"
        default_minimum = 5
        minimum = 4
    else:
        allowed = {"outcome", "activity", "min_samples", "stale_after_days"}
        factor_key = "activity"
        default_minimum = 3
        minimum = 3
    unexpected = sorted(set(parameters) - allowed)
    if unexpected:
        raise PatternError(
            "invalid_evaluation",
            "Pattern evaluation recipe contains unsupported parameters.",
            {"parameters": unexpected, "kind": evaluation.kind},
        )
    min_samples = _integer_parameter(
        parameters,
        "min_samples",
        default=default_minimum,
        minimum=minimum,
    )
    assert min_samples is not None
    stale_after_days = _integer_parameter(
        parameters,
        "stale_after_days",
        default=None,
        minimum=1,
    )
    return _EvaluationRecipe(
        kind=cast(SupportedEvaluationKind, evaluation.kind),
        outcome=_nonblank_parameter(parameters, "outcome"),
        factor=_nonblank_parameter(parameters, factor_key),
        min_samples=min_samples,
        stale_after_days=stale_after_days,
    )


def _run_analysis(
    recipe: _EvaluationRecipe,
    records: tuple[ObservationRecord, ...],
    *,
    as_of: date,
) -> PatternReport:
    if recipe.kind == "numeric-metric-association":
        return analyze_numeric_pattern(
            records=records,
            outcome=recipe.outcome,
            factor=recipe.factor,
            min_samples=recipe.min_samples,
            as_of=as_of,
        )
    return analyze_activity_pattern(
        records=records,
        outcome=recipe.outcome,
        activity=recipe.factor,
        min_group_size=recipe.min_samples,
        as_of=as_of,
    )


def _relevant_records(
    recipe: _EvaluationRecipe,
    records: tuple[ObservationRecord, ...],
) -> tuple[ObservationRecord, ...]:
    if recipe.kind == "numeric-metric-association":
        return tuple(
            item
            for item in records
            if recipe.outcome in item.metrics and recipe.factor in item.metrics
        )
    return tuple(item for item in records if recipe.outcome in item.metrics)


def _reviewed_records(
    observations: tuple[ObservationRecord, ...],
    diagnostics: tuple[PatternEvidenceDiagnostic, ...],
) -> tuple[tuple[ObservationRecord, ...], bool]:
    by_path = {item.path: item for item in observations}
    reviewed_paths: set[str] = set()
    incomplete = False
    for diagnostic in diagnostics:
        reference_path = diagnostic.reference.path
        current_path = diagnostic.current_path
        is_journal_reference = reference_path.startswith("journal/") or (
            current_path is not None and current_path.startswith("journal/")
        )
        if not is_journal_reference:
            continue
        if diagnostic.state == "unchanged":
            path = reference_path
        elif diagnostic.state == "moved" and current_path is not None:
            path = current_path
        else:
            incomplete = True
            continue
        if path not in by_path:
            incomplete = True
            continue
        reviewed_paths.add(path)
    return (
        tuple(item for item in observations if item.path in reviewed_paths),
        incomplete,
    )


def _candidate(report: PatternReport | None) -> CandidatePattern | None:
    if report is None or not report.candidates:
        return None
    return report.candidates[0]


def _last_review_date(artifact: PatternArtifact) -> date | None:
    value = artifact.metadata.last_reviewed_at
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _new_relevant_paths(
    *,
    artifact: PatternArtifact,
    recipe: _EvaluationRecipe,
    observations: tuple[ObservationRecord, ...],
    reviewed_records: tuple[ObservationRecord, ...],
) -> tuple[str, ...]:
    reviewed_paths = {item.path for item in _relevant_records(recipe, reviewed_records)}
    last_review = _last_review_date(artifact)
    new_paths = []
    for item in _relevant_records(recipe, observations):
        if item.path in reviewed_paths:
            continue
        if last_review is not None and item.observed_on <= last_review:
            continue
        new_paths.append(item.path)
    return tuple(sorted(new_paths))


def _evidence_state_reasons(
    diagnostics: tuple[PatternEvidenceDiagnostic, ...],
) -> tuple[PatternReviewReason, ...]:
    reasons: list[PatternReviewReason] = []
    for diagnostic in sorted(diagnostics, key=lambda item: item.reference.path):
        path = diagnostic.reference.path
        if diagnostic.state == "unchanged":
            continue
        paths: tuple[str, ...]
        if diagnostic.state == "changed":
            summary = f"Reviewed evidence changed since the reviewed version: {path}."
            code: ReviewReasonCode = "changed-evidence"
            paths = (path,)
        elif diagnostic.state == "moved":
            destination = diagnostic.current_path or "an unresolved location"
            summary = f"Reviewed evidence moved from {path} to {destination}."
            code = "moved-evidence"
            paths = tuple(dict.fromkeys((path, destination)))
        elif diagnostic.state == "missing":
            summary = f"Reviewed evidence is missing from the authorized current view: {path}."
            code = "missing-evidence"
            paths = (path,)
        elif diagnostic.state == "deleted":
            summary = f"Reviewed evidence has a recorded deletion: {path}."
            code = "deleted-evidence"
            paths = (path,)
        else:
            candidates = ", ".join(diagnostic.candidate_paths) or "multiple current locations"
            summary = f"Reviewed evidence identity is ambiguous for {path}: {candidates}."
            code = "ambiguous-evidence"
            paths = (path, *diagnostic.candidate_paths)
        reasons.append(PatternReviewReason(code=code, summary=summary, evidence_paths=paths))
    return tuple(reasons)


def _analysis_reasons(
    *,
    artifact: PatternArtifact,
    recipe: _EvaluationRecipe,
    observations: tuple[ObservationRecord, ...],
    reviewed_records: tuple[ObservationRecord, ...],
    reviewed_analysis: PatternReport | None,
    current_analysis: PatternReport,
    baseline_incomplete: bool,
    as_of: date,
) -> tuple[PatternReviewReason, ...]:
    reasons: list[PatternReviewReason] = []
    new_paths = _new_relevant_paths(
        artifact=artifact,
        recipe=recipe,
        observations=observations,
        reviewed_records=reviewed_records,
    )
    if new_paths:
        reasons.append(
            PatternReviewReason(
                code="materially-new-evidence",
                summary=(
                    f"{len(new_paths)} new dated observation(s) now enter the deterministic "
                    "evaluation recipe."
                ),
                evidence_paths=new_paths,
            )
        )

    reviewed_candidate = _candidate(reviewed_analysis)
    current_candidate = _candidate(current_analysis)
    if not baseline_incomplete and reviewed_candidate is not None:
        if current_candidate is None or (
            _STRENGTH_RANK[current_candidate.evidence_strength]
            < _STRENGTH_RANK[reviewed_candidate.evidence_strength]
        ):
            reasons.append(
                PatternReviewReason(
                    code="weaker-evidence",
                    summary=(
                        "The current deterministic analysis is weaker than the reconstructable "
                        "reviewed analysis; this is a review signal, not a contradiction."
                    ),
                )
            )
        if (
            current_candidate is not None
            and current_candidate.direction != reviewed_candidate.direction
        ):
            reasons.append(
                PatternReviewReason(
                    code="direction-reversal",
                    summary=(
                        "The current deterministic association points in the opposite direction "
                        "from the reconstructable reviewed analysis."
                    ),
                )
            )
            reasons.append(
                PatternReviewReason(
                    code="new-counter-evidence",
                    summary=(
                        "The aggregate reversal is deterministic counter-evidence to the reviewed "
                        "direction; it does not establish that the hypothesis is false."
                    ),
                    evidence_paths=new_paths,
                )
            )

    if recipe.stale_after_days is not None:
        relevant = _relevant_records(recipe, observations)
        if relevant:
            latest = max(item.observed_on for item in relevant)
            freshness_days = max(0, (as_of - latest).days)
            if freshness_days >= recipe.stale_after_days:
                reasons.append(
                    PatternReviewReason(
                        code="stale-evidence",
                        summary=(
                            f"The newest usable observation is {freshness_days} day(s) old, meeting "
                            f"the recipe's {recipe.stale_after_days}-day staleness threshold."
                        ),
                    )
                )
    return tuple(reasons)


def _review_due_reason(artifact: PatternArtifact, *, now: datetime) -> PatternReviewReason | None:
    value = artifact.metadata.review_due_at
    if value is None:
        return None
    due = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if due > now:
        return None
    return PatternReviewReason(
        code="review-due",
        summary=f"The configured review time is due: {value}.",
    )


def _validate_diagnostics(
    artifact: PatternArtifact,
    diagnostics: tuple[PatternEvidenceDiagnostic, ...],
) -> None:
    references = tuple(item.reference for item in diagnostics)
    if references != artifact.metadata.evidence:
        raise PatternError(
            "evidence_diagnostics_mismatch",
            "Evidence diagnostics must describe the pattern's exact declared evidence context.",
            {"pattern_id": artifact.metadata.pattern_id},
        )


def assess_pattern_review(
    *,
    artifact: PatternArtifact,
    observations: tuple[ObservationRecord, ...],
    evidence_diagnostics: tuple[PatternEvidenceDiagnostic, ...],
    now: datetime | None = None,
) -> PatternReviewAssessment:
    """Re-evaluate one pattern without mutating it or creating a proposal."""
    moment = _aware_now(now)
    _validate_diagnostics(artifact, evidence_diagnostics)
    declared_fingerprint = compute_evidence_fingerprint(artifact.metadata.evidence)
    reasons: list[PatternReviewReason] = []
    if declared_fingerprint != artifact.metadata.evidence_fingerprint:
        reasons.append(
            PatternReviewReason(
                code="evidence-fingerprint-changed",
                summary=(
                    "The declared evidence references no longer match the last reviewed evidence "
                    "fingerprint."
                ),
                evidence_paths=tuple(sorted(item.path for item in artifact.metadata.evidence)),
            )
        )
        if any(item.role == "contesting" for item in artifact.metadata.evidence):
            reasons.append(
                PatternReviewReason(
                    code="new-counter-evidence",
                    summary=(
                        "Contesting evidence is present in an evidence context that differs from "
                        "the last reviewed fingerprint."
                    ),
                    evidence_paths=tuple(
                        sorted(
                            item.path
                            for item in artifact.metadata.evidence
                            if item.role == "contesting"
                        )
                    ),
                )
            )

    reasons.extend(_evidence_state_reasons(evidence_diagnostics))

    reviewed_analysis: PatternReport | None = None
    current_analysis: PatternReport | None = None
    if artifact.metadata.evaluation is not None:
        recipe = _evaluation_recipe(artifact.metadata.evaluation)
        reviewed_records, baseline_incomplete = _reviewed_records(
            observations, evidence_diagnostics
        )
        if reviewed_records and not baseline_incomplete:
            reviewed_analysis = _run_analysis(recipe, reviewed_records, as_of=moment.date())
        current_analysis = _run_analysis(recipe, observations, as_of=moment.date())
        reasons.extend(
            _analysis_reasons(
                artifact=artifact,
                recipe=recipe,
                observations=observations,
                reviewed_records=reviewed_records,
                reviewed_analysis=reviewed_analysis,
                current_analysis=current_analysis,
                baseline_incomplete=baseline_incomplete,
                as_of=moment.date(),
            )
        )

    due_reason = _review_due_reason(artifact, now=moment)
    if due_reason is not None:
        reasons.append(due_reason)

    recommendation: ReviewRecommendation = (
        "review" if reasons and artifact.metadata.status != "archived" else "none"
    )
    return PatternReviewAssessment(
        pattern_id=artifact.metadata.pattern_id,
        pattern_path=artifact.path,
        pattern_content_hash=artifact.content_hash,
        reviewed_evidence_fingerprint=artifact.metadata.evidence_fingerprint,
        declared_evidence_fingerprint=declared_fingerprint,
        recommendation=recommendation,
        reasons=tuple(reasons),
        reviewed_analysis=reviewed_analysis,
        current_analysis=current_analysis,
    )


class PatternReviewService:
    """Read current canonical facts and expose explicit proposal-backed review actions."""

    def __init__(
        self,
        *,
        vault_root: Path,
        registry: Registry,
        allow_path: EvidencePathPredicate,
    ) -> None:
        self.vault_root = vault_root
        self.registry = registry
        self.allow_path = allow_path
        self.artifacts = PatternArtifactService(vault_root=vault_root)

    def assess(
        self,
        pattern_id: str,
        *,
        now: datetime | None = None,
    ) -> PatternReviewAssessment:
        artifact = self.artifacts.find(pattern_id)
        diagnostics = resolve_evidence_states(
            self.registry,
            artifact.metadata.evidence,
            allow_path=self.allow_path,
        )
        observations = tuple(
            item for item in load_observations(self.vault_root) if self.allow_path(item.path)
        )
        return assess_pattern_review(
            artifact=artifact,
            observations=observations,
            evidence_diagnostics=diagnostics,
            now=now,
        )

    def create_review_proposal(
        self,
        assessment: PatternReviewAssessment,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Create a draft needs-review proposal only when this method is explicitly invoked."""
        if not assessment.needs_review:
            raise PatternError(
                "review_not_recommended",
                "A needs-review proposal requires a current review recommendation.",
            )
        current = self.artifacts.find(assessment.pattern_id)
        if (
            current.path != assessment.pattern_path
            or current.content_hash != assessment.pattern_content_hash
        ):
            raise PatternError(
                "stale_assessment",
                "Pattern changed after the review assessment; re-evaluate before proposing a change.",
                {"pattern_id": assessment.pattern_id},
            )
        if current.metadata.status not in {"seed", "active"}:
            raise PatternError(
                "invalid_transition",
                "Only seed or active patterns can be proposed for needs-review.",
                {"from_status": current.metadata.status},
            )
        review_reasons = tuple(reason.summary for reason in assessment.reasons)
        transition_reason = (
            "User explicitly requested a needs-review draft after deterministic re-evaluation."
        )
        return PatternProposalService(
            vault_root=self.vault_root,
            actor_id=actor_id,
        ).publish(
            MarkPatternNeedsReviewRequest(
                target_path=current.path,
                transition_reason=transition_reason,
                review_reasons=review_reasons,
            ),
            now=now,
        )
