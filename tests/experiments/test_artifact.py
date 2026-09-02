from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.experiments import (
    ExperimentArtifactService,
    ExperimentError,
    ExperimentPhase,
    ExperimentProtocol,
    MeasureDefinition,
    Observation,
    SafetyClassification,
)
from lifeos.markdown.parser import parse_markdown_note

NOW = datetime(2026, 7, 16, 9, tzinfo=timezone.utc)


def protocol() -> ExperimentProtocol:
    return ExperimentProtocol(
        question="Does morning walking relate to focus?",
        hypothesis="Morning walking will be followed by higher focus ratings.",
        rationale="A smaller routine change is easier to observe.",
        intervention="Walk for 20 minutes before study.",
        constants=("same study block",),
        comparison="Seven-day no-walk baseline.",
        baseline_requirements="Record focus for seven days.",
        outcome_measures=(
            MeasureDefinition(
                "focus", "Focus", "rating", "primary", "daily", valid_min=1, valid_max=10
            ),
        ),
        phases=(
            ExperimentPhase("baseline", "Baseline", "baseline", "2026-07-16", "2026-07-22"),
            ExperimentPhase(
                "walk", "Morning walk", "intervention", "2026-07-23", "2026-07-29", "20 minute walk"
            ),
        ),
        adherence_expectation="At least five of seven intervention days.",
        confounders=("sleep",),
        risks=(),
        stop_rules=("Stop for pain or dizziness.",),
        success_criteria=("Average focus improves by at least one point.",),
        failure_criteria=("Average focus does not improve.",),
        inconclusive_criteria=("Fewer than five observations per phase.",),
    )


def service(tmp_path: Path) -> ExperimentArtifactService:
    return ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")


def test_create_round_trip_and_preserve_human_annotations(tmp_path: Path) -> None:
    api = service(tmp_path)
    created = api.create(
        title="Morning walk",
        description="Small focus experiment",
        category="productivity",
        protocol=protocol(),
        now=NOW,
    )
    assert created.metadata.state == "idea"
    assert created.path.startswith("experiments/2026/")
    path = tmp_path / created.path
    path.write_text(path.read_text() + "\nKeep this sentence.\n")
    loaded = api.load(created.path)
    drafted = api.transition(created.path, "drafting", expected_hash=loaded.content_hash, now=NOW)
    assert "Keep this sentence." in drafted.human_body
    assert drafted.metadata.lifecycle[-1].to_state == "drafting"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_transition_preserves_exact_body_around_real_managed_block(
    tmp_path: Path, newline: str,
) -> None:
    api = service(tmp_path)
    created = api.create(
        title="Morning walk",
        description="Small focus experiment",
        category="productivity",
        protocol=protocol(),
        now=NOW,
    )
    path = tmp_path / created.path
    real_start = "<!-- lifeos:managed:start personal-experiment -->"
    fake_prefix = (
        "\n\n\n```md\n"
        "<!-- lifeos:managed:start personal-experiment -->\n"
        "```\n"
        "Human experiment text outside the real block.  \n\n"
    )
    original = path.read_bytes().decode("utf-8")
    parsed = parse_markdown_note(path, content=original)
    block = parsed.managed_blocks[0]
    body = (
        fake_prefix
        + parsed.body[block.start_offset : block.end_offset]
        + "\n\n## User annotations\n\nKeep this trailing text.  \n\n\n"
    ).replace("\n", newline)
    original = original[: len(original) - len(parsed.body)] + body
    path.write_bytes(original.encode("utf-8"))
    parsed = parse_markdown_note(path, content=original)
    block = parsed.managed_blocks[0]
    expected_prefix = parsed.body[: block.start_offset].encode("utf-8")
    expected_suffix = parsed.body[block.end_offset :].encode("utf-8")
    current = api.load(created.path)

    api.transition(current.path, "drafting", expected_hash=current.content_hash, now=NOW)

    updated = path.read_bytes().decode("utf-8")
    parsed = parse_markdown_note(path, content=updated)
    assert not parsed.findings
    assert len(parsed.managed_blocks) == 1
    block = parsed.managed_blocks[0]
    assert parsed.body[: block.start_offset].encode("utf-8") == expected_prefix
    assert parsed.body[block.end_offset :].encode("utf-8") == expected_suffix
    assert updated.count(real_start) == 2
    assert "state: drafting" in updated


