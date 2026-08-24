from __future__ import annotations

import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError
from lifeos.daily import content_hash
from lifeos.proposals.loader import load_proposal_directory
from lifeos.reviews import ReviewArtifactService, artifact_item_fingerprints, rebuild_review_state

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
EVENING = datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def seeded_app(tmp_path: Path) -> BridgeApplication:
    write(
        tmp_path / "plans" / "reading.md",
        """---
id: plan-reading
type: plan
title: Reading plan
status: active
tasks:
  - task_id: read-one
    title: Read one chapter
    status: todo
    planned_for: 2026-07-16
---

Human plan notes.
""",
    )
    write(tmp_path / "raw" / "idea.md", "---\ntype: raw\ntitle: Review me\nstatus: inbox\n---\n\nA capture.\n")
    return BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")


def open_review(app: BridgeApplication, *, kind: str = "daily", phase: str | None = "morning", now: datetime = NOW):
    payload = {
        "kind": kind,
        "day": "2026-07-16",
        "timezone": "UTC",
        "now": now.isoformat(),
        "idempotency_key": f"e2e-open-{kind}-{phase or 'week'}",
        "refresh": True,
    }
    if phase is not None:
        payload["phase"] = phase
    return app.dispatch("review.artifact.open", payload)


def _seed_weekly_review(root: Path, day: date) -> None:
    iso = day.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    timestamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    write(
        root / "reviews" / "weekly" / f"{label}.md",
        f"""---
type: review
review_schema: 1
review_id: weekly-{label}
review_kind: weekly
period_start: {day.isoformat()}
period_end: {(day + timedelta(days=6)).isoformat()}
timezone: UTC
status: open
created_at: "{timestamp}"
updated_at: "{timestamp}"
phases:
  - phase_id: weekly
    state: pending
    completed_sections: []
    skipped_sections: []
current_phase: weekly
item_decisions: []
answers: []
proposal_refs: []
migrated_from: []
snapshot_history: []
lifecycle_events: []
---

# Weekly review: {label}

<!-- lifeos:managed:start facts -->
## Review facts

Seeded history fixture.
<!-- lifeos:managed:end facts -->

<!-- lifeos:managed:start items -->
## Review items

No review items.
<!-- lifeos:managed:end items -->

<!-- lifeos:managed:start continuity -->
## Continuity

No previous review is linked.
<!-- lifeos:managed:end continuity -->

## Weekly reflection

<!-- lifeos:managed:start completion-summary -->
## Completion summary

Review is open.
<!-- lifeos:managed:end completion-summary -->
""",
    )


