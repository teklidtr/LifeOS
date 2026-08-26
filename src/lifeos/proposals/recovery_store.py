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
    RecoveryConflictError,
    RecoveryCorruptStateError,
    RecoveryDiscoveryResult,
    RecoveryFinding,
    RecoveryFindingCode,
    RecoveryJournal,
    RecoveryLockUnavailableError,
    RecoveryPhase,
    RecoveryTransactionId,
    RecoveryUnavailableError,
    RecoveryUnknownSchemaError,
    RecoveryValidationError,
    _deserialize_journal,
    _serialize_journal,
    validate_recovery_transaction_id,
)

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
_OS_OPEN_SUPPORTS_DIR_FD = os.open in getattr(os, "supports_dir_fd", set())
_LOCKS_GUARD = threading.Lock()
_HELD_RUNTIME_IDS: set[tuple[int, int]] = set()


@dataclass(frozen=True, slots=True)
class PinnedRecoveryStore:
    """Recovery namespace anchored to one runtime and one canonical-vault authority."""

    runtime_path: Path
    runtime_fd: int
    recovery_fd: int
    authority_path: Path
    authority_fd: int

    @property
    def recovery_root(self) -> Path:
        """Compatibility/display path. Security-sensitive I/O uses ``recovery_fd``."""
        return self.runtime_path / "recovery"

    def require_current_runtime_path(self) -> None:
        """Fail if the configured runtime path no longer names the pinned directory."""
        _require_current_directory_path(
            self.runtime_path,
            self.runtime_fd,
            "Configured runtime path no longer identifies the pinned runtime",
        )

    def require_current_authority_path(self) -> None:
        """Fail if the canonical vault path no longer names the locked vault directory."""
        _require_current_directory_path(
            self.authority_path,
            self.authority_fd,
            "Canonical vault path no longer identifies the locked mutation authority",
        )

    def open_authority_root(self) -> int:
        """Duplicate the locked canonical-vault descriptor after path identity revalidation."""
        self.require_current_authority_path()
        try:
            return os.dup(self.authority_fd)
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to duplicate canonical vault authority") from exc

    def open_transaction(self, transaction_id: RecoveryTransactionId) -> int:
        self.require_current_runtime_path()
        self.require_current_authority_path()
        validate_recovery_transaction_id(transaction_id)
        return _open_dir_at(self.recovery_fd, str(transaction_id), "recovery transaction")

    def discover(self) -> RecoveryDiscoveryResult:
        self.require_current_runtime_path()
        self.require_current_authority_path()
        try:
            names = sorted(os.listdir(self.recovery_fd))
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to list recovery root") from exc

        journals: list[RecoveryJournal] = []
        findings: list[RecoveryFinding] = []
        for name in names:
            state = _stat_at(self.recovery_fd, name)
            if state is None or not stat.S_ISDIR(state.st_mode):
                code = (
                    RecoveryFindingCode.SYMLINKED_DIR
                    if state is not None and stat.S_ISLNK(state.st_mode)
                    else RecoveryFindingCode.UNEXPECTED_FILE
                )
                findings.append(RecoveryFinding(code, name))
                continue
            try:
                tx_id = validate_recovery_transaction_id(name)
            except RecoveryValidationError:
                findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_DIR_NAME, name))
                continue

            tx_fd: int | None = None
            try:
                tx_fd = _open_dir_at(self.recovery_fd, name, "recovery transaction")
                journal_state = _stat_at(tx_fd, "journal.json")
                if journal_state is None:
                    findings.append(RecoveryFinding(RecoveryFindingCode.DIR_WITHOUT_JOURNAL, name))
                    continue
                if stat.S_ISLNK(journal_state.st_mode):
                    findings.append(RecoveryFinding(RecoveryFindingCode.SYMLINKED_JOURNAL, name))
                    continue
                if not stat.S_ISREG(journal_state.st_mode) or not _has_layout(tx_fd):
                    findings.append(RecoveryFinding(RecoveryFindingCode.INVALID_LAYOUT, name))
                    continue
                journal = _deserialize_journal(_read_regular_at(tx_fd, "journal.json"))
            except RecoveryUnknownSchemaError:
                findings.append(RecoveryFinding(RecoveryFindingCode.UNKNOWN_SCHEMA, name))
                continue
            except (RecoveryCorruptStateError, RecoveryUnavailableError):
                findings.append(RecoveryFinding(RecoveryFindingCode.CORRUPT_JSON, name))
                continue
            finally:
                if tx_fd is not None:
                    os.close(tx_fd)

            if journal.transaction_id != tx_id:
                findings.append(RecoveryFinding(RecoveryFindingCode.TRANSACTION_ID_MISMATCH, name))
            else:
                journals.append(journal)

        journals.sort(key=lambda item: str(item.transaction_id))
        findings.sort(key=lambda item: (item.code.value, item.transaction_name))
        return RecoveryDiscoveryResult(tuple(journals), tuple(findings))

    def initialize_transaction(self, journal: RecoveryJournal) -> Path:
        self.require_current_runtime_path()
        self.require_current_authority_path()
        validate_recovery_transaction_id(journal.transaction_id)
        if journal.phase is not RecoveryPhase.PREPARED:
            raise RecoveryValidationError("Initial journal must be prepared")
        name = str(journal.transaction_id)
        if _stat_at(self.recovery_fd, name) is not None:
            raise RecoveryConflictError("Transaction exists")
        try:
            os.mkdir(name, 0o700, dir_fd=self.recovery_fd)
            tx_fd = _open_dir_at(self.recovery_fd, name, "recovery transaction")
            try:
                os.mkdir("staged", 0o700, dir_fd=tx_fd)
                os.mkdir("backups", 0o700, dir_fd=tx_fd)
                _write_new_at(tx_fd, "journal.json", _serialize_journal(journal))
                os.fsync(tx_fd)
            finally:
                os.close(tx_fd)
            os.fsync(self.recovery_fd)
        except OSError as exc:
            raise RecoveryUnavailableError("Initialization failed") from exc
        return self.recovery_root / name

    def write_journal(self, journal: RecoveryJournal) -> None:
        tx_fd = self.open_transaction(journal.transaction_id)
        try:
            _require_layout(tx_fd)
            tmp = f".journal.{secrets.token_hex(8)}.tmp"
            _write_new_at(tx_fd, tmp, _serialize_journal(journal))
            try:
                os.replace(tmp, "journal.json", src_dir_fd=tx_fd, dst_dir_fd=tx_fd)
                os.fsync(tx_fd)
            except OSError as exc:
                try:
                    os.unlink(tmp, dir_fd=tx_fd)
                except OSError:
                    pass
                raise RecoveryUnavailableError("Failed to write journal") from exc
        finally:
            os.close(tx_fd)

    def load_journal(self, transaction_id: RecoveryTransactionId) -> RecoveryJournal:
        tx_fd = self.open_transaction(transaction_id)
        try:
            _require_layout(tx_fd)
            journal = _deserialize_journal(_read_regular_at(tx_fd, "journal.json"))
        finally:
            os.close(tx_fd)
        if journal.transaction_id != transaction_id:
            raise RecoveryCorruptStateError("Journal transaction ID mismatch")
        return journal

    def remove_completed(self, transaction_id: RecoveryTransactionId) -> None:
        if self.load_journal(transaction_id).phase is not RecoveryPhase.COMPLETE:
            raise RecoveryValidationError("Cannot remove incomplete transaction")
        self._remove(transaction_id)

    def remove_rolled_back(self, transaction_id: RecoveryTransactionId) -> None:
        if self.load_journal(transaction_id).phase is RecoveryPhase.COMPLETE:
            raise RecoveryValidationError("Cannot remove complete transaction")
        self._remove(transaction_id)

    def _remove(self, transaction_id: RecoveryTransactionId) -> None:
        self.require_current_runtime_path()
        self.require_current_authority_path()
        _remove_tree_at(self.recovery_fd, str(transaction_id))
        try:
            os.fsync(self.recovery_fd)
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to sync recovery cleanup") from exc


