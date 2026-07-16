from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import ArtifactLink, CaptureError, DerivedValue
from lifeos.captures.extraction import ExtractionResult
from lifeos.captures.integrations import (
    CaptureExperimentMapping,
    CaptureLinkService,
    capture_as_experiment_observation,
)
from lifeos.captures.proposals import CaptureProposalRequest, CaptureProposalService
from lifeos.captures.retrieval_integration import (
    build_capture_representation,
    chunk_capture_representation,
    conversation_evidence,
)
from lifeos.captures.reviews import daily_capture_section, weekly_capture_section
from lifeos.experiments.artifact import ExperimentArtifactService
from lifeos.experiments.contracts import ExperimentPhase, ExperimentProtocol, MeasureDefinition

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def test_linking_is_explicit_and_deduplicated(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(title="Receipt", capture_type="attachment", now=NOW)
    service = CaptureLinkService(captures)
    linked = service.link(
        capture.path,
        ArtifactLink("diary/2026-07-16.md", "supports", "diary"),
        expected_hash=capture.content_hash,
        now=NOW,
    )
    same = service.link(
        linked.path, linked.metadata.links[0], expected_hash=linked.content_hash, now=NOW
    )
    assert len(same.metadata.links) == 1


def test_retrieval_indexes_only_approved_text_and_marks_stale_extraction(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(title="Meal", capture_type="meal", description="Soup", now=NOW)
    suggested = DerivedValue("calories", 500, "kcal", "model-estimate", "low")
    confirmed = DerivedValue("protein", 20, "g", "label-derived", "high", status="confirmed")
    capture = captures.save(
        capture,
        replace(capture.metadata, derived_values=(suggested, confirmed)),
        expected_hash=capture.content_hash,
    )
    representation = build_capture_representation(capture)
    assert "protein" in representation.text and "calories" not in representation.text
    chunked = chunk_capture_representation(representation, indexed_at=NOW)
    assert chunked.document.note_type == "rich-capture-evidence"
    stale = build_capture_representation(
        capture,
        extractions=(ExtractionResult("unknown", "sha256:" + "0" * 64, "ocr", "1", "stale"),),
    )
    assert not stale.stale  # unrelated extraction is ignored


def test_semantic_exclusion_and_conversation_provenance(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(
        title="Audio", capture_type="attachment", description="voice note", now=NOW
    )
    evidence = conversation_evidence(build_capture_representation(capture))
    assert evidence.representation_kinds == ("user-description",)
    excluded = captures.save(
        capture,
        replace(capture.metadata, exclude_from_semantic=True),
        expected_hash=capture.content_hash,
    )
    with pytest.raises(CaptureError) as exc:
        build_capture_representation(excluded)
    assert exc.value.code == "semantic_excluded"


def test_daily_and_weekly_reviews_are_optional_and_non_moralizing(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    captures.create(title="Lunch", capture_type="meal", event_at=NOW, now=NOW)
    captures.create(title="Walk", capture_type="exercise", event_at=NOW, now=NOW)
    daily = daily_capture_section(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        day=date(2026, 7, 16),
        generated_at=NOW,
    )
    weekly = weekly_capture_section(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        range_start=date(2026, 7, 13),
        range_end=date(2026, 7, 19),
        generated_at=NOW,
    )
    assert daily.optional and len(daily.items) == 2
    assert (
        weekly.optional
        and "good" not in weekly.items[0].detail.casefold()
        and "bad" not in weekly.items[0].detail.casefold()
    )


def experiment(tmp_path: Path):
    protocol = ExperimentProtocol(
        question="Does walking affect mood?",
        hypothesis="Mood may differ",
        rationale="Observe a bounded association.",
        intervention="Walk",
        constants=(),
        comparison="Baseline",
        baseline_requirements="One baseline observation",
        outcome_measures=(
            MeasureDefinition(
                "mood",
                "Mood",
                "rating",
                "primary",
                "daily",
                valid_min=0,
                valid_max=10,
            ),
        ),
        phases=(
            ExperimentPhase(
                "baseline",
                "Baseline",
                "baseline",
                "2026-07-15",
                "2026-07-16",
            ),
        ),
        adherence_expectation="Record when available",
        confounders=(),
        risks=(),
        stop_rules=(),
        success_criteria=("Higher mood",),
        failure_criteria=("No higher mood",),
        inconclusive_criteria=("Insufficient observations",),
    )
    return ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos").create(
        title="Walking", description="", category="activity", protocol=protocol, now=NOW
    )


def test_experiment_mapping_requires_visible_confirmation(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(title="Mood", capture_type="exercise", event_at=NOW, now=NOW)
    capture = captures.save(
        capture,
        replace(
            capture.metadata,
            derived_values=(DerivedValue("mood", 7, None, "model-estimate", "medium"),),
        ),
        expected_hash=capture.content_hash,
    )
    mapping = CaptureExperimentMapping("mood", "mood", "baseline")
    with pytest.raises(CaptureError) as exc:
        capture_as_experiment_observation(capture, experiment(tmp_path), mapping)
    assert exc.value.code == "confirmation_required"
    confirmed = captures.save(
        capture,
        replace(
            capture.metadata,
            derived_values=(replace(capture.metadata.derived_values[0], status="confirmed"),),
        ),
        expected_hash=capture.content_hash,
    )
    observation = capture_as_experiment_observation(confirmed, experiment(tmp_path), mapping)
    assert observation.value == 7 and observation.source_refs[0].path == confirmed.path


def test_capture_proposal_is_source_hash_and_target_hash_guarded(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(title="Book page", capture_type="attachment", now=NOW)
    target = tmp_path / "notes" / "book.md"
    target.parent.mkdir()
    target.write_text("# Book\n")
    service = CaptureProposalService(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester"
    )
    request = CaptureProposalRequest(
        capture.path,
        "append-note",
        "notes/book.md",
        "## Finding\n\nCheck this claim.",
        included_actions=("append reviewed text",),
        excluded_actions=("change capture",),
    )
    preview, patch, _ = service.preview(request, now=NOW)
    assert preview.source_capture_hash == capture.content_hash
    assert patch.operations[0].base_hash is not None
    target.write_text("# Book changed\n")
    assert (
        patch.operations[0].base_hash
        != "sha256:" + __import__("hashlib").sha256(target.read_bytes()).hexdigest()
    )
    published = service.publish(request, now=NOW)
    assert (tmp_path / published["proposal_path"] / "patches.json").exists()