def test_daily_review_survives_human_edits_runtime_deletion_and_rebuild(tmp_path: Path) -> None:
    app = seeded_app(tmp_path)
    opened = open_review(app)
    path = tmp_path / opened["artifact"]["path"]
    path.write_text(path.read_text(encoding="utf-8").replace("### Orientation", "### Orientation\n\nProtect the first hour for reading."), encoding="utf-8")

    loaded = app.dispatch("review.artifact.load", {"path": opened["artifact"]["path"], "now": NOW.isoformat()})
    refreshed = app.dispatch("review.artifact.refresh", {
        "review_id": loaded["artifact"]["metadata"]["review_id"],
        "expected_hash": loaded["artifact"]["content_hash"],
        "now": (NOW + timedelta(minutes=5)).isoformat(),
        "idempotency_key": "e2e-refresh-human",
    })
    assert "Protect the first hour for reading." in path.read_text(encoding="utf-8")

    artifact = refreshed["artifact"]
    for section in ("attention", "plans"):
        artifact = app.dispatch("review.artifact.section", {
            "review_id": artifact["metadata"]["review_id"], "phase_id": "morning", "section_id": section,
            "action": "complete", "expected_hash": artifact["content_hash"], "now": NOW.isoformat(),
            "idempotency_key": f"e2e-morning-{section}",
        })
    artifact = app.dispatch("review.artifact.phase", {
        "review_id": artifact["metadata"]["review_id"], "phase_id": "morning", "action": "complete",
        "required_sections": ["attention", "plans"], "expected_hash": artifact["content_hash"],
        "now": NOW.isoformat(), "idempotency_key": "e2e-morning-complete",
    })
    evening = open_review(app, phase="evening", now=EVENING)
    artifact = evening["artifact"]
    for section in ("daily-evidence", "attention"):
        artifact = app.dispatch("review.artifact.section", {
            "review_id": artifact["metadata"]["review_id"], "phase_id": "evening", "section_id": section,
            "action": "complete", "expected_hash": artifact["content_hash"], "now": EVENING.isoformat(),
            "idempotency_key": f"e2e-evening-{section}",
        })
    artifact = app.dispatch("review.artifact.phase", {
        "review_id": artifact["metadata"]["review_id"], "phase_id": "evening", "action": "complete",
        "required_sections": ["daily-evidence", "attention"], "expected_hash": artifact["content_hash"],
        "now": EVENING.isoformat(), "idempotency_key": "e2e-evening-complete",
    })
    artifact = app.dispatch("review.artifact.complete", {
        "review_id": artifact["metadata"]["review_id"], "expected_hash": artifact["content_hash"],
        "now": EVENING.isoformat(), "idempotency_key": "e2e-review-complete",
    })
    assert artifact["metadata"]["status"] == "completed"

    shutil.rmtree(tmp_path / ".lifeos")
    rebuilt = rebuild_review_state(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    assert rebuilt.progress_entries == 1
    resumed = app.dispatch("review.artifact.load", {"review_id": "daily-2026-07-16", "now": EVENING.isoformat()})
    assert resumed["artifact"]["metadata"]["status"] == "completed"
    assert "Protect the first hour for reading." in resumed["artifact"]["body"]


def test_review_proposal_is_draft_and_external_target_stays_unchanged(tmp_path: Path) -> None:
    app = seeded_app(tmp_path)
    opened = open_review(app)
    service = ReviewArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    artifact = service.load_id(opened["artifact"]["metadata"]["review_id"])
    item_id, fingerprint = next((key, value) for key, value in artifact_item_fingerprints(artifact).items() if key.startswith("inbox:"))
    target = tmp_path / "raw" / "idea.md"
    original = target.read_text(encoding="utf-8")
    proposal = app.dispatch("review.proposal.create", {
        "review_id": artifact.metadata.review_id, "item_id": item_id, "evidence_fingerprint": fingerprint,
        "target_path": "raw/idea.md", "expected_target_hash": "sha256:" + content_hash(original),
        "action": "set_note_status", "value": "archived", "rationale": "This capture was reviewed.",
        "now": NOW.isoformat(),
    })
    assert target.read_text(encoding="utf-8") == original
    loaded = load_proposal_directory(tmp_path / proposal["proposal_path"], proposals_root=tmp_path / "proposals")
    assert loaded.proposal is not None and loaded.proposal.metadata.status == "draft"
    decided = app.dispatch("review.artifact.decide", {
        "review_id": artifact.metadata.review_id, "item_id": item_id, "evidence_fingerprint": fingerprint,
        "decision": "propose_change", "proposal_id": proposal["proposal_id"], "expected_hash": artifact.content_hash,
        "idempotency_key": "e2e-attach-proposal", "now": NOW.isoformat(),
    })
    assert proposal["proposal_id"] in decided["metadata"]["proposal_refs"]


def test_sparse_degraded_concurrent_and_migrated_paths_fail_safe(tmp_path: Path) -> None:
    sparse = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    opened = open_review(sparse)
    assert opened["artifact"]["path"] == "reviews/daily/2026-07-16.md"
    assert all(section["state"] in {"empty", "ready", "unavailable"} for section in opened["snapshot"]["sections"])
    with pytest.raises(ProtocolError) as stale:
        sparse.dispatch("review.artifact.refresh", {
            "review_id": "daily-2026-07-16", "expected_hash": "0" * 64,
            "now": NOW.isoformat(), "idempotency_key": "e2e-stale",
        })
    assert stale.value.code == "stale_write"

    legacy = tmp_path / "reviews" / "morning-2026-07-17.md"
    write(legacy, "---\ntype: review\nreview_kind: morning\ndate: 2026-07-17\nstatus: active\n---\n\n# Morning review\n\n<!-- lifeos:managed:start facts -->\nOld\n<!-- lifeos:managed:end facts -->\n\n## Reflection\n\nLegacy human text.\n")
    preview = sparse.dispatch("review.artifact.migration.preview", {})
    expected = {source["path"]: source["content_hash"] for source in preview["candidates"][0]["sources"]}
    migrated = sparse.dispatch("review.artifact.migration.apply", {
        "now": NOW.isoformat(), "idempotency_key": "e2e-migrate", "expected_source_hashes": expected,
    })
    assert migrated["migrated"] == ["daily-2026-07-17"]
    assert legacy.exists()


def test_weekly_history_is_bounded_and_fast_for_a_long_vault(tmp_path: Path) -> None:
    start = date(2024, 1, 1)
    for offset in range(120):
        _seed_weekly_review(tmp_path, start + timedelta(weeks=offset))
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    began = time.perf_counter()
    history = app.dispatch("review.artifact.history", {"kind": "weekly", "limit": 50})
    elapsed = time.perf_counter() - began
    assert len(history) == 50
    assert history[0]["period_start"] > history[-1]["period_start"]
    assert elapsed < 3.0


def test_review_release_surface_is_provider_neutral_and_schema_visible(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    files = [
        root / "src/lifeos/reviews/contracts.py",
        root / "src/lifeos/reviews/artifact.py",
        root / "src/lifeos/reviews/snapshot.py",
        root / "packages/obsidian-plugin/src/review-artifact.ts",
        root / "packages/obsidian-plugin/src/review-workspace.ts",
    ]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
    assert "anthropic" not in text and "claude" not in text
    assert "review_schema_version = 1" in text
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    handshake = app.dispatch("system.handshake", {"protocol": "1.0"})
    for capability in ("review.artifact.open", "review.artifact.refresh", "review.artifact.migration.preview", "review.artifact.rebuild"):
        assert capability in handshake["capabilities"]
