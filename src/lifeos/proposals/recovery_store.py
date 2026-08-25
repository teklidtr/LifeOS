"""Descriptor-pinned runtime/recovery storage for proposal application and recovery."""

from __future__ import annotations

import errno
import fcntl
import os
import secrets
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .recovery import (
    RecoveryCorruptStateError,
    RecoveryDiscoveryResult,
    RecoveryFinding,
    RecoveryFindingCode,
    RecoveryJournal,
    RecoveryLockUnavailableError,
    RecoveryPhase,
    RecoveryUnavailableError,
    RecoveryUnknownSchemaError,
    RecoveryValidationError,
    RecoveryTransactionId,
    _deserialize_journal,
    _serialize_journal,
    validate_recovery_transaction_id,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_REGULAR_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)

_held_runtime_locks_guard = threading.Lock()
_held_runtime_locks: set[tuple[int, int]] = set()


@dataclass(frozen=True, slots=True)
class PinnedRecoveryStore:
    """One recovery namespace anchored to already-open runtime/recovery descriptors."""

    runtime_path: Path
    runtime_fd: int
    recovery_fd: int

    @property
    def recovery_root(self) -> Path:
        """Display/compatibility path only; security-sensitive I/O uses ``recovery_fd``."""
        return self.runtime_path / "recovery"

    def open_transaction(self, transaction_id: RecoveryTransactionId) -> int:
        validate_recovery_transaction_id(transaction_id)
        return _open_transaction_at(self.recovery_fd, str(transaction_id))

    def discover(self) -> RecoveryDiscoveryResult:
        journals: list[RecoveryJournal] = []
        findings: list[RecoveryFinding] = []
        try:
            names = sorted(os.listdir(self.recovery_fd))
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to list recovery root") from exc

        for name in names:
            try:
                state = os.stat(name, dir_fd=self.recovery_fd, follow_symlinks=False)
            except OSError:
                findings.append(RecoveryFinding(RecoveryFindingCode.UNEXPECTED_FILE, name))
                continue
            if stat.S_ISLNK(state.st_mode):
                findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_DIR, name))
                continue
            if not stat.S_ISDIR(state.st_mode):
                findings.append(RecoveryFinding(RecoveryFindingCode.UNEXPECTED_FILE, name))
                continue
            try:
                tx_id = validate_recovery_transaction_id(name)
            except RecoveryValidationError:
                findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_DIR_NAME, name))
                continue

            tx_fd: int | None = None
            try:
                tx_fd = _open_transaction_at(self.recovery_fd, name)
                journal_state = _stat_at(tx_fd, "journal.json")
                if journal_state is None:
                    findings.append(RecoveryFinding(RecoveryFindingCode.DIR_WITHOUT_JOURNAL, name))
                    continue
                if stat.S_ISLNK(journal_state.st_mode):
                    findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_JOURNAL, name))
                    continue
                if not stat.S_ISREG(journal_state.st_mode):
                    findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_LAYOUT, name))
                    continue
                if not _child_is_directory(tx_fd, "staged") or not _child_is_directory(
                    tx_fd, "backups"
                ):
                    findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_LAYOUT, name))
                    continue
                journal = _deserialize_journal(_read_regular_at(tx_fd, "journal.json"))
            except RecoveryUnknownSchemaError:
                findings.append(RecoveryFinding(RecoveryFindingCode.UNKNOWN_SCHEMA, name))
                continue
            except RecoveryCorruptStateError:
                findings.append(RecoveryFinding(RecoveryFindingCode.CORRUPT_JSON, name))
                continue
            except RecoveryUnavailableError:
                findings.append(RecoveryFinding(RecoveryFindingCode.CORRUPT_JSON, name))
                continue
            finally:
                if tx_fd is not None:
                    os.close(tx_fd)

            if journal.transaction_id != tx_id:
                findings.append(RecoveryFinding(RecoveryFindingCode.TRANSACTION_ID_MISMATCH, name))
                continue
            journals.append(journal)

        journals.sort(key=lambda item: str(item.transaction_id))
        findings.sort(key=lambda item: (item.code.value, item.transaction_name))
        return RecoveryDiscoveryResult(tuple(journals), tuple(findings))

    def initialize_transaction(self, journal: RecoveryJournal) -> Path:
        validate_recovery_transaction_id(journal.transaction_id)
        if journal.phase is not RecoveryPhase.PREPARED:
            raise RecoveryValidationError("Initial journal must be prepared")
        name = str(journal.transaction_id)
        if _stat_at(self.recovery_fd, name) is not None:
            from .recovery import RecoveryConflictError

            raise RecoveryConflictError("Transaction exists")
        try:
            os.mkdir(name, 0o700, dir_fd=self.recovery_fd)
            tx_fd = _open_transaction_at(self.recovery_fd, name)
            try:
                os.mkdir("staged", 0o700, dir_fd=tx_fd)
                os.mkdir("backups", 0o700, dir_fd=tx_fd)
                _write_new_regular_at(tx_fd, "journal.json", _serialize_journal(journal))
                os.fsync(tx_fd)
            finally:
                os.close(tx_fd)
            os.fsync(self.recovery_fd)
        except OSError as exc:
            raise RecoveryUnavailableError("Initialization failed") from exc
        return self.recovery_root / name

    def write_journal(self, journal: RecoveryJournal) -> None:
        validate_recovery_transaction_id(journal.transaction_id)
        tx_fd = self.open_transaction(journal.transaction_id)
        try:
            _require_transaction_layout(tx_fd)
            content = _serialize_journal(journal)
            tmp_name = f".journal.{secrets.token_hex(8)}.tmp"
            _write_new_regular_at(tx_fd, tmp_name, content)
            try:
                os.replace(
                    tmp_name,
                    "journal.json",
                    src_dir_fd=tx_fd,
                    dst_dir_fd=tx_fd,
                )
                os.fsync(tx_fd)
            except OSError as exc:
                try:
                    os.unlink(tmp_name, dir_fd=tx_fd)
                except OSError:
                    pass
                raise RecoveryUnavailableError("Failed to write journal") from exc
        finally:
            os.close(tx_fd)

    def load_journal(self, transaction_id: RecoveryTransactionId) -> RecoveryJournal:
        tx_fd = self.open_transaction(transaction_id)
        try:
            _require_transaction_layout(tx_fd)
            journal = _deserialize_journal(_read_regular_at(tx_fd, "journal.json"))
        finally:
            os.close(tx_fd)
        if journal.transaction_id != transaction_id:
            raise RecoveryCorruptStateError("Journal transaction ID mismatch")
        return journal

    def remove_completed(self, transaction_id: RecoveryTransactionId) -> None:
        journal = self.load_journal(transaction_id)
        if journal.phase is not RecoveryPhase.COMPLETE:
            raise RecoveryValidationError("Cannot remove incomplete transaction")
        _remove_tree_at(self.recovery_fd, str(transaction_id))
        os.fsync(self.recovery_fd)

    def remove_rolled_back(self, transaction_id: RecoveryTransactionId) -> None:
        journal = self.load_journal(transaction_id)
        if journal.phase is RecoveryPhase.COMPLETE:
            raise RecoveryValidationError("Cannot remove complete transaction")
        _remove_tree_at(self.recovery_fd, str(transaction_id))
        os.fsync(self.recovery_fd)


