import hashlib
import json
from pathlib import Path

import pytest

import lifeos.proposals.application as application_module
import lifeos.proposals.recovery_service as recovery_service_module
from lifeos.proposals.application import ApplicationError, ApplicationErrorCode, apply_proposal
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import (
    CreateFile,
    CreateGeneratedFileV2,
    PatchDocumentV2,
    ReplaceGeneratedFileV2,
)
from lifeos.proposals.recovery import (
    RecoveryConflictError,
    RecoveryLockUnavailableError,
    RecoveryPhase,
    acquire_recovery_lock,
    discover_recovery_state,
)
from lifeos.proposals.recovery_service import (
    RecoveryAction,
    recover_interrupted_applications,
)
from tests.proposals.test_application import _make_meta, _setup_proposal


class _InjectedInterruption(BaseException):
    pass


def _load_two_target_application(tmp_path: Path):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    operations = (
        ReplaceGeneratedFileV2(
            "op-1", "test1.txt", old_hash, "gen-1", "v1", "new_content1"
        ),
        CreateGeneratedFileV2(
            "op-2", "test2.txt", "absent", "gen-1", "v1", "new_content2"
        ),
    )
    document = PatchDocumentV2(2, meta.id, operations)
    vault_root, proposals_root, proposal_dir = _setup_proposal(tmp_path, meta, document)
    (vault_root / "test1.txt").write_bytes(b"old_content")
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    return meta, vault_root, loaded.proposal


def _load_non_generated_application(tmp_path: Path):
    meta = _make_meta()
    document = PatchDocumentV2(
        2,
        meta.id,
        (CreateFile("op-1", "human.txt", "absent", "human content"),),
    )
    vault_root, proposals_root, proposal_dir = _setup_proposal(
        tmp_path, meta, document
    )
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    return meta, vault_root, loaded.proposal


def _interrupt_at(monkeypatch: pytest.MonkeyPatch, checkpoint_name: str) -> None:
    def checkpoint(name: str) -> None:
        if name == checkpoint_name:
            raise _InjectedInterruption(name)

    monkeypatch.setattr(application_module, "_application_checkpoint", checkpoint)


def _single_journal(vault_root: Path):
    discovery = discover_recovery_state(recovery_root=vault_root / ".lifeos" / "recovery")
    assert discovery.findings == ()
    assert len(discovery.journals) == 1
    return discovery.journals[0]


def _assert_pre_state(vault_root: Path, proposal_id: str) -> None:
    assert (vault_root / "test1.txt").read_bytes() == b"old_content"
    assert not (vault_root / "test2.txt").exists()
    ownership = json.loads((vault_root / "system/generated-ownership.json").read_text())
    assert ownership["owned_files"]["test1.txt"]["content_hash"] == hashlib.sha256(
        b"old_content"
    ).hexdigest()
    proposal_text = (vault_root / "proposals" / proposal_id / "proposal.md").read_text()
    assert "status: approved" in proposal_text
    assert "status: applied" not in proposal_text


def test_recovery_from_prepared_phase_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_prepared_journal")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    first = recover_interrupted_applications(vault_root=vault_root)
    second = recover_interrupted_applications(vault_root=vault_root)

    assert first.transactions[0].action is RecoveryAction.ROLLED_BACK
    assert second.transactions == ()
    _assert_pre_state(vault_root, meta.id)


def test_recovery_from_partial_target_phase_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_target_install:0")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    original_restore = recovery_service_module.restore_canonical_from_backup
    interrupted = False

    def restore_then_interrupt(**kwargs):
        nonlocal interrupted
        result = original_restore(**kwargs)
        if not interrupted:
            interrupted = True
            raise _InjectedInterruption("during recovery rollback")
        return result

    monkeypatch.setattr(
        recovery_service_module,
        "restore_canonical_from_backup",
        restore_then_interrupt,
    )
    with pytest.raises(_InjectedInterruption):
        recover_interrupted_applications(vault_root=vault_root)

    monkeypatch.setattr(
        recovery_service_module,
        "restore_canonical_from_backup",
        original_restore,
    )
    result = recover_interrupted_applications(vault_root=vault_root)
    assert result.transactions[0].phase_before is RecoveryPhase.PREPARED
    assert result.transactions[0].action is RecoveryAction.ROLLED_BACK
    assert recover_interrupted_applications(vault_root=vault_root).transactions == ()
    _assert_pre_state(vault_root, meta.id)


def test_recovery_after_ownership_install_restores_consistency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_ownership_install")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    result = recover_interrupted_applications(vault_root=vault_root)
    assert result.transactions[0].phase_before is RecoveryPhase.TARGETS_INSTALLED
    assert result.transactions[0].action is RecoveryAction.ROLLED_BACK
    _assert_pre_state(vault_root, meta.id)


def test_recovery_after_proposal_commit_finishes_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    original_writer = application_module.write_recovery_journal

    def interrupt_complete(*, recovery_root: Path, journal) -> None:
        if journal.phase is RecoveryPhase.COMPLETE:
            raise _InjectedInterruption("before complete journal")
        original_writer(recovery_root=recovery_root, journal=journal)

    monkeypatch.setattr(application_module, "write_recovery_journal", interrupt_complete)
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_journal(vault_root)
    assert journal.phase is RecoveryPhase.PROPOSAL_COMMITTED

    result = recover_interrupted_applications(vault_root=vault_root)
    assert result.transactions[0].action is RecoveryAction.COMPLETED
    assert not (vault_root / ".lifeos" / "recovery" / str(journal.transaction_id)).exists()
    assert (vault_root / "test1.txt").read_bytes() == b"new_content1"
    assert (vault_root / "test2.txt").read_bytes() == b"new_content2"
    proposal_text = (vault_root / "proposals" / meta.id / "proposal.md").read_text()
    assert "status: applied" in proposal_text