def test_invalid_transition_and_unsafe_activation_fail_closed(tmp_path: Path) -> None:
    api = service(tmp_path)
    created = api.create(
        title="Blocked",
        description="",
        category="health",
        protocol=protocol(),
        safety=SafetyClassification(
            "blocked",
            ("medication-change",),
            "Prescription medication changes require professional guidance.",
            True,
        ),
        now=NOW,
    )
    with pytest.raises(ExperimentError, match="cannot transition") as invalid:
        api.transition(created.path, "active", expected_hash=created.content_hash, now=NOW)
    assert invalid.value.code == "invalid_transition"
    drafted = api.transition(created.path, "drafting", expected_hash=created.content_hash, now=NOW)
    with pytest.raises(ExperimentError) as unsafe:
        api.transition(drafted.path, "baseline", expected_hash=drafted.content_hash, now=NOW)
    assert unsafe.value.code == "unsafe_experiment"


def test_protocol_changes_require_amendment_after_baseline(tmp_path: Path) -> None:
    api = service(tmp_path)
    item = api.create(title="Walk", description="", category="study", protocol=protocol(), now=NOW)
    item = api.transition(item.path, "drafting", expected_hash=item.content_hash, now=NOW)
    changed = replace(protocol(), intervention="Walk for 25 minutes before study.")
    item = api.update_protocol(item.path, changed, expected_hash=item.content_hash, now=NOW)
    item = api.transition(item.path, "baseline", expected_hash=item.content_hash, now=NOW)
    with pytest.raises(ExperimentError) as required:
        api.update_protocol(item.path, protocol(), expected_hash=item.content_hash, now=NOW)
    assert required.value.code == "amendment_required"
    amended = api.amend_protocol(
        item.path,
        protocol(),
        reason="Return to tolerable duration",
        changes=("Intervention changed from 25 to 20 minutes.",),
        expected_hash=item.content_hash,
        now=NOW,
    )
    assert amended.metadata.amendments[0].prior_protocol_hash.startswith("sha256:")


def test_missing_observation_is_not_coerced_to_zero(tmp_path: Path) -> None:
    api = service(tmp_path)
    item = api.create(title="Walk", description="", category="study", protocol=protocol(), now=NOW)
    skipped = Observation("obs-1", "focus", NOW.isoformat(), "baseline", "skipped", note="Travel")
    item = api.append_observation(item.path, skipped, expected_hash=item.content_hash, now=NOW)
    assert item.metadata.observations[0].value is None
    assert item.metadata.observations[0].state == "skipped"
    with pytest.raises(ExperimentError):
        Observation("obs-2", "focus", NOW.isoformat(), "baseline", "not-measured", value=0)


def test_stale_write_duplicate_identity_and_unsupported_schema(tmp_path: Path) -> None:
    api = service(tmp_path)
    item = api.create(title="Walk", description="", category="study", protocol=protocol(), now=NOW)
    updated = api.transition(item.path, "drafting", expected_hash=item.content_hash, now=NOW)
    with pytest.raises(ExperimentError) as stale:
        api.transition(item.path, "drafting", expected_hash=item.content_hash, now=NOW)
    assert stale.value.code == "stale_artifact"
    duplicate = tmp_path / "experiments/2026/duplicate.md"
    duplicate.write_text((tmp_path / updated.path).read_text())
    with pytest.raises(ExperimentError) as identity:
        api.find(updated.metadata.experiment_id)
    assert identity.value.code == "duplicate_identity"
    duplicate.unlink()
    path = tmp_path / updated.path
    path.write_text(path.read_text().replace("experiment_schema: 1", "experiment_schema: 99"))
    with pytest.raises(ExperimentError) as schema:
        api.load(updated.path)
    assert schema.value.code == "unsupported_schema"


def test_clone_preserves_lineage_but_not_observations(tmp_path: Path) -> None:
    api = service(tmp_path)
    item = api.create(title="Walk", description="", category="study", protocol=protocol(), now=NOW)
    clone = api.clone(item.path, now=NOW.replace(second=1))
    assert clone.metadata.repeated_from_experiment_id == item.metadata.experiment_id
    assert clone.metadata.observations == ()
    assert clone.metadata.protocol == item.metadata.protocol
