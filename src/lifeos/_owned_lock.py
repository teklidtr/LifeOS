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

    def _restore_quarantined_entry(self, quarantine_name: str) -> None:
        try:
            os.link(
                quarantine_name,
                self.filename,
                src_dir_fd=self.dir_fd,
                dst_dir_fd=self.dir_fd,
                follow_symlinks=False,
            )
        except OSError:
            return

        try:
            os.unlink(quarantine_name, dir_fd=self.dir_fd)
        except OSError:
            pass

    def _cleanup_failed_acquisition(self, fd: int) -> None:
        try:
            held_stat = os.fstat(fd)
            quarantine_name = (
                f".{self.filename}.{secrets.token_hex(16)}.failed-acquire-quarantine"
            )
            os.replace(
                self.filename,
                quarantine_name,
                src_dir_fd=self.dir_fd,
                dst_dir_fd=self.dir_fd,
            )
            quarantined_stat = os.stat(
                quarantine_name,
                dir_fd=self.dir_fd,
                follow_symlinks=False,
            )
            if (
                held_stat.st_ino == quarantined_stat.st_ino
                and held_stat.st_dev == quarantined_stat.st_dev
            ):
                try:
                    os.unlink(quarantine_name, dir_fd=self.dir_fd)
                except OSError:
                    pass
            else:
                self._restore_quarantined_entry(quarantine_name)
        except Exception:
            # Cleanup must not mask the token-write/fsync error that caused acquisition to fail.
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

            self.lock_fd = None
            self.token = b""

    def acquire(self) -> None:
        if self.lock_fd is not None:
            raise LockError("Lock already acquired")

        self.token = b""
        token = secrets.token_hex(16).encode("utf-8")

        try:
            fd = os.open(
                self.filename,
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
            self._cleanup_failed_acquisition(fd)
            raise

        self.token = token
        self.lock_fd = fd

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

            if held_stat.st_ino == current_stat.st_ino and held_stat.st_dev == current_stat.st_dev:
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
