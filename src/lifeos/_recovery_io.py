import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from lifeos._transaction_files import (
    DirectorySyncResult,
    ParentDescriptor,
    StagingFile,
    cleanup_staging,
    create_staging_file,
    fsync_directory,
    get_target_identity,
    TransactionError,
    publish_replacement,
)
import errno


class RecoveryIOError(Exception):
    pass


class RecoveryIOInvalidArtifactError(RecoveryIOError):
    pass


class RecoveryIOCorruptStateError(RecoveryIOError):
    pass


class RecoveryIOUnavailableError(RecoveryIOError):
    pass


class RecoveryIOConflictError(RecoveryIOError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryArtifact:
    relative_path: str
    content_hash: str
    size: int
    mode: int


def _validate_recovery_artifact(artifact: RecoveryArtifact) -> None:
    if type(artifact) is not RecoveryArtifact:
        raise RecoveryIOInvalidArtifactError("Artifact is not exactly a RecoveryArtifact")
    _validate_artifact_relative_path(artifact.relative_path)
    import re

    if type(artifact.content_hash) is not str or not re.match(
        r"^sha256:[0-9a-f]{64}$", artifact.content_hash
    ):
        raise RecoveryIOInvalidArtifactError("Invalid artifact content hash")
    if type(artifact.size) is not int:
        raise RecoveryIOInvalidArtifactError("Artifact size is not an int")
    if artifact.size < 0:
        raise RecoveryIOInvalidArtifactError("Artifact size cannot be negative")
    if type(artifact.mode) is not int:
        raise RecoveryIOInvalidArtifactError("Artifact mode is not an int")
    if not (0o000 <= artifact.mode <= 0o7777):
        raise RecoveryIOInvalidArtifactError("Artifact mode is out of valid range")


def _validate_artifact_relative_path(path: str) -> None:
    if type(path) is not str:
        raise RecoveryIOInvalidArtifactError("relative_path must be a string")
    if not path:
        raise RecoveryIOInvalidArtifactError("relative_path cannot be empty")
    if "\\" in path:
        raise RecoveryIOInvalidArtifactError("relative_path cannot contain backslashes")
    if "\0" in path:
        raise RecoveryIOInvalidArtifactError("relative_path cannot contain NUL")
    if os.path.isabs(path) or path.startswith("/"):
        raise RecoveryIOInvalidArtifactError("relative_path cannot be absolute")

    parts = path.split("/")
    if len(parts) != 2:
        raise RecoveryIOInvalidArtifactError("relative_path must have exactly two components")
    if parts[0] not in ("staged", "backups"):
        raise RecoveryIOInvalidArtifactError("first component must be 'staged' or 'backups'")
    if not parts[1]:
        raise RecoveryIOInvalidArtifactError("second component cannot be empty")
    if "." in parts or ".." in parts:
        raise RecoveryIOInvalidArtifactError("relative_path cannot contain dot or parent segments")


def _validate_permission_mode(mode: object) -> None:
    if type(mode) is not int or type(mode) is bool:
        raise RecoveryIOInvalidArtifactError("mode must be an exact int")
    if not (0o000 <= mode <= 0o7777):
        raise RecoveryIOInvalidArtifactError("mode is out of valid range")


def _hash_fd(fd: int) -> str:
    h = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        h.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return f"sha256:{h.hexdigest()}"


def _open_transaction_dir(transaction_dir: Path) -> int:
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        fd = os.open(transaction_dir, flags)
    except OSError as e:
        raise RecoveryIOCorruptStateError("Failed to securely open transaction directory") from e

    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            os.close(fd)
            raise RecoveryIOCorruptStateError("Transaction is not a directory")
    except OSError as e:
        os.close(fd)
        raise RecoveryIOCorruptStateError("Failed to stat transaction directory") from e

    return fd


def _open_subdirectory(tx_fd: int, subdir_name: str) -> int:
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        fd = os.open(subdir_name, flags, dir_fd=tx_fd)
    except OSError as e:
        raise RecoveryIOCorruptStateError(
            f"Failed to securely open subdirectory {subdir_name}"
        ) from e

    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            os.close(fd)
            raise RecoveryIOCorruptStateError(f"Subdirectory {subdir_name} is not a directory")
    except OSError as e:
        os.close(fd)
        raise RecoveryIOCorruptStateError(f"Failed to stat subdirectory {subdir_name}") from e

    return fd


def _open_artifact_subdirectory(
    transaction_dir: Path,
    subdir: str,
    *,
    transaction_fd: int | None = None,
) -> int:
    if subdir not in ("staged", "backups"):
        raise RecoveryIOInvalidArtifactError("Subdirectory must be staged or backups")
    if transaction_fd is not None:
        return _open_subdirectory(transaction_fd, subdir)

    try:
        tx_path_state = os.lstat(transaction_dir)
    except OSError as error:
        raise RecoveryIOUnavailableError("Failed to inspect transaction directory") from error
    if stat.S_ISLNK(tx_path_state.st_mode) or not stat.S_ISDIR(tx_path_state.st_mode):
        raise RecoveryIOCorruptStateError("Transaction directory symlink or non-directory")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        tx_fd = os.open(transaction_dir, flags)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise RecoveryIOCorruptStateError(
                "Transaction directory symlink or non-directory"
            ) from error
        raise RecoveryIOUnavailableError("Failed to open transaction directory") from error

    sub_fd: int | None = None
    sub_fd_returned = False
    try:
        try:
            tx_fd_state = os.fstat(tx_fd)
        except OSError as error:
            raise RecoveryIOUnavailableError("Failed to stat transaction directory") from error
        if not stat.S_ISDIR(tx_fd_state.st_mode):
            raise RecoveryIOCorruptStateError("Transaction descriptor is not a directory")
        if tx_fd_state.st_dev != tx_path_state.st_dev or tx_fd_state.st_ino != tx_path_state.st_ino:
            raise RecoveryIOCorruptStateError("Transaction directory changed during open")

        try:
            sub_path_state = os.stat(subdir, dir_fd=tx_fd, follow_symlinks=False)
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR):
                raise RecoveryIOCorruptStateError(
                    "Subdirectory symlink or non-directory"
                ) from error
            raise RecoveryIOUnavailableError("Failed to inspect subdirectory") from error
        if stat.S_ISLNK(sub_path_state.st_mode) or not stat.S_ISDIR(sub_path_state.st_mode):
            raise RecoveryIOCorruptStateError("Subdirectory symlink or non-directory")

        try:
            sub_fd = os.open(subdir, flags, dir_fd=tx_fd)
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR):
                raise RecoveryIOCorruptStateError(
                    "Subdirectory symlink or non-directory"
                ) from error
            raise RecoveryIOUnavailableError("Failed to open subdirectory") from error

        try:
            sub_fd_state = os.fstat(sub_fd)
        except OSError as error:
            raise RecoveryIOUnavailableError("Failed to stat subdirectory") from error
        if not stat.S_ISDIR(sub_fd_state.st_mode):
            raise RecoveryIOCorruptStateError("Subdirectory descriptor is not a directory")
        if (
            sub_fd_state.st_dev != sub_path_state.st_dev
            or sub_fd_state.st_ino != sub_path_state.st_ino
        ):
            raise RecoveryIOCorruptStateError("Subdirectory changed during open")

        sub_fd_returned = True
        return sub_fd
    finally:
        if sub_fd is not None and not sub_fd_returned:
            try:
                os.close(sub_fd)
            except OSError:
                pass
        os.close(tx_fd)


