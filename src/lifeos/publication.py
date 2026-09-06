"""Crash-consistent publication of disposable derived generations."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

PublicationPhase = Literal["prepared", "published", "complete"]
RecoveryState = Literal["none", "prepared", "published", "complete", "corrupt"]
IntegrityState = Literal["valid", "unsupported", "corrupt", "unavailable"]
_INTEGRITY_FILE = "integrity.json"
_RMTREE_AVOIDS_SYMLINK_ATTACKS = shutil.rmtree.avoids_symlink_attacks
FaultInjector = Callable[[str], None]


class PublicationError(RuntimeError):
    """Raised when a derived generation cannot be published or recovered."""


class PublicationConflictError(PublicationError):
    """Raised when another build holds the publication lock."""


@dataclass(frozen=True, slots=True)
class PublicationJournal:
    schema_version: int
    generation_id: str
    staging_name: str
    previous_generation: str | None
    phase: PublicationPhase


@dataclass(frozen=True, slots=True)
class ActiveGeneration:
    schema_version: int
    generation_id: str


@dataclass(frozen=True, slots=True)
class PublicationInspection:
    active_generation: str | None
    recovery_state: RecoveryState
    stale_cleanup: bool


@dataclass(frozen=True, slots=True)
class IntegrityEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class GenerationIntegrity:
    schema_version: int
    files: tuple[IntegrityEntry, ...]


@dataclass(frozen=True, slots=True)
class IntegrityInspection:
    state: IntegrityState
    code: str


@dataclass(frozen=True, slots=True)
class _ObservedFile:
    size: int
    sha256: str
    content: bytes | None = None


class _IntegrityCorruptError(RuntimeError):
    pass


class _IntegrityUnavailableError(RuntimeError):
    pass


class PublicationLock:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._fd: int | None = None

    def __enter__(self) -> PublicationLock:
        self._root.mkdir(parents=True, exist_ok=True)
        lock_path = self._root / ".publication.lock"
        try:
            fd = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if "fd" in locals():
                os.close(fd)
            raise PublicationConflictError("another derived build is already running") from exc
        except OSError as exc:
            if "fd" in locals():
                os.close(fd)
            raise PublicationError("publication lock is unavailable") from exc
        self._fd = fd
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise PublicationError("failed to update publication metadata") from exc


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationError("publication metadata is unreadable") from exc


def _validate_generation_name(value: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise PublicationError("active generation id is invalid")


def _validate_journal_identifiers(
    generation_id: object,
    staging_name: object,
    previous_generation: object,
) -> tuple[str, str, str | None]:
    if (
        not isinstance(generation_id, str)
        or not isinstance(staging_name, str)
        or previous_generation is not None
        and not isinstance(previous_generation, str)
    ):
        raise PublicationError("publication journal fields are invalid")

    try:
        _validate_generation_name(generation_id)
        _validate_generation_name(staging_name)
        if previous_generation is not None:
            _validate_generation_name(previous_generation)
    except PublicationError as exc:
        raise PublicationError("publication journal fields are invalid") from exc

    staging_suffix = staging_name.removeprefix(f".staging-{generation_id[:16]}-")
    if staging_suffix == staging_name or staging_suffix in {"", ".", ".."}:
        raise PublicationError("publication journal fields are invalid")
    return generation_id, staging_name, previous_generation


def _read_active(root: Path) -> ActiveGeneration | None:
    path = root / "active.json"
    if not path.exists():
        return None
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise PublicationError("active generation metadata is invalid")
    if raw.get("schema_version") != 1:
        raise PublicationError("active generation schema is invalid")
    generation_id = raw.get("generation_id")
    if not isinstance(generation_id, str):
        raise PublicationError("active generation id is invalid")
    _validate_generation_name(generation_id)
    return ActiveGeneration(1, generation_id)


def _read_journal(root: Path) -> PublicationJournal | None:
    path = root / "transaction.json"
    if not path.exists():
        return None
    raw = _read_json(path)
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise PublicationError("publication journal is invalid")
    generation_id, staging_name, previous_generation = _validate_journal_identifiers(
        raw.get("generation_id"),
        raw.get("staging_name"),
        raw.get("previous_generation"),
    )
    phase = raw.get("phase")
    if phase not in {"prepared", "published", "complete"}:
        raise PublicationError("publication journal fields are invalid")
    return PublicationJournal(1, generation_id, staging_name, previous_generation, phase)


def _write_journal(root: Path, journal: PublicationJournal) -> None:
    _atomic_write(root / "transaction.json", _json_bytes(asdict(journal)))


def _write_active(root: Path, generation_id: str) -> None:
    _atomic_write(root / "active.json", _json_bytes(asdict(ActiveGeneration(1, generation_id))))


def _generation_id(files: Mapping[str, bytes]) -> str:
    hasher = hashlib.sha256()
    for relative_path, content in sorted(files.items()):
        encoded = relative_path.encode("utf-8")
        hasher.update(len(encoded).to_bytes(4, "big"))
        hasher.update(encoded)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


def _validate_relative_path(relative_path: str) -> tuple[str, ...]:
    parts = tuple(relative_path.split("/"))
    if (
        not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
        or "\x00" in relative_path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise PublicationError("derived output path is invalid")
    return parts


def _integrity_bytes(files: Mapping[str, bytes]) -> bytes:
    entries: list[IntegrityEntry] = []
    for relative_path, content in sorted(files.items()):
        _validate_relative_path(relative_path)
        if relative_path == _INTEGRITY_FILE:
            raise PublicationError("derived output reserves integrity.json")
        entries.append(
            IntegrityEntry(
                path=relative_path,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    return _json_bytes(asdict(GenerationIntegrity(1, tuple(entries))))


def _open_directory(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.ENOENT}:
            raise _IntegrityCorruptError("generation directory is missing or invalid") from exc
        raise _IntegrityUnavailableError("generation directory is unavailable") from exc
    try:
        metadata = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise _IntegrityUnavailableError("generation directory cannot be inspected") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(fd)
        raise _IntegrityCorruptError("generation root is not a directory")
    return fd


def _observe_open_file(fd: int, *, capture: bool) -> _ObservedFile:
    try:
        before = os.fstat(fd)
    except OSError as exc:
        raise _IntegrityUnavailableError("generation file cannot be inspected") from exc
    if not stat.S_ISREG(before.st_mode):
        raise _IntegrityCorruptError("generation entry is not a regular file")
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    byte_count = 0
    try:
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            byte_count += len(chunk)
            hasher.update(chunk)
            if capture:
                chunks.append(chunk)
        after = os.fstat(fd)
    except OSError as exc:
        raise _IntegrityUnavailableError("generation file cannot be read") from exc
    if (
        not stat.S_ISREG(after.st_mode)
        or before.st_size != after.st_size
        or byte_count != before.st_size
    ):
        raise _IntegrityCorruptError("generation file changed during inspection")
    return _ObservedFile(
        size=byte_count,
        sha256=hasher.hexdigest(),
        content=b"".join(chunks) if capture else None,
    )


def _scan_directory(
    directory_fd: int,
    *,
    prefix: tuple[str, ...] = (),
) -> dict[str, _ObservedFile]:
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as exc:
        raise _IntegrityUnavailableError("generation directory cannot be listed") from exc
    observed: dict[str, _ObservedFile] = {}
    for name in names:
        relative_parts = (*prefix, name)
        relative_path = "/".join(relative_parts)
        try:
            _validate_relative_path(relative_path)
        except PublicationError as exc:
            raise _IntegrityCorruptError("generation contains an invalid path") from exc
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise _IntegrityUnavailableError("generation entry cannot be inspected") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise _IntegrityCorruptError("generation contains a symlink")
        if stat.S_ISDIR(metadata.st_mode):
            if relative_path == _INTEGRITY_FILE:
                raise _IntegrityCorruptError("integrity metadata is not a regular file")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                child_fd = os.open(name, flags, dir_fd=directory_fd)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise _IntegrityCorruptError(
                        "generation directory changed during inspection"
                    ) from exc
                raise _IntegrityUnavailableError("generation directory cannot be opened") from exc
            try:
                child_observed = _scan_directory(child_fd, prefix=relative_parts)
            finally:
                os.close(child_fd)
            overlap = observed.keys() & child_observed.keys()
            if overlap:
                raise _IntegrityCorruptError("generation contains duplicate paths")
            observed.update(child_observed)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise _IntegrityCorruptError("generation contains a special file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _IntegrityCorruptError("generation contains a symlink") from exc
            raise _IntegrityUnavailableError("generation file cannot be opened") from exc
        try:
            observation = _observe_open_file(file_fd, capture=relative_path == _INTEGRITY_FILE)
        finally:
            os.close(file_fd)
        if relative_path in observed:
            raise _IntegrityCorruptError("generation contains duplicate paths")
        observed[relative_path] = observation
    return observed


def _scan_generation(generation: Path) -> dict[str, _ObservedFile]:
    root_fd = _open_directory(generation)
    try:
        return _scan_directory(root_fd)
    finally:
        os.close(root_fd)


def _parse_integrity_inventory(content: bytes) -> GenerationIntegrity | None:
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _IntegrityCorruptError("integrity metadata is unreadable") from exc
    if not isinstance(raw, dict):
        raise _IntegrityCorruptError("integrity metadata must be an object")
    version = raw.get("schema_version")
    if type(version) is not int:
        raise _IntegrityCorruptError("integrity schema version is invalid")
    if version != 1:
        return None
    raw_files = raw.get("files")
    if not isinstance(raw_files, list):
        raise _IntegrityCorruptError("integrity file inventory is invalid")
    entries: list[IntegrityEntry] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise _IntegrityCorruptError("integrity file entry is invalid")
        path = item.get("path")
        size = item.get("size")
        digest = item.get("sha256")
        if not isinstance(path, str):
            raise _IntegrityCorruptError("integrity path is invalid")
        try:
            _validate_relative_path(path)
        except PublicationError as exc:
            raise _IntegrityCorruptError("integrity path is invalid") from exc
        if path == _INTEGRITY_FILE or path in seen:
            raise _IntegrityCorruptError("integrity paths are duplicated or reserved")
        if type(size) is not int or size < 0:
            raise _IntegrityCorruptError("integrity size is invalid")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise _IntegrityCorruptError("integrity hash is invalid")
        seen.add(path)
        entries.append(IntegrityEntry(path, size, digest))
    if [entry.path for entry in entries] != sorted(entry.path for entry in entries):
        raise _IntegrityCorruptError("integrity inventory is not deterministic")
    return GenerationIntegrity(1, tuple(entries))


def inspect_generation_integrity(generation: Path) -> IntegrityInspection:
    try:
        observed = _scan_generation(generation)
        inventory_file = observed.get(_INTEGRITY_FILE)
        if inventory_file is None:
            return IntegrityInspection("unsupported", "integrity-inventory-missing")
        if inventory_file.content is None:
            raise _IntegrityCorruptError("integrity metadata was not captured")
        inventory = _parse_integrity_inventory(inventory_file.content)
        if inventory is None:
            return IntegrityInspection("unsupported", "integrity-schema-unsupported")
        actual = {path: item for path, item in observed.items() if path != _INTEGRITY_FILE}
        expected = {entry.path: entry for entry in inventory.files}
        if set(actual) != set(expected):
            raise _IntegrityCorruptError("generation inventory does not match payload")
        for path, entry in expected.items():
            item = actual[path]
            if item.size != entry.size or item.sha256 != entry.sha256:
                raise _IntegrityCorruptError("generation payload does not match inventory")
    except _IntegrityCorruptError:
        return IntegrityInspection("corrupt", "integrity-verification-failed")
    except _IntegrityUnavailableError:
        return IntegrityInspection("unavailable", "integrity-storage-unavailable")
    return IntegrityInspection("valid", "integrity-valid")


def _write_generation(
    staging: Path,
    files: Mapping[str, bytes],
    fault_injector: FaultInjector | None,
) -> None:
    for relative_path, content in sorted(files.items()):
        parts = _validate_relative_path(relative_path)
        destination = staging.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        if fault_injector:
            fault_injector(f"after-file:{relative_path}")


def _validate_generation(generation: Path, files: Mapping[str, bytes]) -> None:
    try:
        observed = _scan_generation(generation)
    except (_IntegrityCorruptError, _IntegrityUnavailableError) as exc:
        raise PublicationError("derived generation cannot be verified") from exc
    if set(observed) != set(files):
        raise PublicationError("derived generation file inventory is incomplete")
    for relative_path, expected_content in sorted(files.items()):
        item = observed[relative_path]
        if (
            item.size != len(expected_content)
            or item.sha256 != hashlib.sha256(expected_content).hexdigest()
        ):
            raise PublicationError("derived generation content verification failed")


def _open_generations_directory(root: Path) -> int | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        directory_fd = os.open(root / "generations", flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PublicationError("publication generations directory is invalid") from exc
    try:
        metadata = os.fstat(directory_fd)
    except OSError as exc:
        os.close(directory_fd)
        raise PublicationError("publication generations directory cannot be inspected") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(directory_fd)
        raise PublicationError("publication generations directory is invalid")
    return directory_fd


def _generation_directory_metadata(
    generations_fd: int,
    generation_name: str,
) -> os.stat_result | None:
    _validate_generation_name(generation_name)
    try:
        metadata = os.stat(
            generation_name,
            dir_fd=generations_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PublicationError("publication generation cannot be inspected") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PublicationError("publication generation entry is invalid")
    return metadata


def _remove_generation_directory(generations_fd: int, generation_name: str) -> None:
    if _generation_directory_metadata(generations_fd, generation_name) is None:
        return
    if not _RMTREE_AVOIDS_SYMLINK_ATTACKS:
        raise PublicationError("safe publication cleanup is unavailable")
    try:
        shutil.rmtree(generation_name, dir_fd=generations_fd)
    except OSError as exc:
        raise PublicationError("publication generation cleanup failed") from exc


def _cleanup_generations_fd(
    generations_fd: int,
    active_generation: str | None,
) -> bool:
    try:
        generation_names = sorted(os.listdir(generations_fd))
    except OSError:
        return True

    stale_cleanup = False
    for generation_name in generation_names:
        if generation_name == active_generation:
            continue
        try:
            _remove_generation_directory(generations_fd, generation_name)
        except (OSError, PublicationError):
            stale_cleanup = True
    return stale_cleanup


def _cleanup_generations(root: Path, active_generation: str | None) -> bool:
    generations_fd = _open_generations_directory(root)
    if generations_fd is None:
        return False
    try:
        return _cleanup_generations_fd(generations_fd, active_generation)
    finally:
        os.close(generations_fd)


def _has_stale_generations(root: Path, active_generation: str | None) -> bool:
    generations_fd = _open_generations_directory(root)
    if generations_fd is None:
        return False
    try:
        generation_names = sorted(os.listdir(generations_fd))
        for generation_name in generation_names:
            _generation_directory_metadata(generations_fd, generation_name)
        return any(name != active_generation for name in generation_names)
    except OSError as exc:
        raise PublicationError("publication generations cannot be inspected") from exc
    finally:
        os.close(generations_fd)


def inspect_publication(root: Path) -> PublicationInspection:
    try:
        active = _read_active(root)
        journal = _read_journal(root)
        stale_cleanup = _has_stale_generations(
            root,
            active.generation_id if active else None,
        )
    except PublicationError:
        return PublicationInspection(None, "corrupt", True)
    recovery_state: RecoveryState = "none" if journal is None else journal.phase
    return PublicationInspection(
        active_generation=active.generation_id if active else None,
        recovery_state=recovery_state,
        stale_cleanup=stale_cleanup,
    )


def recover_publication(root: Path) -> PublicationInspection:
    """Recover an interrupted publication. Caller must hold PublicationLock."""
    journal = _read_journal(root)
    active = _read_active(root)
    active_id = active.generation_id if active else None
    generations_fd = _open_generations_directory(root)
    try:
        if journal is None:
            stale = (
                _cleanup_generations_fd(generations_fd, active_id)
                if generations_fd is not None
                else False
            )
            return PublicationInspection(active_id, "none", stale)

        if journal.staging_name == active_id:
            raise PublicationError("publication journal selects the active generation")

        if generations_fd is not None:
            _generation_directory_metadata(generations_fd, journal.staging_name)
            final_metadata = _generation_directory_metadata(
                generations_fd,
                journal.generation_id,
            )
        else:
            final_metadata = None

        if journal.phase == "prepared" and active_id != journal.generation_id:
            if generations_fd is not None:
                _remove_generation_directory(
                    generations_fd,
                    journal.staging_name,
                )
                _remove_generation_directory(
                    generations_fd,
                    journal.generation_id,
                )
            (root / "transaction.json").unlink(missing_ok=True)
            stale = (
                _cleanup_generations_fd(generations_fd, active_id)
                if generations_fd is not None
                else False
            )
            return PublicationInspection(active_id, "none", stale)

        if active_id != journal.generation_id:
            if final_metadata is None:
                raise PublicationError("published generation is missing during recovery")
            _write_active(root, journal.generation_id)
            active_id = journal.generation_id

        stale = (
            _cleanup_generations_fd(generations_fd, active_id)
            if generations_fd is not None
            else False
        )
        if not stale:
            (root / "transaction.json").unlink(missing_ok=True)
        return PublicationInspection(active_id, "published" if stale else "none", stale)
    finally:
        if generations_fd is not None:
            os.close(generations_fd)


def publish_generation(
    *,
    root: Path,
    files: Mapping[str, bytes],
    fault_injector: FaultInjector | None = None,
) -> PublicationInspection:
    """Publish one complete generation behind an atomic active pointer."""
    if not files:
        raise PublicationError("derived generation must contain at least one file")
    generation_files = dict(files)
    generation_files[_INTEGRITY_FILE] = _integrity_bytes(generation_files)
    generation_id = _generation_id(generation_files)
    generations = root / "generations"
    staging_name = f".staging-{generation_id[:16]}-{secrets.token_hex(4)}"
    staging = generations / staging_name
    final = generations / generation_id

    with PublicationLock(root):
        recover_publication(root)
        previous = _read_active(root)
        generations.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        try:
            _write_generation(staging, generation_files, fault_injector)
            if fault_injector:
                fault_injector("after-generation-write")
            _validate_generation(staging, generation_files)
            if fault_injector:
                fault_injector("after-generation-verify")
            journal = PublicationJournal(
                1,
                generation_id,
                staging_name,
                previous.generation_id if previous else None,
                "prepared",
            )
            _write_journal(root, journal)
            if final.exists():
                _validate_generation(final, generation_files)
                shutil.rmtree(staging)
            else:
                os.replace(staging, final)
            if fault_injector:
                fault_injector("after-generation-install")
            _write_active(root, generation_id)
            _write_journal(
                root,
                PublicationJournal(
                    1,
                    generation_id,
                    staging_name,
                    previous.generation_id if previous else None,
                    "published",
                ),
            )
            if fault_injector:
                fault_injector("after-publication")
            stale = _cleanup_generations(root, generation_id)
            if fault_injector:
                fault_injector("before-cleanup-complete")
            if not stale:
                _write_journal(
                    root,
                    PublicationJournal(
                        1,
                        generation_id,
                        staging_name,
                        previous.generation_id if previous else None,
                        "complete",
                    ),
                )
                (root / "transaction.json").unlink(missing_ok=True)
            return PublicationInspection(generation_id, "published" if stale else "none", stale)
        except Exception:
            if not (root / "transaction.json").exists() and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise


def active_generation_path(root: Path) -> Path | None:
    active = _read_active(root)
    if active is None:
        return None
    path = root / "generations" / active.generation_id
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PublicationError("active generation directory is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PublicationError("active generation directory is invalid")
    return path