def test_recovery_rolls_forward_when_proposal_publish_precedes_phase_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    original_writer = application_module.write_recovery_journal

    def interrupt_phase_update(*, recovery_root: Path, journal) -> None:
        if journal.phase is RecoveryPhase.PROPOSAL_COMMITTED:
            raise _InjectedInterruption("after proposal publish")
        original_writer(recovery_root=recovery_root, journal=journal)

    monkeypatch.setattr(
        application_module,
        "write_recovery_journal",
        interrupt_phase_update,
    )
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_journal(vault_root)
    assert journal.phase is RecoveryPhase.OWNERSHIP_INSTALLED
    proposal_text = (vault_root / "proposals" / meta.id / "proposal.md").read_text()
    assert "status: applied" in proposal_text

    result = recover_interrupted_applications(vault_root=vault_root)

    assert result.transactions[0].action is RecoveryAction.COMPLETED
    assert (vault_root / "test1.txt").read_bytes() == b"new_content1"
    assert (vault_root / "test2.txt").read_bytes() == b"new_content2"
    assert not (vault_root / ".lifeos" / "recovery" / str(journal.transaction_id)).exists()


def test_complete_non_generated_transaction_cleans_without_ownership_rewrite(
    tmp_path: Path,
) -> None:
    meta, vault_root, proposal = _load_non_generated_application(tmp_path)
    ownership_before = (vault_root / "system/generated-ownership.json").read_bytes()

    result = apply_proposal(
        proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )
    assert result.new_status.value == "applied"
    journal = _single_journal(vault_root)
    assert journal.phase is RecoveryPhase.COMPLETE

    recovered = recover_interrupted_applications(vault_root=vault_root)

    assert recovered.transactions[0].action is RecoveryAction.CLEANED
    assert (vault_root / "human.txt").read_text() == "human content"
    assert (vault_root / "system/generated-ownership.json").read_bytes() == ownership_before
    proposal_text = (vault_root / "proposals" / meta.id / "proposal.md").read_text()
    assert "status: applied" in proposal_text


def test_complete_transaction_cleanup_ignores_later_canonical_changes(
    tmp_path: Path,
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    result = apply_proposal(
        proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )
    assert result.new_status.value == "applied"
    journal = _single_journal(vault_root)
    assert journal.phase is RecoveryPhase.COMPLETE

    (vault_root / "test1.txt").unlink()
    (vault_root / "proposals" / meta.id / "proposal.md").unlink()

    recovered = recover_interrupted_applications(vault_root=vault_root)

    assert recovered.transactions[0].action is RecoveryAction.CLEANED
    assert not (vault_root / ".lifeos" / "recovery" / str(journal.transaction_id)).exists()


def test_recovery_twice_has_same_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_target_install:0")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    first = recover_interrupted_applications(vault_root=vault_root)
    second = recover_interrupted_applications(vault_root=vault_root)
    third = recover_interrupted_applications(vault_root=vault_root)

    assert first.recovered_count == 1
    assert second == third
    assert second.recovered_count == 0


def test_recovery_rejects_manually_changed_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_prepared_journal")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    proposal_path = vault_root / "proposals" / meta.id / "proposal.md"
    proposal_path.write_text(proposal_path.read_text() + "\nmanual change\n")

    with pytest.raises(RecoveryConflictError):
        recover_interrupted_applications(vault_root=vault_root)
    assert _single_journal(vault_root).phase is RecoveryPhase.PREPARED


def test_apply_and_recovery_cannot_run_concurrently(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "vault" / ".lifeos"
    with acquire_recovery_lock(runtime_dir=runtime_dir):
        with pytest.raises(RecoveryLockUnavailableError):
            recover_interrupted_applications(vault_root=tmp_path / "vault")


def test_recovery_does_not_require_registry(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    result = recover_interrupted_applications(vault_root=vault_root)
    assert result.transactions == ()


def test_apply_invokes_recovery_before_new_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_target_install:0")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    monkeypatch.setattr(application_module, "_application_checkpoint", lambda _name: None)
    result = apply_proposal(
        proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:01:00Z",
    )
    assert result.new_status.value == "applied"
    assert (vault_root / "test1.txt").read_bytes() == b"new_content1"
    assert (vault_root / "test2.txt").read_bytes() == b"new_content2"


def test_unrecoverable_state_blocks_apply_with_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_prepared_journal")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )
    proposal_path = vault_root / "proposals" / meta.id / "proposal.md"
    proposal_path.write_text(proposal_path.read_text() + "\nmanual change\n")

    monkeypatch.setattr(application_module, "_application_checkpoint", lambda _name: None)
    with pytest.raises(ApplicationError) as error_info:
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:01:00Z",
        )
    assert error_info.value.code is ApplicationErrorCode.RECOVERY_REQUIRED
