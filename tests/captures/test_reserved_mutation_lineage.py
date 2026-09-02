from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import CaptureError, ProvenanceRecord

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "source_entry_point",
    [
        "capture-mutation:",
        "capture-mutation:merge:key:request:1:1",
        "capture-mutation-source:split:key:request:1:1:cap-result",
        "  capture-mutation:split:key:request:1:2  ",
    ],
)
def test_public_create_rejects_reserved_mutation_lineage_before_write(
    tmp_path: Path, source_entry_point: str
) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")

    with pytest.raises(CaptureError) as exc:
        service.create(
            title="Forged lineage",
            capture_type="attachment",
            source_entry_point=source_entry_point,
            now=NOW,
        )

    assert exc.value.code == "reserved_capture_lineage"
    assert exc.value.data == {"field": "source_entry_point"}
    assert not (tmp_path / "captures").exists()


def test_public_create_does_not_reject_ordinary_mutation_words(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")

    created = service.create(
        title="Ordinary note",
        capture_type="attachment",
        source_entry_point="ribbon capture-mutation discussion",
        now=NOW,
    )

    assert created.metadata.source_entry_point == "ribbon capture-mutation discussion"


@pytest.mark.parametrize(
    "reason",
    [
        "merged into",
        "merged into cap-20260902T120000Z-deadbeef",
        "split into",
        "split into cap-one, cap-two",
        "  split into cap-one, cap-two  ",
    ],
)
def test_public_transition_rejects_reserved_archive_lineage_without_mutating_bytes(
    tmp_path: Path, reason: str
) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    created = service.create(title="Source", capture_type="attachment", now=NOW)
    path = tmp_path / created.path
    before = path.read_bytes()

    with pytest.raises(CaptureError) as exc:
        service.transition(
            created.path,
            "archived",
            expected_hash=created.content_hash,
            reason=reason,
            now=NOW,
        )

    assert exc.value.code == "reserved_capture_lineage"
    assert exc.value.data == {"field": "reason"}
    assert path.read_bytes() == before


@pytest.mark.parametrize("reason", ["merged intoish", "split intonation", "user merged into notes"])
def test_public_transition_allows_non_reserved_reason_text(tmp_path: Path, reason: str) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    created = service.create(title="Source", capture_type="attachment", now=NOW)

    archived = service.transition(
        created.path,
        "archived",
        expected_hash=created.content_hash,
        reason=reason,
        now=NOW,
    )

    assert archived.metadata.lifecycle[-1].reason == reason


def test_internal_prepare_paths_can_write_reserved_lineage_without_public_mutation(
    tmp_path: Path,
) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    marker = "capture-mutation:merge:key:request:1:1"
    prepared = service.prepare_create(
        title="Merged result",
        capture_type="attachment",
        source_entry_point=marker,
        now=NOW,
    )

    assert prepared.artifact.metadata.source_entry_point == marker
    assert not (tmp_path / prepared.artifact.path).exists()

    path = tmp_path / prepared.artifact.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prepared.content)
    loaded = service.load(prepared.artifact.path)
    assert loaded.metadata.source_entry_point == marker

    source = service.create(title="Public source", capture_type="attachment", now=NOW)
    archive_reason = f"merged into {loaded.metadata.capture_id}"
    source_marker = "capture-mutation-source:merge:key:request:1:1:" + loaded.metadata.capture_id
    transition = service.prepare_transition(
        source,
        "archived",
        reason=archive_reason,
        provenance_record=ProvenanceRecord(
            "capture-mutation",
            source_marker,
            NOW.isoformat(),
            "Internal merge lineage.",
            source.content_hash,
        ),
        now=NOW,
    )

    assert transition.artifact.metadata.lifecycle[-1].reason == archive_reason
    assert transition.artifact.metadata.provenance[-1].source == source_marker
    assert (tmp_path / source.path).read_bytes() != transition.content.encode("utf-8")
