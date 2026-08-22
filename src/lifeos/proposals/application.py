import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from collections.abc import Callable
from typing import Dict, List, Optional, Tuple

from .._owned_lock import LockError, OwnedLock
from .._recovery_io import RecoveryArtifact, write_recovery_artifact
from .._secure_io import SecureIOError, hash_file_secure, open_directory_secure, read_file_secure
from .._transaction_files import (
    BackupFile,
    DirectorySyncResult,
    DirectorySyncState,
    ParentDescriptor,
    StagingFile,
    TargetIdentity,
    TransactionError,
    cleanup_backup,
    cleanup_staging,
    create_hardlink_backup,
    create_staging_file,
    get_target_identity,
    publish_creation,
    publish_replacement,
    rollback_creation,
    rollback_replacement,
)
from ..markdown.parser import parse_markdown_note
from ..ownership.manifest import (
    DEFAULT_OWNERSHIP_MANIFEST_PATH,
    GeneratedOwnership,
    ManifestEntry,
    serialize_generated_ownership_bytes,
)
from .lifecycle import serialize_proposal_markdown
from .loader import LoadedProposal
from .patches import CreateGeneratedFile, PatchOperation, ReplaceGeneratedFile
from .review_snapshot import REVIEW_SNAPSHOT_FILENAME
from .recovery import (
    RECOVERY_SCHEMA_VERSION,
    RecoveryCorruptStateError,
    RecoveryError,
    RecoveryExpectedState,
    RecoveryJournal,
    RecoveryLockUnavailableError,
    RecoveryOperation,
    RecoveryOperationType,
    RecoveryPhase,
    RecoveryStateFiles,
    RecoveryTransactionId,
    acquire_recovery_lock,
    generate_recovery_transaction_id,
    initialize_recovery_transaction,
    remove_rolled_back_recovery_transaction,
    write_recovery_journal,
)
from .recovery_service import _recover_interrupted_applications_locked
from .schema import ProposalStatus
from .unified_diff import apply_diff
from .validation import preflight_proposal


class OperationState(str, Enum):
    NOT_PREPARED = "not_prepared"
    PREPARED = "prepared"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class ApplicationErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    PREFLIGHT_FAILED = "preflight_failed"
    LOCK_ERROR = "lock_error"
    IO_ERROR = "io_error"
    TARGET_CONFLICT = "target_conflict"
    OWNERSHIP_CONFLICT = "ownership_conflict"
    TARGET_MUTATED = "target_mutated"
    COMMIT_FAILED = "commit_failed"
    UNCERTAIN_DURABILITY = "uncertain_durability"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class OperationApplicationResult:
    operation_id: str
    state: OperationState
    target_path: str
    error: Optional[str] = None


@dataclass(frozen=True)
class ProposalApplicationResult:
    proposal_id: str
    previous_status: str
    new_status: str
    operation_results: Tuple[OperationApplicationResult, ...]
    changed_paths: Tuple[str, ...]
    ownership_changed: bool
    proposal_source_hash_before: str
    proposal_source_hash_after: str
    write_occurred: bool
    durability: str
    rollback_performed: bool
    rollback_succeeded: Optional[bool]
    recovery_required: bool
    cleanup_succeeded: bool
    recovery_artifacts_retained: bool
    vault_lock_released: bool
    proposal_lock_released: bool


@dataclass(frozen=True)
class _OperationCandidate:
    index: int
    op: PatchOperation
    target_path: str
    target_name: str
    parent: ParentDescriptor
    original_identity: Optional[TargetIdentity]
    original_content: Optional[bytes]
    candidate_content: bytes
    intended_mode: int


@dataclass
class _PreparedOp:
    candidate: _OperationCandidate
    staging: StagingFile
    backup: Optional[BackupFile]
    committed: bool = False

    @property
    def index(self) -> int:
        return self.candidate.index

    @property
    def op(self) -> PatchOperation:
        return self.candidate.op

    @property
    def target_path(self) -> str:
        return self.candidate.target_path

    @property
    def target_name(self) -> str:
        return self.candidate.target_name

    @property
    def parent(self) -> ParentDescriptor:
        return self.candidate.parent

    @property
    def original_identity(self) -> Optional[TargetIdentity]:
        return self.candidate.original_identity


@dataclass(frozen=True, slots=True)
class _ApplicationContext:
    proposal: LoadedProposal
    vault_root: Path
    applied_by: str
    applied_at: str
    recovery_root: Path
    outcome: ProposalApplicationResult


@dataclass(frozen=True, slots=True)
class _PhaseResult:
    journal: RecoveryJournal
    phase: RecoveryPhase


@dataclass(frozen=True, slots=True)
class _RollbackResult:
    durability: str
    rollback_succeeded: bool
    recovery_required: bool
    recovery_artifacts_retained: bool
    transaction_initialized: bool
    application_error: Optional["ApplicationError"]
    unexpected_error: Optional[Exception]


@dataclass(frozen=True, slots=True)
class _CleanupResult:
    cleanup_succeeded: bool
    vault_lock_released: bool
    proposal_lock_released: bool


_LEGAL_PHASE_TRANSITIONS = {
    RecoveryPhase.PREPARED: RecoveryPhase.TARGETS_INSTALLED,
    RecoveryPhase.TARGETS_INSTALLED: RecoveryPhase.OWNERSHIP_INSTALLED,
    RecoveryPhase.OWNERSHIP_INSTALLED: RecoveryPhase.PROPOSAL_COMMITTED,
    RecoveryPhase.PROPOSAL_COMMITTED: RecoveryPhase.COMPLETE,
}


class ApplicationError(Exception):
    def __init__(
        self, message: str, outcome: ProposalApplicationResult, code: ApplicationErrorCode
    ) -> None:
        super().__init__(message)
        self.message = message
        self.outcome = outcome
        self.code = code


def _application_checkpoint(_name: str) -> None:
    """Deterministic fault-injection seam used by recovery tests."""


def _create_initial_outcome(proposal: LoadedProposal) -> ProposalApplicationResult:
    operations = tuple(
        OperationApplicationResult(
            operation_id=op.id,
            state=OperationState.NOT_PREPARED,
            target_path=getattr(op, "target_path", getattr(op, "file_path", "")),
        )
        for op in proposal.patch_document.operations
    )
    return ProposalApplicationResult(
        proposal_id=proposal.metadata.id,
        previous_status=proposal.metadata.status,
        new_status=proposal.metadata.status,
        operation_results=operations,
        changed_paths=(),
        ownership_changed=False,
        proposal_source_hash_before=proposal.proposal_source_hash,
        proposal_source_hash_after=proposal.proposal_source_hash,
        write_occurred=False,
        durability="confirmed",
        rollback_performed=False,
        rollback_succeeded=None,
        recovery_required=False,
        cleanup_succeeded=False,
        recovery_artifacts_retained=False,
        vault_lock_released=False,
        proposal_lock_released=False,
    )


