from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

import lifeos.proposals.application as application_module
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.patterns import (
    ArchivePatternRequest,
    CreatePatternSeedRequest,
    MarkPatternNeedsReviewRequest,
    PatternArtifactService,
    PatternError,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    PatternProposalService,
    PatternStatus,
    PromotePatternRequest,
    ResolvePatternReviewRequest,
    RevisePatternRequest,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.proposals import (
    ApplicationError,
    CreateFile,
    PatchHumanFile,
    ProposalStatus,
    apply_proposal,
    approve_proposal,
    load_proposal_directory,
    reject_proposal,
    submit_proposal_for_review,
)
from lifeos.proposals.application import ApplicationErrorCode
from lifeos.proposals.recovery_service import RecoveryAction, recover_interrupted_applications

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
T0 = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 4, 5, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 4, 5, 2, tzinfo=timezone.utc)
T3 = datetime(2026, 9, 4, 5, 3, tzinfo=timezone.utc)
T4 = datetime(2026, 9, 4, 5, 4, tzinfo=timezone.utc)


class _InjectedInterruption(BaseException):
    pass


def _evidence(*, contesting: bool = False) -> tuple[PatternEvidence, ...]:
    items = [
        PatternEvidence(
            path="journal/2026-09-01.md",
            source_id="journal-2026-09-01",
            content_hash=HASH_A,
            role="supporting",
            observation_id="obs-focus-1",
        )
    ]
    if contesting:
        items.append(
            PatternEvidence(
                path="journal/2026-09-02.md",
                content_hash=HASH_B,
                role="contesting",
                event_id="event-focus-2",
            )
        )
    return tuple(items)


def _metadata(*, status: PatternStatus = "seed") -> PatternMetadata:
    evidence = _evidence()
    return PatternMetadata(
        pattern_id="pattern-focus-after-walk",
        title="Focus after walking",
        description="Morning walking may be associated with better focus.",
        status=status,
        confidence="medium",
        review_reasons=(),
        statement="Walking before study tends to precede better focus.",
        origin=PatternOrigin("manual"),
        created_at="2026-09-04T04:00:00Z",
        updated_at="2026-09-04T04:00:00Z",
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
    )


def _vault(tmp_path: Path) -> tuple[Path, PatternProposalService]:
    vault = tmp_path / "vault"
    (vault / "patterns").mkdir(parents=True)
    (vault / "system").mkdir()
    (vault / "system" / "generated-ownership.json").write_bytes(
        serialize_generated_ownership_bytes({})
    )
    return vault, PatternProposalService(vault_root=vault, actor_id="pattern-agent")


def _write_pattern(vault: Path, *, status: PatternStatus = "seed") -> Path:
    target = vault / "patterns" / "focus-after-walk.md"
    target.write_text(
        serialize_pattern(
            _metadata(status=status),
            body_prefix="\n# Working hypothesis\n\nHuman context stays here.  \n\n",
            body_suffix="\n\n## Reflection\n\nKeep this exact.  \n",
        ),
        encoding="utf-8",
    )
    return target


def _load(vault: Path, proposal_id: str):
    result = load_proposal_directory(
        vault / "proposals" / proposal_id,
        proposals_root=vault / "proposals",
    )
    assert result.findings == ()
    assert result.proposal is not None
    return result.proposal


def _submit(vault: Path, proposal_id: str):
    draft = _load(vault, proposal_id)
    submit_proposal_for_review(
        draft,
        proposals_root=vault / "proposals",
        submitted_by="reviewer",
        submitted_at="2026-09-04T05:10:00Z",
    )
    return _load(vault, proposal_id)


def _approve(vault: Path, proposal_id: str):
    pending = _submit(vault, proposal_id)
    approve_proposal(
        pending,
        proposals_root=vault / "proposals",
        approved_by="approver",
        approved_at="2026-09-04T05:11:00Z",
    )
    return _load(vault, proposal_id)


def _publish_id(
    service: PatternProposalService,
    request,
    *,
    now: datetime,
) -> str:
    result = service.publish(request, now=now)
    proposal_id = result["proposal_id"]
    assert isinstance(proposal_id, str)
    return proposal_id


