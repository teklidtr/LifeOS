from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from lifeos.bridge.personal_model_workspace import PersonalModelWorkspaceBridge
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.patterns import (
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    PersonalModelService,
    build_personal_pattern_context,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.proposals import (
    apply_proposal,
    approve_proposal,
    load_proposal_directory,
    submit_proposal_for_review,
)
from lifeos.registry import Registry

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-09-04T12:00:00+00:00"
LARGE_VAULT_PATTERN_COUNT = 192
LARGE_VAULT_ORDINARY_PATTERN_NOTES = 768


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write(vault: Path, relative_path: str, content: str) -> Path:
    target = vault / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _metadata(
    pattern_id: str,
    *,
    status: str = "seed",
    confidence: str = "medium",
    review_reasons: tuple[str, ...] = (),
    evidence: tuple[PatternEvidence, ...] = (),
) -> PatternMetadata:
    return PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id.replace("-", " ").title(),
        description=f"Release fixture for {pattern_id}.",
        status=status,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        review_reasons=review_reasons,
        statement=f"Working hypothesis represented by {pattern_id}.",
        origin=PatternOrigin("manual"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-02T09:00:00Z",
        last_reviewed_at="2026-09-02T09:00:00Z" if status != "seed" else None,
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
    )


def _write_pattern(vault: Path, relative_path: str, metadata: PatternMetadata) -> Path:
    return _write(vault, relative_path, serialize_pattern(metadata))


def _load_proposal(vault: Path, proposal_id: str):
    result = load_proposal_directory(
        vault / "proposals" / proposal_id,
        proposals_root=vault / "proposals",
    )
    assert result.findings == ()
    assert result.proposal is not None
    return result.proposal


def _approve_and_apply(vault: Path, proposal_id: str, *, minute: int) -> None:
    draft = _load_proposal(vault, proposal_id)
    submit_proposal_for_review(
        draft,
        proposals_root=vault / "proposals",
        submitted_by="release-reviewer",
        submitted_at=f"2026-09-04T12:{minute:02d}:00Z",
    )
    pending = _load_proposal(vault, proposal_id)
    approve_proposal(
        pending,
        proposals_root=vault / "proposals",
        approved_by="release-approver",
        approved_at=f"2026-09-04T12:{minute + 1:02d}:00Z",
    )
    approved = _load_proposal(vault, proposal_id)
    apply_proposal(
        approved,
        vault_root=vault,
        applied_by="release-operator",
        applied_at=f"2026-09-04T12:{minute + 2:02d}:00Z",
    )


def test_release_history_matrix_keeps_uncertainty_and_lifecycle_visible(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    contesting = (
        PatternEvidence(
            path="journal/contesting.md",
            content_hash="sha256:" + "c" * 64,
            role="contesting",
        ),
    )
    histories = (
        _metadata("pattern-stable", status="active"),
        _metadata(
            "pattern-weakening",
            status="needs-review",
            review_reasons=("weaker-evidence",),
        ),
        _metadata(
            "pattern-contradicting",
            status="needs-review",
            review_reasons=("direction-reversal", "new-counter-evidence"),
            evidence=contesting,
        ),
        _metadata(
            "pattern-stale",
            status="needs-review",
            review_reasons=("stale-evidence",),
        ),
        _metadata("pattern-archived", status="archived"),
        _metadata("pattern-sparse", status="seed", confidence="low"),
    )
    for metadata in histories:
        _write_pattern(vault, f"patterns/{metadata.pattern_id}.md", metadata)

    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    service = PersonalModelService(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        registry=registry,
        allow_path=lambda _path: True,
    )
    document = service.rebuild(now=NOW)

    assert [item.pattern_id for item in document.active] == ["pattern-stable"]
    assert [item.pattern_id for item in document.archived] == ["pattern-archived"]
    assert [item.pattern_id for item in document.seeds] == ["pattern-sparse"]
    assert {item.pattern_id for item in document.needs_review} == {
        "pattern-contradicting",
        "pattern-stale",
        "pattern-weakening",
    }
    contradicting = next(
        item for item in document.needs_review if item.pattern_id == "pattern-contradicting"
    )
    assert contradicting.evidence[0].role == "contesting"
    assert document.seeds[0].confidence == "low"
    assert not hasattr(document, "score")


def test_large_vault_rebuild_is_bounded_deterministic_and_preserves_ordinary_markdown(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    arbitrary = _write(
        vault,
        "patterns/legacy-looking.md",
        "---\ntype: pattern\nstatus: active\nconfidence: high\n---\n"
        "# My old note\n\nThese fields are user-authored and are not a Phase 17 schema.\n",
    )
    arbitrary_before = arbitrary.read_bytes()

    for index in range(LARGE_VAULT_PATTERN_COUNT):
        pattern_id = f"pattern-release-{index:04d}"
        _write_pattern(vault, f"patterns/release/{index:04d}.md", _metadata(pattern_id))
    for index in range(LARGE_VAULT_ORDINARY_PATTERN_NOTES):
        _write(
            vault,
            f"patterns/notes/{index:04d}.md",
            f"# Ordinary pattern-area note {index}\n\n"
            "Human-authored prose remains ordinary Markdown.\n",
        )

    runtime = tmp_path / "runtime"
    registry = Registry(runtime / "registry.db")
    registry.initialize()
    service = PersonalModelService(
        vault_root=vault,
        runtime_dir=runtime,
        registry=registry,
        allow_path=lambda _path: True,
    )

    first = service.rebuild(now=NOW)
    second = service.rebuild(now=NOW)

    assert len(first.items) == LARGE_VAULT_PATTERN_COUNT
    assert first == second
    assert arbitrary.read_bytes() == arbitrary_before
    assert all(item.pattern_id.startswith("pattern-release-") for item in first.items)


def test_evidence_to_obsidian_release_flow_keeps_semantic_changes_proposal_gated(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "system/generated-ownership.json",
        serialize_generated_ownership_bytes({}).decode("utf-8"),
    )
    source_before = (
        "---\nid: journal-focus\ntype: journal\n---\n"
        "Walking preceded a focused block.\n"
    )
    source = _write(vault, "journal/focus.md", source_before)
    bridge = PersonalModelWorkspaceBridge(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        actor_id="obsidian-local",
    )
    bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})

    track = bridge.dispatch(
        "personal-model.proposal.create",
        {
            "action": "track",
            "target_path": "patterns/focus-after-walk.md",
            "pattern_id": "focus-after-walk",
            "title": "Focus after walk",
            "description": "Walking may be associated with a better next focus block.",
            "statement": "A short walk may precede a better next focus block.",
            "confidence": "low",
            "transition_reason": "Track this as a reviewable seed, not as a fact.",
            "evidence": [
                {
                    "path": "journal/focus.md",
                    "content_hash": _digest(source_before),
                    "role": "supporting",
                }
            ],
            "now": NOW_TEXT,
        },
    )
    assert not (vault / "patterns" / "focus-after-walk.md").exists()
    _approve_and_apply(vault, str(track["proposal_id"]), minute=5)

    seeded = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    seed = seeded["groups"]["seeds"][0]
    assert seed["pattern_id"] == "focus-after-walk"

    adopt = bridge.dispatch(
        "personal-model.proposal.create",
        {
            "action": "adopt",
            "target_path": seed["pattern_path"],
            "expected_target_hash": seed["pattern_content_hash"],
            "transition_reason": "I reviewed the evidence and accept this as working context.",
            "now": NOW_TEXT,
        },
    )
    _approve_and_apply(vault, str(adopt["proposal_id"]), minute=10)

    source_after = source_before.replace(
        "Walking preceded a focused block.",
        "Walking preceded a distracted block.",
    )
    source.write_text(source_after, encoding="utf-8")
    inspected = bridge.dispatch(
        "personal-model.rebuild",
        {"now": "2026-09-05T12:00:00+00:00"},
    )
    active = inspected["groups"]["active"][0]

    assert active["pattern_id"] == "focus-after-walk"
    assert active["review_recommendation"] == "review"
    assert active["evidence_changes"][0]["state"] == "changed"
    assert active["evidence_changes"][0]["reviewed_content_hash"] == _digest(source_before)
    assert active["evidence_changes"][0]["current_content_hash"] == _digest(source_after)

    context = build_personal_pattern_context(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        question="focus after walk",
    )
    item = next(
        candidate for candidate in context.items if candidate.pattern_id == "focus-after-walk"
    )
    assert item.interpretation == "reviewed-working-hypothesis"
    assert item.role == "evidence-not-instruction"
    assert item.can_authorize_mutation is False