def _verify_open_artifact(
    *,
    fd: int,
    expected_size: int,
    expected_hash: str,
    expected_mode: int,
) -> None:
    if type(expected_size) is not int or type(expected_size) is bool:
        raise RecoveryIOInvalidArtifactError("expected_size must be exact int")
    if type(expected_hash) is not str:
        raise RecoveryIOInvalidArtifactError("expected_hash must be exact str")
    if type(expected_mode) is not int or type(expected_mode) is bool:
        raise RecoveryIOInvalidArtifactError("expected_mode must be exact int")

    try:
        st = os.fstat(fd)
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to fstat descriptor") from e

    if not stat.S_ISREG(st.st_mode):
        raise RecoveryIOCorruptStateError("Not a regular file")
    if st.st_size != expected_size:
        raise RecoveryIOCorruptStateError("Size mismatch")
    if stat.S_IMODE(st.st_mode) != stat.S_IMODE(expected_mode):
        raise RecoveryIOCorruptStateError("Mode mismatch")

    h = hashlib.sha256()
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            h.update(chunk)
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to read descriptor for hash") from e

    actual_hash = f"sha256:{h.hexdigest()}"
    if actual_hash != expected_hash:
        raise RecoveryIOCorruptStateError("Hash mismatch")


def write_recovery_artifact(
    *,
    transaction_dir: Path,
    artifact: RecoveryArtifact,
    content: bytes,
    transaction_fd: int | None = None,
) -> None:
    if not isinstance(transaction_dir, Path):
        raise RecoveryIOInvalidArtifactError("transaction_dir must be exactly Path")
    if type(content) is not bytes:
        raise RecoveryIOInvalidArtifactError("content must be exactly bytes")

    _validate_recovery_artifact(artifact)

    subdir, filename = artifact.relative_path.split("/")
    sub_fd = _open_artifact_subdirectory(
        transaction_dir,
        subdir,
        transaction_fd=transaction_fd,
    )

    try:
        try:
            os.stat(filename, dir_fd=sub_fd, follow_symlinks=False)
            raise RecoveryIOConflictError("Existing final entry")
        except FileNotFoundError:
            pass
        except OSError as e:
            raise RecoveryIOUnavailableError("Failed to stat final entry") from e

        tmp_name = f".{filename}.{secrets.token_hex(8)}.tmp"
        try:
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            tmp_fd = os.open(tmp_name, flags, 0o600, dir_fd=sub_fd)
        except OSError as e:
            raise RecoveryIOUnavailableError("Failed to open temporary file") from e

        try:
            written = 0
            while written < len(content):
                chunk = os.write(tmp_fd, content[written:])
                if chunk == 0:
                    raise OSError("Write returned 0")
                written += chunk

            os.fchmod(tmp_fd, artifact.mode)

            _verify_open_artifact(
                fd=tmp_fd,
                expected_size=artifact.size,
                expected_hash=artifact.content_hash,
                expected_mode=artifact.mode,
            )
        except (
            RecoveryIOCorruptStateError,
            RecoveryIOConflictError,
            RecoveryIOInvalidArtifactError,
        ):
            os.close(tmp_fd)
            try:
                os.unlink(tmp_name, dir_fd=sub_fd)
            except OSError:
                pass
            raise
        except OSError as e:
            os.close(tmp_fd)
            try:
                os.unlink(tmp_name, dir_fd=sub_fd)
            except OSError:
                pass
            raise RecoveryIOUnavailableError("Pre-publication failure") from e

        os.close(tmp_fd)

        try:
            os.link(
                tmp_name,
                filename,
                src_dir_fd=sub_fd,
                dst_dir_fd=sub_fd,
                follow_symlinks=False,
            )
        except FileExistsError as e:
            try:
                os.unlink(tmp_name, dir_fd=sub_fd)
            except OSError:
                pass
            raise RecoveryIOConflictError("Publication conflict") from e
        except OSError as e:
            try:
                os.unlink(tmp_name, dir_fd=sub_fd)
            except OSError:
                pass
            raise RecoveryIOUnavailableError("Publication failure") from e

        try:
            os.unlink(tmp_name, dir_fd=sub_fd)
        except OSError as e:
            raise RecoveryIOUnavailableError(
                "Failed to unlink temporary file after publication"
            ) from e

        try:
            final_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            final_fd = os.open(filename, final_flags, dir_fd=sub_fd)
        except OSError as e:
            raise RecoveryIOUnavailableError("Final verification open failure") from e

        try:
            _verify_open_artifact(
                fd=final_fd,
                expected_size=artifact.size,
                expected_hash=artifact.content_hash,
                expected_mode=artifact.mode,
            )
        finally:
            os.close(final_fd)

    finally:
        os.close(sub_fd)


