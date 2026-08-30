from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.facade.research_tools import (
    ResearchEvidenceCaptureRequest,
    capture_research_evidence,
)
from lifeos.research import ResearchError, ResearchEvidenceService


def _capture(
    service: ResearchEvidenceService,
    *,
    evidence_text: str = "External evidence body.",
    reason: str = "The vault lacks evidence for the queried mechanism.",
    now: datetime | None = None,
):
    return service.capture(
        evidence_text=evidence_text,
        source_title="Example research source",
        source_locator="https://example.test/research",
        source_author="External Author",
        source_publisher="Example Publisher",
        research_reason=reason,
        research_context="Agent selected this passage because it addresses the evidence gap.",
        captured_by="agent:trusted",
        origin_kind="conversation",
        origin_ref="conv-20260830T154000Z-abcd1234#turn-002",
        now=now or datetime(2026, 8, 30, 15, 40, tzinfo=timezone.utc),
    )


def test_capture_creates_hash_bound_raw_research_artifact(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    service = ResearchEvidenceService(vault_root=vault_root)

    result = _capture(service)

    assert result.created is True
    assert result.acquisition_added is True
    assert result.artifact.relative_path.startswith("raw/research/")
    assert result.artifact.metadata.snapshot_hash.startswith("sha256:")
    assert result.artifact.metadata.first_captured_by == "agent:trusted"
    assert result.artifact.metadata.source_author == "External Author"
    assert result.artifact.metadata.source_publisher == "Example Publisher"
    assert result.artifact.evidence_text == "External evidence body."
    acquisition = result.artifact.metadata.acquisitions[0]
    assert acquisition.captured_by == "agent:trusted"
    assert acquisition.origin_ref == "conv-20260830T154000Z-abcd1234#turn-002"
    assert acquisition.research_reason == "The vault lacks evidence for the queried mechanism."
    assert acquisition.research_context.startswith("Agent selected this passage")


def test_identical_snapshot_and_acquisition_are_idempotent(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    service = ResearchEvidenceService(vault_root=vault_root)

    first = _capture(service)
    second = _capture(
        service,
        now=datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc),
    )

    assert second.created is False
    assert second.acquisition_added is False
    assert second.artifact.relative_path == first.artifact.relative_path
    assert second.artifact.content_hash == first.artifact.content_hash
    assert len(second.artifact.metadata.acquisitions) == 1


def test_same_snapshot_can_accumulate_distinct_acquisition_reasons(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    service = ResearchEvidenceService(vault_root=vault_root)

    first = _capture(service)
    second = _capture(
        service,
        reason="A later query needs the same source for a different comparison.",
        now=datetime(2026, 8, 30, 16, 5, tzinfo=timezone.utc),
    )

    assert second.created is False
    assert second.acquisition_added is True
    assert second.artifact.relative_path == first.artifact.relative_path
    assert second.artifact.metadata.snapshot_hash == first.artifact.metadata.snapshot_hash
    assert second.artifact.evidence_text == first.artifact.evidence_text
    assert len(second.artifact.metadata.acquisitions) == 2
    assert {item.research_reason for item in second.artifact.metadata.acquisitions} == {
        "The vault lacks evidence for the queried mechanism.",
        "A later query needs the same source for a different comparison.",
    }


def test_changed_snapshot_preserves_prior_evidence_history(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    service = ResearchEvidenceService(vault_root=vault_root)

    first = _capture(service, evidence_text="Snapshot version one.")
    second = _capture(
        service,
        evidence_text="Snapshot version two.",
        now=datetime(2026, 8, 30, 16, 10, tzinfo=timezone.utc),
    )

    assert first.artifact.relative_path != second.artifact.relative_path
    assert first.artifact.metadata.source_identity == second.artifact.metadata.source_identity
    assert first.artifact.metadata.snapshot_hash != second.artifact.metadata.snapshot_hash
    assert service.load(first.artifact.relative_path).evidence_text == "Snapshot version one."
    assert service.load(second.artifact.relative_path).evidence_text == "Snapshot version two."


def test_snapshot_tampering_fails_hash_validation(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    service = ResearchEvidenceService(vault_root=vault_root)
    captured = _capture(service)
    path = vault_root / captured.artifact.relative_path

    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace("External evidence body.", "Silently rewritten evidence."),
        encoding="utf-8",
    )

    with pytest.raises(ResearchError) as error:
        service.load(captured.artifact.relative_path)
    assert error.value.code == "snapshot_mismatch"


def test_facade_keeps_capture_actor_server_authoritative(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    request = ResearchEvidenceCaptureRequest(
        evidence_text="Grounding source.",
        source_title="Source title",
        source_locator="doi:10.0000/example",
        source_author="Source Author",
        research_reason="Need independent evidence for the comparison.",
        origin_kind="query",
        origin_ref="query:comparison-1",
    )

    result = capture_research_evidence(
        vault_root=vault_root,
        trusted_actor_id="server:agent-a",
        request=request,
    )
    artifact = ResearchEvidenceService(vault_root=vault_root).load(result.source_path)

    assert "captured_by" not in {item.name for item in fields(ResearchEvidenceCaptureRequest)}
    assert artifact.metadata.first_captured_by == "server:agent-a"
    assert artifact.metadata.source_author == "Source Author"
    assert "owner" not in artifact.metadata.to_frontmatter()
