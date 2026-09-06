import fcntl
import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, NewType

from lifeos.proposals.schema import ProposalSchemaError, validate_proposal_id

RecoveryTransactionId = NewType("RecoveryTransactionId", str)


class RecoveryError(Exception):
    pass


class RecoveryValidationError(RecoveryError):
    pass


class RecoveryConflictError(RecoveryError):
    pass


class RecoveryCorruptStateError(RecoveryError):
    pass


class RecoveryUnknownSchemaError(RecoveryCorruptStateError):
    pass


class RecoveryLockUnavailableError(RecoveryError):
    pass


class RecoveryUnavailableError(RecoveryError):
    pass


class RecoveryPhase(Enum):
    PREPARED = "prepared"
    TARGETS_INSTALLED = "targets_installed"
    OWNERSHIP_INSTALLED = "ownership_installed"
    PROPOSAL_COMMITTED = "proposal_committed"
    COMPLETE = "complete"


RECOVERY_SCHEMA_VERSION = 2


class RecoveryOperationType(Enum):
    CREATE_FILE = "create_file"
    PATCH_HUMAN_FILE = "patch_human_file"
    CREATE_GENERATED_FILE = "create_generated_file"
    REPLACE_GENERATED_FILE = "replace_generated_file"
    REPLACE_MANAGED_BLOCK = "replace_managed_block"


class RecoveryExpectedState(Enum):
    PRESENT = "present"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class RecoveryStateFiles:
    expected_pre_state: RecoveryExpectedState
    expected_pre_hash: str | None
    expected_pre_mode: int | None
    staged_path: str
    staged_hash: str
    staged_mode: int
    backup_path: str | None
    backup_hash: str | None
    staged_size: int = 0
    backup_size: int | None = None

    def __post_init__(self) -> None:
        if self.expected_pre_state == RecoveryExpectedState.PRESENT:
            if type(self.expected_pre_hash) is not str:
                raise RecoveryValidationError(
                    "expected_pre_hash must be a string for PRESENT state"
                )
            if type(self.expected_pre_mode) is not int:
                raise RecoveryValidationError("expected_pre_mode must be an int for PRESENT state")
            if type(self.backup_hash) is not str:
                raise RecoveryValidationError("backup_hash must be a string for PRESENT state")
            if type(self.backup_path) is not str:
                raise RecoveryValidationError("backup_path must be a string for PRESENT state")
            if type(self.backup_size) is not int or type(self.backup_size) is bool:
                raise RecoveryValidationError("backup_size must be an int for PRESENT state")
            if self.backup_size < 0:
                raise RecoveryValidationError("backup_size cannot be negative")
            _validate_permission_mode(self.expected_pre_mode)
        elif self.expected_pre_state == RecoveryExpectedState.ABSENT:
            if self.expected_pre_hash is not None:
                raise RecoveryValidationError("expected_pre_hash must be None for ABSENT state")
            if self.expected_pre_mode is not None:
                raise RecoveryValidationError("expected_pre_mode must be None for ABSENT state")
            if self.backup_hash is not None:
                raise RecoveryValidationError("backup_hash must be None for ABSENT state")
            if self.backup_path is not None:
                raise RecoveryValidationError("backup_path must be None for ABSENT state")
            if self.backup_size is not None:
                raise RecoveryValidationError("backup_size must be None for ABSENT state")
        else:
            raise RecoveryValidationError("Invalid expected_pre_state")

        if type(self.staged_hash) is not str:
            raise RecoveryValidationError("staged_hash must be a string")
        if type(self.staged_path) is not str:
            raise RecoveryValidationError("staged_path must be a string")
        if type(self.staged_size) is not int or type(self.staged_size) is bool:
            raise RecoveryValidationError("staged_size must be an int")
        if self.staged_size < 0:
            raise RecoveryValidationError("staged_size cannot be negative")
        _validate_permission_mode(self.staged_mode)