@contextmanager
def acquire_pinned_recovery_store(*, runtime_dir: Path) -> Iterator[PinnedRecoveryStore]:
    """Pin the runtime directory once, then acquire recovery lock and recovery root beneath it."""
    if not hasattr(os, "O_NOFOLLOW") or os.open not in getattr(os, "supports_dir_fd", set()):
        raise RecoveryLockUnavailableError("Descriptor-safe runtime traversal is unavailable")

    runtime_path = Path(os.path.abspath(runtime_dir))
    runtime_fd: int | None = None
    recovery_fd: int | None = None
    lock_fd: int | None = None
    lock_key: tuple[int, int] | None = None
    try:
        runtime_fd = _open_or_create_directory_chain(runtime_path)
        runtime_state = os.fstat(runtime_fd)
        lock_key = (runtime_state.st_dev, runtime_state.st_ino)
        with _held_runtime_locks_guard:
            if lock_key in _held_runtime_locks:
                raise RecoveryLockUnavailableError("Lock already acquired")
            _held_runtime_locks.add(lock_key)

        try:
            lock_flags = (
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            lock_fd = os.open("recovery.lock", lock_flags, 0o600, dir_fd=runtime_fd)
            lock_state = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_state.st_mode):
                raise RecoveryLockUnavailableError("Recovery lock is not a regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RecoveryLockUnavailableError("Failed to acquire recovery lock") from exc

        recovery_fd = _open_or_create_child_directory(runtime_fd, "recovery")
        yield PinnedRecoveryStore(runtime_path, runtime_fd, recovery_fd)
    finally:
        if lock_key is not None:
            with _held_runtime_locks_guard:
                _held_runtime_locks.discard(lock_key)
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_fd)
            except OSError:
                pass
        if recovery_fd is not None:
            try:
                os.close(recovery_fd)
            except OSError:
                pass
        if runtime_fd is not None:
            try:
                os.close(runtime_fd)
            except OSError:
                pass


