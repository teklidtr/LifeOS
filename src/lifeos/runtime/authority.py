"""Descriptor-bound authority for long-lived disposable runtime state."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


class RuntimeAuthorityError(RuntimeError):
    """Raised when runtime storage cannot be bound to a safe directory inode."""


def _open_absolute_directory(path: Path) -> int:
    candidate = Path(os.path.abspath(path))
    if not candidate.is_absolute():
        raise RuntimeAuthorityError("Runtime directory authority requires an absolute path")

    current_fd = os.open(candidate.anchor, _DIRECTORY_FLAGS)
    try:
        for component in candidate.parts[1:]:
            next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


@dataclass(slots=True)
class RuntimeDirectoryAuthority:
    """Keep one runtime directory inode open for the lifetime of a service process."""

    path: Path
    fd: int
    device: int
    inode: int

    @classmethod
    def open(cls, path: Path) -> "RuntimeDirectoryAuthority":
        candidate = Path(os.path.abspath(path))
        parent_fd = -1
        runtime_fd = -1
        try:
            parent_fd = _open_absolute_directory(candidate.parent)
            try:
                runtime_fd = os.open(candidate.name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(candidate.name, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    # A concurrent creator won the race; the no-follow open below decides
                    # whether the resulting entry is acceptable.
                    pass
                runtime_fd = os.open(candidate.name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            state = os.fstat(runtime_fd)
            if not stat.S_ISDIR(state.st_mode):
                raise RuntimeAuthorityError("Runtime path is not a directory")
            return cls(
                path=candidate,
                fd=runtime_fd,
                device=state.st_dev,
                inode=state.st_ino,
            )
        except RuntimeAuthorityError:
            if runtime_fd != -1:
                os.close(runtime_fd)
            raise
        except OSError as exc:
            if runtime_fd != -1:
                os.close(runtime_fd)
            raise RuntimeAuthorityError(
                f"Could not bind runtime directory authority: {exc}"
            ) from exc
        finally:
            if parent_fd != -1:
                os.close(parent_fd)

    def path_is_current(self) -> bool:
        """Return whether the configured pathname still selects the pinned directory inode."""
        current_fd = -1
        try:
            current_fd = _open_absolute_directory(self.path)
            state = os.fstat(current_fd)
            return (state.st_dev, state.st_ino) == (self.device, self.inode)
        except (OSError, RuntimeAuthorityError):
            return False
        finally:
            if current_fd != -1:
                os.close(current_fd)

    def close(self) -> None:
        """Release the pinned directory descriptor."""
        if self.fd != -1:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "RuntimeDirectoryAuthority":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()