@dataclass(frozen=True, slots=True)
class RecoveryOperation:
    operation_id: str
    operation_type: RecoveryOperationType
    target_path: str
    expected_pre_state: RecoveryExpectedState
    expected_pre_hash: str | None
    expected_pre_mode: int | None
    staged_path: str
    staged_hash: str
    staged_mode: int
    backup_path: str | None
    backup_hash: str | None
    staged_size: int = 0
    backup_size: int | None = None


@dataclass(frozen=True, slots=True)
class RecoveryJournal:
    schema_version: int
    transaction_id: RecoveryTransactionId
    proposal_id: str
    review_digest: str
    authorized_actor: str
    phase: RecoveryPhase
    created_at: str
    operations: tuple[RecoveryOperation, ...]
    ownership_state: RecoveryStateFiles
    proposal_state: RecoveryStateFiles


class RecoveryFindingCode(Enum):
    DIR_WITHOUT_JOURNAL = "dir_without_journal"
    CORRUPT_JSON = "corrupt_json"
    INVALID_LAYOUT = "invalid_layout"
    UNKNOWN_SCHEMA = "unknown_schema"
    INVALID_DIR_NAME = "invalid_dir_name"
    TRANSACTION_ID_MISMATCH = "transaction_id_mismatch"
    SYMLINKED_DIR = "symlinked_dir"
    SYMLINKED_JOURNAL = "symlinked_journal"
    UNEXPECTED_FILE = "unexpected_file"


@dataclass(frozen=True, slots=True)
class RecoveryFinding:
    code: RecoveryFindingCode
    transaction_name: str


@dataclass(frozen=True, slots=True)
class RecoveryDiscoveryResult:
    journals: tuple[RecoveryJournal, ...]
    findings: tuple[RecoveryFinding, ...]


_TX_ID_REGEX = re.compile(r"^prop-\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{8}$")
_SHA256_REGEX = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_recovery_transaction_id(value: object) -> RecoveryTransactionId:
    if type(value) is not str:
        raise RecoveryValidationError("Invalid transaction ID type")
    if not _TX_ID_REGEX.match(value):
        raise RecoveryValidationError("Invalid transaction ID format")
    return RecoveryTransactionId(value)


def _validate_vault_relative_path(path: object) -> None:
    if type(path) is not str:
        raise RecoveryValidationError("Path must be a string")
    if not path:
        raise RecoveryValidationError("Invalid path")
    if "\\" in path:
        raise RecoveryValidationError("Invalid path")
    if "\0" in path:
        raise RecoveryValidationError("Invalid path")
    if os.path.isabs(path) or path.startswith("/"):
        raise RecoveryValidationError("Invalid path")
    parts = path.split("/")
    if "." in parts or ".." in parts:
        raise RecoveryValidationError("Invalid path")
    if "" in parts:
        raise RecoveryValidationError("Invalid path")


def generate_recovery_transaction_id(
    *,
    proposal_id: str,
    suffix_factory: Callable[[], str],
) -> RecoveryTransactionId:
    try:
        validate_proposal_id(proposal_id)
    except ProposalSchemaError as e:
        raise RecoveryValidationError("Invalid proposal ID") from e

    suffix = suffix_factory()
    if type(suffix) is not str:
        raise RecoveryValidationError("Suffix must be a string")
    if not re.match(r"^[0-9a-f]{8}$", suffix):
        raise RecoveryValidationError("Invalid suffix")

    tx_id = f"{proposal_id}-{suffix}"
    return validate_recovery_transaction_id(tx_id)


def _validate_permission_mode(mode: object) -> None:
    if type(mode) is not int or type(mode) is bool:
        raise RecoveryValidationError("Invalid permission mode type")
    if not (0o000 <= mode <= 0o7777):
        raise RecoveryValidationError("Invalid permission mode value")


