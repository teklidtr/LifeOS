from __future__ import annotations

import shutil
import struct
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.bridge import BridgeApplication, ReferenceBridgeClient
from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import ArtifactLink, DerivedValue
from lifeos.captures.extraction import LocalExtractionService
from lifeos.captures.retrieval_integration import (
    build_capture_representation,
    conversation_evidence,
)
from lifeos.captures.reviews import daily_capture_section, weekly_capture_section
from lifeos.captures.visualization import build_capture_visualization

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def _client(tmp_path: Path) -> tuple[ReferenceBridgeClient, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    return (
        ReferenceBridgeClient(
            BridgeApplication(vault_root=vault, runtime_dir=runtime, actor_id="e2e")
        ),
        vault,
        runtime,
    )


def _png(path: Path) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 32, 24) + b"\x00" * 16)


def test_rich_capture_saves_original_first_then_integrates_without_a_provider(
    tmp_path: Path,
) -> None:
    bridge, vault, runtime = _client(tmp_path)
    capabilities = set(bridge.call("system.handshake", protocol="1.2")["capabilities"])
    assert {
        "capture.create",
        "capture.attachment.add",
        "capture.enrichment.run",
        "capture.visualization.build",
        "capture.privacy.preview",
        "capture.proposal.create",
    } <= capabilities

    created = bridge.call(
        "capture.create",
        title="Lunch photo",
        capture_type="meal",
        description="Soup and bread; nutrition not tracked",
        source_entry_point="mobile-share",
        now=NOW.isoformat(),
    )
    original_markdown = (vault / created["path"]).read_text(encoding="utf-8")
    image = tmp_path / "meal.png"
    _png(image)
    attached = bridge.call(
        "capture.attachment.add",
        path=created["path"],
        expected_hash=created["content_hash"],
        source_path=str(image),
        now=NOW.isoformat(),
    )
    capture = attached["capture"]
    reference = attached["attachment"]["reference"]
    assert (vault / reference["canonical_path"]).read_bytes() == image.read_bytes()
    assert reference["canonical_path"].startswith("attachments/originals/")

    job = bridge.call(
        "capture.enrichment.start",
        path=capture["path"],
        expected_hash=capture["content_hash"],
        now=NOW.isoformat(),
    )
    completed = bridge.call("capture.enrichment.run", job_id=job["job_id"], now=NOW.isoformat())
    assert completed["state"] == "completed"
    current = bridge.call("capture.read", path=capture["path"])
    result = LocalExtractionService(vault_root=vault, runtime_dir=runtime).load(
        reference["attachment_id"]
    )
    assert result is not None and result.method == "image-metadata"
    assert result.metadata == {"format": "png", "height": 24, "width": 32}

    representation = build_capture_representation(
        CaptureArtifactService(vault_root=vault, runtime_dir=runtime).load(current["path"])
    )
    evidence = conversation_evidence(representation)
    assert evidence.capture_path == current["path"]
    assert evidence.representation_kinds == ("user-description",)
    assert "nutrition not tracked" in evidence.text

    daily = daily_capture_section(
        vault_root=vault, runtime_dir=runtime, day=date(2026, 7, 16), generated_at=NOW
    )
    weekly = weekly_capture_section(
        vault_root=vault,
        runtime_dir=runtime,
        range_start=date(2026, 7, 13),
        range_end=date(2026, 7, 19),
        generated_at=NOW,
    )
    assert daily.optional and daily.items
    assert weekly.optional and "good" not in weekly.items[0].detail.casefold()

    denied = bridge.call(
        "capture.privacy.preview",
        capture_path=current["path"],
        selected_attachment_ids=[reference["attachment_id"]],
        requested_operations=["image-description"],
        external_processing_intent=False,
    )
    assert denied["provider_payload_paths"] == []
    assert denied["omissions"][0]["reason"] == "explicit-processing-intent-required"

    proposal = bridge.call(
        "capture.proposal.create",
        capture_path=current["path"],
        action="create-knowledge-note",
        target_path="notes/lunch.md",
        content="# Lunch observation\n",
        create_target=True,
        attachment_ids=[reference["attachment_id"]],
        included_actions=["create reviewed note"],
        excluded_actions=["change diet"],
        now=NOW.isoformat(),
    )
    assert (vault / proposal["proposal_path"] / "patches.json").exists()
    assert not (vault / "notes" / "lunch.md").exists()

    canonical_after = (vault / current["path"]).read_text(encoding="utf-8")
    assert original_markdown.split("## User annotations", 1)[1] in canonical_after
    shutil.rmtree(runtime)
    rebuilt = bridge.call(
        "capture.rebuild", delete_runtime=True, rebuild_manifests=True, batch_size=1
    )
    assert rebuilt["index"]["state"] == "ready"
    assert (vault / current["path"]).read_text(encoding="utf-8") == canonical_after
    assert (vault / reference["canonical_path"]).read_bytes() == image.read_bytes()


def test_exercise_visualization_keeps_plan_outcome_and_missing_duration_distinct(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    captures = CaptureArtifactService(vault_root=vault, runtime_dir=runtime)
    planned = captures.create(title="Planned walk", capture_type="exercise", now=NOW)
    planned = captures.save(
        planned,
        replace(
            planned.metadata,
            domain_data={
                "exercise": {
                    "activity_type": "walking",
                    "outcome": "planned",
                    "duration_minutes": 20,
                }
            },
        ),
        expected_hash=planned.content_hash,
    )
    performed = captures.create(
        title="Actual walk",
        capture_type="exercise",
        description="Walked, duration unknown",
        now=NOW,
    )
    performed = captures.save(
        performed,
        replace(
            performed.metadata,
            domain_data={
                "exercise": {
                    "activity_type": "walking",
                    "outcome": "performed",
                    "duration_minutes": None,
                }
            },
            links=(ArtifactLink("experiments/walking.md", "observation", "experiment"),),
            derived_values=(DerivedValue("duration_minutes", None, "min", "unknown", "unknown"),),
        ),
        expected_hash=performed.content_hash,
    )
    view = build_capture_visualization(vault_root=vault, runtime_dir=runtime)
    outcomes = {item.outcome: item for item in view.exercise_trends}
    assert outcomes["planned"].duration_minutes == 20
    assert outcomes["performed"].duration_minutes is None
    assert view.missing_data["exercise_duration"] == 1
    assert view.experiment_linked[0]["capture_path"] == performed.path
