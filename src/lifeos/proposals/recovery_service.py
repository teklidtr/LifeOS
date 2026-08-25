from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from lifeos._recovery_io import (
    RecoveryArtifact,
    RecoveryIOConflictError,
    RecoveryIOCorruptStateError,
    RecoveryIOError,
    RecoveryIOUnavailableError,
    remove_installed_creation,
    restore_canonical_from_backup,
)
from lifeos._transaction_files import (
    ParentDescriptor,
    TargetIdentity,
    TransactionError,
    get_target_identity,
)
from lifeos.config import runtime_overlaps_reserved_canonical
from lifeos.proposals.recovery import (
    RecoveryConflictError,
    RecoveryCorruptStateError,
    RecoveryExpectedState,
    RecoveryJournal,
    RecoveryOperation,
    RecoveryOperationType,
    RecoveryPhase,
    RecoveryStateFiles,
    RecoveryUnavailableError,
)
from lifeos.proposals.recovery_store import (
    PinnedRecoveryStore,
    acquire_pinned_recovery_store,
)


class RecoveryAction(str, Enum):
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"
    CLEANED = "cleaned"


@dataclass(frozen=True, slots=True)
class RecoveryTransactionResult:
    transaction_id: str
    proposal_id: str
    phase_before: RecoveryPhase
    action: RecoveryAction


@dataclass(frozen=True, slots=True)
class RecoveryRunResult:
    transactions: tuple[RecoveryTransactionResult, ...]

    @property
    def recovered_count(self) -> int:
        return len(self.transactions)


class _CanonicalState(str, Enum):
    PRE = "pre"
    STAGED = "staged"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class _FileExpectation:
    expected_pre_state: RecoveryExpectedState
    expected_pre_hash: str | None
    expected_pre_mode: int | None
    staged_hash: str
    staged_mode: int
    backup_path: str | None
    backup_hash: str | None
    backup_size: int | None


def recover_interrupted_applications(
    *,
    vault_root: Path,
    runtime_dir: Path | None = None,
) -> RecoveryRunResult:
    resolved_runtime_dir = runtime_dir or (vault_root / ".lifeos")
    try:
        if resolved_runtime_dir.resolve(strict=False) == vault_root.resolve(strict=False):
            raise RecoveryCorruptStateError(
                "Runtime directory overlaps the canonical vault root"
            )
    except (OSError, RuntimeError) as exc:
        raise RecoveryUnavailableError("Could not validate runtime directory boundary") from exc
    if runtime_overlaps_reserved_canonical(vault_root, resolved_runtime_dir):
        raise RecoveryCorruptStateError(
            "Runtime directory overlaps a reserved canonical subtree"
        )
    with acquire_pinned_recovery_store(
        runtime_dir=resolved_runtime_dir,
        authority_root=vault_root,
    ) as recovery_store:
        return _recover_interrupted_applications_locked(
            vault_root=vault_root,
            runtime_dir=resolved_runtime_dir,
            recovery_store=recovery_store,
        )


def _recover_interrupted_applications_locked(
    *,
    vault_root: Path,
    runtime_dir: Path | None = None,
    recovery_store: PinnedRecoveryStore | None = None,
) -> RecoveryRunResult:
    """Recover all transactions through one descriptor-pinned runtime authority."""
    if recovery_store is None:
        resolved_runtime_dir = runtime_dir or (vault_root / ".lifeos")
        if runtime_overlaps_reserved_canonical(vault_root, resolved_runtime_dir):
            raise RecoveryCorruptStateError(
                "Runtime directory overlaps a reserved canonical subtree"
            )
        with acquire_pinned_recovery_store(
            runtime_dir=resolved_runtime_dir,
            authority_root=vault_root,
        ) as owned_store:
            return _recover_interrupted_applications_locked(
                vault_root=vault_root,
                runtime_dir=resolved_runtime_dir,
                recovery_store=owned_store,
            )

    discovery = recovery_store.discover()
    if discovery.findings:
        raise RecoveryCorruptStateError("Recovery state contains unresolved findings")

    results: list[RecoveryTransactionResult] = []
    for journal in discovery.journals:
        results.append(
            _recover_transaction(
                vault_root=vault_root,
                recovery_store=recovery_store,
                journal=journal,
            )
        )
    return RecoveryRunResult(transactions=tuple(results))