def test_create_seed_is_proposal_only_human_owned_and_detects_collision(tmp_path: Path) -> None:
    vault, service = _vault(tmp_path)
    ownership_before = (vault / "system" / "generated-ownership.json").read_bytes()
    request = CreatePatternSeedRequest(
        target_path="patterns/focus-after-walk.md",
        pattern_id="pattern-focus-after-walk",
        title="Focus after walking",
        description="Morning walking may be associated with better focus.",
        statement="Walking before study may precede better focus.",
        confidence="low",
        origin=PatternOrigin("observation", "observe:focus-after-walk"),
        evidence=_evidence(),
        transition_reason="Track this hypothesis without adopting it.",
    )

    preview, patch, proposal_markdown = service.preview(request, now=T0)

    assert preview.action == "create-seed"
    assert preview.from_status is None
    assert preview.to_status == "seed"
    assert isinstance(patch.operations[0], CreateFile)
    assert b"status: draft" in proposal_markdown
    assert not (vault / request.target_path).exists()

    proposal_id = _publish_id(service, request, now=T0)
    approved = _approve(vault, proposal_id)
    apply_proposal(
        approved,
        vault_root=vault,
        applied_by="operator",
        applied_at="2026-09-04T05:12:00Z",
    )

    artifact = PatternArtifactService(vault_root=vault).load(request.target_path)
    assert artifact.metadata.status == "seed"
    assert artifact.metadata.last_reviewed_at is None
    assert (vault / "system" / "generated-ownership.json").read_bytes() == ownership_before

    with pytest.raises(PatternError) as collision:
        service.preview(
            replace(request, pattern_id="pattern-other"),
            now=T1,
        )
    assert collision.value.code == "target_exists"


def test_promote_requires_proposal_review_and_rejection_leaves_seed_unchanged(
    tmp_path: Path,
) -> None:
    vault, service = _vault(tmp_path)
    target = _write_pattern(vault)
    before = target.read_bytes()
    request = PromotePatternRequest(
        target_path="patterns/focus-after-walk.md",
        transition_reason="Reviewed the evidence and want to use this as active context.",
    )

    preview, patch, _ = service.preview(request, now=T1)
    assert preview.from_status == "seed"
    assert preview.to_status == "active"
    assert preview.base_hash is not None
    assert isinstance(patch.operations[0], PatchHumanFile)
    assert target.read_bytes() == before

    rejected_id = _publish_id(service, request, now=T1)
    pending = _submit(vault, rejected_id)
    reject_proposal(
        pending,
        proposals_root=vault / "proposals",
        rejected_by="reviewer",
        rejected_at="2026-09-04T05:13:00Z",
        rejection_reason="Evidence is not convincing enough yet.",
    )
    assert _load(vault, rejected_id).metadata.status is ProposalStatus.REJECTED
    assert target.read_bytes() == before
    assert PatternArtifactService(vault_root=vault).load(
        "patterns/focus-after-walk.md"
    ).metadata.status == "seed"

    approved_id = _publish_id(service, request, now=T2)
    approved = _approve(vault, approved_id)
    apply_proposal(
        approved,
        vault_root=vault,
        applied_by="operator",
        applied_at="2026-09-04T05:14:00Z",
    )
    active = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")
    assert active.metadata.status == "active"
    assert active.metadata.last_reviewed_at == "2026-09-04T05:02:00Z"


def test_revision_keeps_counter_evidence_and_archive_preserves_human_body(tmp_path: Path) -> None:
    vault, service = _vault(tmp_path)
    target = _write_pattern(vault, status="active")
    original = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")
    evidence = _evidence(contesting=True)
    request = RevisePatternRequest(
        target_path="patterns/focus-after-walk.md",
        transition_reason="New journal evidence contests the earlier interpretation.",
        statement="Walking may help focus, but the effect appears context-dependent.",
        evidence=evidence,
        confidence="low",
    )

    revision_id = _publish_id(service, request, now=T1)
    apply_proposal(
        _approve(vault, revision_id),
        vault_root=vault,
        applied_by="operator",
        applied_at="2026-09-04T05:15:00Z",
    )
    revised = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")
    assert [item.role for item in revised.metadata.evidence] == ["supporting", "contesting"]
    assert revised.metadata.evidence_fingerprint == compute_evidence_fingerprint(evidence)
    assert revised.metadata.evidence_fingerprint != original.metadata.evidence_fingerprint
    assert revised.metadata.confidence == "low"
    assert revised.body_prefix == original.body_prefix
    assert revised.body_suffix == original.body_suffix

    archive_id = _publish_id(
        service,
        ArchivePatternRequest(
            target_path="patterns/focus-after-walk.md",
            transition_reason="Keep the history but remove this from ordinary active context.",
        ),
        now=T2,
    )
    apply_proposal(
        _approve(vault, archive_id),
        vault_root=vault,
        applied_by="operator",
        applied_at="2026-09-04T05:16:00Z",
    )
    archived = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")
    assert archived.metadata.status == "archived"
    assert archived.body_prefix == original.body_prefix
    assert archived.body_suffix == original.body_suffix
    assert target.exists()


