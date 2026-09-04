from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.bridge.personal_model_workspace import PersonalModelWorkspaceBridge
from lifeos.bridge.protocol import CAPABILITIES, ProtocolError
from lifeos.patterns import (
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-09-04T12:00:00+00:00"


def _metadata(pattern_id: str, *, status: str = "seed") -> PatternMetadata:
    return PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id.replace("-", " ").title(),
        description=f"Description for {pattern_id}.",
        status=status,  # type: ignore[arg-type]
        confidence="medium",
        review_reasons=("Needs another look.",) if status == "needs-review" else (),
        statement=f"Statement for {pattern_id}.",
        origin=PatternOrigin("manual", source_ref="reviews/daily/2026-09-04.md"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-02T09:00:00Z",
        last_reviewed_at="2026-09-02T09:00:00Z" if status != "seed" else None,
        review_due_at=None,
        evidence_fingerprint=compute_evidence_fingerprint(()),
        evidence=(),
    )


def _write_pattern(vault: Path, name: str, metadata: PatternMetadata) -> Path:
    path = vault / "patterns" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_pattern(metadata), encoding="utf-8")
    return path


def _bridge(tmp_path: Path) -> tuple[PersonalModelWorkspaceBridge, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    return (
        PersonalModelWorkspaceBridge(
            vault_root=vault,
            runtime_dir=tmp_path / "runtime",
            actor_id="obsidian-local",
        ),
        vault,
    )


def test_capabilities_advertise_personal_model_workspace_contract() -> None:
    assert {
        "personal-model.workspace.get",
        "personal-model.rebuild",
        "personal-model.proposal.preview",
        "personal-model.proposal.create",
    } <= set(CAPABILITIES)


def test_missing_runtime_requires_explicit_rebuild_and_empty_model_is_valid(tmp_path: Path) -> None:
    bridge, _vault = _bridge(tmp_path)

    with pytest.raises(ProtocolError) as missing:
        bridge.dispatch("personal-model.workspace.get", {"now": NOW_TEXT})
    assert missing.value.code == "personal_model_rebuild_required"

    rebuilt = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    assert rebuilt["runtime_state"] == "ready"
    assert rebuilt["groups"] == {
        "active": [],
        "needs_review": [],
        "seeds": [],
        "archived": [],
    }


def test_workspace_exposes_mixed_states_statement_and_related_review_links(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    _write_pattern(vault, "active.md", _metadata("pattern-active", status="active"))
    _write_pattern(vault, "seed.md", _metadata("pattern-seed"))
    _write_pattern(vault, "review.md", _metadata("pattern-review", status="needs-review"))
    _write_pattern(vault, "archive.md", _metadata("pattern-archive", status="archived"))

    workspace = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    groups = workspace["groups"]
    assert [item["pattern_id"] for item in groups["active"]] == ["pattern-active"]
    assert [item["pattern_id"] for item in groups["seeds"]] == ["pattern-seed"]
    assert [item["pattern_id"] for item in groups["needs_review"]] == ["pattern-review"]
    assert [item["pattern_id"] for item in groups["archived"]] == ["pattern-archive"]
    active = groups["active"][0]
    assert active["statement"] == "Statement for pattern-active."
    assert active["confidence"] == "medium"
    assert active["evidence_health"] == "none"
    assert active["related_paths"] == [
        {"path": "reviews/daily/2026-09-04.md", "kind": "review"}
    ]


def test_proposal_preview_is_read_only_and_create_keeps_pattern_unchanged(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    pattern = _write_pattern(vault, "seed.md", _metadata("pattern-seed"))
    workspace = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    item = workspace["groups"]["seeds"][0]
    before = pattern.read_text(encoding="utf-8")
    params = {
        "action": "adopt",
        "target_path": item["pattern_path"],
        "expected_target_hash": item["pattern_content_hash"],
        "transition_reason": "I reviewed the visible evidence and want to use this as working context.",
        "now": NOW_TEXT,
    }

    preview = bridge.dispatch("personal-model.proposal.preview", params)
    assert preview["preview"]["action"] == "promote-active"
    assert preview["preview"]["from_status"] == "seed"
    assert preview["preview"]["to_status"] == "active"
    assert pattern.read_text(encoding="utf-8") == before
    assert not (vault / "proposals").exists()

    created = bridge.dispatch("personal-model.proposal.create", params)
    assert created["proposal_id"] == preview["preview"]["proposal_id"]
    assert (vault / created["proposal_path"] / "proposal.md").exists()
    assert pattern.read_text(encoding="utf-8") == before


def test_existing_pattern_actions_fail_closed_when_inspected_hash_is_stale(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    pattern = _write_pattern(vault, "seed.md", _metadata("pattern-seed"))
    workspace = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    item = workspace["groups"]["seeds"][0]

    changed = replace(_metadata("pattern-seed"), statement="Statement changed in Obsidian.")
    pattern.write_text(serialize_pattern(changed), encoding="utf-8")

    with pytest.raises(ProtocolError) as stale:
        bridge.dispatch(
            "personal-model.proposal.preview",
            {
                "action": "adopt",
                "target_path": item["pattern_path"],
                "expected_target_hash": item["pattern_content_hash"],
                "transition_reason": "Adopt after review.",
                "now": NOW_TEXT,
            },
        )
    assert stale.value.code == "stale_target"
    assert not (vault / "proposals").exists()


def test_track_contest_revise_and_archive_are_proposal_backed(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})

    tracked = bridge.dispatch(
        "personal-model.proposal.preview",
        {
            "action": "track",
            "target_path": "patterns/focus.md",
            "pattern_id": "focus-after-walk",
            "title": "Focus after walk",
            "description": "A working hypothesis to inspect.",
            "statement": "A short walk may improve my next focus block.",
            "confidence": "low",
            "transition_reason": "Track this as a seed, not as a fact.",
            "evidence": [],
            "now": NOW_TEXT,
        },
    )
    assert tracked["preview"]["action"] == "create-seed"
    assert not (vault / "patterns" / "focus.md").exists()

    pattern = _write_pattern(vault, "existing.md", _metadata("pattern-existing", status="active"))
    bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    workspace = bridge.dispatch("personal-model.workspace.get", {"now": NOW_TEXT})
    item = workspace["groups"]["active"][0]
    base = {
        "target_path": item["pattern_path"],
        "expected_target_hash": item["pattern_content_hash"],
        "now": NOW_TEXT,
    }
    contest = bridge.dispatch(
        "personal-model.proposal.preview",
        {
            **base,
            "action": "contest",
            "transition_reason": "The displayed evidence no longer feels sufficient.",
        },
    )
    revise = bridge.dispatch(
        "personal-model.proposal.preview",
        {
            **base,
            "action": "revise",
            "transition_reason": "Narrow the claim to match what I actually observed.",
            "statement": "A short walk may sometimes improve my next focus block.",
        },
    )
    archive = bridge.dispatch(
        "personal-model.proposal.preview",
        {
            **base,
            "action": "archive",
            "transition_reason": "I no longer want this hypothesis in current review rotation.",
        },
    )
    assert contest["preview"]["action"] == "mark-needs-review"
    assert revise["preview"]["action"] == "revise"
    assert archive["preview"]["action"] == "archive"
    assert pattern.exists()
