"""Recoverable file-set transactions for canonical capture mutations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from lifeos._transaction_files import (
    BackupFile,
    DirectorySyncResult,
    DirectorySyncState,
    ParentDescriptor,
    StagingFile,
    TargetIdentity,
    TransactionError,
    capture_directory_binding,
    create_hardlink_backup,
    create_staging_file,
    fsync_directory,
    get_target_identity,
    publish_creation,
    publish_replacement,
    remove_verified_target,
    rollback_creation,
    rollback_replacement,
)
from lifeos.proposals.recovery import RecoveryError, RecoveryLockUnavailableError
from lifeos.proposals.recovery_store import PinnedRecoveryStore, acquire_pinned_recovery_store
from lifeos.vault import VaultAccessError, validate_vault_relative_path

_SCHEMA_VERSION = 1
_MAX_JOURNAL_BYTES = 1024 * 1024
_IDEMPOTENCY_KEY_RE = re.compile(r"^[a-z0-9._-]{1,128}$")
_TRANSACTION_ID_RE = re.compile(r"^ctx-[a-f0-9]{32}$")
_HEX_32_RE = re.compile(r"^[a-f0-9]{32}$")
_HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")
_PHASES = frozenset({"preparing", "prepared", "committed"})
_OPERATIONS = frozenset({"merge", "split"})
_DIR_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


class CaptureTransactionError(RuntimeError):
    def __init__(self, code: str, message: str, data: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


@dataclass(frozen=True, slots=True)
class CaptureFileWrite:
    path: str
    content: bytes
    expected_hash: str | None = None


@dataclass(frozen=True, slots=True)
class CaptureTransactionReceipt:
    operation: Literal["merge", "split"]
    idempotency_key_hash: str
    request_fingerprint: str
    result_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _JournalIdentity:
    dev: int
    ino: int
    mode: int
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class _JournalOperation:
    path: str
    kind: Literal["create", "replace"]
    candidate_hash: str
    candidate_size: int
    intended_mode: int
    parent_dev: int
    parent_ino: int
    artifact_token: str
    original: _JournalIdentity | None

    @property
    def target_name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def parent_path(self) -> str:
        return PurePosixPath(self.path).parent.as_posix()

    @property
    def staging_name(self) -> str:
        return f".{self.target_name}.{self.artifact_token}.staged"

    @property
    def backup_name(self) -> str:
        return f".{self.target_name}.{self.artifact_token}.backup"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "candidate_hash": self.candidate_hash,
            "candidate_size": self.candidate_size,
            "intended_mode": self.intended_mode,
            "parent_dev": self.parent_dev,
            "parent_ino": self.parent_ino,
            "artifact_token": self.artifact_token,
            "original": None if self.original is None else self.original.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _CaptureTransactionJournal:
    transaction_id: str
    intent_hash: str
    phase: Literal["preparing", "prepared", "committed"]
    operation: Literal["merge", "split"]
    idempotency_key_hash: str
    request_fingerprint: str
    result_paths: tuple[str, ...]
    vault_dev: int
    vault_ino: int
    operations: tuple[_JournalOperation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "transaction_id": self.transaction_id,
            "intent_hash": self.intent_hash,
            "phase": self.phase,
            "operation": self.operation,
            "idempotency_key_hash": self.idempotency_key_hash,
            "request_fingerprint": self.request_fingerprint,
            "result_paths": list(self.result_paths),
            "vault_dev": self.vault_dev,
            "vault_ino": self.vault_ino,
            "operations": [item.to_dict() for item in self.operations],
        }

    def receipt(self) -> CaptureTransactionReceipt:
        return CaptureTransactionReceipt(
            self.operation,
            self.idempotency_key_hash,
            self.request_fingerprint,
            self.result_paths,
        )


@dataclass(slots=True)
class _PreparedOperation:
    journal: _JournalOperation
    parent: ParentDescriptor
    content: bytes
    staging: StagingFile | None = None
    backup: BackupFile | None = None


def _capture_transaction_checkpoint(_name: str) -> None:
    """Deterministic fault-injection seam for interruption and rollback tests."""


def _validate_prefixed_hash(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or _HEX_64_RE.fullmatch(value.removeprefix("sha256:")) is None
    ):
        raise CaptureTransactionError("invalid_transaction", f"{field} must be a SHA-256 hash.")
    return value


def _validate_capture_path(value: object, field: str = "path") -> str:
    if type(value) is not str:
        raise CaptureTransactionError("invalid_transaction", f"{field} must be a string.")
    try:
        validate_vault_relative_path(value)
    except VaultAccessError as error:
        raise CaptureTransactionError(
            "invalid_transaction", f"{field} is not vault-relative."
        ) from error
    parts = PurePosixPath(value).parts
    if len(parts) != 3 or parts[0] != "captures" or not value.casefold().endswith(".md"):
        raise CaptureTransactionError(
            "invalid_transaction", f"{field} must select captures/<year>/<capture>.md."
        )
    return value


def _validate_operation(value: object) -> Literal["merge", "split"]:
    if type(value) is not str or value not in _OPERATIONS:
        raise CaptureTransactionError("invalid_transaction", "Capture transaction type is invalid.")
    return value  # type: ignore[return-value]


def validate_idempotency_key(value: object) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY_RE.fullmatch(value) is None:
        raise CaptureTransactionError(
            "invalid_idempotency_key",
            "Idempotency key must use 1-128 lowercase letters, digits, dot, underscore, or hyphen.",
        )
    return value


def idempotency_key_hash(value: str) -> str:
    return hashlib.sha256(validate_idempotency_key(value).encode("utf-8")).hexdigest()


def _serialize_json(value: dict[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _operation_intent(operation: _JournalOperation) -> dict[str, object]:
    """Return the immutable operation fields bound by the transaction intent."""

    return {
        "path": operation.path,
        "kind": operation.kind,
        "candidate_hash": operation.candidate_hash,
        "candidate_size": operation.candidate_size,
        "intended_mode": operation.intended_mode,
        "parent_dev": operation.parent_dev,
        "parent_ino": operation.parent_ino,
        "original": None if operation.original is None else operation.original.to_dict(),
    }


def _intent_hash(
    *,
    operation: Literal["merge", "split"],
    idempotency_key_hash: str,
    request_fingerprint: str,
    result_paths: tuple[str, ...],
    vault_dev: int,
    vault_ino: int,
    operations: tuple[_JournalOperation, ...],
) -> str:
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "operation": operation,
        "idempotency_key_hash": idempotency_key_hash,
        "request_fingerprint": request_fingerprint,
        "result_paths": list(result_paths),
        "vault_dev": vault_dev,
        "vault_ino": vault_ino,
        "operations": [_operation_intent(item) for item in operations],
    }
    return hashlib.sha256(_serialize_json(payload)).hexdigest()


def _artifact_token(intent_hash: str, index: int, path: str) -> str:
    return hashlib.sha256(
        f"capture-transaction-artifact-v1\0{intent_hash}\0{index}\0{path}".encode()
    ).hexdigest()[:32]


def _finalize_journal(
    *,
    phase: Literal["preparing", "prepared", "committed"],
    operation: Literal["merge", "split"],
    idempotency_key_hash: str,
    request_fingerprint: str,
    result_paths: tuple[str, ...],
    vault_dev: int,
    vault_ino: int,
    prepared: list[_PreparedOperation],
) -> _CaptureTransactionJournal:
    raw_operations = tuple(item.journal for item in prepared)
    digest = _intent_hash(
        operation=operation,
        idempotency_key_hash=idempotency_key_hash,
        request_fingerprint=request_fingerprint,
        result_paths=result_paths,
        vault_dev=vault_dev,
        vault_ino=vault_ino,
        operations=raw_operations,
    )
    operations = tuple(
        replace(item, artifact_token=_artifact_token(digest, index, item.path))
        for index, item in enumerate(raw_operations)
    )
    for prepared_item, journal_operation in zip(prepared, operations, strict=True):
        prepared_item.journal = journal_operation
    return _CaptureTransactionJournal(
        transaction_id=f"ctx-{digest[:32]}",
        intent_hash=digest,
        phase=phase,
        operation=operation,
        idempotency_key_hash=idempotency_key_hash,
        request_fingerprint=request_fingerprint,
        result_paths=result_paths,
        vault_dev=vault_dev,
        vault_ino=vault_ino,
        operations=operations,
    )


def _read_regular_at(parent_fd: int, name: str, *, max_bytes: int) -> bytes:
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction state could not be opened."
        ) from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise CaptureTransactionError(
                "recovery_required", "Capture transaction state is not a regular file."
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise CaptureTransactionError(
                    "recovery_required", "Capture transaction state exceeds its size limit."
                )
            chunks.append(chunk)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise CaptureTransactionError(
                "recovery_required", "Capture transaction state changed while it was read."
            )
        return b"".join(chunks)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction state could not be read."
        ) from error
    finally:
        os.close(fd)


def _write_new_at(parent_fd: int, name: str, content: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    fd: int | None = None
    created = False
    try:
        fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
        created = True
        try:
            offset = 0
            while offset < len(content):
                written = os.write(fd, content[offset:])
                if written == 0:
                    raise OSError("write returned zero bytes")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
            fd = None
    except OSError as error:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if created:
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                pass
        raise CaptureTransactionError(
            "storage_write_failure", "Capture transaction state could not be written."
        ) from error


def _replace_file_at(parent_fd: int, name: str, content: bytes) -> None:
    temporary = f".{name}.next"
    _write_new_at(parent_fd, temporary, content)
    try:
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as error:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except OSError:
            pass
        raise CaptureTransactionError(
            "storage_write_failure", "Capture transaction state could not be committed."
        ) from error


def _open_directory_at(parent_fd: int, name: str) -> int:
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction directory could not be opened."
        ) from error
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise CaptureTransactionError(
                "recovery_required", "Capture transaction entry is not a directory."
            )
    except Exception:
        os.close(fd)
        raise
    return fd


def _open_or_create_directory_at(parent_fd: int, name: str) -> int:
    try:
        return _open_directory_at(parent_fd, name)
    except CaptureTransactionError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        except OSError as error:
            raise CaptureTransactionError(
                "storage_write_failure", "Capture transaction directory could not be created."
            ) from error
        return _open_directory_at(parent_fd, name)


def _identity_from_dict(value: object) -> _JournalIdentity:
    if type(value) is not dict or set(value) != {"dev", "ino", "mode", "content_hash"}:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction identity is invalid."
        )
    dev = value["dev"]
    ino = value["ino"]
    mode = value["mode"]
    digest = value["content_hash"]
    if (
        type(dev) is not int
        or dev < 0
        or type(ino) is not int
        or ino < 1
        or type(mode) is not int
        or mode < 0
        or type(digest) is not str
        or _HEX_64_RE.fullmatch(digest) is None
    ):
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction identity is invalid."
        )
    return _JournalIdentity(dev, ino, mode, digest)


def _operation_from_dict(value: object) -> _JournalOperation:
    expected_keys = {
        "path",
        "kind",
        "candidate_hash",
        "candidate_size",
        "intended_mode",
        "parent_dev",
        "parent_ino",
        "artifact_token",
        "original",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction operation is invalid."
        )
    path = _validate_capture_path(value["path"])
    kind = value["kind"]
    candidate_hash = value["candidate_hash"]
    candidate_size = value["candidate_size"]
    intended_mode = value["intended_mode"]
    parent_dev = value["parent_dev"]
    parent_ino = value["parent_ino"]
    token = value["artifact_token"]
    if type(kind) is not str or kind not in {"create", "replace"}:
        raise CaptureTransactionError("recovery_required", "Capture transaction kind is invalid.")
    selected_kind = cast(Literal["create", "replace"], kind)
    if type(candidate_hash) is not str or _HEX_64_RE.fullmatch(candidate_hash) is None:
        raise CaptureTransactionError("recovery_required", "Capture candidate hash is invalid.")
    if type(candidate_size) is not int or candidate_size < 0:
        raise CaptureTransactionError("recovery_required", "Capture candidate size is invalid.")
    if type(intended_mode) is not int or intended_mode < 0:
        raise CaptureTransactionError("recovery_required", "Capture candidate mode is invalid.")
    if (
        type(parent_dev) is not int
        or parent_dev < 0
        or type(parent_ino) is not int
        or parent_ino < 1
    ):
        raise CaptureTransactionError("recovery_required", "Capture parent identity is invalid.")
    if type(token) is not str or _HEX_32_RE.fullmatch(token) is None:
        raise CaptureTransactionError("recovery_required", "Capture artifact token is invalid.")
    original = None if value["original"] is None else _identity_from_dict(value["original"])
    if (kind == "create") != (original is None):
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction pre-state is invalid."
        )
    return _JournalOperation(
        path,
        selected_kind,
        candidate_hash,
        candidate_size,
        intended_mode,
        parent_dev,
        parent_ino,
        token,
        original,
    )


def _journal_from_bytes(content: bytes) -> _CaptureTransactionJournal:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction journal is corrupt."
        ) from error
    expected_keys = {
        "schema_version",
        "transaction_id",
        "intent_hash",
        "phase",
        "operation",
        "idempotency_key_hash",
        "request_fingerprint",
        "result_paths",
        "vault_dev",
        "vault_ino",
        "operations",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction journal is invalid."
        )
    if value["schema_version"] != _SCHEMA_VERSION or type(value["schema_version"]) is not int:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction schema is unsupported."
        )
    tx_id = value["transaction_id"]
    intent_hash = value["intent_hash"]
    phase = value["phase"]
    operation = _validate_operation(value["operation"])
    key_hash = value["idempotency_key_hash"]
    fingerprint = _validate_prefixed_hash(value["request_fingerprint"], "request_fingerprint")
    result_paths = value["result_paths"]
    vault_dev = value["vault_dev"]
    vault_ino = value["vault_ino"]
    raw_operations = value["operations"]
    if type(tx_id) is not str or _TRANSACTION_ID_RE.fullmatch(tx_id) is None:
        raise CaptureTransactionError("recovery_required", "Capture transaction ID is invalid.")
    if type(intent_hash) is not str or _HEX_64_RE.fullmatch(intent_hash) is None:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction intent digest is invalid."
        )
    if type(phase) is not str or phase not in _PHASES:
        raise CaptureTransactionError("recovery_required", "Capture transaction phase is invalid.")
    selected_phase = cast(Literal["preparing", "prepared", "committed"], phase)
    if type(key_hash) is not str or _HEX_64_RE.fullmatch(key_hash) is None:
        raise CaptureTransactionError("recovery_required", "Capture idempotency digest is invalid.")
    if type(result_paths) is not list or not result_paths:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction results are invalid."
        )
    normalized_results = tuple(_validate_capture_path(item, "result_path") for item in result_paths)
    if len(normalized_results) != len(set(normalized_results)):
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction results are duplicated."
        )
    if type(vault_dev) is not int or vault_dev < 0 or type(vault_ino) is not int or vault_ino < 1:
        raise CaptureTransactionError("recovery_required", "Capture vault identity is invalid.")
    if type(raw_operations) is not list or not raw_operations:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction operations are invalid."
        )
    operations = tuple(_operation_from_dict(item) for item in raw_operations)
    paths = tuple(item.path for item in operations)
    if len(paths) != len(set(paths)):
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction paths are duplicated."
        )
    created = {item.path for item in operations if item.kind == "create"}
    replaced = tuple(item.path for item in operations if item.kind == "replace")
    if set(normalized_results) != created:
        raise CaptureTransactionError(
            "recovery_required", "Capture results are not created targets."
        )
    if operation == "merge" and (len(normalized_results) != 1 or len(replaced) < 2):
        raise CaptureTransactionError("recovery_required", "Capture merge plan is incomplete.")
    if operation == "split" and (len(normalized_results) < 2 or len(replaced) != 1):
        raise CaptureTransactionError("recovery_required", "Capture split plan is incomplete.")
    journal = _CaptureTransactionJournal(
        tx_id,
        intent_hash,
        selected_phase,
        operation,
        key_hash,
        fingerprint,
        normalized_results,
        vault_dev,
        vault_ino,
        operations,
    )
    expected_intent = _intent_hash(
        operation=journal.operation,
        idempotency_key_hash=journal.idempotency_key_hash,
        request_fingerprint=journal.request_fingerprint,
        result_paths=journal.result_paths,
        vault_dev=journal.vault_dev,
        vault_ino=journal.vault_ino,
        operations=journal.operations,
    )
    expected_tokens = tuple(
        _artifact_token(expected_intent, index, item.path)
        for index, item in enumerate(journal.operations)
    )
    if (
        journal.intent_hash != expected_intent
        or journal.transaction_id != f"ctx-{expected_intent[:32]}"
        or tuple(item.artifact_token for item in journal.operations) != expected_tokens
    ):
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction intent binding is invalid."
        )
    return journal


def _receipt_from_bytes(content: bytes) -> CaptureTransactionReceipt:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture idempotency state is corrupt."
        ) from error
    if type(value) is not dict or set(value) != {
        "schema_version",
        "operation",
        "idempotency_key_hash",
        "request_fingerprint",
        "result_paths",
    }:
        raise CaptureTransactionError("recovery_required", "Capture idempotency state is invalid.")
    if value["schema_version"] != _SCHEMA_VERSION or type(value["schema_version"]) is not int:
        raise CaptureTransactionError(
            "recovery_required", "Capture idempotency schema is unsupported."
        )
    operation = _validate_operation(value["operation"])
    key_hash = value["idempotency_key_hash"]
    fingerprint = _validate_prefixed_hash(value["request_fingerprint"], "request_fingerprint")
    paths = value["result_paths"]
    if type(key_hash) is not str or _HEX_64_RE.fullmatch(key_hash) is None:
        raise CaptureTransactionError("recovery_required", "Capture idempotency digest is invalid.")
    if type(paths) is not list or not paths:
        raise CaptureTransactionError(
            "recovery_required", "Capture idempotency results are invalid."
        )
    result_paths = tuple(_validate_capture_path(item, "result_path") for item in paths)
    if len(result_paths) != len(set(result_paths)):
        raise CaptureTransactionError(
            "recovery_required", "Capture idempotency results are duplicated."
        )
    return CaptureTransactionReceipt(operation, key_hash, fingerprint, result_paths)


def _receipt_bytes(receipt: CaptureTransactionReceipt) -> bytes:
    return _serialize_json(
        {
            "schema_version": _SCHEMA_VERSION,
            "operation": receipt.operation,
            "idempotency_key_hash": receipt.idempotency_key_hash,
            "request_fingerprint": receipt.request_fingerprint,
            "result_paths": list(receipt.result_paths),
        }
    )


def _load_receipt(store: PinnedRecoveryStore, key_hash: str) -> CaptureTransactionReceipt | None:
    results_fd = _open_or_create_directory_at(store.runtime_fd, "results")
    try:
        name = f"{key_hash}.json"
        try:
            os.stat(name, dir_fd=results_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise CaptureTransactionError(
                "recovery_required", "Capture idempotency state could not be inspected."
            ) from error
        receipt = _receipt_from_bytes(
            _read_regular_at(results_fd, name, max_bytes=_MAX_JOURNAL_BYTES)
        )
        if receipt.idempotency_key_hash != key_hash:
            raise CaptureTransactionError(
                "recovery_required",
                "Capture idempotency state does not match its storage key.",
            )
        return receipt
    finally:
        os.close(results_fd)


def _write_receipt(store: PinnedRecoveryStore, receipt: CaptureTransactionReceipt) -> None:
    results_fd = _open_or_create_directory_at(store.runtime_fd, "results")
    try:
        name = f"{receipt.idempotency_key_hash}.json"
        existing: CaptureTransactionReceipt | None = None
        try:
            os.stat(name, dir_fd=results_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            try:
                existing = _receipt_from_bytes(
                    _read_regular_at(results_fd, name, max_bytes=_MAX_JOURNAL_BYTES)
                )
            except CaptureTransactionError as error:
                raise CaptureTransactionError(
                    "recovery_required", "Capture idempotency state is invalid."
                ) from error
            if existing.idempotency_key_hash != receipt.idempotency_key_hash:
                raise CaptureTransactionError(
                    "recovery_required",
                    "Capture idempotency state does not match its storage key.",
                )
        if existing is not None:
            if existing != receipt:
                raise CaptureTransactionError(
                    "recovery_required",
                    "Capture idempotency state conflicts with a proven canonical transaction.",
                )
            return
        _write_new_at(results_fd, name, _receipt_bytes(receipt))
        os.fsync(results_fd)
    finally:
        os.close(results_fd)


def _write_journal(tx_fd: int, journal: _CaptureTransactionJournal, *, create: bool) -> None:
    content = _serialize_json(journal.to_dict())
    if create:
        _write_new_at(tx_fd, "journal.json", content)
        os.fsync(tx_fd)
    else:
        _replace_file_at(tx_fd, "journal.json", content)


def _initialize_journal(store: PinnedRecoveryStore, journal: _CaptureTransactionJournal) -> int:
    try:
        os.mkdir(journal.transaction_id, 0o700, dir_fd=store.recovery_fd)
        os.fsync(store.recovery_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "storage_write_failure", "Capture transaction could not be initialized."
        ) from error
    tx_fd = _open_directory_at(store.recovery_fd, journal.transaction_id)
    try:
        _write_journal(tx_fd, journal, create=True)
    except Exception:
        os.close(tx_fd)
        try:
            os.rmdir(journal.transaction_id, dir_fd=store.recovery_fd)
            os.fsync(store.recovery_fd)
        except OSError:
            pass
        raise
    return tx_fd


def _discard_unpublished_journal(tx_fd: int) -> None:
    temporary = ".journal.json.next"
    try:
        observed = os.stat(temporary, dir_fd=tx_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction journal staging could not be inspected."
        ) from error
    if not stat.S_ISREG(observed.st_mode) or observed.st_size > _MAX_JOURNAL_BYTES:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction journal staging is invalid."
        )
    try:
        os.unlink(temporary, dir_fd=tx_fd)
        os.fsync(tx_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction journal staging could not be removed."
        ) from error


def _load_journal(tx_fd: int, expected_name: str) -> _CaptureTransactionJournal:
    _discard_unpublished_journal(tx_fd)
    try:
        names = os.listdir(tx_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction directory could not be listed."
        ) from error
    if names != ["journal.json"]:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction directory has an unexpected layout."
        )
    journal = _journal_from_bytes(
        _read_regular_at(tx_fd, "journal.json", max_bytes=_MAX_JOURNAL_BYTES)
    )
    if journal.transaction_id != expected_name:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction ID does not match its directory."
        )
    return journal


def _remove_journal(store: PinnedRecoveryStore, journal: _CaptureTransactionJournal) -> None:
    tx_fd = _open_directory_at(store.recovery_fd, journal.transaction_id)
    try:
        _discard_unpublished_journal(tx_fd)
        if os.listdir(tx_fd) != ["journal.json"]:
            raise CaptureTransactionError(
                "recovery_required", "Capture transaction cleanup found an unexpected layout."
            )
        os.unlink("journal.json", dir_fd=tx_fd)
        os.fsync(tx_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction journal could not be removed."
        ) from error
    finally:
        os.close(tx_fd)
    try:
        os.rmdir(journal.transaction_id, dir_fd=store.recovery_fd)
        os.fsync(store.recovery_fd)
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction directory could not be removed."
        ) from error


def _open_parent(root_fd: int, relative_path: str, *, create: bool) -> ParentDescriptor:
    current_fd = os.dup(root_fd)
    try:
        for component in PurePosixPath(relative_path).parts:
            try:
                next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise CaptureTransactionError(
                        "stale_capture", "A capture parent directory is missing."
                    )
                try:
                    os.mkdir(component, 0o755, dir_fd=current_fd)
                    sync = fsync_directory(current_fd)
                    if sync.state == DirectorySyncState.FAILED:
                        raise CaptureTransactionError(
                            "storage_write_failure",
                            "A capture parent directory could not be synced.",
                        )
                except FileExistsError:
                    pass
                next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
            except OSError as error:
                raise CaptureTransactionError(
                    "unsafe_path", "A capture parent directory could not be opened safely."
                ) from error
            os.close(current_fd)
            current_fd = next_fd
        observed = os.fstat(current_fd)
        return ParentDescriptor(
            current_fd,
            observed.st_dev,
            observed.st_ino,
            relative_path,
            authority_fd=root_fd,
        )
    except Exception:
        os.close(current_fd)
        raise


def _open_journal_parents(
    root_fd: int, journal: _CaptureTransactionJournal
) -> dict[str, ParentDescriptor]:
    root = os.fstat(root_fd)
    if (root.st_dev, root.st_ino) != (journal.vault_dev, journal.vault_ino):
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction belongs to a different vault identity."
        )
    parents: dict[str, ParentDescriptor] = {}
    try:
        for operation in journal.operations:
            if operation.parent_path in parents:
                continue
            parent = _open_parent(root_fd, operation.parent_path, create=False)
            if (parent.dev, parent.ino) != (operation.parent_dev, operation.parent_ino):
                os.close(parent.fd)
                raise CaptureTransactionError(
                    "recovery_required", "A capture transaction parent directory changed."
                )
            parents[operation.parent_path] = parent
        return parents
    except Exception:
        _close_parents(parents)
        raise


def _close_parents(parents: dict[str, ParentDescriptor]) -> None:
    for parent in parents.values():
        try:
            os.close(parent.fd)
        except OSError:
            pass


def _target_identity(identity: _JournalIdentity) -> TargetIdentity:
    return TargetIdentity(identity.dev, identity.ino, identity.mode, identity.content_hash)


def _staging_for(operation: _JournalOperation, parent: ParentDescriptor) -> StagingFile:
    return StagingFile(
        operation.staging_name,
        parent,
        operation.candidate_hash,
        operation.candidate_size,
        operation.intended_mode,
        capture_directory_binding(parent.fd),
    )


def _backup_for(operation: _JournalOperation, parent: ParentDescriptor) -> BackupFile:
    assert operation.original is not None
    return BackupFile(
        operation.backup_name,
        parent,
        _target_identity(operation.original),
        DirectorySyncResult(DirectorySyncState.CONFIRMED, None),
    )


def _same_identity(first: TargetIdentity | None, second: TargetIdentity | None) -> bool:
    return bool(
        first is not None
        and second is not None
        and first.dev == second.dev
        and first.ino == second.ino
        and stat.S_IMODE(first.mode) == stat.S_IMODE(second.mode)
        and first.content_hash == second.content_hash
    )


def _candidate_proof(
    operation: _JournalOperation, parent: ParentDescriptor
) -> TargetIdentity | None:
    identity = get_target_identity(operation.staging_name, parent)
    if identity is None:
        return None
    if identity.content_hash != operation.candidate_hash or stat.S_IMODE(
        identity.mode
    ) != stat.S_IMODE(operation.intended_mode):
        raise CaptureTransactionError(
            "recovery_required", "A capture transaction staging artifact changed."
        )
    return identity


def _verify_backup(operation: _JournalOperation, parent: ParentDescriptor) -> None:
    if operation.original is None:
        if get_target_identity(operation.backup_name, parent) is not None:
            raise CaptureTransactionError(
                "recovery_required", "An unexpected capture transaction backup exists."
            )
        return
    observed = get_target_identity(operation.backup_name, parent)
    if not _same_identity(observed, _target_identity(operation.original)):
        raise CaptureTransactionError(
            "recovery_required", "A capture transaction backup is missing or changed."
        )


def _verify_artifact_layout(operation: _JournalOperation, parent: ParentDescriptor) -> None:
    allowed = {operation.staging_name}
    if operation.original is not None:
        allowed.add(operation.backup_name)
    prefix = f".{operation.target_name}."
    try:
        unexpected = sorted(
            name
            for name in os.listdir(parent.fd)
            if name.startswith(prefix) and name not in allowed
        )
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction artifacts could not be inspected."
        ) from error
    if unexpected:
        raise CaptureTransactionError(
            "recovery_required",
            "Unexpected capture mutation artifacts require manual recovery.",
            {"path": operation.path, "artifacts": unexpected},
        )


def _verify_artifacts_removed(operation: _JournalOperation, parent: ParentDescriptor) -> None:
    prefix = f".{operation.target_name}."
    try:
        remaining = sorted(name for name in os.listdir(parent.fd) if name.startswith(prefix))
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction cleanup could not be inspected."
        ) from error
    if remaining:
        raise CaptureTransactionError(
            "recovery_required",
            "Capture transaction cleanup left reserved artifacts.",
            {"path": operation.path, "artifacts": remaining},
        )


def _target_state(
    operation: _JournalOperation, parent: ParentDescriptor
) -> Literal["original", "candidate", "foreign"]:
    _verify_artifact_layout(operation, parent)
    target = get_target_identity(operation.target_name, parent)
    if operation.original is None:
        if target is None:
            return "original"
    elif _same_identity(target, _target_identity(operation.original)):
        return "original"
    proof = _candidate_proof(operation, parent)
    if _same_identity(target, proof):
        return "candidate"
    return "foreign"


def _remove_artifact(
    name: str,
    parent: ParentDescriptor,
    *,
    expected: TargetIdentity | None,
    label: str,
) -> None:
    observed = get_target_identity(name, parent)
    if observed is None:
        return
    if expected is None or not _same_identity(observed, expected):
        raise CaptureTransactionError(
            "recovery_required", f"A capture transaction {label} changed before cleanup."
        )
    result = remove_verified_target(name, parent, observed)
    if result.state == DirectorySyncState.FAILED:
        raise CaptureTransactionError(
            "recovery_required", f"A capture transaction {label} cleanup could not be synced."
        )


def _cleanup_artifacts(operation: _JournalOperation, parent: ParentDescriptor) -> None:
    proof = _candidate_proof(operation, parent)
    _remove_artifact(operation.staging_name, parent, expected=proof, label="staging artifact")
    if operation.original is not None:
        _remove_artifact(
            operation.backup_name,
            parent,
            expected=_target_identity(operation.original),
            label="backup",
        )


def _verify_committed_backup(operation: _JournalOperation, parent: ParentDescriptor) -> None:
    observed = get_target_identity(operation.backup_name, parent)
    if operation.original is None:
        if observed is not None:
            raise CaptureTransactionError(
                "recovery_required", "An unexpected capture transaction backup exists."
            )
        return
    if observed is not None and not _same_identity(observed, _target_identity(operation.original)):
        raise CaptureTransactionError(
            "recovery_required", "A capture transaction backup changed during cleanup."
        )


def _rollback_prepared(
    journal: _CaptureTransactionJournal, parents: dict[str, ParentDescriptor]
) -> None:
    foreign_paths: list[str] = []
    for operation in reversed(journal.operations):
        parent = parents[operation.parent_path]
        state = _target_state(operation, parent)
        if state == "foreign":
            foreign_paths.append(operation.path)
            continue
        if state == "candidate":
            staging = _staging_for(operation, parent)
            try:
                if operation.original is None:
                    result = rollback_creation(operation.target_name, staging)
                else:
                    _verify_backup(operation, parent)
                    result = rollback_replacement(
                        operation.target_name, staging, _backup_for(operation, parent)
                    )
            except (OSError, TransactionError) as error:
                raise CaptureTransactionError(
                    "recovery_required", "A capture transaction could not be rolled back safely."
                ) from error
            if result.state == DirectorySyncState.FAILED:
                raise CaptureTransactionError(
                    "recovery_required", "Capture rollback durability could not be confirmed."
                )
    if foreign_paths:
        raise CaptureTransactionError(
            "recovery_required",
            "A capture changed during transaction recovery; canonical edits were preserved.",
            {"paths": sorted(foreign_paths)},
        )
    for operation in journal.operations:
        _cleanup_artifacts(operation, parents[operation.parent_path])
    for operation in journal.operations:
        _verify_artifacts_removed(operation, parents[operation.parent_path])


def _cleanup_committed(
    journal: _CaptureTransactionJournal, parents: dict[str, ParentDescriptor]
) -> None:
    for operation in journal.operations:
        if operation.original is not None:
            _remove_artifact(
                operation.backup_name,
                parents[operation.parent_path],
                expected=_target_identity(operation.original),
                label="backup",
            )
    for operation in journal.operations:
        parent = parents[operation.parent_path]
        proof = _candidate_proof(operation, parent)
        _remove_artifact(
            operation.staging_name,
            parent,
            expected=proof,
            label="staging artifact",
        )
    for operation in journal.operations:
        _verify_artifacts_removed(operation, parents[operation.parent_path])


def _verify_committed(
    journal: _CaptureTransactionJournal, parents: dict[str, ParentDescriptor]
) -> None:
    incomplete: list[str] = []
    for operation in journal.operations:
        parent = parents[operation.parent_path]
        if _target_state(operation, parent) != "candidate":
            incomplete.append(operation.path)
            continue
    if incomplete:
        raise CaptureTransactionError(
            "recovery_required",
            "A committed capture transaction does not have every planned canonical candidate.",
            {"paths": sorted(incomplete)},
        )
    for operation in journal.operations:
        parent = parents[operation.parent_path]
        if journal.phase == "committed":
            _verify_committed_backup(operation, parent)
        else:
            _verify_backup(operation, parent)


def _recover_one_locked(
    store: PinnedRecoveryStore,
    root_fd: int,
    journal: _CaptureTransactionJournal,
) -> CaptureTransactionReceipt | None:
    parents = _open_journal_parents(root_fd, journal)
    try:
        if journal.phase == "committed":
            _verify_committed(journal, parents)
            receipt = journal.receipt()
            _write_receipt(store, receipt)
            _cleanup_committed(journal, parents)
            _remove_journal(store, journal)
            return receipt
        _rollback_prepared(journal, parents)
        _remove_journal(store, journal)
        return None
    finally:
        _close_parents(parents)


def _recover_all_locked(
    store: PinnedRecoveryStore, root_fd: int
) -> tuple[CaptureTransactionReceipt, ...]:
    try:
        names = sorted(os.listdir(store.recovery_fd))
    except OSError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction recovery state could not be listed."
        ) from error
    receipts: list[CaptureTransactionReceipt] = []
    for name in names:
        if _TRANSACTION_ID_RE.fullmatch(name) is None:
            raise CaptureTransactionError(
                "recovery_required", "Capture transaction recovery contains an unexpected entry."
            )
        tx_fd = _open_directory_at(store.recovery_fd, name)
        try:
            journal = _load_journal(tx_fd, name)
        finally:
            os.close(tx_fd)
        receipt = _recover_one_locked(store, root_fd, journal)
        if receipt is not None:
            receipts.append(receipt)
    return tuple(receipts)


def _recover_all_required(
    store: PinnedRecoveryStore, root_fd: int
) -> tuple[CaptureTransactionReceipt, ...]:
    try:
        return _recover_all_locked(store, root_fd)
    except CaptureTransactionError as error:
        if error.code == "recovery_required":
            raise
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction recovery state is invalid."
        ) from error


def _build_prepared_operations(
    root_fd: int, writes: tuple[CaptureFileWrite, ...]
) -> tuple[list[_PreparedOperation], dict[str, ParentDescriptor]]:
    if not writes:
        raise CaptureTransactionError("invalid_transaction", "Capture transaction has no writes.")
    paths = tuple(_validate_capture_path(item.path) for item in writes)
    if len(paths) != len(set(paths)):
        raise CaptureTransactionError(
            "invalid_transaction", "Capture transaction paths are duplicated."
        )
    parents: dict[str, ParentDescriptor] = {}
    prepared: list[_PreparedOperation] = []
    try:
        for index, write in enumerate(writes):
            if type(write.content) is not bytes:
                raise CaptureTransactionError(
                    "invalid_transaction", "Capture transaction content must be bytes."
                )
            path = paths[index]
            parent_path = PurePosixPath(path).parent.as_posix()
            if parent_path not in parents:
                parents[parent_path] = _open_parent(
                    root_fd,
                    parent_path,
                    create=write.expected_hash is None,
                )
            parent = parents[parent_path]
            target_name = PurePosixPath(path).name
            original = get_target_identity(target_name, parent)
            if write.expected_hash is None:
                if original is not None:
                    raise CaptureTransactionError(
                        "target_conflict",
                        "A capture transaction creation target already exists.",
                        {"path": path},
                    )
                intended_mode = 0o644
                journal_original = None
                kind: Literal["create", "replace"] = "create"
            else:
                expected_hash = _validate_prefixed_hash(write.expected_hash, "expected_hash")
                if original is None or original.content_hash != expected_hash.removeprefix(
                    "sha256:"
                ):
                    raise CaptureTransactionError(
                        "stale_capture",
                        "A source capture changed before transaction preparation.",
                        {"path": path},
                    )
                intended_mode = stat.S_IMODE(original.mode)
                journal_original = _JournalIdentity(
                    original.dev,
                    original.ino,
                    original.mode,
                    original.content_hash,
                )
                kind = "replace"
            candidate_hash = hashlib.sha256(write.content).hexdigest()
            if original is not None and candidate_hash == original.content_hash:
                raise CaptureTransactionError(
                    "invalid_transaction",
                    "A capture replacement does not change its target.",
                    {"path": path},
                )
            journal_operation = _JournalOperation(
                path,
                kind,
                candidate_hash,
                len(write.content),
                intended_mode,
                parent.dev,
                parent.ino,
                "0" * 32,
                journal_original,
            )
            prepared.append(_PreparedOperation(journal_operation, parent, write.content))
        return prepared, parents
    except Exception:
        _close_parents(parents)
        raise


def _prepare_artifacts(prepared: list[_PreparedOperation]) -> None:
    for item in prepared:
        operation = item.journal
        item.staging = create_staging_file(
            operation.target_name,
            item.content,
            item.parent,
            operation.intended_mode,
            artifact_token=operation.artifact_token,
        )
        if operation.original is not None:
            item.backup = create_hardlink_backup(
                operation.target_name,
                item.parent,
                _target_identity(operation.original),
                artifact_token=operation.artifact_token,
            )


def _verify_unpublished(prepared: list[_PreparedOperation]) -> None:
    for item in prepared:
        operation = item.journal
        _verify_artifact_layout(operation, item.parent)
        current = get_target_identity(operation.target_name, item.parent)
        if operation.original is None:
            if current is not None:
                raise CaptureTransactionError(
                    "target_conflict",
                    "A capture creation target appeared before publication.",
                    {"path": operation.path},
                )
        elif not _same_identity(current, _target_identity(operation.original)):
            raise CaptureTransactionError(
                "stale_capture",
                "A source capture changed before publication.",
                {"path": operation.path},
            )
        proof = _candidate_proof(operation, item.parent)
        if proof is None:
            raise CaptureTransactionError(
                "storage_write_failure",
                "A capture staging artifact disappeared before publication.",
            )
        _verify_backup(operation, item.parent)


def _publish(prepared: list[_PreparedOperation]) -> None:
    for index, item in enumerate(prepared):
        assert item.staging is not None
        operation = item.journal
        try:
            if operation.original is None:
                result = publish_creation(
                    operation.target_name, item.staging, preserve_staging=True
                )
            else:
                result = publish_replacement(
                    operation.target_name,
                    item.staging,
                    _target_identity(operation.original),
                    preserve_staging=True,
                )
        except (OSError, TransactionError) as error:
            raise CaptureTransactionError(
                "transaction_failed", "Capture transaction publication failed."
            ) from error
        if result.state == DirectorySyncState.FAILED:
            raise CaptureTransactionError(
                "transaction_failed", "Capture transaction publication could not be synced."
            )
        _capture_transaction_checkpoint(f"after_publish:{index}")


def _abort_before_publication(
    store: PinnedRecoveryStore,
    journal: _CaptureTransactionJournal,
    prepared: list[_PreparedOperation],
) -> None:
    for item in prepared:
        _cleanup_artifacts(item.journal, item.parent)
    for item in prepared:
        _verify_artifacts_removed(item.journal, item.parent)
    _remove_journal(store, journal)


def _matching_receipt(
    existing: CaptureTransactionReceipt,
    *,
    idempotency_key_hash: str,
    operation: Literal["merge", "split"],
    request_fingerprint: str,
    result_paths: tuple[str, ...],
) -> CaptureTransactionReceipt:
    if existing.idempotency_key_hash != idempotency_key_hash:
        raise CaptureTransactionError(
            "recovery_required", "Capture idempotency state has the wrong storage key."
        )
    if existing.operation != operation or existing.request_fingerprint != request_fingerprint:
        raise CaptureTransactionError(
            "idempotency_conflict", "Idempotency key was reused for a different capture mutation."
        )
    if existing.result_paths != result_paths:
        raise CaptureTransactionError(
            "recovery_required", "Capture idempotency results do not match the canonical plan."
        )
    return existing


def execute_capture_transaction(
    *,
    vault_root: Path,
    runtime_dir: Path,
    operation: Literal["merge", "split"],
    idempotency_key: str,
    request_fingerprint: str,
    result_paths: tuple[str, ...],
    writes: tuple[CaptureFileWrite, ...],
) -> CaptureTransactionReceipt:
    selected_operation = _validate_operation(operation)
    key_hash = idempotency_key_hash(idempotency_key)
    fingerprint = _validate_prefixed_hash(request_fingerprint, "request_fingerprint")
    normalized_results = tuple(_validate_capture_path(item, "result_path") for item in result_paths)
    if not normalized_results or len(normalized_results) != len(set(normalized_results)):
        raise CaptureTransactionError("invalid_transaction", "Capture result paths are invalid.")
    if selected_operation == "merge" and len(normalized_results) != 1:
        raise CaptureTransactionError("invalid_transaction", "A merge must create one result.")
    if selected_operation == "split" and len(normalized_results) < 2:
        raise CaptureTransactionError("invalid_transaction", "A split must create two results.")
    try:
        with acquire_pinned_recovery_store(
            runtime_dir=runtime_dir / "capture-mutations",
            authority_root=vault_root,
        ) as store:
            root_fd = store.open_authority_root()
            try:
                _recover_all_required(store, root_fd)
                try:
                    existing = _load_receipt(store, key_hash)
                except CaptureTransactionError as error:
                    if error.code == "recovery_required":
                        raise
                    raise CaptureTransactionError(
                        "recovery_required", "Capture idempotency state is invalid."
                    ) from error
                if existing is not None:
                    raise CaptureTransactionError(
                        "recovery_required",
                        "Cached capture mutation state requires canonical lineage reconciliation.",
                    )

                prepared, parents = _build_prepared_operations(root_fd, writes)
                root_identity = os.fstat(root_fd)
                journal = _finalize_journal(
                    phase="preparing",
                    operation=selected_operation,
                    idempotency_key_hash=key_hash,
                    request_fingerprint=fingerprint,
                    result_paths=normalized_results,
                    vault_dev=root_identity.st_dev,
                    vault_ino=root_identity.st_ino,
                    prepared=prepared,
                )
                tx_fd: int | None = None
                publication_started = False
                try:
                    created_paths = {
                        item.journal.path for item in prepared if item.journal.kind == "create"
                    }
                    replacement_count = sum(item.journal.kind == "replace" for item in prepared)
                    if set(normalized_results) != created_paths:
                        raise CaptureTransactionError(
                            "invalid_transaction", "Capture results are not transaction creations."
                        )
                    if selected_operation == "merge" and replacement_count < 2:
                        raise CaptureTransactionError(
                            "invalid_transaction", "A merge must replace at least two sources."
                        )
                    if selected_operation == "split" and replacement_count != 1:
                        raise CaptureTransactionError(
                            "invalid_transaction", "A split must replace exactly one source."
                        )
                    tx_fd = _initialize_journal(store, journal)
                    _capture_transaction_checkpoint("after_journal_initialized")
                    _prepare_artifacts(prepared)
                    _verify_unpublished(prepared)
                    journal = replace(journal, phase="prepared")
                    _write_journal(tx_fd, journal, create=False)
                    _capture_transaction_checkpoint("after_prepared")
                    _verify_unpublished(prepared)
                    publication_started = True
                    _publish(prepared)
                    _verify_committed(journal, parents)
                    journal = replace(journal, phase="committed")
                    _write_journal(tx_fd, journal, create=False)
                    _capture_transaction_checkpoint("after_committed")
                    receipt = journal.receipt()
                    _write_receipt(store, receipt)
                    _cleanup_committed(journal, parents)
                    _remove_journal(store, journal)
                    return receipt
                except Exception as error:
                    if tx_fd is None:
                        raise
                    try:
                        if publication_started:
                            recovered = _recover_one_locked(store, root_fd, journal)
                            if recovered is not None:
                                return _matching_receipt(
                                    recovered,
                                    idempotency_key_hash=key_hash,
                                    operation=selected_operation,
                                    request_fingerprint=fingerprint,
                                    result_paths=normalized_results,
                                )
                        else:
                            _abort_before_publication(store, journal, prepared)
                    except CaptureTransactionError as recovery_error:
                        raise recovery_error from error
                    if isinstance(error, CaptureTransactionError):
                        raise error
                    raise CaptureTransactionError(
                        "transaction_failed", "Capture transaction failed before commit."
                    ) from error
                finally:
                    if tx_fd is not None:
                        os.close(tx_fd)
                    _close_parents(parents)
            finally:
                os.close(root_fd)
    except RecoveryLockUnavailableError as error:
        raise CaptureTransactionError(
            "transaction_locked", "Another canonical vault mutation is in progress."
        ) from error
    except RecoveryError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction recovery state is unavailable."
        ) from error
    except (OSError, TransactionError) as error:
        raise CaptureTransactionError(
            "transaction_failed", "Capture transaction storage is unavailable."
        ) from error


def recover_capture_transactions(*, vault_root: Path, runtime_dir: Path) -> None:
    try:
        with acquire_pinned_recovery_store(
            runtime_dir=runtime_dir / "capture-mutations",
            authority_root=vault_root,
        ) as store:
            root_fd = store.open_authority_root()
            try:
                _recover_all_required(store, root_fd)
            finally:
                os.close(root_fd)
    except RecoveryLockUnavailableError as error:
        raise CaptureTransactionError(
            "transaction_locked", "Another canonical vault mutation is in progress."
        ) from error
    except RecoveryError as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction recovery state is unavailable."
        ) from error
    except (OSError, TransactionError) as error:
        raise CaptureTransactionError(
            "recovery_required", "Capture transaction recovery storage is unavailable."
        ) from error