def _serialize_journal(journal: RecoveryJournal) -> bytes:
    if type(journal.schema_version) is not int:
        raise RecoveryValidationError("schema_version must be exact int")
    if journal.schema_version != RECOVERY_SCHEMA_VERSION:
        raise RecoveryValidationError("Invalid schema version")

    if type(journal.review_digest) is not str:
        raise RecoveryValidationError("review_digest must be string")
    if not _SHA256_REGEX.match(journal.review_digest):
        raise RecoveryValidationError("Invalid review digest")

    if type(journal.created_at) is not str:
        raise RecoveryValidationError("created_at must be string")
    try:
        parsed = datetime.strptime(journal.created_at, "%Y-%m-%dT%H:%M:%SZ")
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != journal.created_at:
            raise RecoveryValidationError("Invalid created_at")
    except ValueError as e:
        raise RecoveryValidationError("Invalid created_at") from e

    if type(journal.authorized_actor) is not str:
        raise RecoveryValidationError("authorized_actor must be string")
    if not journal.authorized_actor or journal.authorized_actor.strip() != journal.authorized_actor:
        raise RecoveryValidationError("Invalid authorized actor")

    if type(journal.phase) is not RecoveryPhase:
        raise RecoveryValidationError("Invalid phase type")

    if type(journal.operations) is not tuple:
        raise RecoveryValidationError("Operations must be exact tuple")

    validate_recovery_transaction_id(journal.transaction_id)
    try:
        if type(journal.proposal_id) is not str:
            raise RecoveryValidationError("proposal_id must be string")
        validate_proposal_id(journal.proposal_id)
    except ProposalSchemaError as e:
        raise RecoveryValidationError("Invalid proposal ID") from e

    if not str(journal.transaction_id).startswith(f"{journal.proposal_id}-"):
        raise RecoveryValidationError("Transaction ID mismatch")

    op_ids = set()
    for op in journal.operations:
        if type(op) is not RecoveryOperation:
            raise RecoveryValidationError("Operation member must be RecoveryOperation")

        if type(op.operation_id) is not str or not op.operation_id:
            raise RecoveryValidationError("Invalid operation ID")
        if op.operation_id in op_ids:
            raise RecoveryValidationError("Duplicate operation ID")
        op_ids.add(op.operation_id)

        if type(op.operation_type) is not RecoveryOperationType:
            raise RecoveryValidationError("Invalid operation type")

        _validate_vault_relative_path(op.target_path)
        _validate_vault_relative_path(op.staged_path)
        if not op.staged_path.startswith("staged/"):
            raise RecoveryValidationError("Invalid staged path")

        if op.backup_path is not None:
            _validate_vault_relative_path(op.backup_path)
            if not op.backup_path.startswith("backups/"):
                raise RecoveryValidationError("Invalid backup path")

        if type(op.expected_pre_state) is not RecoveryExpectedState:
            raise RecoveryValidationError("Invalid expected pre state type")

        if op.expected_pre_state == RecoveryExpectedState.ABSENT:
            if op.expected_pre_hash is not None:
                raise RecoveryValidationError("Invalid pre-hash")
            if op.expected_pre_mode is not None:
                raise RecoveryValidationError("Invalid pre-mode")
            if op.backup_path is not None:
                raise RecoveryValidationError("Invalid backup path")
            if op.backup_hash is not None:
                raise RecoveryValidationError("Invalid backup hash")
            if op.backup_size is not None:
                raise RecoveryValidationError("Invalid backup size")
        else:
            if type(op.expected_pre_hash) is not str or not _SHA256_REGEX.match(
                op.expected_pre_hash
            ):
                raise RecoveryValidationError("Invalid pre-hash")
            _validate_permission_mode(op.expected_pre_mode)

            if op.backup_path is None or op.backup_hash is None:
                raise RecoveryValidationError("Invalid backup")
            if type(op.backup_hash) is not str or not _SHA256_REGEX.match(op.backup_hash):
                raise RecoveryValidationError("Invalid backup hash")
            if type(op.backup_size) is not int or type(op.backup_size) is bool:
                raise RecoveryValidationError("Invalid backup size")
            if op.backup_size < 0:
                raise RecoveryValidationError("Invalid backup size")

        if op.operation_type in (
            RecoveryOperationType.CREATE_FILE,
            RecoveryOperationType.CREATE_GENERATED_FILE,
        ):
            if op.expected_pre_state != RecoveryExpectedState.ABSENT:
                raise RecoveryValidationError("Invalid pre-state")
        else:
            if op.expected_pre_state != RecoveryExpectedState.PRESENT:
                raise RecoveryValidationError("Invalid pre-state")

        if type(op.staged_hash) is not str or not _SHA256_REGEX.match(op.staged_hash):
            raise RecoveryValidationError("Invalid staged hash")
        if type(op.staged_size) is not int or type(op.staged_size) is bool:
            raise RecoveryValidationError("Invalid staged size")
        if op.staged_size < 0:
            raise RecoveryValidationError("Invalid staged size")
        _validate_permission_mode(op.staged_mode)

    if type(journal.ownership_state) is not RecoveryStateFiles:
        raise RecoveryValidationError("Invalid ownership state type")
    if type(journal.proposal_state) is not RecoveryStateFiles:
        raise RecoveryValidationError("Invalid proposal state type")

    for state in (journal.ownership_state, journal.proposal_state):
        if type(state.expected_pre_state) is not RecoveryExpectedState:
            raise RecoveryValidationError("Invalid expected pre state type")

        if state.expected_pre_state == RecoveryExpectedState.ABSENT:
            if state.expected_pre_hash is not None:
                raise RecoveryValidationError("Invalid pre-hash")
            if state.expected_pre_mode is not None:
                raise RecoveryValidationError("Invalid pre-mode")
            if state.backup_path is not None:
                raise RecoveryValidationError("Invalid backup path")
            if state.backup_hash is not None:
                raise RecoveryValidationError("Invalid backup hash")
        else:
            if type(state.expected_pre_hash) is not str or not _SHA256_REGEX.match(
                state.expected_pre_hash
            ):
                raise RecoveryValidationError("Invalid pre-hash")
            _validate_permission_mode(state.expected_pre_mode)

            if state.backup_path is None or state.backup_hash is None:
                raise RecoveryValidationError("Invalid backup")
            if type(state.backup_hash) is not str or not _SHA256_REGEX.match(state.backup_hash):
                raise RecoveryValidationError("Invalid backup hash")

        _validate_vault_relative_path(state.staged_path)
        if not state.staged_path.startswith("staged/"):
            raise RecoveryValidationError("Invalid staged path")
        if type(state.staged_hash) is not str or not _SHA256_REGEX.match(state.staged_hash):
            raise RecoveryValidationError("Invalid staged hash")
        _validate_permission_mode(state.staged_mode)

        if state.backup_path is not None:
            _validate_vault_relative_path(state.backup_path)
            if not state.backup_path.startswith("backups/"):
                raise RecoveryValidationError("Invalid backup path")

    data = {
        "schema_version": journal.schema_version,
        "transaction_id": journal.transaction_id,
        "proposal_id": journal.proposal_id,
        "review_digest": journal.review_digest,
        "authorized_actor": journal.authorized_actor,
        "phase": journal.phase.value,
        "created_at": journal.created_at,
        "operations": [
            {
                "operation_id": op.operation_id,
                "operation_type": op.operation_type.value,
                "target_path": op.target_path,
                "expected_pre_state": op.expected_pre_state.value,
                "expected_pre_hash": op.expected_pre_hash,
                "expected_pre_mode": op.expected_pre_mode,
                "staged_path": op.staged_path,
                "staged_hash": op.staged_hash,
                "staged_size": op.staged_size,
                "staged_mode": op.staged_mode,
                "backup_path": op.backup_path,
                "backup_hash": op.backup_hash,
                "backup_size": op.backup_size,
            }
            for op in journal.operations
        ],
        "ownership_state": {
            "expected_pre_state": journal.ownership_state.expected_pre_state.value,
            "expected_pre_hash": journal.ownership_state.expected_pre_hash,
            "expected_pre_mode": journal.ownership_state.expected_pre_mode,
            "staged_path": journal.ownership_state.staged_path,
            "staged_hash": journal.ownership_state.staged_hash,
            "staged_size": journal.ownership_state.staged_size,
            "staged_mode": journal.ownership_state.staged_mode,
            "backup_path": journal.ownership_state.backup_path,
            "backup_hash": journal.ownership_state.backup_hash,
            "backup_size": journal.ownership_state.backup_size,
        },
        "proposal_state": {
            "expected_pre_state": journal.proposal_state.expected_pre_state.value,
            "expected_pre_hash": journal.proposal_state.expected_pre_hash,
            "expected_pre_mode": journal.proposal_state.expected_pre_mode,
            "staged_path": journal.proposal_state.staged_path,
            "staged_hash": journal.proposal_state.staged_hash,
            "staged_size": journal.proposal_state.staged_size,
            "staged_mode": journal.proposal_state.staged_mode,
            "backup_path": journal.proposal_state.backup_path,
            "backup_hash": journal.proposal_state.backup_hash,
            "backup_size": journal.proposal_state.backup_size,
        },
    }
    text = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (text + "\n").encode("utf-8")


