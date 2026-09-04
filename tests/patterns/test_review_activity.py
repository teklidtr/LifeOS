from __future__ import annotations

from datetime import date, datetime, timezone

from lifeos.observation import ObservationRecord
from lifeos.patterns import (
    PatternArtifact,
    PatternEvaluation,
    PatternEvidence,
    PatternEvidenceDiagnostic,
    PatternMetadata,
    PatternOrigin,
    assess_pattern_review,
    compute_evidence_fingerprint,
)

HASH = "sha256:" + "a" * 64


def _records() -> tuple[ObservationRecord, ...]:
    values = (5.0, 5.0, 4.0, 2.0, 2.0, 3.0)
    return tuple(
        ObservationRecord(
            observed_on=date(2026, 7, index + 1),
            path=f"journal/2026-07-{index + 1:02d}.md",
            metrics={"energy": value},
            activities=("running",) if index < 3 else (),
        )
        for index, value in enumerate(values)
    )


def test_activity_outcome_recipe_reuses_cautious_phase7_analysis() -> None:
    reviewed = _records()
    evidence = tuple(
        PatternEvidence(
            path=item.path,
            content_hash="sha256:" + f"{index:064x}",
            role="supporting",
        )
        for index, item in enumerate(reviewed, start=1)
    )
    metadata = PatternMetadata(
        pattern_id="pattern-running-energy",
        title="Running and energy",
        description="Working hypothesis about running days and energy.",
        status="active",
        confidence="medium",
        review_reasons=(),
        statement="Running days tend to have higher energy.",
        origin=PatternOrigin("observation"),
        created_at="2026-07-06T10:00:00Z",
        updated_at="2026-07-06T10:00:00Z",
        last_reviewed_at="2026-07-06T12:00:00Z",
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
        evaluation=PatternEvaluation(
            kind="activity-outcome-comparison",
            parameters={"outcome": "energy", "activity": "running", "min_samples": 3},
        ),
    )
    artifact = PatternArtifact(
        path="patterns/running-energy.md",
        content_hash=HASH,
        metadata=metadata,
        body_prefix="\n",
        managed_summary="",
        body_suffix="\n",
    )
    diagnostics = tuple(
        PatternEvidenceDiagnostic(
            reference=item,
            state="unchanged",
            current_path=item.path,
            current_content_hash=item.content_hash,
        )
        for item in evidence
    )

    assessment = assess_pattern_review(
        artifact=artifact,
        observations=reviewed,
        evidence_diagnostics=diagnostics,
        now=datetime(2026, 7, 6, 18, 0, tzinfo=timezone.utc),
    )

    assert assessment.recommendation == "none"
    assert assessment.reviewed_analysis is not None
    assert assessment.current_analysis is not None
    assert assessment.reviewed_analysis.candidates[0].direction == "higher"
    assert assessment.current_analysis.candidates[0].direction == "higher"
