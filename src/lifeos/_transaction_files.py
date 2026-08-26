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
    authority_fd: int | None = None


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


def _open_relative_directory_chain(root_fd: int, relative_path: str) -> int:
    current_fd = os.dup(root_fd)
    if relative_path in ("", "."):
        return current_fd
    try:
        for component in relative_path.split("/"):
            if component in ("", ".", ".."):
                raise TransactionError("Invalid canonical parent path")
            try:
                next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as error:
                raise TransactionError("Canonical parent directory moved before mutation") from error
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def open_live_parent_for_mutation(parent: ParentDescriptor) -> int:
    """Open the reviewed parent from pinned authority and prove it is the reviewed inode."""
    if parent.authority_fd is None:
        return parent.fd
    live_fd = _open_relative_directory_chain(parent.authority_fd, parent.path)
    live = os.fstat(live_fd)
    if (live.st_dev, live.st_ino) != (parent.dev, parent.ino):
        os.close(live_fd)
        raise TransactionError("Canonical parent directory moved before mutation")
    return live_fd


def _close_live_parent(parent: ParentDescriptor, live_fd: int) -> None:
    if parent.authority_fd is not None:
        os.close(live_fd)


def require_live_parent(parent: ParentDescriptor) -> None:
    """Prove the reviewed vault-relative path still selects the opened parent."""
    if parent.authority_fd is None:
        return
    live_fd = open_live_parent_for_mutation(parent)
    os.close(live_fd)


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


def _target_identity_at(name: str, dir_fd: int) -> TargetIdentity | None:
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise TransactionError(f"Failed to stat {name}: {e}") from e

    if not stat.S_ISREG(st.st_mode):
        raise TransactionError(f"Target {name} is not a regular file")

    content_hash = _hash_file_secure(name, dir_fd)
    return TargetIdentity(dev=st.st_dev, ino=st.st_ino, mode=st.st_mode, content_hash=content_hash)


def _content_identity_matches(observed: TargetIdentity | None, expected: TargetIdentity) -> bool:
    return bool(
        observed is not None
        and observed.dev == expected.dev
        and observed.ino == expected.ino
        and observed.content_hash == expected.content_hash
    )


def _identity_matches(observed: TargetIdentity | None, expected: TargetIdentity) -> bool:
    return bool(
        _content_identity_matches(observed, expected)
        and observed is not None
        and stat.S_IMODE(observed.mode) == stat.S_IMODE(expected.mode)
    )