def _deserialize_journal(content: bytes) -> RecoveryJournal:
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RecoveryCorruptStateError("Corrupt JSON content") from e

    try:
        if type(data) is not dict:
            raise RecoveryCorruptStateError("Root must be an object")

        if "schema_version" not in data:
            raise RecoveryCorruptStateError("Missing schema version")

        schema_version = data["schema_version"]

        if type(schema_version) is not int:
            raise RecoveryCorruptStateError("Invalid schema version type")

        if schema_version != RECOVERY_SCHEMA_VERSION:
            raise RecoveryUnknownSchemaError("Unknown schema version")

        if type(data.get("operations")) is not list:
            raise RecoveryCorruptStateError("Operations must be a list")

        ops = []
        for op in data["operations"]:
            if type(op) is not dict:
                raise RecoveryCorruptStateError("Operation must be an object")
            ops.append(
                RecoveryOperation(
                    operation_id=op["operation_id"],
                    operation_type=RecoveryOperationType(op["operation_type"]),
                    target_path=op["target_path"],
                    expected_pre_state=RecoveryExpectedState(op["expected_pre_state"]),
                    expected_pre_hash=op.get("expected_pre_hash"),
                    expected_pre_mode=op.get("expected_pre_mode"),
                    staged_path=op["staged_path"],
                    staged_hash=op["staged_hash"],
                    staged_mode=op["staged_mode"],
                    backup_path=op.get("backup_path"),
                    backup_hash=op.get("backup_hash"),
                    staged_size=op["staged_size"],
                    backup_size=op.get("backup_size"),
                )
            )

        if type(data.get("ownership_state")) is not dict:
            raise RecoveryCorruptStateError("Ownership state must be an object")
        if type(data.get("proposal_state")) is not dict:
            raise RecoveryCorruptStateError("Proposal state must be an object")

        if "transaction_id" not in data:
            raise RecoveryCorruptStateError("Missing transaction_id")
        try:
            validate_recovery_transaction_id(data["transaction_id"])
        except RecoveryValidationError as e:
            raise RecoveryCorruptStateError("Invalid persisted transaction_id") from e

        journal = RecoveryJournal(
            schema_version=data["schema_version"],
            transaction_id=data["transaction_id"],
            proposal_id=data["proposal_id"],
            review_digest=data["review_digest"],
            authorized_actor=data["authorized_actor"],
            phase=RecoveryPhase(data["phase"]),
            created_at=data["created_at"],
            operations=tuple(ops),
            ownership_state=RecoveryStateFiles(
                expected_pre_state=RecoveryExpectedState(
                    data["ownership_state"]["expected_pre_state"]
                ),
                expected_pre_hash=data["ownership_state"].get("expected_pre_hash"),
                expected_pre_mode=data["ownership_state"].get("expected_pre_mode"),
                staged_path=data["ownership_state"]["staged_path"],
                staged_hash=data["ownership_state"]["staged_hash"],
                staged_mode=data["ownership_state"]["staged_mode"],
                backup_path=data["ownership_state"].get("backup_path"),
                backup_hash=data["ownership_state"].get("backup_hash"),
                staged_size=data["ownership_state"]["staged_size"],
                backup_size=data["ownership_state"].get("backup_size"),
            ),
            proposal_state=RecoveryStateFiles(
                expected_pre_state=RecoveryExpectedState(
                    data["proposal_state"]["expected_pre_state"]
                ),
                expected_pre_hash=data["proposal_state"].get("expected_pre_hash"),
                expected_pre_mode=data["proposal_state"].get("expected_pre_mode"),
                staged_path=data["proposal_state"]["staged_path"],
                staged_hash=data["proposal_state"]["staged_hash"],
                staged_mode=data["proposal_state"]["staged_mode"],
                backup_path=data["proposal_state"].get("backup_path"),
                backup_hash=data["proposal_state"].get("backup_hash"),
                staged_size=data["proposal_state"]["staged_size"],
                backup_size=data["proposal_state"].get("backup_size"),
            ),
        )
    except KeyError as e:
        raise RecoveryCorruptStateError("Missing field") from e
    except TypeError as e:
        raise RecoveryCorruptStateError("Invalid field type") from e
    except ValueError as e:
        raise RecoveryCorruptStateError("Invalid field value") from e

    try:
        _serialize_journal(journal)
    except RecoveryValidationError as e:
        raise RecoveryCorruptStateError("Logical validation failed") from e

    return journal


