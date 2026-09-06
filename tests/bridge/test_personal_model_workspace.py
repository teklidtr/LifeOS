from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.bridge.personal_model_workspace import PersonalModelWorkspaceBridge
from lifeos.bridge.protocol import CAPABILITIES, ProtocolError
from lifeos.patterns import (
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-09-04T12:00:00+00:00"


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _metadata(
    pattern_id: str,
    *,
    status: str = "seed",
    evidence: tuple[PatternEvidence, ...] = (),
) -> PatternMetadata:
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
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
    )


def _write_pattern(vault: Path, name: str, metadata: PatternMetadata) -> Path:
    path = vault / "patterns" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_pattern(metadata), encoding="utf-8")
    return path


def _write(vault: Path, relative_path: str, content: str) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_policy(vault: Path) -> None:
    _write(
        vault,
        "system/retrieval-policy.yml",
        "schema_version: 1\n"
        "protected_prefixes:\n"
        "  - patterns/private\n"
        "  - journal/private\n"
        "  - reviews/private\n",
    )


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
    assert active["related_paths"] == [{"path": "reviews/daily/2026-09-04.md", "kind": "review"}]


def test_read_only_refresh_uses_current_evidence_without_mutating_persisted_registry(
    tmp_path: Path,
) -> None:
    bridge, vault = _bridge(tmp_path)
    before = "---\nid: source-one\ntype: note\ntitle: Source\n---\nbefore\n"
    source = _write(vault, "journal/source.md", before)
    evidence = (
        PatternEvidence(
            path="journal/source.md",
            source_id="source-one",
            content_hash=_digest(before),
            role="supporting",
        ),
    )
    _write_pattern(vault, "tracked.md", _metadata("pattern-tracked", evidence=evidence))
    bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})

    registry_path = tmp_path / "runtime" / "registry.db"
    persisted_before = registry_path.read_bytes()
    after = before.replace("before", "after")
    source.write_text(after, encoding="utf-8")

    workspace = bridge.dispatch("personal-model.workspace.get", {"now": NOW_TEXT})
    tracked = workspace["groups"]["seeds"][0]

    assert tracked["evidence_health"] == "attention"
    assert tracked["evidence_changes"] == [
        {
            "role": "supporting",
            "reviewed_path": "journal/source.md",
            "reviewed_content_hash": _digest(before),
            "state": "changed",
            "current_path": "journal/source.md",
            "current_content_hash": _digest(after),
        }
    ]
    assert registry_path.read_bytes() == persisted_before


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


def test_proposal_target_is_authorized_before_hash_or_content_disclosure(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    _write_policy(vault)
    _write_pattern(vault, "private/secret.md", _metadata("private-secret"))

    with pytest.raises(ProtocolError) as denied:
        bridge.dispatch(
            "personal-model.proposal.preview",
            {
                "action": "adopt",
                "target_path": "patterns/private/secret.md",
                "expected_target_hash": _digest("wrong"),
                "transition_reason": "Should be denied before reading the target.",
                "now": NOW_TEXT,
            },
        )

    assert denied.value.code == "authorization_denied"
    assert "current_hash" not in (denied.value.data or {})
    assert not (vault / "proposals").exists()


def test_proposal_preview_does_not_reexpose_protected_preserved_evidence(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    _write_policy(vault)
    evidence = (
        PatternEvidence(
            path="journal/private/source.md",
            content_hash=_digest("reviewed"),
            role="supporting",
        ),
    )
    pattern = _write_pattern(vault, "allowed.md", _metadata("allowed", evidence=evidence))
    current_hash = _digest(pattern.read_text(encoding="utf-8"))

    with pytest.raises(ProtocolError) as denied:
        bridge.dispatch(
            "personal-model.proposal.preview",
            {
                "action": "adopt",
                "target_path": "patterns/allowed.md",
                "expected_target_hash": current_hash,
                "transition_reason": "Protected evidence must remain outside the preview.",
                "now": NOW_TEXT,
            },
        )

    assert denied.value.code == "authorization_denied"
    assert not (vault / "proposals").exists()


def test_workspace_and_proposals_do_not_disclose_protected_origin_paths(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    _write_policy(vault)
    metadata = replace(
        _metadata("allowed-origin"),
        origin=PatternOrigin("manual", source_ref="reviews/private/secret.md"),
    )
    pattern = _write_pattern(vault, "allowed-origin.md", metadata)

    workspace = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    item = workspace["groups"]["seeds"][0]
    assert item["origin"] == {"kind": "manual", "source_ref": None}
    assert item["related_paths"] == []

    with pytest.raises(ProtocolError) as denied:
        bridge.dispatch(
            "personal-model.proposal.preview",
            {
                "action": "adopt",
                "target_path": "patterns/allowed-origin.md",
                "expected_target_hash": _digest(pattern.read_text(encoding="utf-8")),
                "transition_reason": "Protected origin identity must not enter a candidate.",
                "now": NOW_TEXT,
            },
        )

    assert denied.value.code == "authorization_denied"
    assert not (vault / "proposals").exists()


def test_track_duplicate_scan_never_opens_protected_pattern_bytes(tmp_path: Path) -> None:
    bridge, vault = _bridge(tmp_path)
    _write_policy(vault)
    _write(
        vault,
        "patterns/private/broken.md",
        "---\npattern_schema: 1\ntype: pattern\nevidence: [\n",
    )

    preview = bridge.dispatch(
        "personal-model.proposal.preview",
        {
            "action": "track",
            "target_path": "patterns/visible.md",
            "pattern_id": "visible-seed",
            "title": "Visible seed",
            "description": "Allowed working hypothesis.",
            "statement": "This remains a cautious seed.",
            "confidence": "low",
            "transition_reason": "Track only within the authorized pattern scope.",
            "evidence": [],
            "now": NOW_TEXT,
        },
    )

    assert preview["preview"]["action"] == "create-seed"
    assert not (vault / "patterns" / "visible.md").exists()


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
