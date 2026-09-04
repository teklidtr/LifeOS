from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.observation import ObservationRecord
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.patterns import (
    PatternArtifact,
    PatternArtifactService,
    PatternError,
    PatternEvaluation,
    PatternEvidence,
    PatternEvidenceDiagnostic,
    PatternMetadata,
    PatternOrigin,
    PatternReviewAssessment,
    PatternReviewReason,
    PatternReviewService,
    assess_pattern_review,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.registry import Registry

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
PATTERN_HASH = "sha256:" + "f" * 64
CHANGED_HASH = "sha256:" + "e" * 64


def _hash(index: int) -> str:
    return "sha256:" + f"{index:064x}"


def _record(day: int, sleep: float, energy: float) -> ObservationRecord:
    return ObservationRecord(
        observed_on=date(2026, 7, day),
        path=f"journal/2026-07-{day:02d}.md",
        metrics={"sleep": sleep, "energy": energy},
        activities=(),
    )


def _positive_records(count: int) -> tuple[ObservationRecord, ...]:
    return tuple(_record(day, float(day), float(day + 1)) for day in range(1, count + 1))


def _numeric_evaluation(*, stale_after_days: int | None = None) -> PatternEvaluation:
    parameters: dict[str, object] = {
        "outcome": "energy",
        "factor": "sleep",
        "min_samples": 5,
    }
    if stale_after_days is not None:
        parameters["stale_after_days"] = stale_after_days
    return PatternEvaluation(kind="numeric-metric-association", parameters=parameters)


def _evidence(records: tuple[ObservationRecord, ...]) -> tuple[PatternEvidence, ...]:
    return tuple(
        PatternEvidence(
            path=item.path,
            content_hash=_hash(index),
            role="supporting",
        )
        for index, item in enumerate(records, start=1)
    )


def _artifact(
    reviewed_records: tuple[ObservationRecord, ...],
    *,
    evaluation: PatternEvaluation | None = None,
    review_due_at: str | None = None,
    status: str = "active",
    evidence: tuple[PatternEvidence, ...] | None = None,
    evidence_fingerprint: str | None = None,
) -> PatternArtifact:
    reviewed_evidence = evidence if evidence is not None else _evidence(reviewed_records)
    fingerprint = evidence_fingerprint or compute_evidence_fingerprint(reviewed_evidence)
    metadata = PatternMetadata(
        pattern_id="pattern-sleep-energy",
        title="Sleep and energy",
        description="Working hypothesis about sleep and next-day energy.",
        status=status,  # type: ignore[arg-type]
        confidence="medium",
        review_reasons=(),
        statement="More sleep tends to accompany higher next-day energy.",
        origin=PatternOrigin("observation"),
        created_at="2026-07-10T10:00:00Z",
        updated_at="2026-07-10T10:00:00Z",
        last_reviewed_at="2026-07-10T12:00:00Z",
        review_due_at=review_due_at,
        evidence_fingerprint=fingerprint,
        evidence=reviewed_evidence,
        evaluation=evaluation,
    )
    return PatternArtifact(
        path="patterns/sleep-energy.md",
        content_hash=PATTERN_HASH,
        metadata=metadata,
        body_prefix="\n",
        managed_summary="",
        body_suffix="\n",
    )


def _unchanged_diagnostics(artifact: PatternArtifact) -> tuple[PatternEvidenceDiagnostic, ...]:
    return tuple(
        PatternEvidenceDiagnostic(
            reference=item,
            state="unchanged",
            current_path=item.path,
            current_content_hash=item.content_hash,
        )
        for item in artifact.metadata.evidence
    )


def _codes(assessment: PatternReviewAssessment) -> tuple[str, ...]:
    return tuple(reason.code for reason in assessment.reasons)


def test_same_direction_growth_recommends_review_without_reinterpreting_pattern() -> None:
    reviewed = _positive_records(10)
    artifact = _artifact(reviewed, evaluation=_numeric_evaluation())
    current = _positive_records(12)

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=current,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert assessment.recommendation == "review"
    assert _codes(assessment) == ("materially-new-evidence",)
    assert assessment.reviewed_analysis is not None
    assert assessment.current_analysis is not None
    assert assessment.reviewed_analysis.candidates[0].direction == "positive"
    assert assessment.current_analysis.candidates[0].direction == "positive"
    assert artifact.metadata.status == "active"
    assert artifact.metadata.statement == "More sleep tends to accompany higher next-day energy."


def test_weaker_current_analysis_is_an_explicit_review_reason() -> None:
    reviewed = _positive_records(10)
    artifact = _artifact(reviewed, evaluation=_numeric_evaluation())
    current = reviewed + tuple(
        _record(day, float(day), float(12 - ((day - 11) * 2)))
        for day in range(11, 17)
    )

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=current,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert "materially-new-evidence" in _codes(assessment)
    assert "weaker-evidence" in _codes(assessment)
    assert "direction-reversal" not in _codes(assessment)


def test_direction_reversal_is_counter_evidence_not_a_truth_decision() -> None:
    reviewed = _positive_records(10)
    artifact = _artifact(reviewed, evaluation=_numeric_evaluation())
    current = reviewed + tuple(
        _record(day, float(day), float(12 - ((day - 11) * 2)))
        for day in range(11, 21)
    )

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=current,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert "direction-reversal" in _codes(assessment)
    assert "new-counter-evidence" in _codes(assessment)
    assert assessment.current_analysis is not None
    assert assessment.current_analysis.candidates[0].direction == "negative"
    counter = next(reason for reason in assessment.reasons if reason.code == "new-counter-evidence")
    assert "does not establish" in counter.summary
    assert artifact.metadata.status == "active"


def test_changed_and_missing_sources_explain_review_without_semantic_analysis() -> None:
    records = _positive_records(2)
    artifact = _artifact(records, evaluation=None)
    first, second = artifact.metadata.evidence
    diagnostics = (
        PatternEvidenceDiagnostic(
            reference=first,
            state="changed",
            current_path=first.path,
            current_content_hash=CHANGED_HASH,
        ),
        PatternEvidenceDiagnostic(reference=second, state="missing"),
    )

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=records,
        evidence_diagnostics=diagnostics,
        now=NOW,
    )

    assert _codes(assessment) == ("changed-evidence", "missing-evidence")
    assert assessment.recommendation == "review"
    assert assessment.reviewed_analysis is None
    assert assessment.current_analysis is None


