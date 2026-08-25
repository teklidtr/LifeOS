import ast
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lifeos.proposals.application as application_module
from lifeos.proposals.recovery import (
    RecoveryCorruptStateError,
    RecoveryExpectedState,
    RecoveryJournal,
    RecoveryOperation,
    RecoveryOperationType,
    RecoveryPhase,
    RecoveryStateFiles,
    RecoveryTransactionId,
    _serialize_journal,
)


_SHA_ZERO = "sha256:" + "0" * 64
_SHA_ONE = "sha256:" + "1" * 64
_SHA_TWO = "sha256:" + "2" * 64


def _state_files(prefix: str) -> RecoveryStateFiles:
    return RecoveryStateFiles(
        expected_pre_state=RecoveryExpectedState.PRESENT,
        expected_pre_hash=_SHA_ZERO,
        expected_pre_mode=0o644,
        staged_path=f"staged/{prefix}.tmp",
        staged_hash=_SHA_ONE,
        staged_mode=0o644,
        backup_path=f"backups/{prefix}.bak",
        backup_hash=_SHA_ZERO,
        staged_size=11,
        backup_size=10,
    )


def _journal(
    *,
    phase: RecoveryPhase = RecoveryPhase.PREPARED,
    operation_type: RecoveryOperationType = RecoveryOperationType.REPLACE_GENERATED_FILE,
) -> RecoveryJournal:
    is_creation = operation_type in {
        RecoveryOperationType.CREATE_FILE,
        RecoveryOperationType.CREATE_GENERATED_FILE,
    }
    operation = RecoveryOperation(
        operation_id="op-1",
        operation_type=operation_type,
        target_path="wiki/target.md",
        expected_pre_state=(
            RecoveryExpectedState.ABSENT if is_creation else RecoveryExpectedState.PRESENT
        ),
        expected_pre_hash=None if is_creation else _SHA_ZERO,
        expected_pre_mode=None if is_creation else 0o644,
        staged_path="staged/wiki_target.md.tmp",
        staged_hash=_SHA_ONE,
        staged_mode=0o644,
        backup_path=None if is_creation else "backups/wiki_target.md.bak",
        backup_hash=None if is_creation else _SHA_ZERO,
        staged_size=11,
        backup_size=None if is_creation else 10,
    )
    return RecoveryJournal(
        schema_version=2,
        transaction_id=RecoveryTransactionId("prop-20260714T120000Z-1234abcd-a1b2c3d4"),
        proposal_id="prop-20260714T120000Z-1234abcd",
        review_digest=_SHA_TWO,
        authorized_actor="user@example.com",
        phase=phase,
        created_at="2026-07-14T12:00:00Z",
        operations=(operation,),
        ownership_state=_state_files("ownership.json"),
        proposal_state=_state_files("proposal.md"),
    )


def test_application_context_and_phase_results_are_immutable() -> None:
    assert application_module._ApplicationContext.__dataclass_params__.frozen
    assert application_module._PhaseResult.__dataclass_params__.frozen
    assert application_module._RollbackResult.__dataclass_params__.frozen
    assert application_module._CleanupResult.__dataclass_params__.frozen


def test_apply_proposal_locked_is_small_orchestrator() -> None:
    source = Path(application_module.__file__).read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_proposal_locked"
    )

    assert function.end_lineno - function.lineno + 1 <= 25
    calls = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls == {"_execute_application_transaction", "_ApplicationContext"}


def test_application_transaction_uses_extracted_state_machine_steps() -> None:
    source = Path(application_module.__file__).read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_application_transaction"
    )
    calls = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert {
        "_validate_application_proposal",
        "_validate_precommit_state",
        "_install_prepared_targets",
        "_install_ownership_manifest",
        "_commit_proposal_lifecycle",
        "_advance_recovery_phase",
        "_rollback_application",
        "_cleanup_application_resources",
    } <= calls
    assert function.end_lineno - function.lineno + 1 < 700


def test_recovery_phase_transitions_are_sequential_and_byte_compatible() -> None:
    written: list[RecoveryJournal] = []
    store = MagicMock()
    store.write_journal.side_effect = written.append

    journal = _journal()
    sequence = (
        RecoveryPhase.TARGETS_INSTALLED,
        RecoveryPhase.OWNERSHIP_INSTALLED,
        RecoveryPhase.PROPOSAL_COMMITTED,
        RecoveryPhase.COMPLETE,
    )
    for phase in sequence:
        expected = replace(journal, phase=phase)
        result = application_module._advance_recovery_phase(
            journal=journal,
            next_phase=phase,
            recovery_store=store,
        )
        assert result.phase is phase
        assert result.journal == expected
        assert _serialize_journal(result.journal) == _serialize_journal(expected)
        journal = result.journal

    assert tuple(item.phase for item in written) == sequence


def test_illegal_recovery_phase_transition_is_rejected_before_write() -> None:
    store = MagicMock()

    with pytest.raises(RecoveryCorruptStateError, match="Illegal recovery phase transition"):
        application_module._advance_recovery_phase(
            journal=_journal(),
            next_phase=RecoveryPhase.COMPLETE,
            recovery_store=store,
        )

    store.write_journal.assert_not_called()


@pytest.mark.parametrize("phase", tuple(RecoveryPhase))
@pytest.mark.parametrize("operation_type", tuple(RecoveryOperationType))
def test_existing_operation_and_journal_phase_matrix_remains_serializable(
    phase: RecoveryPhase,
    operation_type: RecoveryOperationType,
) -> None:
    serialized = _serialize_journal(_journal(phase=phase, operation_type=operation_type))

    assert f'"phase":"{phase.value}"'.encode() in serialized
    assert f'"operation_type":"{operation_type.value}"'.encode() in serialized