def _recover_transaction(
    *,
    vault_root: Path,
    recovery_store: PinnedRecoveryStore,
    journal: RecoveryJournal,
) -> RecoveryTransactionResult:
    transaction_dir = recovery_store.recovery_root / str(journal.transaction_id)

    if journal.phase is RecoveryPhase.COMPLETE:
        # COMPLETE is a terminal commit record, not an unresolved recovery
        # phase. Canonical files may legitimately change after the application
        # commits and before this retained journal is cleaned by the next run.
        recovery_store.remove_completed(journal.transaction_id)
        return RecoveryTransactionResult(
            transaction_id=str(journal.transaction_id),
            proposal_id=journal.proposal_id,
            phase_before=journal.phase,
            action=RecoveryAction.CLEANED,
        )

    if journal.phase is RecoveryPhase.PROPOSAL_COMMITTED:
        _verify_all_staged(vault_root=vault_root, journal=journal)
        _complete_transaction(recovery_store=recovery_store, journal=journal)
        return RecoveryTransactionResult(
            transaction_id=str(journal.transaction_id),
            proposal_id=journal.proposal_id,
            phase_before=journal.phase,
            action=RecoveryAction.COMPLETED,
        )

    proposal_state = _classify_path(
        vault_root=vault_root,
        target_path=f"proposals/{journal.proposal_id}/proposal.md",
        expectation=_expectation(journal.proposal_state),
    )
    if proposal_state is _CanonicalState.OTHER:
        raise RecoveryConflictError("Proposal state changed outside recovery")

    if (
        journal.phase is RecoveryPhase.OWNERSHIP_INSTALLED
        and proposal_state is _CanonicalState.STAGED
    ):
        _verify_all_staged(vault_root=vault_root, journal=journal)
        _complete_transaction(recovery_store=recovery_store, journal=journal)
        return RecoveryTransactionResult(
            transaction_id=str(journal.transaction_id),
            proposal_id=journal.proposal_id,
            phase_before=journal.phase,
            action=RecoveryAction.COMPLETED,
        )

    if proposal_state is not _CanonicalState.PRE:
        raise RecoveryConflictError("Proposal state is inconsistent with rollback phase")

    transaction_fd = recovery_store.open_transaction(journal.transaction_id)
    try:
        for operation in reversed(journal.operations):
            _rollback_operation(
                vault_root=vault_root,
                transaction_dir=transaction_dir,
                transaction_fd=transaction_fd,
                operation=operation,
            )

        _rollback_state_file(
            vault_root=vault_root,
            transaction_dir=transaction_dir,
            transaction_fd=transaction_fd,
            target_path="system/generated-ownership.json",
            state=journal.ownership_state,
        )
        _rollback_state_file(
            vault_root=vault_root,
            transaction_dir=transaction_dir,
            transaction_fd=transaction_fd,
            target_path=f"proposals/{journal.proposal_id}/proposal.md",
            state=journal.proposal_state,
        )
    finally:
        os.close(transaction_fd)

    _verify_all_pre(vault_root=vault_root, journal=journal)
    recovery_store.remove_rolled_back(journal.transaction_id)
    return RecoveryTransactionResult(
        transaction_id=str(journal.transaction_id),
        proposal_id=journal.proposal_id,
        phase_before=journal.phase,
        action=RecoveryAction.ROLLED_BACK,
    )


def _complete_transaction(
    *, recovery_store: PinnedRecoveryStore, journal: RecoveryJournal
) -> None:
    completed = replace(journal, phase=RecoveryPhase.COMPLETE)
    recovery_store.write_journal(completed)
    recovery_store.remove_completed(journal.transaction_id)


def _expectation(value: RecoveryOperation | RecoveryStateFiles) -> _FileExpectation:
    return _FileExpectation(
        expected_pre_state=value.expected_pre_state,
        expected_pre_hash=value.expected_pre_hash,
        expected_pre_mode=value.expected_pre_mode,
        staged_hash=value.staged_hash,
        staged_mode=value.staged_mode,
        backup_path=value.backup_path,
        backup_hash=value.backup_hash,
        backup_size=value.backup_size,
    )


def _prefixed_hash(identity: TargetIdentity) -> str:
    if identity.content_hash.startswith("sha256:"):
        return identity.content_hash
    return f"sha256:{identity.content_hash}"


def _matches(identity: TargetIdentity, *, expected_hash: str, expected_mode: int) -> bool:
    return (
        _prefixed_hash(identity) == expected_hash
        and stat.S_IMODE(identity.mode) == stat.S_IMODE(expected_mode)
    )