@contextmanager
def acquire_pinned_recovery_store(
    *,
    runtime_dir: Path,
    authority_root: Path | None = None,
) -> Iterator[PinnedRecoveryStore]:
    """Pin runtime and hold one stable mutation authority for the whole store lifetime."""
    if not hasattr(os, "O_NOFOLLOW") or not _OS_OPEN_SUPPORTS_DIR_FD:
        raise RecoveryLockUnavailableError("Descriptor-safe runtime traversal is unavailable")

    runtime_path = Path(os.path.abspath(runtime_dir))
    authority_path = Path(os.path.abspath(authority_root or runtime_path.parent))
    authority_fd: int | None = None
    runtime_fd: int | None = None
    recovery_fd: int | None = None
    lock_fd: int | None = None
    runtime_id: tuple[int, int] | None = None
    try:
        try:
            authority_fd = _open_runtime_chain(authority_path, create_missing=False)
            fcntl.flock(authority_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, RecoveryLockUnavailableError) as exc:
            raise RecoveryLockUnavailableError("Failed to acquire mutation authority") from exc

        runtime_fd = _open_runtime_from_authority(
            runtime_path=runtime_path,
            authority_path=authority_path,
            authority_fd=authority_fd,
        )
        runtime_state = os.fstat(runtime_fd)
        runtime_id = (runtime_state.st_dev, runtime_state.st_ino)
        with _LOCKS_GUARD:
            if runtime_id in _HELD_RUNTIME_IDS:
                raise RecoveryLockUnavailableError("Lock already acquired")
            _HELD_RUNTIME_IDS.add(runtime_id)

        try:
            lock_fd = os.open(
                "recovery.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=runtime_fd,
            )
            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise RecoveryLockUnavailableError("Recovery lock is not a regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RecoveryLockUnavailableError("Failed to acquire recovery lock") from exc

        recovery_fd = _open_or_create_dir_at(runtime_fd, "recovery")
        yield PinnedRecoveryStore(
            runtime_path=runtime_path,
            runtime_fd=runtime_fd,
            recovery_fd=recovery_fd,
            authority_path=authority_path,
            authority_fd=authority_fd,
        )
    finally:
        if runtime_id is not None:
            with _LOCKS_GUARD:
                _HELD_RUNTIME_IDS.discard(runtime_id)
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_fd)
            except OSError:
                pass
        for fd in (recovery_fd, runtime_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if authority_fd is not None:
            try:
                fcntl.flock(authority_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(authority_fd)
            except OSError:
                pass


def _require_current_directory_path(path: Path, pinned_fd: int, message: str) -> None:
    current_fd: int | None = None
    try:
        current_fd = _open_runtime_chain(path, create_missing=False)
        pinned = os.fstat(pinned_fd)
        current = os.fstat(current_fd)
    except (OSError, RecoveryLockUnavailableError) as exc:
        raise RecoveryUnavailableError(message) from exc
    finally:
        if current_fd is not None:
            os.close(current_fd)
    if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
        raise RecoveryUnavailableError(message)


def _open_runtime_chain(path: Path, *, create_missing: bool = True) -> int:
    absolute = Path(os.path.abspath(path))
    try:
        current_fd = os.open(absolute.anchor, _DIR_FLAGS)
    except OSError as exc:
        raise RecoveryLockUnavailableError("Failed to open runtime path anchor") from exc
    try:
        for component in absolute.parts[1:]:
            try:
                next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create_missing:
                    raise RecoveryLockUnavailableError("Runtime directory path changed")
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise RecoveryLockUnavailableError(
                        "Failed to create runtime directory component"
                    ) from exc
                try:
                    next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
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
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_runtime_from_authority(
    *, runtime_path: Path, authority_path: Path, authority_fd: int
) -> int:
    """Acquire an in-vault runtime and validate its selected root before runtime state."""
    try:
        relative = runtime_path.relative_to(authority_path)
    except ValueError:
        return _open_runtime_chain(runtime_path)
    if not relative.parts:
        raise RecoveryLockUnavailableError("Runtime overlaps canonical vault authority")

    current_fd = os.dup(authority_fd)
    try:
        for index, component in enumerate(relative.parts):
            try:
                next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
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
                    next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
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
            if index == 0:
                selected = os.fstat(next_fd)
                for reserved in ("proposals", "system"):
                    try:
                        reserved_fd = os.open(reserved, _DIR_FLAGS, dir_fd=authority_fd)
                    except FileNotFoundError:
                        continue
                    try:
                        canonical = os.fstat(reserved_fd)
                    finally:
                        os.close(reserved_fd)
                    if (selected.st_dev, selected.st_ino) == (
                        canonical.st_dev,
                        canonical.st_ino,
                    ):
                        os.close(next_fd)
                        raise RecoveryLockUnavailableError(
                            "Runtime overlaps reserved canonical authority"
                        )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_or_create_dir_at(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise RecoveryUnavailableError("Failed to create recovery directory") from exc
        return _open_dir_at(parent_fd, name, "recovery directory")
    except OSError as exc:
        raise RecoveryCorruptStateError("Recovery root is a symlink or non-directory") from exc


def _open_dir_at(parent_fd: int, name: str, label: str) -> int:
    state = _stat_at(parent_fd, name)
    if state is None or stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise RecoveryCorruptStateError(f"{label} is a symlink or non-directory")
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        opened = os.fstat(fd)
    except OSError as exc:
        raise RecoveryUnavailableError(f"Failed to open {label}") from exc
    if (opened.st_dev, opened.st_ino) != (state.st_dev, state.st_ino):
        os.close(fd)
        raise RecoveryCorruptStateError(f"{label} changed during open")
    return fd


def _stat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to inspect recovery entry") from exc


def _has_layout(tx_fd: int) -> bool:
    staged = _stat_at(tx_fd, "staged")
    backups = _stat_at(tx_fd, "backups")
    return all(
        item is not None and stat.S_ISDIR(item.st_mode) and not stat.S_ISLNK(item.st_mode)
        for item in (staged, backups)
    )


def _require_layout(tx_fd: int) -> None:
    journal = _stat_at(tx_fd, "journal.json")
    if (
        journal is None
        or stat.S_ISLNK(journal.st_mode)
        or not stat.S_ISREG(journal.st_mode)
        or not _has_layout(tx_fd)
    ):
        raise RecoveryCorruptStateError("Recovery transaction layout is invalid")


def _read_regular_at(parent_fd: int, name: str) -> bytes:
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=parent_fd)
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
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or total != after.st_size:
            raise RecoveryCorruptStateError("Recovery file changed during read")
        return b"".join(chunks)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to read recovery file") from exc
    finally:
        os.close(fd)


def _write_new_at(parent_fd: int, name: str, content: bytes) -> None:
    try:
        fd = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        try:
            offset = 0
            while offset < len(content):
                written = os.write(fd, content[offset:])
                if written <= 0:
                    raise OSError("write returned no bytes")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise RecoveryUnavailableError("Failed to write recovery file") from exc


def _remove_tree_at(parent_fd: int, name: str) -> None:
    child_fd = _open_dir_at(parent_fd, name, "recovery tree")
    try:
        for entry in os.listdir(child_fd):
            state = _stat_at(child_fd, entry)
            if (
                state is not None
                and stat.S_ISDIR(state.st_mode)
                and not stat.S_ISLNK(state.st_mode)
            ):
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