def test_no_new_evidence_produces_no_review_recommendation() -> None:
    reviewed = _positive_records(10)
    artifact = _artifact(reviewed, evaluation=_numeric_evaluation())

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=reviewed,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc),
    )

    assert assessment.reasons == ()
    assert assessment.recommendation == "none"
    assert assessment.reviewed_evidence_fingerprint == assessment.declared_evidence_fingerprint


def test_due_review_date_is_a_reason_even_for_manual_pattern() -> None:
    records = _positive_records(1)
    artifact = _artifact(
        records,
        evaluation=None,
        review_due_at="2026-07-19T12:00:00Z",
    )

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=records,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert _codes(assessment) == ("review-due",)
    assert assessment.recommendation == "review"


def test_manual_pattern_limits_automation_to_factual_state_and_timing() -> None:
    records = _positive_records(1)
    artifact = _artifact(records, evaluation=None)

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=records,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert assessment.recommendation == "none"
    assert assessment.reasons == ()
    assert assessment.reviewed_analysis is None
    assert assessment.current_analysis is None


def test_stale_recipe_evidence_is_reported_without_treating_silence_as_contradiction() -> None:
    reviewed = _positive_records(10)
    artifact = _artifact(reviewed, evaluation=_numeric_evaluation(stale_after_days=5))

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=reviewed,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert _codes(assessment) == ("stale-evidence",)
    stale = assessment.reasons[0]
    assert "staleness threshold" in stale.summary
    assert "counter" not in stale.summary.casefold()