def require_replacement_identity(
    identity: TargetIdentity | None,
    *,
    target_kind: str,
) -> TargetIdentity:
    if not identity:
        raise ValueError(f"Missing original identity for replacement of {target_kind}")
    return identity


def _prefixed_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _identity_hash(identity: TargetIdentity) -> str:
    if identity.content_hash.startswith("sha256:"):
        return identity.content_hash
    return f"sha256:{identity.content_hash}"


def _operation_type(op: PatchOperation) -> RecoveryOperationType:
    return {
        "create_file": RecoveryOperationType.CREATE_FILE,
        "patch_human_file": RecoveryOperationType.PATCH_HUMAN_FILE,
        "create_generated_file": RecoveryOperationType.CREATE_GENERATED_FILE,
        "replace_generated_file": RecoveryOperationType.REPLACE_GENERATED_FILE,
        "replace_managed_block": RecoveryOperationType.REPLACE_MANAGED_BLOCK,
    }[op.op]


def _artifact(path: str, content: bytes, mode: int) -> RecoveryArtifact:
    return RecoveryArtifact(
        relative_path=path,
        content_hash=_prefixed_hash(content),
        size=len(content),
        mode=stat.S_IMODE(mode),
    )


def _record_sync_result(result: DirectorySyncResult, durability: str) -> str:
    if result.state in (DirectorySyncState.UNSUPPORTED, DirectorySyncState.FAILED):
        return "uncertain"
    return durability


def _cleanup_staging_file(staging: StagingFile) -> bool:
    try:
        cleanup_staging(staging)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _cleanup_backup_file(backup: BackupFile) -> bool:
    try:
        cleanup_backup(backup)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _public_application_error(error: ApplicationError) -> ApplicationError:
    message = (
        "Proposal rollback could not safely restore all committed paths."
        if error.outcome.recovery_required
        else "Application failed"
    )
    if (
        error.message.startswith("Preflight failed")
        or error.message == "unsupported_generated_provenance"
    ):
        message = error.message
    public_error = ApplicationError(message, error.outcome, code=error.code)
    public_error.__cause__ = error.__cause__ if error.__cause__ else error
    return public_error


def _advance_recovery_phase(
    *,
    journal: RecoveryJournal,
    next_phase: RecoveryPhase,
    recovery_root: Path,
) -> _PhaseResult:
    expected = _LEGAL_PHASE_TRANSITIONS.get(journal.phase)
    if expected is not next_phase:
        raise RecoveryCorruptStateError(
            f"Illegal recovery phase transition: {journal.phase.value} -> {next_phase.value}"
        )
    updated = replace(journal, phase=next_phase)
    write_recovery_journal(recovery_root=recovery_root, journal=updated)
    return _PhaseResult(journal=updated, phase=next_phase)


def _validate_application_proposal(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    outcome: ProposalApplicationResult,
) -> None:
    if proposal.patch_document.schema_version == 1:
        for operation in proposal.patch_document.operations:
            if isinstance(operation, (CreateGeneratedFile, ReplaceGeneratedFile)):
                raise ApplicationError(
                    "unsupported_generated_provenance",
                    outcome,
                    code=ApplicationErrorCode.VALIDATION_ERROR,
                )

    preflight_result = preflight_proposal(proposal, vault_root=vault_root)
    if preflight_result.state == "valid":
        return
    finding_messages = [finding.message for finding in preflight_result.findings]
    for operation_result in preflight_result.operations:
        finding_messages.extend(finding.message for finding in operation_result.findings)
    raise ApplicationError(
        f"Preflight failed: {finding_messages}",
        outcome,
        code=ApplicationErrorCode.PREFLIGHT_FAILED,
    )


def _validate_proposal_sources_locked(
    proposal: LoadedProposal,
    *,
    prop_fd: int,
    vault_root: Path,
    outcome: ProposalApplicationResult,
) -> None:
    expected_sources = (
        ("proposal.md", proposal.proposal_source_hash),
        ("patches.json", proposal.patches_source_hash),
    )
    for filename, expected_hash in expected_sources:
        try:
            content = read_file_secure(filename, vault_root, dir_fd=prop_fd)
        except SecureIOError as error:
            raise ApplicationError(
                f"Could not verify {filename}",
                outcome,
                code=ApplicationErrorCode.VALIDATION_ERROR,
            ) from error
        if _prefixed_hash(content) != expected_hash:
            raise ApplicationError(
                f"{filename} changed after proposal loading",
                outcome,
                code=ApplicationErrorCode.VALIDATION_ERROR,
            )

    try:
        review_content = read_file_secure(
            REVIEW_SNAPSHOT_FILENAME,
            vault_root,
            dir_fd=prop_fd,
        )
    except SecureIOError as error:
        if error.code == "open_failed" and "No such file" in error.message:
            review_hash = None
        else:
            raise ApplicationError(
                f"Could not verify {REVIEW_SNAPSHOT_FILENAME}",
                outcome,
                code=ApplicationErrorCode.VALIDATION_ERROR,
            ) from error
    else:
        review_hash = _prefixed_hash(review_content)
    if review_hash != proposal.review_snapshot_source_hash:
        raise ApplicationError(
            f"{REVIEW_SNAPSHOT_FILENAME} changed after proposal loading",
            outcome,
            code=ApplicationErrorCode.VALIDATION_ERROR,
        )


def _candidate_for_operation(
    *,
    index: int,
    operation: PatchOperation,
    parent: ParentDescriptor,
    vault_root: Path,
) -> _OperationCandidate:
    target_path = operation.target_path
    target_name = Path(target_path).name
    original_identity: Optional[TargetIdentity] = None
    original_content: Optional[bytes] = None

    if operation.op in (
        "replace_generated_file",
        "patch_human_file",
        "replace_managed_block",
    ):
        original_identity = require_replacement_identity(
            get_target_identity(target_name, parent), target_kind=operation.op
        )
        original_content = read_file_secure(target_name, vault_root, dir_fd=parent.fd)
        intended_mode = stat.S_IMODE(original_identity.mode)
    else:
        intended_mode = 0o600

    if operation.op in ("create_file", "create_generated_file", "replace_generated_file"):
        candidate_content = operation.new_content.encode("utf-8")
    elif operation.op == "patch_human_file":
        assert original_content is not None
        new_content = apply_diff(original_content.decode("utf-8"), operation.unified_diff)
        parsed = parse_markdown_note(vault_root / target_path, content=new_content)
        if parsed.managed_blocks:
            raise TransactionError("Markdown result contains managed blocks")
        candidate_content = new_content.encode("utf-8")
    elif operation.op == "replace_managed_block":
        assert original_content is not None
        original_text = original_content.decode("utf-8")
        parsed = parse_markdown_note(vault_root / target_path, content=original_text)
        matching_blocks = [
            block for block in parsed.managed_blocks if block.name == operation.block_name
        ]
        if not matching_blocks:
            raise TransactionError(f"Block '{operation.block_name}' not found")
        target_block = matching_blocks[0]
        lines = original_text.splitlines(keepends=True)
        before = "".join(lines[: target_block.start_line])
        after = "".join(lines[target_block.end_line - 1 :])
        new_content = before + operation.new_content + after
        reparsed = parse_markdown_note(vault_root / target_path, content=new_content)
        if (
            len([block for block in reparsed.managed_blocks if block.name == operation.block_name])
            != 1
        ):
            raise TransactionError(f"Block '{operation.block_name}' not preserved exactly once")
        candidate_content = new_content.encode("utf-8")
    else:
        raise TransactionError("Unsupported operation type")

    return _OperationCandidate(
        index=index,
        op=operation,
        target_path=target_path,
        target_name=target_name,
        parent=parent,
        original_identity=original_identity,
        original_content=original_content,
        candidate_content=candidate_content,
        intended_mode=intended_mode,
    )