def _check_symlink_containment(path: Path, root: Path) -> None:
    if path.is_symlink():
        raise RecoveryCorruptStateError("Symlinked paths are not permitted")
    if not path.exists():
        raise RecoveryCorruptStateError("Path does not exist")
    try:
        resolved = path.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
    except OSError as e:
        raise RecoveryCorruptStateError("Path resolution failed") from e
    try:
        resolved.relative_to(root_resolved)
    except ValueError as e:
        raise RecoveryCorruptStateError("Symlink escape detected") from e


def _validate_transaction_layout(
    *,
    recovery_root: Path,
    transaction_id: RecoveryTransactionId,
) -> Path:
    validate_recovery_transaction_id(transaction_id)
    _check_symlink_containment(recovery_root, recovery_root)
    tx_dir = recovery_root / transaction_id
    _check_symlink_containment(tx_dir, recovery_root)
    if not tx_dir.is_dir():
        raise RecoveryCorruptStateError("Transaction must be a directory")

    journal_path = tx_dir / "journal.json"
    _check_symlink_containment(journal_path, recovery_root)
    if not journal_path.is_file():
        raise RecoveryCorruptStateError("Journal must be a regular file")

    staged_dir = tx_dir / "staged"
    _check_symlink_containment(staged_dir, recovery_root)
    if not staged_dir.is_dir():
        raise RecoveryCorruptStateError("Staged must be a directory")

    backups_dir = tx_dir / "backups"
    _check_symlink_containment(backups_dir, recovery_root)
    if not backups_dir.is_dir():
        raise RecoveryCorruptStateError("Backups must be a directory")

    return tx_dir