def test_changed_fingerprint_with_contesting_evidence_is_review_scoped() -> None:
    records = _positive_records(2)
    supporting = _evidence(records[:1])[0]
    contesting = PatternEvidence(
        path=records[1].path,
        content_hash=_hash(99),
        role="contesting",
    )
    evidence = (supporting, contesting)
    artifact = _artifact(
        records,
        evaluation=None,
        evidence=evidence,
        evidence_fingerprint=_hash(1000),
    )

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=records,
        evidence_diagnostics=_unchanged_diagnostics(artifact),
        now=NOW,
    )

    assert _codes(assessment) == (
        "evidence-fingerprint-changed",
        "new-counter-evidence",
    )
    assert assessment.reviewed_evidence_fingerprint != assessment.declared_evidence_fingerprint


def test_assessment_rejects_diagnostics_for_a_different_evidence_context() -> None:
    records = _positive_records(1)
    artifact = _artifact(records, evaluation=None)
    other = PatternEvidence(
        path="journal/other.md",
        content_hash=_hash(2000),
        role="supporting",
    )

    with pytest.raises(PatternError, match="diagnostics"):
        assess_pattern_review(
            artifact=artifact,
            observations=records,
            evidence_diagnostics=(PatternEvidenceDiagnostic(reference=other, state="unchanged"),),
            now=NOW,
        )


def test_review_assessment_is_read_only_until_explicit_proposal_action(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "patterns").mkdir(parents=True)
    (vault / "system").mkdir()
    (vault / "system" / "generated-ownership.json").write_bytes(
        serialize_generated_ownership_bytes({})
    )
    records = _positive_records(1)
    metadata = _artifact(records, evaluation=None).metadata
    target = vault / "patterns" / "sleep-energy.md"
    target.write_text(serialize_pattern(metadata), encoding="utf-8")
    artifact = PatternArtifactService(vault_root=vault).find(metadata.pattern_id)
    assessment = PatternReviewAssessment(
        pattern_id=artifact.metadata.pattern_id,
        pattern_path=artifact.path,
        pattern_content_hash=artifact.content_hash,
        reviewed_evidence_fingerprint=artifact.metadata.evidence_fingerprint,
        declared_evidence_fingerprint=artifact.metadata.evidence_fingerprint,
        recommendation="review",
        reasons=(PatternReviewReason("review-due", "The configured review time is due."),),
        reviewed_analysis=None,
        current_analysis=None,
    )
    before = target.read_text(encoding="utf-8")
    service = PatternReviewService(
        vault_root=vault,
        registry=Registry(tmp_path / "unused-registry.sqlite"),
        allow_path=lambda _path: True,
    )

    assert not (vault / "proposals").exists()
    assert target.read_text(encoding="utf-8") == before

    result = service.create_review_proposal(
        assessment,
        actor_id="pattern-reviewer",
        now=NOW,
    )

    proposal_path = vault / str(result["proposal_path"])
    assert (proposal_path / "proposal.md").exists()
    assert (proposal_path / "patches.json").exists()
    assert target.read_text(encoding="utf-8") == before


def test_review_proposal_rejects_stale_assessment(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "patterns").mkdir(parents=True)
    records = _positive_records(1)
    metadata = _artifact(records, evaluation=None).metadata
    target = vault / "patterns" / "sleep-energy.md"
    target.write_text(serialize_pattern(metadata), encoding="utf-8")
    artifact = PatternArtifactService(vault_root=vault).find(metadata.pattern_id)
    assessment = PatternReviewAssessment(
        pattern_id=artifact.metadata.pattern_id,
        pattern_path=artifact.path,
        pattern_content_hash=artifact.content_hash,
        reviewed_evidence_fingerprint=artifact.metadata.evidence_fingerprint,
        declared_evidence_fingerprint=artifact.metadata.evidence_fingerprint,
        recommendation="review",
        reasons=(PatternReviewReason("review-due", "The configured review time is due."),),
        reviewed_analysis=None,
        current_analysis=None,
    )
    target.write_text(target.read_text(encoding="utf-8") + "\nUser edit.\n", encoding="utf-8")
    service = PatternReviewService(
        vault_root=vault,
        registry=Registry(tmp_path / "unused-registry.sqlite"),
        allow_path=lambda _path: True,
    )

    with pytest.raises(PatternError, match="changed after the review assessment"):
        service.create_review_proposal(
            assessment,
            actor_id="pattern-reviewer",
            now=NOW,
        )
