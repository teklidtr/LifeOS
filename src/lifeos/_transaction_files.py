import os
import secrets
import stat
import hashlib
import sys
import errno
from enum import Enum
from dataclasses import dataclass


class TransactionError(Exception):
    pass


class DirectorySyncState(str, Enum):
    CONFIRMED = "confirmed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True)
class DirectorySyncResult:
    state: DirectorySyncState
    errno_name: str | None


@dataclass(frozen=True)
class ParentDescriptor:
    fd: int
    dev: int
    ino: int
    path: str


@dataclass(frozen=True)
class TargetIdentity:
    dev: int
    ino: int
    mode: int
    content_hash: str


DirectoryBinding = tuple[tuple[int, int, str, int, int], ...]


@dataclass(frozen=True)
class StagingFile:
    name: str
    parent: ParentDescriptor
    candidate_hash: str
    size: int
    intended_mode: int
    parent_binding: DirectoryBinding


@dataclass(frozen=True)
class BackupFile:
    name: str
    parent: ParentDescriptor
    original_identity: TargetIdentity
    sync_result: DirectorySyncResult


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _directory_entry_name(parent_fd: int, child_stat: os.stat_result) -> str:
    try:
        with os.scandir(parent_fd) as entries:
            for entry in entries:
                try:
                    observed = os.stat(entry.name, dir_fd=parent_fd, follow_symlinks=False)
                except OSError:
                    continue
                if (observed.st_dev, observed.st_ino) == (
                    child_stat.st_dev,
                    child_stat.st_ino,
                ):
                    return entry.name
    except OSError as error:
        raise TransactionError("Failed to inspect canonical parent binding") from error
    raise TransactionError("Canonical parent directory is detached from its live path")


def capture_directory_binding(fd: int) -> DirectoryBinding:
    """Capture the live ancestry of an opened directory descriptor."""
    current_fd = os.dup(fd)
    binding: list[tuple[int, int, str, int, int]] = []
    try:
        while True:
            child_stat = os.fstat(current_fd)
            try:
                parent_fd = os.open("..", _DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as error:
                raise TransactionError("Failed to inspect canonical parent binding") from error
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) == (
                child_stat.st_dev,
                child_stat.st_ino,
            ):
                os.close(parent_fd)
                break
            name = _directory_entry_name(parent_fd, child_stat)
            binding.append(
                (
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                    name,
                    child_stat.st_dev,
                    child_stat.st_ino,
                )
            )
            os.close(current_fd)
            current_fd = parent_fd
        return tuple(binding)
    finally:
        os.close(current_fd)


def require_directory_binding(fd: int, expected: DirectoryBinding) -> None:
    """Fail closed when an opened canonical parent no longer has its reviewed ancestry."""
    if capture_directory_binding(fd) != expected:
        raise TransactionError("Canonical parent directory moved before mutation")