def _release_reviewed_ownership_entries(
    *,
    proposal: LoadedProposal,
    operation_indexes: list[int],
    entries: dict[str, ManifestEntry],
    root_fd: int,
    outcome: ProposalApplicationResult,
) -> None:
    for index in operation_indexes:
        operation = proposal.patch_document.operations[index]
        entry = entries.get(operation.target_path)
        if entry is None:
            raise ApplicationError(
                "Ownership entry changed after review",
                outcome,
                code=ApplicationErrorCode.OWNERSHIP_CONFLICT,
            )
        reviewed_entry = (
            getattr(operation, "expected_content_hash", ""),
            getattr(operation, "expected_generator_id", ""),
            getattr(operation, "expected_generator_version", ""),
            getattr(operation, "expected_created_at", ""),
            getattr(operation, "expected_updated_at", ""),
        )
        current_entry = (
            f"sha256:{entry.content_hash}",
            entry.generator_id,
            entry.generator_version,
            entry.created_at,
            entry.updated_at,
        )
        if reviewed_entry != current_entry:
            raise ApplicationError(
                "Ownership entry changed after review",
                outcome,
                code=ApplicationErrorCode.OWNERSHIP_CONFLICT,
            )
        try:
            os.stat(operation.target_path, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ApplicationError(
                "Failed to verify orphaned ownership target",
                outcome,
                code=ApplicationErrorCode.TARGET_CONFLICT,
            ) from error
        else:
            raise ApplicationError(
                "Ownership target was restored after review",
                outcome,
                code=ApplicationErrorCode.TARGET_CONFLICT,
            )
        del entries[operation.target_path]


def _validate_precommit_state(
    *,
    vault_root: Path,
    root_fd: int,
    prop_fd: int,
    vault_lock: OwnedLock,
    proposal_lock: OwnedLock,
    parent_descriptors: Dict[str, ParentDescriptor],
    prepared_ops: List[_PreparedOp],
    manifest_bytes: Optional[bytes],
    ownership_changed: bool,
    outcome: ProposalApplicationResult,
) -> None:
    vault_lock_stat = os.stat(
        ".lifeos/locks/vault-mutation.lock",
        dir_fd=root_fd,
        follow_symlinks=False,
    )
    assert vault_lock.lock_fd is not None
    vault_lock_fd_stat = os.fstat(vault_lock.lock_fd)
    if (
        vault_lock_stat.st_dev != vault_lock_fd_stat.st_dev
        or vault_lock_stat.st_ino != vault_lock_fd_stat.st_ino
    ):
        raise ApplicationError(
            "Vault lock identity mismatch",
            outcome,
            code=ApplicationErrorCode.TARGET_MUTATED,
        )

    proposal_lock_stat = os.stat(".lifeos-transition.lock", dir_fd=prop_fd, follow_symlinks=False)
    assert proposal_lock.lock_fd is not None
    proposal_lock_fd_stat = os.fstat(proposal_lock.lock_fd)
    if (
        proposal_lock_stat.st_dev != proposal_lock_fd_stat.st_dev
        or proposal_lock_stat.st_ino != proposal_lock_fd_stat.st_ino
    ):
        raise ApplicationError(
            "Proposal lock identity mismatch",
            outcome,
            code=ApplicationErrorCode.TARGET_MUTATED,
        )

    for relative_path, descriptor in parent_descriptors.items():
        if relative_path == ".":
            continue
        parent_stat = os.stat(descriptor.path, dir_fd=root_fd, follow_symlinks=False)
        if parent_stat.st_dev != descriptor.dev or parent_stat.st_ino != descriptor.ino:
            raise ApplicationError(
                "Parent descriptor mutated",
                outcome,
                code=ApplicationErrorCode.TARGET_MUTATED,
            )

    for prepared in prepared_ops:
        if prepared.original_identity is not None:
            current_identity = get_target_identity(prepared.target_name, prepared.parent)
            if (
                current_identity is None
                or current_identity.dev != prepared.original_identity.dev
                or current_identity.ino != prepared.original_identity.ino
                or current_identity.content_hash != prepared.original_identity.content_hash
            ):
                raise ApplicationError(
                    "Target mutated externally",
                    outcome,
                    code=ApplicationErrorCode.TARGET_MUTATED,
                )
            assert prepared.backup is not None
            backup_stat = os.stat(
                prepared.backup.name,
                dir_fd=prepared.backup.parent.fd,
                follow_symlinks=False,
            )
            if (
                backup_stat.st_dev != prepared.original_identity.dev
                or backup_stat.st_ino != prepared.original_identity.ino
            ):
                raise ApplicationError(
                    "Backup mutated externally",
                    outcome,
                    code=ApplicationErrorCode.TARGET_MUTATED,
                )
        else:
            try:
                os.stat(
                    prepared.target_name,
                    dir_fd=prepared.parent.fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise ApplicationError(
                    "Creation target raced in",
                    outcome,
                    code=ApplicationErrorCode.TARGET_CONFLICT,
                )
        staging_hash = hash_file_secure(
            prepared.staging.name,
            vault_root,
            prepared.staging.parent.fd,
            max_bytes=None,
        )
        if staging_hash != prepared.staging.candidate_hash:
            raise ApplicationError(
                "Staging file mutated externally",
                outcome,
                code=ApplicationErrorCode.TARGET_MUTATED,
            )

    if manifest_bytes is not None:
        current_manifest_hash = hash_file_secure(
            "generated-ownership.json",
            vault_root,
            parent_descriptors["system"].fd,
            max_bytes=None,
        )
        if current_manifest_hash != hashlib.sha256(manifest_bytes).hexdigest():
            raise ApplicationError(
                "Ownership manifest mutated externally",
                outcome,
                code=ApplicationErrorCode.TARGET_MUTATED,
            )
    elif ownership_changed:
        try:
            os.stat(
                "generated-ownership.json",
                dir_fd=parent_descriptors["system"].fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise ApplicationError(
                "Ownership manifest raced in",
                outcome,
                code=ApplicationErrorCode.OWNERSHIP_CONFLICT,
            )


def _install_prepared_targets(
    *,
    prepared_ops: List[_PreparedOp],
    outcome: ProposalApplicationResult,
    durability: str,
    update_op_state: Callable[[int, OperationState, Optional[str]], None],
) -> tuple[str, bool]:
    write_occurred = False
    for prepared in prepared_ops:
        try:
            if prepared.original_identity is not None:
                sync_result = publish_replacement(
                    prepared.target_name, prepared.staging, prepared.original_identity
                )
            else:
                sync_result = publish_creation(prepared.target_name, prepared.staging)
        except (OSError, TransactionError) as error:
            update_op_state(prepared.index, OperationState.PREPARED, "Commit failed")
            raise ApplicationError(
                "Commit failed, rollback performed",
                outcome,
                code=ApplicationErrorCode.COMMIT_FAILED,
            ) from error
        durability = _record_sync_result(sync_result, durability)
        prepared.committed = True
        write_occurred = True
        update_op_state(prepared.index, OperationState.COMMITTED, None)
        _application_checkpoint(f"after_target_install:{prepared.index}")
    return durability, write_occurred


def _install_ownership_manifest(
    *,
    ownership_changed: bool,
    manifest_staging: Optional[StagingFile],
    manifest_identity: Optional[TargetIdentity],
    outcome: ProposalApplicationResult,
    durability: str,
) -> tuple[str, bool, ProposalApplicationResult]:
    if not ownership_changed:
        _application_checkpoint("after_ownership_install")
        return durability, False, outcome
    assert manifest_staging is not None
    try:
        if manifest_identity is not None:
            sync_result = publish_replacement(
                "generated-ownership.json", manifest_staging, manifest_identity
            )
        else:
            sync_result = publish_creation("generated-ownership.json", manifest_staging)
    except (OSError, TransactionError) as error:
        raise ApplicationError(
            "Failed to write updated ownership manifest",
            outcome,
            code=ApplicationErrorCode.COMMIT_FAILED,
        ) from error
    durability = _record_sync_result(sync_result, durability)
    _application_checkpoint("after_ownership_install")
    return durability, True, replace(outcome, ownership_changed=True)


def _commit_proposal_lifecycle(
    *,
    lifecycle_staging: StagingFile,
    proposal_identity: TargetIdentity,
    outcome: ProposalApplicationResult,
    durability: str,
) -> str:
    try:
        sync_result = publish_replacement("proposal.md", lifecycle_staging, proposal_identity)
    except (OSError, TransactionError) as error:
        raise ApplicationError(
            "Failed to commit lifecycle",
            outcome,
            code=ApplicationErrorCode.COMMIT_FAILED,
        ) from error
    return _record_sync_result(sync_result, durability)


def _rollback_application(
    *,
    error: Exception,
    prepared_ops: List[_PreparedOp],
    lifecycle_committed: bool,
    lifecycle_staging: Optional[StagingFile],
    lifecycle_backup: Optional[BackupFile],
    manifest_committed: bool,
    manifest_staging: Optional[StagingFile],
    manifest_backup: Optional[BackupFile],
    transaction_initialized: bool,
    transaction_id: Optional[RecoveryTransactionId],
    recovery_root: Path,
    durability: str,
    recovery_artifacts_retained: bool,
    update_op_state: Callable[[int, OperationState, Optional[str]], None],
    manifest_operation_indexes: tuple[int, ...] = (),
) -> _RollbackResult:
    rollback_succeeded = True
    recovery_required = False

    if lifecycle_committed:
        try:
            assert lifecycle_staging is not None
            assert lifecycle_backup is not None
            sync_result = rollback_replacement("proposal.md", lifecycle_staging, lifecycle_backup)
            durability = _record_sync_result(sync_result, durability)
        except Exception:
            rollback_succeeded = False
            recovery_required = True
            durability = "uncertain"

    if manifest_committed:
        try:
            assert manifest_staging is not None
            if manifest_backup is not None:
                sync_result = rollback_replacement(
                    "generated-ownership.json", manifest_staging, manifest_backup
                )
            else:
                sync_result = rollback_creation("generated-ownership.json", manifest_staging)
            durability = _record_sync_result(sync_result, durability)
            for index in manifest_operation_indexes:
                update_op_state(index, OperationState.ROLLED_BACK, None)
        except Exception:
            rollback_succeeded = False
            recovery_required = True
            durability = "uncertain"
            for index in manifest_operation_indexes:
                update_op_state(index, OperationState.ROLLBACK_FAILED, "Rollback failed")

    for prepared in reversed(prepared_ops):
        if not prepared.committed:
            continue
        try:
            if prepared.original_identity is not None:
                assert prepared.backup is not None
                sync_result = rollback_replacement(
                    prepared.target_name, prepared.staging, prepared.backup
                )
            else:
                sync_result = rollback_creation(prepared.target_name, prepared.staging)
            durability = _record_sync_result(sync_result, durability)
            prepared.committed = False
            update_op_state(prepared.index, OperationState.ROLLED_BACK, None)
        except Exception:
            rollback_succeeded = False
            recovery_required = True
            durability = "uncertain"
            update_op_state(
                prepared.index,
                OperationState.ROLLBACK_FAILED,
                "Rollback failed",
            )

    if transaction_initialized and rollback_succeeded:
        assert transaction_id is not None
        try:
            remove_rolled_back_recovery_transaction(
                recovery_root=recovery_root,
                transaction_id=transaction_id,
            )
            transaction_initialized = False
        except RecoveryError:
            rollback_succeeded = False
            recovery_required = True
            recovery_artifacts_retained = True
    elif transaction_initialized:
        recovery_artifacts_retained = True

    return _RollbackResult(
        durability=durability,
        rollback_succeeded=rollback_succeeded,
        recovery_required=recovery_required,
        recovery_artifacts_retained=recovery_artifacts_retained,
        transaction_initialized=transaction_initialized,
        application_error=error if isinstance(error, ApplicationError) else None,
        unexpected_error=None if isinstance(error, ApplicationError) else error,
    )


def _cleanup_application_resources(
    *,
    prepared_ops: List[_PreparedOp],
    manifest_staging: Optional[StagingFile],
    manifest_backup: Optional[BackupFile],
    lifecycle_staging: Optional[StagingFile],
    lifecycle_backup: Optional[BackupFile],
    parent_descriptors: Dict[str, ParentDescriptor],
    root_fd: Optional[int],
    proposal_locked: bool,
    proposal_lock: Optional[OwnedLock],
    vault_locked: bool,
    vault_lock: Optional[OwnedLock],
    prop_fd: Optional[int],
    locks_fd: Optional[int],
    lifeos_fd: Optional[int],
) -> _CleanupResult:
    cleanup_succeeded = True
    for prepared in prepared_ops:
        cleanup_succeeded = _cleanup_staging_file(prepared.staging) and cleanup_succeeded
        if prepared.backup is not None:
            cleanup_succeeded = _cleanup_backup_file(prepared.backup) and cleanup_succeeded
    if manifest_staging is not None:
        cleanup_succeeded = _cleanup_staging_file(manifest_staging) and cleanup_succeeded
    if manifest_backup is not None:
        cleanup_succeeded = _cleanup_backup_file(manifest_backup) and cleanup_succeeded
    if lifecycle_staging is not None:
        cleanup_succeeded = _cleanup_staging_file(lifecycle_staging) and cleanup_succeeded
    if lifecycle_backup is not None:
        cleanup_succeeded = _cleanup_backup_file(lifecycle_backup) and cleanup_succeeded

    for descriptor in parent_descriptors.values():
        if descriptor.fd == root_fd:
            continue
        try:
            os.close(descriptor.fd)
        except OSError:
            cleanup_succeeded = False
    if root_fd is not None:
        try:
            os.close(root_fd)
        except OSError:
            cleanup_succeeded = False

    proposal_lock_released = False
    vault_lock_released = False
    if proposal_locked and proposal_lock is not None:
        try:
            release_result = proposal_lock.release()
            proposal_lock_released = release_result.released
            if not release_result.descriptor_closed:
                cleanup_succeeded = False
        except Exception:
            cleanup_succeeded = False
    if vault_locked and vault_lock is not None:
        try:
            release_result = vault_lock.release()
            vault_lock_released = release_result.released
            if not release_result.descriptor_closed:
                cleanup_succeeded = False
        except Exception:
            cleanup_succeeded = False

    for descriptor_fd in (prop_fd, locks_fd, lifeos_fd):
        if descriptor_fd is None:
            continue
        try:
            os.close(descriptor_fd)
        except OSError:
            cleanup_succeeded = False

    return _CleanupResult(
        cleanup_succeeded=cleanup_succeeded,
        vault_lock_released=vault_lock_released,
        proposal_lock_released=proposal_lock_released,
    )


def apply_proposal(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    applied_by: str,
    applied_at: str,
) -> ProposalApplicationResult:
    outcome = _create_initial_outcome(proposal)
    if not applied_by:
        raise ApplicationError(
            "applied_by must be non-empty",
            outcome,
            code=ApplicationErrorCode.VALIDATION_ERROR,
        )
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", applied_at):
        raise ApplicationError(
            "applied_at must be strict RFC 3339 UTC",
            outcome,
            code=ApplicationErrorCode.VALIDATION_ERROR,
        )

    runtime_dir = vault_root / ".lifeos"
    recovery_root = runtime_dir / "recovery"
    try:
        with acquire_recovery_lock(runtime_dir=runtime_dir):
            try:
                _recover_interrupted_applications_locked(vault_root=vault_root)
            except RecoveryCorruptStateError as error:
                raise ApplicationError(
                    "Recovery state is ambiguous",
                    outcome,
                    code=ApplicationErrorCode.RECOVERY_REQUIRED,
                ) from error
            except RecoveryError as error:
                raise ApplicationError(
                    "Recovery state is unavailable",
                    outcome,
                    code=ApplicationErrorCode.RECOVERY_REQUIRED,
                ) from error
            return _apply_proposal_locked(
                proposal,
                vault_root=vault_root,
                applied_by=applied_by,
                applied_at=applied_at,
                recovery_root=recovery_root,
                outcome=outcome,
            )
    except RecoveryLockUnavailableError as error:
        raise ApplicationError(
            "Failed to acquire recovery lock",
            outcome,
            code=ApplicationErrorCode.LOCK_ERROR,
        ) from error


def _apply_proposal_locked(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    applied_by: str,
    applied_at: str,
    recovery_root: Path,
    outcome: ProposalApplicationResult,
) -> ProposalApplicationResult:
    """Orchestrate one locked application through the explicit state machine."""
    return _execute_application_transaction(
        _ApplicationContext(
            proposal=proposal,
            vault_root=vault_root,
            applied_by=applied_by,
            applied_at=applied_at,
            recovery_root=recovery_root,
            outcome=outcome,
        )
    )


def _execute_application_transaction(
    context: _ApplicationContext,
) -> ProposalApplicationResult:
    proposal = context.proposal
    vault_root = context.vault_root
    applied_by = context.applied_by
    applied_at = context.applied_at
    recovery_root = context.recovery_root
    outcome = context.outcome
    canonical_proposals_root = vault_root / "proposals"
    proposal_dir_path = canonical_proposals_root / proposal.proposal_dir

    vault_lock: Optional[OwnedLock] = None
    proposal_lock: Optional[OwnedLock] = None
    vault_locked = False
    proposal_locked = False
    lifeos_fd: Optional[int] = None
    locks_fd: Optional[int] = None
    root_fd: Optional[int] = None
    prop_fd: Optional[int] = None

    parent_descriptors: Dict[str, ParentDescriptor] = {}
    prepared_ops: List[_PreparedOp] = []
    manifest_operation_indexes: list[int] = []
    manifest_staging: Optional[StagingFile] = None
    manifest_backup: Optional[BackupFile] = None
    lifecycle_staging: Optional[StagingFile] = None
    lifecycle_backup: Optional[BackupFile] = None

    manifest_committed = False
    lifecycle_committed = False
    ownership_changed = False
    write_occurred = False
    rollback_performed = False
    rollback_succeeded: Optional[bool] = None
    recovery_required = False
    durability = "confirmed"
    cleanup_succeeded = True
    recovery_artifacts_retained = False
    transaction_id: Optional[RecoveryTransactionId] = None
    recovery_journal: Optional[RecoveryJournal] = None
    transaction_initialized = False
    application_error: Optional[ApplicationError] = None
    unexpected_error: Optional[Exception] = None

    def update_op_state(index: int, state: OperationState, error: Optional[str] = None) -> None:
        nonlocal outcome
        operation_results = list(outcome.operation_results)
        operation_results[index] = replace(operation_results[index], state=state, error=error)
        outcome = replace(outcome, operation_results=tuple(operation_results))

    try:
        try:
            lifeos_fd = open_directory_secure(vault_root / ".lifeos")
            try:
                locks_fd = open_directory_secure(vault_root / ".lifeos" / "locks", dir_fd=lifeos_fd)
            except SecureIOError:
                os.mkdir("locks", 0o700, dir_fd=lifeos_fd)
                locks_fd = open_directory_secure(vault_root / ".lifeos" / "locks", dir_fd=lifeos_fd)
        except (OSError, SecureIOError) as error:
            raise ApplicationError(
                "Failed to setup transaction",
                outcome,
                code=ApplicationErrorCode.IO_ERROR,
            ) from error

        vault_lock = OwnedLock(locks_fd, "vault-mutation.lock")
        try:
            vault_lock.acquire()
            vault_locked = True
        except LockError as error:
            raise ApplicationError(
                "Failed to acquire vault mutation lock",
                outcome,
                code=ApplicationErrorCode.LOCK_ERROR,
            ) from error

        try:
            prop_fd = open_directory_secure(proposal_dir_path)
        except SecureIOError as error:
            raise ApplicationError(
                "Failed to open proposal dir",
                outcome,
                code=ApplicationErrorCode.IO_ERROR,
            ) from error
        proposal_lock = OwnedLock(prop_fd, ".lifeos-transition.lock")
        try:
            proposal_lock.acquire()
            proposal_locked = True
        except LockError as error:
            raise ApplicationError(
                "Failed to acquire proposal transition lock",
                outcome,
                code=ApplicationErrorCode.LOCK_ERROR,
            ) from error

        _validate_proposal_sources_locked(
            proposal,
            prop_fd=prop_fd,
            vault_root=vault_root,
            outcome=outcome,
        )
        _validate_application_proposal(proposal, vault_root=vault_root, outcome=outcome)

        try:
            root_fd = open_directory_secure(vault_root)
        except SecureIOError as error:
            raise ApplicationError(
                "Failed to open vault root",
                outcome,
                code=ApplicationErrorCode.IO_ERROR,
            ) from error

        root_stat = os.fstat(root_fd)
        parent_descriptors["."] = ParentDescriptor(
            fd=root_fd, dev=root_stat.st_dev, ino=root_stat.st_ino, path="."
        )
        proposals_fd = open_directory_secure(canonical_proposals_root, dir_fd=root_fd)
        proposals_stat = os.fstat(proposals_fd)
        parent_descriptors["proposals"] = ParentDescriptor(
            fd=proposals_fd,
            dev=proposals_stat.st_dev,
            ino=proposals_stat.st_ino,
            path="proposals",
        )

        try:
            system_fd = open_directory_secure(vault_root / "system")
        except SecureIOError:
            system_fd = None
        if system_fd is not None:
            system_stat = os.fstat(system_fd)
            parent_descriptors["system"] = ParentDescriptor(
                fd=system_fd,
                dev=system_stat.st_dev,
                ino=system_stat.st_ino,
                path="system",
            )

        for op in proposal.patch_document.operations:
            if op.op == "release_generated_ownership":
                continue
            target_path = op.target_path
            parent_relative = str(Path(target_path).parent)
            if parent_relative not in parent_descriptors:
                try:
                    parent_fd = open_directory_secure(vault_root / parent_relative)
                    parent_stat = os.fstat(parent_fd)
                except SecureIOError as error:
                    raise ApplicationError(
                        "Missing target parent directory",
                        outcome,
                        code=ApplicationErrorCode.TARGET_CONFLICT,
                    ) from error
                parent_descriptors[parent_relative] = ParentDescriptor(
                    fd=parent_fd,
                    dev=parent_stat.st_dev,
                    ino=parent_stat.st_ino,
                    path=parent_relative,
                )

        manifest_bytes: Optional[bytes] = None
        if "system" in parent_descriptors:
            try:
                manifest_bytes = read_file_secure(
                    "generated-ownership.json",
                    vault_root,
                    dir_fd=parent_descriptors["system"].fd,
                )
            except SecureIOError:
                pass
        ownership = (
            GeneratedOwnership.from_bytes(
                manifest_bytes,
                manifest_path=vault_root / DEFAULT_OWNERSHIP_MANIFEST_PATH,
                vault_root=vault_root,
            )
            if manifest_bytes is not None
            else GeneratedOwnership(vault_root / DEFAULT_OWNERSHIP_MANIFEST_PATH, vault_root, {})
        )

        operation_candidates: List[_OperationCandidate] = []
        for index, operation in enumerate(proposal.patch_document.operations):
            if operation.op == "release_generated_ownership":
                manifest_operation_indexes.append(index)
                continue
            parent = parent_descriptors[str(Path(operation.target_path).parent)]
            try:
                candidate = _candidate_for_operation(
                    index=index,
                    operation=operation,
                    parent=parent,
                    vault_root=vault_root,
                )
            except (OSError, SecureIOError, TransactionError, ValueError) as error:
                update_op_state(
                    index,
                    OperationState.NOT_PREPARED,
                    error="Operation preparation failed",
                )
                raise ApplicationError(
                    f"Preparation failed for operation {operation.id}",
                    outcome,
                    code=ApplicationErrorCode.IO_ERROR,
                ) from error
            operation_candidates.append(candidate)

        new_entries = dict(ownership.entries)
        for candidate in operation_candidates:
            if candidate.op.op not in (
                "create_generated_file",
                "replace_generated_file",
            ):
                continue
            ownership_changed = True
            generator_id = getattr(
                candidate.op,
                "generator_id",
                getattr(candidate.op, "expected_generator_id", None),
            )
            if not generator_id and candidate.target_path in new_entries:
                generator_id = new_entries[candidate.target_path].generator_id
            created_at = applied_at
            if candidate.op.op == "replace_generated_file" and candidate.target_path in new_entries:
                created_at = new_entries[candidate.target_path].created_at
            new_entries[candidate.target_path] = ManifestEntry(
                generator_id=str(generator_id or ""),
                generator_version=getattr(candidate.op, "generator_version", "v1"),
                content_hash=hashlib.sha256(candidate.candidate_content).hexdigest(),
                created_at=created_at,
                updated_at=applied_at,
            )

        assert root_fd is not None
        _release_reviewed_ownership_entries(
            proposal=proposal,
            operation_indexes=manifest_operation_indexes,
            entries=new_entries,
            root_fd=root_fd,
            outcome=outcome,
        )
        ownership_changed = ownership_changed or bool(manifest_operation_indexes)

        if ownership_changed:
            if "system" not in parent_descriptors:
                raise ApplicationError(
                    "Missing system directory for ownership update",
                    outcome,
                    code=ApplicationErrorCode.TARGET_CONFLICT,
                )
            manifest_candidate = serialize_generated_ownership_bytes(new_entries)
        else:
            manifest_candidate = (
                manifest_bytes
                if manifest_bytes is not None
                else serialize_generated_ownership_bytes(new_entries)
            )

        new_metadata = replace(
            proposal.metadata,
            status=ProposalStatus.APPLIED,
            applied_by=applied_by,
            applied_at=applied_at,
        )
        proposal_candidate = serialize_proposal_markdown(new_metadata, proposal.body)

        for candidate in operation_candidates:
            try:
                staging = create_staging_file(
                    target_name=candidate.target_name,
                    content=candidate.candidate_content,
                    parent=candidate.parent,
                    intended_mode=candidate.intended_mode,
                )
                backup = None
                if candidate.original_identity is not None:
                    backup = create_hardlink_backup(
                        candidate.target_name,
                        candidate.parent,
                        candidate.original_identity,
                    )
                    durability = _record_sync_result(backup.sync_result, durability)
            except (OSError, TransactionError) as error:
                update_op_state(
                    candidate.index,
                    OperationState.NOT_PREPARED,
                    error="Operation preparation failed",
                )
                raise ApplicationError(
                    f"Preparation failed for operation {candidate.op.id}",
                    outcome,
                    code=ApplicationErrorCode.IO_ERROR,
                ) from error
            prepared_ops.append(_PreparedOp(candidate=candidate, staging=staging, backup=backup))
            update_op_state(candidate.index, OperationState.PREPARED)

        manifest_identity: Optional[TargetIdentity] = None
        manifest_mode = 0o600
        if manifest_bytes is not None:
            assert "system" in parent_descriptors
            manifest_identity = require_replacement_identity(
                get_target_identity("generated-ownership.json", parent_descriptors["system"]),
                target_kind="generated-ownership.json",
            )
            manifest_mode = stat.S_IMODE(manifest_identity.mode)
        if ownership_changed:
            system_parent = parent_descriptors["system"]
            manifest_staging = create_staging_file(
                "generated-ownership.json",
                manifest_candidate,
                system_parent,
                intended_mode=manifest_mode,
            )
            if manifest_identity is not None:
                manifest_backup = create_hardlink_backup(
                    "generated-ownership.json", system_parent, manifest_identity
                )
                durability = _record_sync_result(manifest_backup.sync_result, durability)
            for index in manifest_operation_indexes:
                update_op_state(index, OperationState.PREPARED)

        proposal_parent = ParentDescriptor(
            fd=prop_fd,
            dev=os.fstat(prop_fd).st_dev,
            ino=os.fstat(prop_fd).st_ino,
            path=proposal.proposal_dir,
        )
        proposal_identity = require_replacement_identity(
            get_target_identity("proposal.md", proposal_parent),
            target_kind="proposal.md",
        )
        proposal_original = read_file_secure("proposal.md", vault_root, dir_fd=proposal_parent.fd)
        proposal_mode = stat.S_IMODE(proposal_identity.mode)
        lifecycle_staging = create_staging_file(
            "proposal.md",
            proposal_candidate,
            proposal_parent,
            intended_mode=proposal_mode,
        )
        lifecycle_backup = create_hardlink_backup("proposal.md", proposal_parent, proposal_identity)
        durability = _record_sync_result(lifecycle_backup.sync_result, durability)

        transaction_id = generate_recovery_transaction_id(
            proposal_id=proposal.metadata.id,
            suffix_factory=lambda: secrets.token_hex(4),
        )
        recovery_operations = tuple(
            RecoveryOperation(
                operation_id=prepared.op.id,
                operation_type=_operation_type(prepared.op),
                target_path=prepared.target_path,
                expected_pre_state=(
                    RecoveryExpectedState.PRESENT
                    if prepared.original_identity is not None
                    else RecoveryExpectedState.ABSENT
                ),
                expected_pre_hash=(
                    _identity_hash(prepared.original_identity)
                    if prepared.original_identity is not None
                    else None
                ),
                expected_pre_mode=(
                    stat.S_IMODE(prepared.original_identity.mode)
                    if prepared.original_identity is not None
                    else None
                ),
                staged_path=f"staged/op-{prepared.index:04d}-{prepared.op.id}",
                staged_hash=_prefixed_hash(prepared.candidate.candidate_content),
                staged_mode=prepared.candidate.intended_mode,
                backup_path=(
                    f"backups/op-{prepared.index:04d}-{prepared.op.id}"
                    if prepared.original_identity is not None
                    else None
                ),
                backup_hash=(
                    _prefixed_hash(prepared.candidate.original_content)
                    if prepared.candidate.original_content is not None
                    else None
                ),
                staged_size=len(prepared.candidate.candidate_content),
                backup_size=(
                    len(prepared.candidate.original_content)
                    if prepared.candidate.original_content is not None
                    else None
                ),
            )
            for prepared in prepared_ops
        )
        ownership_state = RecoveryStateFiles(
            expected_pre_state=(
                RecoveryExpectedState.PRESENT
                if manifest_bytes is not None
                else RecoveryExpectedState.ABSENT
            ),
            expected_pre_hash=(
                _prefixed_hash(manifest_bytes) if manifest_bytes is not None else None
            ),
            expected_pre_mode=(
                stat.S_IMODE(manifest_identity.mode) if manifest_identity is not None else None
            ),
            staged_path="staged/ownership",
            staged_hash=_prefixed_hash(manifest_candidate),
            staged_mode=manifest_mode,
            backup_path=("backups/ownership" if manifest_bytes is not None else None),
            backup_hash=(_prefixed_hash(manifest_bytes) if manifest_bytes is not None else None),
            staged_size=len(manifest_candidate),
            backup_size=(len(manifest_bytes) if manifest_bytes is not None else None),
        )
        proposal_state = RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.PRESENT,
            expected_pre_hash=_prefixed_hash(proposal_original),
            expected_pre_mode=proposal_mode,
            staged_path="staged/proposal",
            staged_hash=_prefixed_hash(proposal_candidate),
            staged_mode=proposal_mode,
            backup_path="backups/proposal",
            backup_hash=_prefixed_hash(proposal_original),
            staged_size=len(proposal_candidate),
            backup_size=len(proposal_original),
        )
        review_digest = proposal.metadata.review_digest
        if review_digest is None:
            raise ApplicationError(
                "Approved proposal is missing review digest",
                outcome,
                code=ApplicationErrorCode.VALIDATION_ERROR,
            )
        recovery_journal = RecoveryJournal(
            schema_version=RECOVERY_SCHEMA_VERSION,
            transaction_id=transaction_id,
            proposal_id=proposal.metadata.id,
            review_digest=review_digest,
            authorized_actor=applied_by,
            phase=RecoveryPhase.PREPARED,
            created_at=applied_at,
            operations=recovery_operations,
            ownership_state=ownership_state,
            proposal_state=proposal_state,
        )
        transaction_dir = initialize_recovery_transaction(
            recovery_root=recovery_root, journal=recovery_journal
        )
        transaction_initialized = True

        for prepared, recovery_operation in zip(prepared_ops, recovery_operations, strict=True):
            write_recovery_artifact(
                transaction_dir=transaction_dir,
                artifact=RecoveryArtifact(
                    relative_path=recovery_operation.staged_path,
                    content_hash=recovery_operation.staged_hash,
                    size=recovery_operation.staged_size,
                    mode=recovery_operation.staged_mode,
                ),
                content=prepared.candidate.candidate_content,
            )
            if recovery_operation.backup_path is not None:
                assert prepared.candidate.original_content is not None
                assert recovery_operation.backup_hash is not None
                assert recovery_operation.backup_size is not None
                write_recovery_artifact(
                    transaction_dir=transaction_dir,
                    artifact=RecoveryArtifact(
                        relative_path=recovery_operation.backup_path,
                        content_hash=recovery_operation.backup_hash,
                        size=recovery_operation.backup_size,
                        mode=recovery_operation.expected_pre_mode or 0,
                    ),
                    content=prepared.candidate.original_content,
                )

        write_recovery_artifact(
            transaction_dir=transaction_dir,
            artifact=_artifact(ownership_state.staged_path, manifest_candidate, manifest_mode),
            content=manifest_candidate,
        )
        if manifest_bytes is not None:
            assert ownership_state.backup_path is not None
            write_recovery_artifact(
                transaction_dir=transaction_dir,
                artifact=_artifact(ownership_state.backup_path, manifest_bytes, manifest_mode),
                content=manifest_bytes,
            )
        write_recovery_artifact(
            transaction_dir=transaction_dir,
            artifact=_artifact(proposal_state.staged_path, proposal_candidate, proposal_mode),
            content=proposal_candidate,
        )
        write_recovery_artifact(
            transaction_dir=transaction_dir,
            artifact=_artifact(
                proposal_state.backup_path or "backups/proposal",
                proposal_original,
                proposal_mode,
            ),
            content=proposal_original,
        )
        write_recovery_journal(recovery_root=recovery_root, journal=recovery_journal)
        _application_checkpoint("after_prepared_journal")

        assert root_fd is not None
        assert prop_fd is not None
        assert vault_lock is not None
        assert proposal_lock is not None
        _validate_precommit_state(
            vault_root=vault_root,
            root_fd=root_fd,
            prop_fd=prop_fd,
            vault_lock=vault_lock,
            proposal_lock=proposal_lock,
            parent_descriptors=parent_descriptors,
            prepared_ops=prepared_ops,
            manifest_bytes=manifest_bytes,
            ownership_changed=ownership_changed,
            outcome=outcome,
        )

        durability, targets_written = _install_prepared_targets(
            prepared_ops=prepared_ops,
            outcome=outcome,
            durability=durability,
            update_op_state=update_op_state,
        )
        write_occurred = write_occurred or targets_written

        assert recovery_journal is not None
        recovery_journal = _advance_recovery_phase(
            journal=recovery_journal,
            next_phase=RecoveryPhase.TARGETS_INSTALLED,
            recovery_root=recovery_root,
        ).journal
        _application_checkpoint("after_all_targets")

        durability, manifest_committed, outcome = _install_ownership_manifest(
            ownership_changed=ownership_changed,
            manifest_staging=manifest_staging,
            manifest_identity=manifest_identity,
            outcome=outcome,
            durability=durability,
        )
        write_occurred = write_occurred or manifest_committed
        if manifest_committed:
            for index in manifest_operation_indexes:
                update_op_state(index, OperationState.COMMITTED)

        assert recovery_journal is not None
        recovery_journal = _advance_recovery_phase(
            journal=recovery_journal,
            next_phase=RecoveryPhase.OWNERSHIP_INSTALLED,
            recovery_root=recovery_root,
        ).journal
        _application_checkpoint("before_proposal_commit")

        assert lifecycle_staging is not None
        durability = _commit_proposal_lifecycle(
            lifecycle_staging=lifecycle_staging,
            proposal_identity=proposal_identity,
            outcome=outcome,
            durability=durability,
        )
        lifecycle_committed = True
        write_occurred = True

        assert recovery_journal is not None
        recovery_journal = _advance_recovery_phase(
            journal=recovery_journal,
            next_phase=RecoveryPhase.PROPOSAL_COMMITTED,
            recovery_root=recovery_root,
        ).journal
        recovery_journal = _advance_recovery_phase(
            journal=recovery_journal,
            next_phase=RecoveryPhase.COMPLETE,
            recovery_root=recovery_root,
        ).journal

        outcome = replace(
            outcome,
            new_status=ProposalStatus.APPLIED,
            changed_paths=tuple(
                dict.fromkeys(
                    str(DEFAULT_OWNERSHIP_MANIFEST_PATH)
                    if operation.op == "release_generated_ownership"
                    else operation.target_path
                    for operation in proposal.patch_document.operations
                )
            ),
            proposal_source_hash_after=_prefixed_hash(proposal_candidate),
        )

    except Exception as error:
        rollback_performed = True
        rollback_result = _rollback_application(
            error=error,
            prepared_ops=prepared_ops,
            lifecycle_committed=lifecycle_committed,
            lifecycle_staging=lifecycle_staging,
            lifecycle_backup=lifecycle_backup,
            manifest_committed=manifest_committed,
            manifest_staging=manifest_staging,
            manifest_backup=manifest_backup,
            transaction_initialized=transaction_initialized,
            transaction_id=transaction_id,
            recovery_root=recovery_root,
            durability=durability,
            recovery_artifacts_retained=recovery_artifacts_retained,
            update_op_state=update_op_state,
            manifest_operation_indexes=tuple(manifest_operation_indexes),
        )
        durability = rollback_result.durability
        rollback_succeeded = rollback_result.rollback_succeeded
        recovery_required = rollback_result.recovery_required
        recovery_artifacts_retained = rollback_result.recovery_artifacts_retained
        transaction_initialized = rollback_result.transaction_initialized
        application_error = rollback_result.application_error
        unexpected_error = rollback_result.unexpected_error

    finally:
        cleanup_result = _cleanup_application_resources(
            prepared_ops=prepared_ops,
            manifest_staging=manifest_staging,
            manifest_backup=manifest_backup,
            lifecycle_staging=lifecycle_staging,
            lifecycle_backup=lifecycle_backup,
            parent_descriptors=parent_descriptors,
            root_fd=root_fd,
            proposal_locked=proposal_locked,
            proposal_lock=proposal_lock,
            vault_locked=vault_locked,
            vault_lock=vault_lock,
            prop_fd=prop_fd,
            locks_fd=locks_fd,
            lifeos_fd=lifeos_fd,
        )
        cleanup_succeeded = cleanup_result.cleanup_succeeded
        vault_lock_released = cleanup_result.vault_lock_released
        proposal_lock_released = cleanup_result.proposal_lock_released

        if transaction_initialized and (
            recovery_journal is None or recovery_journal.phase is not RecoveryPhase.COMPLETE
        ):
            recovery_artifacts_retained = True
            recovery_required = True

        outcome = replace(
            outcome,
            write_occurred=write_occurred,
            durability=durability,
            rollback_performed=rollback_performed,
            rollback_succeeded=rollback_succeeded,
            recovery_required=recovery_required,
            cleanup_succeeded=cleanup_succeeded,
            recovery_artifacts_retained=recovery_artifacts_retained,
            vault_lock_released=vault_lock_released,
            proposal_lock_released=proposal_lock_released,
        )
        if application_error is not None:
            application_error.outcome = replace(
                application_error.outcome,
                operation_results=outcome.operation_results,
                ownership_changed=outcome.ownership_changed,
                write_occurred=outcome.write_occurred,
                durability=outcome.durability,
                rollback_performed=outcome.rollback_performed,
                rollback_succeeded=outcome.rollback_succeeded,
                recovery_required=outcome.recovery_required,
                cleanup_succeeded=outcome.cleanup_succeeded,
                recovery_artifacts_retained=outcome.recovery_artifacts_retained,
                vault_lock_released=outcome.vault_lock_released,
                proposal_lock_released=outcome.proposal_lock_released,
            )

    if unexpected_error is not None:
        raise unexpected_error
    if application_error is not None:
        raise _public_application_error(application_error)
    return outcome