def initialize_recovery_transaction(
    *,
    recovery_root: Path,
    journal: RecoveryJournal,
) -> Path:
    validate_recovery_transaction_id(journal.transaction_id)
    if journal.phase is not RecoveryPhase.PREPARED:
        raise RecoveryValidationError("Initial journal must be prepared")

    tx_dir = recovery_root / journal.transaction_id
    if tx_dir.exists() or tx_dir.is_symlink():
        raise RecoveryConflictError("Transaction exists")

    content = _serialize_journal(journal)

    if recovery_root.is_symlink():
        raise RecoveryCorruptStateError("Symlinked root not permitted")

    try:
        tx_dir.mkdir(parents=True)
        (tx_dir / "staged").mkdir()
        (tx_dir / "backups").mkdir()

        journal_path = tx_dir / "journal.json"
        journal_path.write_bytes(content)

        _validate_transaction_layout(
            recovery_root=recovery_root, transaction_id=journal.transaction_id
        )

        return tx_dir
    except OSError as e:
        raise RecoveryUnavailableError("Initialization failed") from e


def write_recovery_journal(
    *,
    recovery_root: Path,
    journal: RecoveryJournal,
) -> None:
    validate_recovery_transaction_id(journal.transaction_id)
    tx_dir = _validate_transaction_layout(
        recovery_root=recovery_root, transaction_id=journal.transaction_id
    )

    journal_path = tx_dir / "journal.json"
    content = _serialize_journal(journal)
    tmp_path = tx_dir / "journal.json.tmp"

    if tmp_path.is_symlink():
        raise RecoveryCorruptStateError("Symlinked temporary path is not permitted")

    try:
        tmp_path.write_bytes(content)
        os.replace(tmp_path, journal_path)
    except OSError as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise RecoveryUnavailableError("Failed to write journal") from e


