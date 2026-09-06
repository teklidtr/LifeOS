import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SecureIOError(Exception):
    code: str
    message: str


def _open_absolute_directory_secure(dir_path: Path, flags: int) -> int:
    """Open an absolute directory path component-by-component without following symlinks."""
    absolute = Path(os.path.abspath(dir_path))
    current_fd = os.open(absolute.anchor or os.sep, flags)
    try:
        for component in absolute.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError:
        os.close(current_fd)
        raise


def open_directory_secure(dir_path: Path, dir_fd: int | None = None) -> int:
    """Securely open a directory, rejecting symlinks in the entire traversed path.
    Returns a file descriptor for the directory.
    """
    path_str = str(dir_path) if dir_fd is None else dir_path.name
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= getattr(os, "O_DIRECTORY")
    if hasattr(os, "O_NOFOLLOW"):
        flags |= getattr(os, "O_NOFOLLOW")

    supports_dir_fd = getattr(os, "open") in getattr(os, "supports_dir_fd", set())
    try:
        if dir_fd is not None and supports_dir_fd:
            fd = os.open(path_str, flags, dir_fd=dir_fd)
        elif dir_fd is None and supports_dir_fd:
            fd = _open_absolute_directory_secure(dir_path, flags)
        else:
            fd = os.open(str(dir_path), flags)
    except OSError as e:
        raise SecureIOError(
            code="dir_open_failed", message=f"Failed to open directory: {e.strerror}"
        )

    return fd


def read_file_secure(
    filename: str | Path,
    base_path: Path,
    dir_fd: int | None = None,
    max_bytes: int | None = None,
) -> bytes:
    """Reads a regular file strictly, preventing symlink traversal.
    Returns the file content bytes.
    Raises SecureIOError on any failure.
    """
    path_str = str(filename)
    try:
        flags = os.O_RDONLY | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= getattr(os, "O_NOFOLLOW")

        if dir_fd is not None and getattr(os, "open") in getattr(os, "supports_dir_fd", set()):
            fd = os.open(path_str, flags, dir_fd=dir_fd)
        else:
            # Fallback when dir_fd not supported
            fd = os.open(str(base_path / path_str), flags)
    except OSError as e:
        raise SecureIOError(code="open_failed", message=f"Failed to open file: {e.strerror}")

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SecureIOError(code="not_regular_file", message="Path is not a regular file")

        identity = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

        chunks = []
        total_read = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total_read += len(chunk)
            if max_bytes is not None and total_read > max_bytes:
                raise SecureIOError(
                    code="target_too_large_for_inspection",
                    message=f"File exceeds maximum inspection size of {max_bytes} bytes",
                )

        content = b"".join(chunks)

        st2 = os.fstat(fd)
        identity2 = (st2.st_dev, st2.st_ino, st2.st_size, st2.st_mtime_ns)
        if identity != identity2:
            raise SecureIOError(
                code="file_changed", message="File identity or metadata changed during reading"
            )

        return content

    finally:
        os.close(fd)


def hash_file_secure(
    filename: str | Path,
    base_path: Path,
    dir_fd: int | None = None,
    max_bytes: int | None = None,
) -> str:
    """Streams a regular file strictly and returns its hex digest.
    Does not buffer the entire file, preventing size limits on hashing.
    """
    path_str = str(filename)
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= getattr(os, "O_NOFOLLOW")

        if dir_fd is not None and getattr(os, "open") in getattr(os, "supports_dir_fd", set()):
            fd = os.open(path_str, flags, dir_fd=dir_fd)
        else:
            fd = os.open(str(base_path / path_str), flags)
    except OSError as e:
        raise SecureIOError(code="open_failed", message=f"Failed to open file: {e.strerror}")

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SecureIOError(code="not_regular_file", message="Path is not a regular file")

        identity = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

        hasher = hashlib.sha256()
        total_read = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total_read += len(chunk)
            if max_bytes is not None and total_read > max_bytes:
                raise SecureIOError(
                    code="target_too_large_for_inspection",
                    message=f"File exceeds maximum inspection size of {max_bytes} bytes",
                )
            hasher.update(chunk)

        st2 = os.fstat(fd)
        identity2 = (st2.st_dev, st2.st_ino, st2.st_size, st2.st_mtime_ns)
        if identity != identity2:
            raise SecureIOError(
                code="file_changed", message="File identity or metadata changed during reading"
            )

        return hasher.hexdigest()

    finally:
        os.close(fd)