def _create_verified_guard(
    target_name: str,
    guard_name: str,
    dir_fd: int,
    expected_identity: TargetIdentity,
    *,
    require_mode: bool,
) -> None:
    """Hard-link the live target and prove the link captured the reviewed inode."""
    try:
        os.link(
            target_name,
            guard_name,
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        raise TransactionError(f"Failed to create mutation guard: {error}") from error

    try:
        guard_identity = _target_identity_at(guard_name, dir_fd)
        matches = (
            _identity_matches(guard_identity, expected_identity)
            if require_mode
            else _content_identity_matches(guard_identity, expected_identity)
        )
        if not matches:
            raise TransactionError("Mutation guard captured an unexpected target identity")
    except Exception as error:
        try:
            _remove_created_artifact(guard_name, dir_fd)
        except TransactionError as cleanup_error:
            raise TransactionError(
                f"Mutation guard verification failed: {error}. Cleanup failed: {cleanup_error}"
            ) from error
        if isinstance(error, TransactionError):
            raise
        raise TransactionError(f"Mutation guard verification failed: {error}") from error


def get_target_identity(name: str, parent: ParentDescriptor) -> TargetIdentity | None:
    return _target_identity_at(name, parent.fd)


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


def _remove_created_artifact(name: str, parent_fd: int) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    except OSError as error:
        raise TransactionError(f"Failed to clean up transaction artifact {name}: {error}") from error


def create_staging_file(
    target_name: str, content: bytes, parent: ParentDescriptor, intended_mode: int
) -> StagingFile:
    require_live_parent(parent)
    parent_binding = capture_directory_binding(parent.fd)
    random_hex = secrets.token_hex(8)
    staging_name = f".{target_name}.{random_hex}.staged"

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    live_parent_fd: int | None = None
    try:
        require_directory_binding(parent.fd, parent_binding)
        live_parent_fd = open_live_parent_for_mutation(parent)
        fd = os.open(staging_name, flags, 0o600, dir_fd=live_parent_fd)
    except (OSError, TransactionError) as e:
        raise TransactionError(f"Failed to create staging file {staging_name}: {e}") from e
    finally:
        if live_parent_fd is not None:
            _close_live_parent(parent, live_parent_fd)

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
            _remove_created_artifact(staging_name, parent.fd)
        except TransactionError as unlink_e:
            raise TransactionError(f"Failed to stage data: {e}. Unlink failed: {unlink_e}") from e
        raise TransactionError(f"Failed to stage data: {e}") from e

    os.close(fd)

    candidate_hash = _hash_file_secure(staging_name, parent.fd)
    expected_hash = hashlib.sha256(content).hexdigest()
    if candidate_hash != expected_hash:
        try:
            _remove_created_artifact(staging_name, parent.fd)
        except TransactionError as unlink_e:
            raise TransactionError(
                f"Staging file hash verification failed. Unlink failed: {unlink_e}"
            ) from unlink_e
        raise TransactionError("Staging file hash verification failed")

    try:
        require_directory_binding(parent.fd, parent_binding)
        require_live_parent(parent)
    except TransactionError as error:
        try:
            _remove_created_artifact(staging_name, parent.fd)
        except TransactionError as cleanup_error:
            raise TransactionError(
                f"Canonical parent directory moved before mutation; cleanup failed: {cleanup_error}"
            ) from error
        raise

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
    live_parent_fd: int | None = None

    try:
        live_parent_fd = open_live_parent_for_mutation(parent)
        live_identity = _target_identity_at(target_name, live_parent_fd)
        if not _content_identity_matches(live_identity, original_identity):
            raise TransactionError("Target identity mutated before backup")
        os.link(
            target_name,
            backup_name,
            src_dir_fd=live_parent_fd,
            dst_dir_fd=live_parent_fd,
            follow_symlinks=False,
        )
    except OSError as e:
        raise TransactionError(f"Failed to create hardlink backup: {e}") from e
    finally:
        if live_parent_fd is not None:
            _close_live_parent(parent, live_parent_fd)

    try:
        st = os.stat(backup_name, dir_fd=parent.fd, follow_symlinks=False)
        if st.st_dev != original_identity.dev or st.st_ino != original_identity.ino:
            raise TransactionError("Backup identity mismatch")

        backup_hash = _hash_file_secure(backup_name, parent.fd)
        if backup_hash != original_identity.content_hash:
            raise TransactionError("Backup content hash mismatch")

        require_live_parent(parent)
        sync_result = fsync_directory(parent.fd)
        if sync_result.state == DirectorySyncState.FAILED:
            raise TransactionError(f"Directory sync failed with errno {sync_result.errno_name}")

    except Exception as e:
        try:
            _remove_created_artifact(backup_name, parent.fd)
        except TransactionError as unlink_e:
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

    live_parent_fd = open_live_parent_for_mutation(staging.parent)
    try:
        try:
            os.stat(target_name, dir_fd=live_parent_fd, follow_symlinks=False)
            raise TransactionError("Target already exists during creation publication")
        except FileNotFoundError:
            pass
        os.link(
            staging.name,
            target_name,
            src_dir_fd=staging.parent.fd,
            dst_dir_fd=live_parent_fd,
            follow_symlinks=False,
        )
        try:
            require_live_parent(staging.parent)
        except TransactionError:
            try:
                os.unlink(target_name, dir_fd=live_parent_fd)
            except OSError:
                pass
            raise
    except OSError as e:
        raise TransactionError(f"Failed to publish creation via link: {e}") from e
    finally:
        _close_live_parent(staging.parent, live_parent_fd)

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
    if not _content_identity_matches(current_target, original_identity):
        if current_target is None:
            raise TransactionError("Target identity mutated (absent) before replacement")
        if (
            current_target.dev != original_identity.dev
            or current_target.ino != original_identity.ino
        ):
            raise TransactionError("Target identity mutated before replacement")
        raise TransactionError("Target content hash mutated before replacement")

    current_staging_hash = _hash_file_secure(staging.name, staging.parent.fd)
    if current_staging_hash != staging.candidate_hash:
        raise TransactionError("Staging hash mutated before publication")

    st = os.stat(staging.name, dir_fd=staging.parent.fd, follow_symlinks=False)
    if stat.S_IMODE(st.st_mode) != stat.S_IMODE(staging.intended_mode):
        raise TransactionError("Staging mode mutated before publication")
    require_directory_binding(staging.parent.fd, staging.parent_binding)

    live_parent_fd = open_live_parent_for_mutation(staging.parent)
    guard_name = f".{target_name}.{secrets.token_hex(8)}.replace-guard"
    guard_created = False
    try:
        live_identity = _target_identity_at(target_name, live_parent_fd)
        if not _content_identity_matches(live_identity, original_identity):
            raise TransactionError("Target identity mutated before replacement")
        _create_verified_guard(
            target_name,
            guard_name,
            live_parent_fd,
            original_identity,
            require_mode=False,
        )
        guard_created = True
        os.replace(
            staging.name,
            target_name,
            src_dir_fd=staging.parent.fd,
            dst_dir_fd=live_parent_fd,
        )
        try:
            require_live_parent(staging.parent)
        except TransactionError as binding_error:
            try:
                os.replace(
                    guard_name,
                    target_name,
                    src_dir_fd=live_parent_fd,
                    dst_dir_fd=live_parent_fd,
                )
                guard_created = False
            except OSError as restore_error:
                raise TransactionError(
                    "Canonical parent moved after replacement and original restoration failed"
                ) from restore_error
            raise binding_error
    except OSError as e:
        raise TransactionError(f"Failed to publish replacement: {e}") from e
    finally:
        if guard_created:
            try:
                os.unlink(guard_name, dir_fd=live_parent_fd)
            except OSError:
                pass
        _close_live_parent(staging.parent, live_parent_fd)

    return fsync_directory(staging.parent.fd)


def remove_verified_target(
    target_name: str,
    parent: ParentDescriptor,
    expected_identity: TargetIdentity,
) -> DirectorySyncResult:
    """Remove one reviewed target without ever switching to a replacement parent inode."""
    live_parent_fd = open_live_parent_for_mutation(parent)
    guard_name = f".{target_name}.{secrets.token_hex(8)}.unlink-guard"
    guard_created = False
    try:
        live_identity = _target_identity_at(target_name, live_parent_fd)
        if not _identity_matches(live_identity, expected_identity):
            raise TransactionError("Canonical target changed before removal")
        _create_verified_guard(
            target_name,
            guard_name,
            live_parent_fd,
            expected_identity,
            require_mode=True,
        )
        guard_created = True
        os.unlink(target_name, dir_fd=live_parent_fd)
        try:
            require_live_parent(parent)
        except TransactionError as binding_error:
            try:
                os.replace(
                    guard_name,
                    target_name,
                    src_dir_fd=live_parent_fd,
                    dst_dir_fd=live_parent_fd,
                )
                guard_created = False
            except OSError as restore_error:
                raise TransactionError(
                    "Canonical parent moved after removal and target restoration failed"
                ) from restore_error
            raise binding_error
        os.unlink(guard_name, dir_fd=live_parent_fd)
        guard_created = False
    except OSError as e:
        raise TransactionError(f"Failed to remove verified target: {e}") from e
    finally:
        if guard_created:
            try:
                os.unlink(guard_name, dir_fd=live_parent_fd)
            except OSError:
                pass
        _close_live_parent(parent, live_parent_fd)

    return fsync_directory(parent.fd)


def rollback_creation(target_name: str, staging: StagingFile) -> DirectorySyncResult:
    require_directory_binding(staging.parent.fd, staging.parent_binding)
    current_identity = get_target_identity(target_name, staging.parent)
    if current_identity is None:
        return DirectorySyncResult(DirectorySyncState.CONFIRMED, None)  # already absent
    if current_identity.content_hash != staging.candidate_hash:
        raise TransactionError("Canonical file mutated externally, rollback refused")
    require_directory_binding(staging.parent.fd, staging.parent_binding)
    return remove_verified_target(target_name, staging.parent, current_identity)


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
        raise TransactionError("Backup content hash mutated")
    require_directory_binding(staging.parent.fd, staging.parent_binding)

    live_parent_fd = open_live_parent_for_mutation(staging.parent)
    guard_name = f".{target_name}.{secrets.token_hex(8)}.rollback-guard"
    guard_created = False
    try:
        live_target = _target_identity_at(target_name, live_parent_fd)
        if live_target is None or live_target.content_hash != staging.candidate_hash:
            raise TransactionError("Canonical file mutated externally, rollback refused")
        _create_verified_guard(
            target_name,
            guard_name,
            live_parent_fd,
            live_target,
            require_mode=True,
        )
        guard_created = True
        os.replace(
            backup.name,
            target_name,
            src_dir_fd=backup.parent.fd,
            dst_dir_fd=live_parent_fd,
        )
        require_live_parent(staging.parent)
    except OSError as e:
        raise TransactionError(f"Rollback replace failed: {e}") from e
    finally:
        if guard_created:
            try:
                os.unlink(guard_name, dir_fd=live_parent_fd)
            except OSError:
                pass
        _close_live_parent(staging.parent, live_parent_fd)

    return fsync_directory(staging.parent.fd)


def cleanup_staging(staging: StagingFile) -> None:
    os.unlink(staging.name, dir_fd=staging.parent.fd)


def cleanup_backup(backup: BackupFile) -> None:
    os.unlink(backup.name, dir_fd=backup.parent.fd)