def read_verified_recovery_artifact(
    *,
    transaction_dir: Path,
    artifact: RecoveryArtifact,
    transaction_fd: int | None = None,
) -> bytes:
    _validate_recovery_artifact(artifact)

    subdir, filename = artifact.relative_path.split("/")
    sub_fd = _open_artifact_subdirectory(
        transaction_dir,
        subdir,
        transaction_fd=transaction_fd,
    )

    try:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(filename, flags, dir_fd=sub_fd)
        except OSError as e:
            if getattr(e, "errno", None) == errno.ELOOP:
                raise RecoveryIOCorruptStateError("Corrupt symlink state") from e
            raise RecoveryIOUnavailableError("Failed to open final entry") from e

        try:
            try:
                st = os.fstat(fd)
            except OSError as e:
                raise RecoveryIOUnavailableError("Failed to initial fstat") from e

            if not stat.S_ISREG(st.st_mode):
                raise RecoveryIOCorruptStateError("Not a regular file")
            if st.st_size != artifact.size:
                raise RecoveryIOCorruptStateError("Initial size mismatch")
            if stat.S_IMODE(st.st_mode) != stat.S_IMODE(artifact.mode):
                raise RecoveryIOCorruptStateError("Initial mode mismatch")

            chunks: list[bytes] = []
            try:
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except OSError as e:
                raise RecoveryIOUnavailableError("Failed to read") from e

            content = b"".join(chunks)
            if len(content) != artifact.size:
                raise RecoveryIOCorruptStateError("Exact byte count mismatch")

            if f"sha256:{hashlib.sha256(content).hexdigest()}" != artifact.content_hash:
                raise RecoveryIOCorruptStateError("Content hash mismatch")

            try:
                final_st = os.fstat(fd)
            except OSError as e:
                raise RecoveryIOUnavailableError("Failed to final fstat") from e

            if not stat.S_ISREG(final_st.st_mode):
                raise RecoveryIOCorruptStateError("Not a regular file on final fstat")
            if final_st.st_size != artifact.size:
                raise RecoveryIOCorruptStateError("Final size mismatch")
            if stat.S_IMODE(final_st.st_mode) != stat.S_IMODE(artifact.mode):
                raise RecoveryIOCorruptStateError("Final mode mismatch")

        finally:
            os.close(fd)

    finally:
        os.close(sub_fd)

    return content


