import os
import uuid
from typing import Literal, Callable


class AtomicWriteError(Exception):
    def __init__(self, message: str, write_occurred: bool) -> None:
        super().__init__(message)
        self.write_occurred = write_occurred


def atomic_write_file_secure(
    dir_fd: int | None,
    filename: str,
    content: bytes,
    *,
    pre_replace_check: Callable[[], None] | None = None,
) -> Literal["confirmed", "uncertain"]:
    """
    Atomically writes `content` to `filename` inside `dir_fd`.
    Replaces existing file atomically.
    Throws AtomicWriteError(write_occurred=False) on failure before replacement.
    """
    temp_name = f"{filename}.{uuid.uuid4().hex}.tmp"
    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL

    try:
        temp_fd = os.open(temp_name, open_flags, 0o644, dir_fd=dir_fd)
    except OSError as e:
        raise AtomicWriteError(f"Failed to create temporary file: {e.strerror}", write_occurred=False)

    try:
        # Write content completely
        written = 0
        while written < len(content):
            chunk = os.write(temp_fd, content[written:])
            if chunk == 0:
                raise OSError("write returned 0 bytes")
            written += chunk
        # Fsync file
        os.fsync(temp_fd)
    except Exception as e:
        os.close(temp_fd)
        try:
            os.unlink(temp_name, dir_fd=dir_fd)
        except OSError:
            pass
        raise AtomicWriteError(f"Failed to write temporary file: {e}", write_occurred=False)

    os.close(temp_fd)

    try:
        if pre_replace_check is not None:
            pre_replace_check()
        os.replace(temp_name, filename, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except Exception as e:
        try:
            os.unlink(temp_name, dir_fd=dir_fd)
        except OSError:
            pass
        if isinstance(e, OSError):
            raise AtomicWriteError(f"Failed to replace file: {e.strerror}", write_occurred=False)
        raise

    durability: Literal["confirmed", "uncertain"] = "confirmed"
    if dir_fd is not None and hasattr(os, "fsync"):
        try:
            os.fsync(dir_fd)
        except OSError:
            durability = "uncertain"
    else:
        durability = "uncertain"

    return durability