def _classify_path(
    *, vault_root: Path, target_path: str, expectation: _FileExpectation
) -> _CanonicalState:
    parent, target_name = _open_target_parent(vault_root=vault_root, target_path=target_path)
    try:
        identity = get_target_identity(target_name, parent)
    except TransactionError as error:
        raise RecoveryCorruptStateError("Canonical target is not a regular file") from error
    except OSError as error:
        raise RecoveryUnavailableError("Failed to inspect canonical target") from error
    finally:
        os.close(parent.fd)

    if identity is None:
        if expectation.expected_pre_state is RecoveryExpectedState.ABSENT:
            return _CanonicalState.PRE
        return _CanonicalState.OTHER

    if (
        expectation.expected_pre_state is RecoveryExpectedState.PRESENT
        and expectation.expected_pre_hash is not None
        and expectation.expected_pre_mode is not None
        and _matches(
            identity,
            expected_hash=expectation.expected_pre_hash,
            expected_mode=expectation.expected_pre_mode,
        )
    ):
        return _CanonicalState.PRE

    if _matches(
        identity,
        expected_hash=expectation.staged_hash,
        expected_mode=expectation.staged_mode,
    ):
        return _CanonicalState.STAGED

    return _CanonicalState.OTHER


def _rollback_operation(
    *,
    vault_root: Path,
    transaction_dir: Path,
    transaction_fd: int,
    operation: RecoveryOperation,
) -> None:
    _rollback_entry(
        vault_root=vault_root,
        transaction_dir=transaction_dir,
        transaction_fd=transaction_fd,
        target_path=operation.target_path,
        expectation=_expectation(operation),
    )


def _rollback_state_file(
    *,
    vault_root: Path,
    transaction_dir: Path,
    transaction_fd: int,
    target_path: str,
    state: RecoveryStateFiles,
) -> None:
    _rollback_entry(
        vault_root=vault_root,
        transaction_dir=transaction_dir,
        transaction_fd=transaction_fd,
        target_path=target_path,
        expectation=_expectation(state),
    )


def _rollback_entry(
    *,
    vault_root: Path,
    transaction_dir: Path,
    transaction_fd: int,
    target_path: str,
    expectation: _FileExpectation,
) -> None:
    current = _classify_path(
        vault_root=vault_root,
        target_path=target_path,
        expectation=expectation,
    )
    if current is _CanonicalState.PRE:
        return
    if current is _CanonicalState.OTHER:
        raise RecoveryConflictError("Canonical target changed outside recovery")

    parent, target_name = _open_target_parent(vault_root=vault_root, target_path=target_path)
    try:
        if expectation.expected_pre_state is RecoveryExpectedState.ABSENT:
            remove_installed_creation(
                target_name=target_name,
                target_parent=parent,
                expected_installed_hash=expectation.staged_hash,
                expected_installed_mode=expectation.staged_mode,
            )
        else:
            if (
                expectation.backup_path is None
                or expectation.backup_hash is None
                or expectation.backup_size is None
                or expectation.expected_pre_mode is None
                or expectation.expected_pre_hash is None
            ):
                raise RecoveryCorruptStateError("Recovery backup metadata is incomplete")
            restore_canonical_from_backup(
                transaction_dir=transaction_dir,
                transaction_fd=transaction_fd,
                backup=RecoveryArtifact(
                    relative_path=expectation.backup_path,
                    content_hash=expectation.backup_hash,
                    size=expectation.backup_size,
                    mode=expectation.expected_pre_mode,
                ),
                target_name=target_name,
                target_parent=parent,
                expected_installed_hash=expectation.staged_hash,
                expected_installed_mode=expectation.staged_mode,
                expected_restored_hash=expectation.expected_pre_hash,
                expected_restored_mode=expectation.expected_pre_mode,
            )
    except RecoveryIOConflictError as error:
        raise RecoveryConflictError("Canonical target conflicts with recovery journal") from error
    except RecoveryIOCorruptStateError as error:
        raise RecoveryCorruptStateError("Recovery artifact or target is corrupt") from error
    except (RecoveryIOUnavailableError, RecoveryIOError, TransactionError, OSError) as error:
        raise RecoveryUnavailableError("Recovery filesystem operation failed") from error
    finally:
        os.close(parent.fd)


