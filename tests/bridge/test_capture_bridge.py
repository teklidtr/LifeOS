from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc).isoformat()


def client(tmp_path: Path) -> tuple[ReferenceBridgeClient, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    app = BridgeApplication(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="local")
    return ReferenceBridgeClient(app), vault


def test_capture_bridge_vertical_slice_and_capabilities(tmp_path: Path) -> None:
    bridge, vault = client(tmp_path)
    handshake = bridge.call("system.handshake", protocol="1.0")
    for capability in (
        "capture.create",
        "capture.attachment.add",
        "capture.enrichment.start",
        "capture.inference.decide",
        "capture.merge.preview",
        "capture.proposal.create",
    ):
        assert capability in handshake["capabilities"]

    created = bridge.call(
        "capture.create",
        title="Lunch",
        capture_type="meal",
        description="Soup",
        source_entry_point="quick-capture",
        now=NOW,
    )
    loaded = bridge.call("capture.read", path=created["path"])
    assert loaded["metadata"]["description"] == "Soup"
    updated = bridge.call(
        "capture.update",
        path=created["path"],
        expected_hash=created["content_hash"],
        description="Soup and bread",
        tags=["meal"],
        now=NOW,
    )
    assert updated["metadata"]["tags"] == ["meal"]

    source = tmp_path / "receipt.txt"
    source.write_text("Receipt text")
    attached = bridge.call(
        "capture.attachment.add",
        path=updated["path"],
        expected_hash=updated["content_hash"],
        source_path=str(source),
        now=NOW,
    )
    capture = attached["capture"]
    attachment_id = attached["attachment"]["reference"]["attachment_id"]
    assert (vault / attached["attachment"]["reference"]["canonical_path"]).read_text() == "Receipt text"
    assert bridge.call("capture.attachment.audit", attachment_id=attachment_id)["status"] == "ok"

    job = bridge.call(
        "capture.enrichment.start",
        path=capture["path"],
        expected_hash=capture["content_hash"],
        now=NOW,
    )
    completed = bridge.call("capture.enrichment.run", job_id=job["job_id"], now=NOW)
    assert completed["state"] == "completed"
    listed = bridge.call("capture.filter", capture_types=["meal"], states=["enriched"])
    assert len(listed) == 1


def test_capture_bridge_links_merges_and_proposals_are_guarded(tmp_path: Path) -> None:
    bridge, vault = client(tmp_path)
    first = bridge.call("capture.create", title="One", capture_type="attachment", now=NOW)
    second = bridge.call("capture.create", title="Two", capture_type="attachment", now=NOW)
    linked = bridge.call(
        "capture.link",
        path=first["path"],
        expected_hash=first["content_hash"],
        target_path="diary/2026-07-16.md",
        relation="supports",
        artifact_type="diary",
        now=NOW,
    )
    assert linked["metadata"]["links"][0]["relation"] == "supports"
    preview = bridge.call("capture.merge.preview", source_paths=[linked["path"], second["path"]])
    merged = bridge.call("capture.merge.apply", preview=preview, now=NOW)
    assert len(merged["metadata"]["merged_from"]) == 2

    proposal = bridge.call(
        "capture.proposal.preview",
        capture_path=merged["path"],
        action="create-knowledge-note",
        target_path="notes/capture.md",
        content="# Reviewed capture",
        create_target=True,
        attachment_ids=[],
        included_actions=["create note"],
        excluded_actions=["change capture"],
        now=NOW,
    )
    assert proposal["operation"] == "create_file"
    assert not (vault / "notes" / "capture.md").exists()


def test_capture_bridge_rejects_extra_fields_stale_writes_and_bad_shapes(tmp_path: Path) -> None:
    bridge, _ = client(tmp_path)
    created = bridge.call("capture.create", title="Walk", capture_type="exercise", now=NOW)
    with pytest.raises(ProtocolError) as extra:
        bridge.call("capture.read", path=created["path"], surprise=True)
    assert extra.value.code == "extra_fields"
    with pytest.raises(ProtocolError) as stale:
        bridge.call(
            "capture.update",
            path=created["path"],
            expected_hash="sha256:" + "0" * 64,
            description="changed",
        )
    assert stale.value.code == "stale_capture"
    with pytest.raises(ProtocolError) as malformed:
        bridge.call("capture.split", path=created["path"], expected_hash=created["content_hash"], groups="bad")
    assert malformed.value.code == "invalid_params"


def test_capture_processing_can_be_cancelled_and_retried(tmp_path: Path) -> None:
    bridge, _ = client(tmp_path)
    created = bridge.call("capture.create", title="Audio", capture_type="attachment", now=NOW)
    job = bridge.call(
        "capture.enrichment.start",
        path=created["path"],
        expected_hash=created["content_hash"],
        now=NOW,
    )
    cancelled = bridge.call("capture.enrichment.cancel", job_id=job["job_id"], now=NOW)
    assert cancelled["state"] == "cancelled"
    retry = bridge.call("capture.enrichment.retry", job_id=job["job_id"], now=NOW)
    assert retry["state"] == "queued"
