import os
import secrets
from typing import Optional, Any
from dataclasses import dataclass


class LockError(Exception):
    """Raised when lock acquisition fails."""

    pass


@dataclass(frozen=True)
class LockReleaseResult:
    ownership_verified: bool
    path_unlinked: bool
    descriptor_closed: bool
    released: bool


class OwnedLock:
    def __init__(self, dir_fd: int, filename: str) -> None:
        self.dir_fd = dir_fd
        self.filename = filename
        self.lock_fd: Optional[int] = None
        self.token: bytes = b""

    @staticmethod
    def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
        return left.st_ino == right.st_ino and left.st_dev == right.st_dev

    def _cleanup_staging_alias(self, fd: int, staging_name: str) -> None:
        try:
            cleanup_name = f".{staging_name}.{secrets.token_hex(16)}.cleanup"
            held_stat = os.fstat(fd)
            os.rename(
                staging_name,
                cleanup_name,
                src_dir_fd=self.dir_fd,
                dst_dir_fd=self.dir_fd,
            )
            cleanup_stat = os.stat(
                cleanup_name,
                dir_fd=self.dir_fd,
                follow_symlinks=False,
            )
            if self._same_identity(held_stat, cleanup_stat):
                try:
                    os.unlink(cleanup_name, dir_fd=self.dir_fd)
                except OSError:
                    pass
                return

            # The random staging pathname was replaced before cleanup. Restore the foreign entry
            # without overwriting anything newer and never unlink it unless restoration succeeded.
            try:
                os.link(
                    cleanup_name,
                    staging_name,
                    src_dir_fd=self.dir_fd,
                    dst_dir_fd=self.dir_fd,
                    follow_symlinks=False,
                )
            except OSError:
                return
            try:
                os.unlink(cleanup_name, dir_fd=self.dir_fd)
            except OSError:
                pass
        except Exception:
            # Alias cleanup is always best-effort. In particular, cleanup-name generation must not
            # mask a primary acquisition error or turn an already-published lock into an unowned
            # failure.
            pass

    def _cleanup_unpublished_acquisition(self, fd: int, staging_name: str) -> None:
        try:
            self._cleanup_staging_alias(fd, staging_name)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

            self.lock_fd = None
            self.token = b""

    def _require_canonical_absent(self) -> None:
        try:
            os.stat(self.filename, dir_fd=self.dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as e:
            raise LockError("Failed to acquire lock: already exists or permission denied") from e
        raise LockError("Failed to acquire lock: already exists or permission denied")

    def acquire(self) -> None:
        if self.lock_fd is not None:
            raise LockError("Lock already acquired")

        self.token = b""
        self._require_canonical_absent()
        token = secrets.token_hex(16).encode("utf-8")
        staging_name = f".{self.filename}.{secrets.token_hex(16)}.acquiring"

        try:
            fd = os.open(
                staging_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self.dir_fd,
            )
        except OSError as e:
            raise LockError("Failed to acquire lock: already exists or permission denied") from e

        try:
            written = 0
            while written < len(token):
                chunk = os.write(fd, token[written:])
                if chunk <= 0:
                    raise OSError("write returned 0 bytes")
                written += chunk
            os.fsync(fd)
        except OSError:
            self._cleanup_unpublished_acquisition(fd, staging_name)
            raise

        try:
            os.link(
                staging_name,
                self.filename,
                src_dir_fd=self.dir_fd,
                dst_dir_fd=self.dir_fd,
                follow_symlinks=False,
            )
        except OSError as e:
            self._cleanup_unpublished_acquisition(fd, staging_name)
            raise LockError("Failed to acquire lock: already exists or permission denied") from e

        try:
            held_stat = os.fstat(fd)
            canonical_stat = os.stat(
                self.filename,
                dir_fd=self.dir_fd,
                follow_symlinks=False,
            )
        except OSError as e:
            self._cleanup_unpublished_acquisition(fd, staging_name)
            raise LockError("Failed to acquire lock: already exists or permission denied") from e
        if not self._same_identity(held_stat, canonical_stat):
            self._cleanup_unpublished_acquisition(fd, staging_name)
            raise LockError("Failed to acquire lock: already exists or permission denied")

        # The canonical name now verifiably selects the held descriptor. Record ownership before
        # any best-effort alias cleanup so no cleanup failure can strand a published lock outside
        # instance state.
        self.token = token
        self.lock_fd = fd
        self._cleanup_staging_alias(fd, staging_name)

    def release(self) -> LockReleaseResult:
        if self.lock_fd is None:
            return LockReleaseResult(False, False, False, False)

        ownership_verified = False
        path_unlinked = False
        descriptor_closed = False
        released = False

        try:
            held_stat = os.fstat(self.lock_fd)
            current_stat = os.stat(self.filename, dir_fd=self.dir_fd, follow_symlinks=False)

            if self._same_identity(held_stat, current_stat):
                os.lseek(self.lock_fd, 0, os.SEEK_SET)
                current_token = os.read(self.lock_fd, 1024)
                if current_token == self.token:
                    ownership_verified = True
        except OSError:
            pass

        if ownership_verified:
            try:
                os.unlink(self.filename, dir_fd=self.dir_fd)
                path_unlinked = True
                released = True
            except OSError:
                pass

        try:
            os.close(self.lock_fd)
            descriptor_closed = True
        except OSError:
            pass

        self.lock_fd = None

        return LockReleaseResult(
            ownership_verified=ownership_verified,
            path_unlinked=path_unlinked,
            descriptor_closed=descriptor_closed,
            released=released,
        )

    def __enter__(self) -> "OwnedLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