def prepare_canonical_staging_from_artifact(
    *,
    transaction_dir: Path,
    artifact: RecoveryArtifact,
    target_name: str,
    target_parent: ParentDescriptor,
    intended_mode: int,
    transaction_fd: int | None = None,
) -> StagingFile:
    _validate_recovery_artifact(artifact)
    _validate_artifact_relative_path("staged/" + target_name)
    if type(target_parent) is not ParentDescriptor:
        raise RecoveryIOInvalidArtifactError("target_parent must be a ParentDescriptor")
    if type(intended_mode) is not int or not (0o000 <= intended_mode <= 0o7777):
        raise RecoveryIOInvalidArtifactError("Invalid intended_mode")
    if artifact.mode != intended_mode:
        raise RecoveryIOInvalidArtifactError("Artifact mode does not match intended mode")

    content = read_verified_recovery_artifact(
        transaction_dir=transaction_dir,
        artifact=artifact,
        transaction_fd=transaction_fd,
    )

    return create_staging_file(
        target_name=target_name,
        content=content,
        parent=target_parent,
        intended_mode=intended_mode,
    )


def remove_installed_creation(
    *,
    target_name: str,
    target_parent: ParentDescriptor,
    expected_installed_hash: str,
    expected_installed_mode: int,
) -> DirectorySyncResult:
    _validate_artifact_relative_path("staged/" + target_name) # Validates it's a valid filename
    if type(target_parent) is not ParentDescriptor:
        raise RecoveryIOInvalidArtifactError("target_parent must be a ParentDescriptor")
    import re

    if type(expected_installed_hash) is not str or not re.match(
        r"^sha256:[0-9a-f]{64}$", expected_installed_hash
    ):
        raise RecoveryIOInvalidArtifactError("Invalid expected_installed_hash")
    if type(expected_installed_mode) is not int or not (0o000 <= expected_installed_mode <= 0o7777):
        raise RecoveryIOInvalidArtifactError("Invalid expected_installed_mode")

    try:
        st = os.stat(target_name, dir_fd=target_parent.fd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise RecoveryIOCorruptStateError("Canonical target is not a regular file")
        if stat.S_IMODE(st.st_mode) != stat.S_IMODE(expected_installed_mode):
            raise RecoveryIOConflictError("Canonical target mode mutated externally")
    except FileNotFoundError as e:
        raise RecoveryIOConflictError("Expected installed target is absent before rollback") from e
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to stat target") from e

    try:
        target_id = get_target_identity(target_name, target_parent)
    except TransactionError as e:
        raise RecoveryIOUnavailableError("Failed to get target identity") from e

    if target_id is None:
        raise RecoveryIOConflictError("Expected installed target is absent before rollback")

    if (
        target_id.content_hash
        if target_id.content_hash.startswith("sha256:")
        else f"sha256:{target_id.content_hash}"
    ) != expected_installed_hash:
        raise RecoveryIOConflictError("Canonical target hash mutated externally")

    live_name = target_name
    live_fd = target_parent.fd
    if target_parent.authority_fd is not None:
        live_name = (
            target_name
            if target_parent.path in ("", ".")
            else f"{target_parent.path}/{target_name}"
        )
        live_fd = target_parent.authority_fd
        try:
            live_state = os.stat(live_name, dir_fd=live_fd, follow_symlinks=False)
        except OSError as e:
            raise RecoveryIOUnavailableError("Failed to inspect live canonical target") from e
        if (live_state.st_dev, live_state.st_ino) != (target_id.dev, target_id.ino):
            raise RecoveryIOConflictError("Canonical target path changed before rollback")
    try:
        os.unlink(live_name, dir_fd=live_fd)
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to unlink target") from e

    try:
        os.stat(target_name, dir_fd=target_parent.fd, follow_symlinks=False)
        raise RecoveryIOCorruptStateError("Target still exists after unlink")
    except FileNotFoundError:
        pass
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to verify target absence") from e

    return fsync_directory(target_parent.fd)


def restore_canonical_from_backup(
    *,
    transaction_dir: Path,
    backup: RecoveryArtifact,
    target_name: str,
    target_parent: ParentDescriptor,
    expected_installed_hash: str,
    expected_installed_mode: int,
    expected_restored_hash: str,
    expected_restored_mode: int,
    transaction_fd: int | None = None,
) -> DirectorySyncResult:
    _validate_recovery_artifact(backup)
    _validate_artifact_relative_path("staged/" + target_name)
    if type(target_parent) is not ParentDescriptor:
        raise RecoveryIOInvalidArtifactError("target_parent must be a ParentDescriptor")
    import re

    if type(expected_installed_hash) is not str or not re.match(
        r"^sha256:[0-9a-f]{64}$", expected_installed_hash
    ):
        raise RecoveryIOInvalidArtifactError("Invalid expected_installed_hash")
    if type(expected_restored_hash) is not str or not re.match(
        r"^sha256:[0-9a-f]{64}$", expected_restored_hash
    ):
        raise RecoveryIOInvalidArtifactError("Invalid expected_restored_hash")
    if type(expected_installed_mode) is not int or not (0o000 <= expected_installed_mode <= 0o7777):
        raise RecoveryIOInvalidArtifactError("Invalid expected_installed_mode")
    if type(expected_restored_mode) is not int or not (0o000 <= expected_restored_mode <= 0o7777):
        raise RecoveryIOInvalidArtifactError("Invalid expected_restored_mode")
    if (
        backup.content_hash
        if backup.content_hash.startswith("sha256:")
        else f"sha256:{backup.content_hash}"
    ) != expected_restored_hash:
        raise RecoveryIOInvalidArtifactError("Backup artifact hash mismatch")
    if backup.mode != expected_restored_mode:
        raise RecoveryIOInvalidArtifactError("Backup artifact mode mismatch")

    target_id = get_target_identity(target_name, target_parent)
    if target_id is None:
        raise RecoveryIOConflictError("Canonical target is absent, expected installed")

    try:
        st = os.stat(target_name, dir_fd=target_parent.fd, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode):
            raise RecoveryIOCorruptStateError("Canonical target is not a regular file")
        if stat.S_IMODE(st.st_mode) != stat.S_IMODE(expected_installed_mode):
            raise RecoveryIOConflictError("Canonical target mode mutated externally")
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to stat canonical target") from e

    if (
        target_id.content_hash
        if target_id.content_hash.startswith("sha256:")
        else f"sha256:{target_id.content_hash}"
    ) != expected_installed_hash:
        raise RecoveryIOConflictError("Canonical target hash mutated externally")

    staging = prepare_canonical_staging_from_artifact(
        transaction_dir=transaction_dir,
        artifact=backup,
        target_name=target_name,
        target_parent=target_parent,
        intended_mode=expected_restored_mode,
        transaction_fd=transaction_fd,
    )

    try:
        result = publish_replacement(
            target_name=target_name,
            staging=staging,
            original_identity=target_id,
        )
    except (OSError, TransactionError):
        try:
            cleanup_staging(staging)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        raise

    restored_id = get_target_identity(target_name, target_parent)
    if restored_id is None:
        raise RecoveryIOCorruptStateError("Canonical target disappeared after restore")
    if (
        restored_id.content_hash
        if restored_id.content_hash.startswith("sha256:")
        else f"sha256:{restored_id.content_hash}"
    ) != expected_restored_hash:
        raise RecoveryIOCorruptStateError("Restored canonical target hash mismatch")

    try:
        st2 = os.stat(target_name, dir_fd=target_parent.fd, follow_symlinks=False)
        if stat.S_IMODE(st2.st_mode) != stat.S_IMODE(expected_restored_mode):
            raise RecoveryIOCorruptStateError("Restored canonical target mode mismatch")
    except OSError as e:
        raise RecoveryIOUnavailableError("Failed to verify restored target mode") from e

    return result