def _open_or_create_directory_chain(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute():
        raise RecoveryLockUnavailableError("Runtime directory must resolve to an absolute path")
    try:
        current_fd = os.open(absolute.anchor, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise RecoveryLockUnavailableError("Failed to open runtime path anchor") from exc

    try:
        for component in absolute.parts[1:]:
            try:
                next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise RecoveryLockUnavailableError(
                        "Failed to create runtime directory component"
                    ) from exc
                try:
                    next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
                except OSError as exc:
                    raise RecoveryLockUnavailableError(
                        "Failed to open created runtime directory component"
                    ) from exc
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise RecoveryLockUnavailableError(
                        "Runtime directory contains a symlink or non-directory component"
                    ) from exc
                raise RecoveryLockUnavailableError(
                    "Failed to open runtime directory component"
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        state = os.fstat(current_fd)
        if not stat.S_ISDIR(state.st_mode):
            raise RecoveryLockUnavailableError("Runtime descriptor is not a directory")
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_or_create_child_directory(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to create recovery directory") from exc
        try:
            return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to open recovery directory") from exc
    except OSError as exc:
        raise RecoveryCorruptStateError("Recovery root is a symlink or non-directory") from exc


def _open_transaction_at(recovery_fd: int, name: str) -> int:
    try:
        state = os.stat(name, dir_fd=recovery_fd, follow_symlinks=False)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to inspect recovery transaction") from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise RecoveryCorruptStateError("Recovery transaction is a symlink or non-directory")
    try:
        fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=recovery_fd)
    except OSError as exc:
        raise RecoveryCorruptStateError("Failed to open recovery transaction") from exc
    opened = os.fstat(fd)
    if opened.st_dev != state.st_dev or opened.st_ino != state.st_ino:
        os.close(fd)
        raise RecoveryCorruptStateError("Recovery transaction changed during open")
    return fd


def _stat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to inspect recovery entry") from exc


def _child_is_directory(parent_fd: int, name: str) -> bool:
    state = _stat_at(parent_fd, name)
    return state is not None and not stat.S_ISLNK(state.st_mode) and stat.S_ISDIR(state.st_mode)


def _require_transaction_layout(tx_fd: int) -> None:
    journal = _stat_at(tx_fd, "journal.json")
    if journal is None or stat.S_ISLNK(journal.st_mode) or not stat.S_ISREG(journal.st_mode):
        raise RecoveryCorruptStateError("Journal must be a regular file")
    if not _child_is_directory(tx_fd, "staged") or not _child_is_directory(tx_fd, "backups"):
        raise RecoveryCorruptStateError("Recovery transaction layout is invalid")


def _read_regular_at(parent_fd: int, name: str) -> bytes:
    try:
        fd = os.open(name, _REGULAR_READ_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to open recovery file") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise RecoveryCorruptStateError("Recovery file is not regular")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or total != after.st_size
        ):
            raise RecoveryCorruptStateError("Recovery file changed during read")
        return b"".join(chunks)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to read recovery file") from exc
    finally:
        os.close(fd)


def _write_new_regular_at(parent_fd: int, name: str, content: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to create recovery file") from exc
    try:
        written = 0
        while written < len(content):
            count = os.write(fd, content[written:])
            if count <= 0:
                raise OSError("write returned no bytes")
            written += count
        os.fsync(fd)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to write recovery file") from exc
    finally:
        os.close(fd)


def _remove_tree_at(parent_fd: int, name: str) -> None:
    try:
        state = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to inspect recovery tree") from exc
    if not stat.S_ISDIR(state.st_mode) or stat.S_ISLNK(state.st_mode):
        raise RecoveryCorruptStateError("Recovery tree root is not a directory")
    child_fd = _open_transaction_at(parent_fd, name)
    try:
        for entry in os.listdir(child_fd):
            entry_state = os.stat(entry, dir_fd=child_fd, follow_symlinks=False)
            if stat.S_ISDIR(entry_state.st_mode) and not stat.S_ISLNK(entry_state.st_mode):
                _remove_tree_at(child_fd, entry)
            else:
                os.unlink(entry, dir_fd=child_fd)
        os.fsync(child_fd)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to remove recovery tree contents") from exc
    finally:
        os.close(child_fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to remove recovery transaction") from exc