def load_recovery_journal(
    *,
    recovery_root: Path,
    transaction_id: RecoveryTransactionId,
) -> RecoveryJournal:
    validate_recovery_transaction_id(transaction_id)
    tx_dir = _validate_transaction_layout(
        recovery_root=recovery_root, transaction_id=transaction_id
    )

    journal_path = tx_dir / "journal.json"
    try:
        content = journal_path.read_bytes()
    except OSError as e:
        raise RecoveryUnavailableError("Failed to read journal") from e

    journal = _deserialize_journal(content)
    if journal.transaction_id != transaction_id:
        raise RecoveryCorruptStateError("Journal transaction ID mismatch")
    return journal


def discover_recovery_state(
    *,
    recovery_root: Path,
) -> RecoveryDiscoveryResult:
    if recovery_root.is_symlink():
        raise RecoveryCorruptStateError("Invalid recovery root")

    if not recovery_root.exists():
        return RecoveryDiscoveryResult(journals=(), findings=())

    if not recovery_root.is_dir():
        raise RecoveryCorruptStateError("Invalid recovery root")

    journals = []
    findings = []
    try:
        entries = sorted(recovery_root.iterdir(), key=lambda p: p.name)
    except OSError as e:
        raise RecoveryUnavailableError("Failed to list recovery root") from e

    for entry in entries:
        tx_id = entry.name

        if entry.is_symlink():
            findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_DIR, tx_id))
            continue

        if not entry.is_dir():
            findings.append(RecoveryFinding(RecoveryFindingCode.UNEXPECTED_FILE, tx_id))
            continue

        try:
            validate_recovery_transaction_id(tx_id)
        except RecoveryValidationError:
            findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_DIR_NAME, tx_id))
            continue

        try:
            _check_symlink_containment(entry, recovery_root)
        except RecoveryCorruptStateError:
            findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_DIR, tx_id))
            continue

        journal_path = entry / "journal.json"
        if journal_path.is_symlink():
            findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_JOURNAL, tx_id))
            continue

        if not journal_path.is_file():
            findings.append(RecoveryFinding(RecoveryFindingCode.DIR_WITHOUT_JOURNAL, tx_id))
            continue

        try:
            _check_symlink_containment(journal_path, recovery_root)
        except RecoveryCorruptStateError:
            findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_JOURNAL, tx_id))
            continue

        try:
            _validate_transaction_layout(
                recovery_root=recovery_root,
                transaction_id=RecoveryTransactionId(tx_id),
            )
        except RecoveryCorruptStateError:
            findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_LAYOUT, tx_id))
            continue

        try:
            content = journal_path.read_bytes()
            journal = _deserialize_journal(content)
        except RecoveryUnknownSchemaError:
            findings.append(RecoveryFinding(RecoveryFindingCode.UNKNOWN_SCHEMA, tx_id))
            continue
        except RecoveryCorruptStateError:
            findings.append(RecoveryFinding(RecoveryFindingCode.CORRUPT_JSON, tx_id))
            continue
        except OSError:
            findings.append(RecoveryFinding(RecoveryFindingCode.CORRUPT_JSON, tx_id))
            continue

        if journal.transaction_id != tx_id:
            findings.append(RecoveryFinding(RecoveryFindingCode.TRANSACTION_ID_MISMATCH, tx_id))
            continue

        journals.append(journal)

    journals.sort(key=lambda j: str(j.transaction_id))
    findings.sort(key=lambda f: (f.code.value, f.transaction_name))
    return RecoveryDiscoveryResult(journals=tuple(journals), findings=tuple(findings))


