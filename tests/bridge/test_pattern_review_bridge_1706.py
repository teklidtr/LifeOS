from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lifeos.bridge import BridgeApplication
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.patterns import PatternMetadata, PatternOrigin, compute_evidence_fingerprint, serialize_pattern

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_pattern(vault: Path, pattern_id: str) -> Path:
    metadata = PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id,
        description="Quiet active pattern.",
        status="active",
        confidence="medium",
        review_reasons=(),
        statement="Quiet working hypothesis.",
        origin=PatternOrigin("manual"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-01T09:00:00Z",
        last_reviewed_at="2026-09-01T09:00:00Z",
        review_due_at=None,
        evidence_fingerprint=compute_evidence_fingerprint(()),
        evidence=(),
        evaluation=None,
    )
    return _write(vault / "patterns" / f"{pattern_id}.md", serialize_pattern(metadata))


def _pattern_items(payload: dict[str, object]) -> list[dict[str, object]]:
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    sections = snapshot["sections"]
    assert isinstance(sections, list)
    section = next(
        item
        for item in sections
        if isinstance(item, dict) and item.get("section_id") == "personal-patterns-daily"
    )
    items = section["items"]
    assert isinstance(items, list)
    return items


def test_public_bridge_carries_explicit_daily_pattern_attention_on_open_and_refresh(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    _write_pattern(vault, "quiet")
    app = BridgeApplication(vault_root=vault, runtime_dir=runtime, actor_id="tester")

    opened = app.dispatch(
        "review.artifact.open",
        {
            "kind": "daily",
            "day": "2026-09-04",
            "timezone": "UTC",
            "now": NOW.isoformat(),
            "phase": "morning",
            "refresh": True,
            "pinned_pattern_ids": ["quiet"],
            "urgent_pattern_ids": [],
            "idempotency_key": "pattern-open",
        },
    )
    assert isinstance(opened, dict)
    assert [item["item_id"] for item in _pattern_items(opened)] == ["personal-pattern:quiet"]

    artifact = opened["artifact"]
    assert isinstance(artifact, dict)
    metadata = artifact["metadata"]
    assert isinstance(metadata, dict)
    refreshed = app.dispatch(
        "review.artifact.refresh",
        {
            "review_id": metadata["review_id"],
            "expected_hash": artifact["content_hash"],
            "now": NOW.isoformat(),
            "pinned_pattern_ids": ["quiet"],
            "urgent_pattern_ids": [],
            "idempotency_key": "pattern-refresh",
        },
    )
    assert isinstance(refreshed, dict)
    assert [item["item_id"] for item in _pattern_items(refreshed)] == ["personal-pattern:quiet"]


def test_pattern_propose_change_via_review_decision_creates_and_attaches_draft(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    _write(
        vault / "system" / "generated-ownership.json",
        serialize_generated_ownership_bytes({}).decode("utf-8"),
    )
    target = _write_pattern(vault, "quiet")
    before = target.read_text(encoding="utf-8")
    app = BridgeApplication(vault_root=vault, runtime_dir=runtime, actor_id="tester")
    opened = app.dispatch(
        "review.artifact.open",
        {
            "kind": "daily",
            "day": "2026-09-04",
            "timezone": "UTC",
            "now": NOW.isoformat(),
            "phase": "morning",
            "refresh": True,
            "pinned_pattern_ids": ["quiet"],
            "idempotency_key": "proposal-open",
        },
    )
    assert isinstance(opened, dict)
    item = _pattern_items(opened)[0]
    artifact = opened["artifact"]
    assert isinstance(artifact, dict)
    metadata = artifact["metadata"]
    assert isinstance(metadata, dict)

    decided = app.dispatch(
        "review.artifact.decide",
        {
            "review_id": metadata["review_id"],
            "item_id": item["item_id"],
            "evidence_fingerprint": item["evidence_fingerprint"],
            "decision": "propose_change",
            "expected_hash": artifact["content_hash"],
            "idempotency_key": "proposal-decide",
            "now": NOW.isoformat(),
            "note": "Explicit review handoff.",
        },
    )
    assert isinstance(decided, dict)
    decision = next(
        entry
        for entry in decided["metadata"]["item_decisions"]
        if entry["item_id"] == "personal-pattern:quiet"
    )
    proposal_id = decision["proposal_id"]
    assert proposal_id
    assert (vault / "proposals" / proposal_id / "proposal.md").exists()
    assert target.read_text(encoding="utf-8") == before