def _verify_all_pre(*, vault_root: Path, journal: RecoveryJournal) -> None:
    for operation in journal.operations:
        _require_state(
            vault_root=vault_root,
            target_path=operation.target_path,
            expectation=_expectation(operation),
            required=_CanonicalState.PRE,
        )
    _require_state(
        vault_root=vault_root,
        target_path="system/generated-ownership.json",
        expectation=_expectation(journal.ownership_state),
        required=_CanonicalState.PRE,
    )
    _require_state(
        vault_root=vault_root,
        target_path=f"proposals/{journal.proposal_id}/proposal.md",
        expectation=_expectation(journal.proposal_state),
        required=_CanonicalState.PRE,
    )


def _verify_all_staged(*, vault_root: Path, journal: RecoveryJournal) -> None:
    for operation in journal.operations:
        _require_state(
            vault_root=vault_root,
            target_path=operation.target_path,
            expectation=_expectation(operation),
            required=_CanonicalState.STAGED,
        )
    ownership_required = (
        _CanonicalState.STAGED
        if _journal_changes_ownership(journal)
        else _CanonicalState.PRE
    )
    _require_state(
        vault_root=vault_root,
        target_path="system/generated-ownership.json",
        expectation=_expectation(journal.ownership_state),
        required=ownership_required,
    )
    _require_state(
        vault_root=vault_root,
        target_path=f"proposals/{journal.proposal_id}/proposal.md",
        expectation=_expectation(journal.proposal_state),
        required=_CanonicalState.STAGED,
    )


def _require_state(
    *,
    vault_root: Path,
    target_path: str,
    expectation: _FileExpectation,
    required: _CanonicalState,
) -> None:
    actual = _classify_path(
        vault_root=vault_root,
        target_path=target_path,
        expectation=expectation,
    )
    if actual is required:
        return
    if _pre_and_staged_are_equivalent(expectation) and actual in (
        _CanonicalState.PRE,
        _CanonicalState.STAGED,
    ):
        return
    raise RecoveryConflictError("Canonical state does not match recovery phase")


def _pre_and_staged_are_equivalent(expectation: _FileExpectation) -> bool:
    return (
        expectation.expected_pre_state is RecoveryExpectedState.PRESENT
        and expectation.expected_pre_hash == expectation.staged_hash
        and expectation.expected_pre_mode is not None
        and stat.S_IMODE(expectation.expected_pre_mode)
        == stat.S_IMODE(expectation.staged_mode)
    )


def _journal_changes_ownership(journal: RecoveryJournal) -> bool:
    return any(
        operation.operation_type
        in (
            RecoveryOperationType.CREATE_GENERATED_FILE,
            RecoveryOperationType.REPLACE_GENERATED_FILE,
        )
        for operation in journal.operations
    )


def _open_target_parent(*, vault_root: Path, target_path: str) -> tuple[ParentDescriptor, str]:
    path = Path(target_path)
    if path.is_absolute() or not path.name or any(part in ("", ".", "..") for part in path.parts):
        raise RecoveryCorruptStateError("Recovery target path is invalid")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        current_fd = os.open(vault_root, flags)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise RecoveryCorruptStateError(
                "Vault root is a symlink or non-directory"
            ) from error
        raise RecoveryUnavailableError("Failed to open vault root") from error

    try:
        for component in path.parent.parts:
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise RecoveryCorruptStateError(
                        "Recovery target parent is a symlink or non-directory"
                    ) from error
                raise RecoveryUnavailableError("Failed to open recovery target parent") from error
            try:
                os.close(current_fd)
            except OSError as error:
                os.close(next_fd)
                raise RecoveryUnavailableError(
                    "Failed to close recovery target parent descriptor"
                ) from error
            current_fd = next_fd

        try:
            state = os.fstat(current_fd)
        except OSError as error:
            raise RecoveryUnavailableError(
                "Failed to inspect recovery target parent"
            ) from error
        if not stat.S_ISDIR(state.st_mode):
            raise RecoveryCorruptStateError("Recovery target parent is not a directory")
        return (
            ParentDescriptor(
                fd=current_fd,
                dev=state.st_dev,
                ino=state.st_ino,
                path=path.parent.as_posix(),
            ),
            path.name,
        )
    except (RecoveryConflictError, RecoveryCorruptStateError, RecoveryUnavailableError):
        try:
            os.close(current_fd)
        except OSError:
            pass
        raise