def test_review_resolution_requires_explicit_seed_or_active_target(tmp_path: Path) -> None:
    vault, service = _vault(tmp_path)
    _write_pattern(vault)
    mark_id = _publish_id(
        service,
        MarkPatternNeedsReviewRequest(
            target_path="patterns/focus-after-walk.md",
            transition_reason="The reviewed evidence version changed.",
            review_reasons=("evidence-changed",),
        ),
        now=T1,
    )
    apply_proposal(
        _approve(vault, mark_id),
        vault_root=vault,
        applied_by="operator",
        applied_at="2026-09-04T05:17:00Z",
    )

    needs_review = PatternArtifactService(vault_root=vault).load(
        "patterns/focus-after-walk.md"
    )
    assert needs_review.metadata.status == "needs-review"
    assert needs_review.metadata.review_reasons == ("evidence-changed",)

    resolve_id = _publish_id(
        service,
        ResolvePatternReviewRequest(
            target_path="patterns/focus-after-walk.md",
            transition_reason="Reviewed the change; keep this hypothesis exploratory.",
            target_status="seed",
        ),
        now=T2,
    )
    apply_proposal(
        _approve(vault, resolve_id),
        vault_root=vault,
        applied_by="operator",
        applied_at="2026-09-04T05:18:00Z",
    )
    resolved = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")
    assert resolved.metadata.status == "seed"
    assert resolved.metadata.review_reasons == ()
    assert resolved.metadata.last_reviewed_at == "2026-09-04T05:02:00Z"


def test_stale_target_blocks_approved_pattern_transition(tmp_path: Path) -> None:
    vault, service = _vault(tmp_path)
    target = _write_pattern(vault)
    proposal_id = _publish_id(
        service,
        PromotePatternRequest(
            target_path="patterns/focus-after-walk.md",
            transition_reason="Adopt after explicit review.",
        ),
        now=T1,
    )
    approved = _approve(vault, proposal_id)

    target.write_text(
        target.read_text(encoding="utf-8") + "\nExternal reflection.\n", encoding="utf-8"
    )
    externally_modified = target.read_bytes()

    with pytest.raises(ApplicationError) as stale:
        apply_proposal(
            approved,
            vault_root=vault,
            applied_by="operator",
            applied_at="2026-09-04T05:19:00Z",
        )
    assert stale.value.code is ApplicationErrorCode.PREFLIGHT_FAILED
    assert target.read_bytes() == externally_modified
    assert _load(vault, proposal_id).metadata.status is ProposalStatus.APPROVED


def test_interrupted_pattern_patch_uses_shared_recovery_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, service = _vault(tmp_path)
    target = _write_pattern(vault, status="active")
    before = target.read_bytes()
    proposal_id = _publish_id(
        service,
        RevisePatternRequest(
            target_path="patterns/focus-after-walk.md",
            transition_reason="Refine wording without bypassing recovery.",
            statement="Walking before study sometimes precedes better focus.",
        ),
        now=T1,
    )
    approved = _approve(vault, proposal_id)

    def checkpoint(name: str) -> None:
        if name == "after_all_targets":
            raise _InjectedInterruption(name)

    monkeypatch.setattr(application_module, "_application_checkpoint", checkpoint)
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            approved,
            vault_root=vault,
            applied_by="operator",
            applied_at="2026-09-04T05:20:00Z",
        )

    assert target.read_bytes() != before
    recovered = recover_interrupted_applications(vault_root=vault)

    assert recovered.transactions[0].action is RecoveryAction.ROLLED_BACK
    assert target.read_bytes() == before
    assert _load(vault, proposal_id).metadata.status is ProposalStatus.APPROVED