def _hash_fd(fd: int) -> str:
    hasher = hashlib.sha256()
    with os.fdopen(os.dup(fd), "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _hash_file_secure(name: str, dir_fd: int) -> str:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError as e:
        raise TransactionError(f"Failed to open for hashing: {e}") from e
    try:
        return _hash_fd(fd)
    finally:
        os.close(fd)


def get_target_identity(name: str, parent: ParentDescriptor) -> TargetIdentity | None:
    try:
        st = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise TransactionError(f"Failed to stat {name}: {e}") from e

    if not stat.S_ISREG(st.st_mode):
        raise TransactionError(f"Target {name} is not a regular file")

    content_hash = _hash_file_secure(name, parent.fd)
    return TargetIdentity(dev=st.st_dev, ino=st.st_ino, mode=st.st_mode, content_hash=content_hash)


def fsync_directory(fd: int) -> DirectorySyncResult:
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            return DirectorySyncResult(state=DirectorySyncState.FAILED, errno_name="ENOTDIR")
    except OSError as e:
        err_name = errno.errorcode.get(e.errno, str(e.errno)) if e.errno is not None else "UNKNOWN"
        return DirectorySyncResult(state=DirectorySyncState.FAILED, errno_name=err_name)

    while True:
        try:
            os.fsync(fd)
            return DirectorySyncResult(state=DirectorySyncState.CONFIRMED, errno_name=None)
        except OSError as e:
            if e.errno == errno.EINTR:
                continue
            err_name = (
                errno.errorcode.get(e.errno, str(e.errno)) if e.errno is not None else "UNKNOWN"
            )
            if e.errno in (
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
                errno.ENOSYS,
            ):
                return DirectorySyncResult(
                    state=DirectorySyncState.UNSUPPORTED, errno_name=err_name
                )
            if e.errno == errno.EINVAL and sys.platform == "darwin":
                return DirectorySyncResult(
                    state=DirectorySyncState.UNSUPPORTED, errno_name=err_name
                )
            return DirectorySyncResult(state=DirectorySyncState.FAILED, errno_name=err_name)


def create_staging_file(
    target_name: str, content: bytes, parent: ParentDescriptor, intended_mode: int
) -> StagingFile:
    parent_binding = capture_directory_binding(parent.fd)
    random_hex = secrets.token_hex(8)
    staging_name = f".{target_name}.{random_hex}.staged"

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        require_directory_binding(parent.fd, parent_binding)
        fd = os.open(staging_name, flags, 0o600, dir_fd=parent.fd)
    except OSError as e:
        raise TransactionError(f"Failed to create staging file {staging_name}: {e}") from e

    try:
        written = 0
        while written < len(content):
            chunk = os.write(fd, content[written:])
            if chunk == 0:
                raise OSError("write returned 0 bytes")
            written += chunk

        os.fchmod(fd, intended_mode)
        while True:
            try:
                os.fsync(fd)
                break
            except OSError as sync_e:
                if sync_e.errno == errno.EINTR:
                    continue
                raise

        st = os.fstat(fd)
        if st.st_size != len(content):
            raise TransactionError("Staging file size mismatch after write")

    except Exception as e:
        os.close(fd)
        try:
            os.unlink(staging_name, dir_fd=parent.fd)
        except OSError as unlink_e:
            raise TransactionError(f"Failed to stage data: {e}. Unlink failed: {unlink_e}") from e
        raise TransactionError(f"Failed to stage data: {e}") from e

    os.close(fd)

    candidate_hash = _hash_file_secure(staging_name, parent.fd)
    expected_hash = hashlib.sha256(content).hexdigest()
    if candidate_hash != expected_hash:
        try:
            os.unlink(staging_name, dir_fd=parent.fd)
        except OSError as unlink_e:
            raise TransactionError(
                f"Staging file hash verification failed. Unlink failed: {unlink_e}"
            )
        raise TransactionError("Staging file hash verification failed")
    require_directory_binding(parent.fd, parent_binding)

    return StagingFile(
        name=staging_name,
        parent=parent,
        candidate_hash=candidate_hash,
        size=len(content),
        intended_mode=intended_mode,
        parent_binding=parent_binding,
    )


def create_hardlink_backup(
    target_name: str, parent: ParentDescriptor, original_identity: TargetIdentity
) -> BackupFile:
    random_hex = secrets.token_hex(8)
    backup_name = f".{target_name}.{random_hex}.backup"

    try:
        os.link(
            target_name,
            backup_name,
            src_dir_fd=parent.fd,
            dst_dir_fd=parent.fd,
            follow_symlinks=False,
        )
    except OSError as e:
        raise TransactionError(f"Failed to create hardlink backup: {e}") from e

    try:
        st = os.stat(backup_name, dir_fd=parent.fd, follow_symlinks=False)
        if st.st_dev != original_identity.dev or st.st_ino != original_identity.ino:
            raise TransactionError("Backup identity mismatch")

        backup_hash = _hash_file_secure(backup_name, parent.fd)
        if backup_hash != original_identity.content_hash:
            raise TransactionError("Backup content hash mismatch")

        sync_result = fsync_directory(parent.fd)
        if sync_result.state == DirectorySyncState.FAILED:
            raise TransactionError(f"Directory sync failed with errno {sync_result.errno_name}")

    except Exception as e:
        try:
            os.unlink(backup_name, dir_fd=parent.fd)
        except OSError as unlink_e:
            raise TransactionError(
                f"Backup verification failed: {e}. Unlink failed: {unlink_e}"
            ) from e
        raise TransactionError(f"Backup verification failed: {e}") from e

    return BackupFile(
        name=backup_name,
        parent=parent,
        original_identity=original_identity,
        sync_result=sync_result,
    )


def publish_creation(target_name: str, staging: StagingFile) -> DirectorySyncResult:
    require_directory_binding(staging.parent.fd, staging.parent_binding)
    try:
        os.stat(target_name, dir_fd=staging.parent.fd, follow_symlinks=False)
        raise TransactionError("Target already exists during creation publication")
    except FileNotFoundError:
        pass
    except OSError as e:
        raise TransactionError(f"Failed to verify target absence: {e}") from e

    current_staging_hash = _hash_file_secure(staging.name, staging.parent.fd)
    if current_staging_hash != staging.candidate_hash:
        raise TransactionError("Staging hash mutated before publication")
    require_directory_binding(staging.parent.fd, staging.parent_binding)

    try:
        os.link(
            staging.name,
            target_name,
            src_dir_fd=staging.parent.fd,
            dst_dir_fd=staging.parent.fd,
            follow_symlinks=False,
        )
    except OSError as e:
        raise TransactionError(f"Failed to publish creation via link: {e}") from e

    try:
        os.unlink(staging.name, dir_fd=staging.parent.fd)
    except OSError:
        pass  # Not critical to failure of publication

    return fsync_directory(staging.parent.fd)


def publish_replacement(
    target_name: str, staging: StagingFile, original_identity: TargetIdentity
) -> DirectorySyncResult:
    require_directory_binding(staging.parent.fd, staging.parent_binding)
    current_target = get_target_identity(target_name, staging.parent)
    if current_target is None:
        raise TransactionError("Target identity mutated (absent) before replacement")
    if current_target.dev != original_identity.dev or current_target.ino != original_identity.ino:
        raise TransactionError("Target identity mutated before replacement")
    if current_target.content_hash != original_identity.content_hash:
        raise TransactionError("Target content hash mutated before replacement")

    current_staging_hash = _hash_file_secure(staging.name, staging.parent.fd)
    if current_staging_hash != staging.candidate_hash:
        raise TransactionError("Staging hash mutated before publication")

    st = os.stat(staging.name, dir_fd=staging.parent.fd, follow_symlinks=False)
    if stat.S_IMODE(st.st_mode) != stat.S_IMODE(staging.intended_mode):
        raise TransactionError("Staging mode mutated before publication")
    require_directory_binding(staging.parent.fd, staging.parent_binding)

    try:
        os.replace(
            staging.name, target_name, src_dir_fd=staging.parent.fd, dst_dir_fd=staging.parent.fd
        )
    except OSError as e:
        raise TransactionError(f"Failed to publish replacement: {e}") from e

    return fsync_directory(staging.parent.fd)


def rollback_creation(target_name: str, staging: StagingFile) -> DirectorySyncResult:
    require_directory_binding(staging.parent.fd, staging.parent_binding)
    try:
        os.stat(target_name, dir_fd=staging.parent.fd, follow_symlinks=False)
    except FileNotFoundError:
        return DirectorySyncResult(DirectorySyncState.CONFIRMED, None)  # already absent
    except OSError as e:
        raise TransactionError(f"Rollback stat failed: {e}") from e

    current_hash = _hash_file_secure(target_name, staging.parent.fd)
    if current_hash != staging.candidate_hash:
        raise TransactionError("Canonical file mutated externally, rollback refused")
    require_directory_binding(staging.parent.fd, staging.parent_binding)

    try:
        os.unlink(target_name, dir_fd=staging.parent.fd)
    except OSError as e:
        raise TransactionError(f"Rollback unlink failed: {e}") from e

    return fsync_directory(staging.parent.fd)


def rollback_replacement(
    target_name: str, staging: StagingFile, backup: BackupFile
) -> DirectorySyncResult:
    require_directory_binding(staging.parent.fd, staging.parent_binding)
    try:
        os.stat(target_name, dir_fd=staging.parent.fd, follow_symlinks=False)
    except OSError as e:
        raise TransactionError(f"Rollback target stat failed: {e}") from e

    current_hash = _hash_file_secure(target_name, staging.parent.fd)
    if current_hash != staging.candidate_hash:
        raise TransactionError("Canonical file mutated externally, rollback refused")

    try:
        bk_st = os.stat(backup.name, dir_fd=backup.parent.fd, follow_symlinks=False)
    except OSError as e:
        raise TransactionError(f"Rollback backup stat failed: {e}") from e

    if bk_st.st_dev != backup.original_identity.dev or bk_st.st_ino != backup.original_identity.ino:
        raise TransactionError("Backup identity mutated")

    bk_hash = _hash_file_secure(backup.name, backup.parent.fd)
    if bk_hash != backup.original_identity.content_hash:
        raise TransactionError("Backup identity mutated")
    require_directory_binding(staging.parent.fd, staging.parent_binding)

    try:
        os.replace(
            backup.name, target_name, src_dir_fd=backup.parent.fd, dst_dir_fd=staging.parent.fd
        )
    except OSError as e:
        raise TransactionError(f"Rollback replace failed: {e}") from e

    return fsync_directory(staging.parent.fd)


def cleanup_staging(staging: StagingFile) -> None:
    os.unlink(staging.name, dir_fd=staging.parent.fd)


def cleanup_backup(backup: BackupFile) -> None:
    os.unlink(backup.name, dir_fd=backup.parent.fd)