def unresolved_recovery_journals(
    discovery: RecoveryDiscoveryResult,
) -> tuple[RecoveryJournal, ...]:
    if discovery.findings:
        raise RecoveryCorruptStateError("Ambiguous recovery state must block discovery")
    return tuple(j for j in discovery.journals if j.phase != RecoveryPhase.COMPLETE)


def remove_completed_recovery_transaction(
    *,
    recovery_root: Path,
    transaction_id: RecoveryTransactionId,
) -> None:
    validate_recovery_transaction_id(transaction_id)
    tx_dir = _validate_transaction_layout(
        recovery_root=recovery_root, transaction_id=transaction_id
    )
    journal = load_recovery_journal(recovery_root=recovery_root, transaction_id=transaction_id)
    if journal.phase != RecoveryPhase.COMPLETE:
        raise RecoveryValidationError("Cannot remove incomplete transaction")

    import shutil

    try:
        shutil.rmtree(tx_dir)
    except OSError as e:
        raise RecoveryUnavailableError("Failed to remove transaction") from e


@dataclass(frozen=True, slots=True)
class RecoveryLock:
    path: Path


_held_locks_lock = threading.Lock()
_held_locks: set[Path] = set()


@contextmanager
def acquire_recovery_lock(
    *,
    runtime_dir: Path,
) -> Iterator[RecoveryLock]:
    lock_path = runtime_dir / "recovery.lock"

    if lock_path.is_symlink():
        raise RecoveryLockUnavailableError("Symlinked lock file not permitted")

    abs_lock_path = lock_path.resolve() if lock_path.exists() else lock_path.absolute()

    with _held_locks_lock:
        if abs_lock_path in _held_locks:
            raise RecoveryLockUnavailableError("Lock already acquired")
        _held_locks.add(abs_lock_path)

    fd = None
    try:
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True)
            flags = (
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            )
            fd = os.open(lock_path, flags, 0o600)
        except OSError as e:
            raise RecoveryLockUnavailableError("Failed to open lock file") from e

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RecoveryLockUnavailableError("Lock acquired by another process") from e

        yield RecoveryLock(path=lock_path)
    finally:
        with _held_locks_lock:
            _held_locks.discard(abs_lock_path)
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def remove_rolled_back_recovery_transaction(
    *,
    recovery_root: Path,
    transaction_id: RecoveryTransactionId,
) -> None:
    validate_recovery_transaction_id(transaction_id)
    tx_dir = _validate_transaction_layout(
        recovery_root=recovery_root, transaction_id=transaction_id
    )
    journal = load_recovery_journal(recovery_root=recovery_root, transaction_id=transaction_id)
    if journal.phase == RecoveryPhase.COMPLETE:
        raise RecoveryValidationError("Cannot remove complete transaction")

    import shutil

    try:
        shutil.rmtree(tx_dir)
    except OSError as e:
        raise RecoveryUnavailableError("Failed to remove rolled-back transaction") from e
