import errno
import os
from unittest import mock

import pytest

from lifeos._owned_lock import LockError, OwnedLock


@pytest.fixture
def lock_dir(tmp_path):
    d = tmp_path / "locks"
    d.mkdir()
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    yield d, fd
    os.close(fd)


def test_lock_acquire_and_release_success(lock_dir):
    _, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    lock.acquire()

    assert lock.lock_fd is not None
    assert os.path.exists(os.path.join(lock_dir[0], "test.lock"))

    res = lock.release()
    assert res.released is True
    assert res.ownership_verified is True
    assert res.path_unlinked is True
    assert res.descriptor_closed is True
    assert not os.path.exists(os.path.join(lock_dir[0], "test.lock"))


def test_lock_unlink_failure(lock_dir):
    _, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    lock.acquire()

    with mock.patch("os.unlink", side_effect=OSError(errno.EACCES, "Permission denied")):
        res = lock.release()

    assert res.ownership_verified is True
    assert res.path_unlinked is False
    assert res.released is False
    assert res.descriptor_closed is True


def test_lock_close_failure(lock_dir):
    _, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    lock.acquire()

    with mock.patch("os.close", side_effect=OSError(errno.EBADF, "Bad file descriptor")):
        res = lock.release()

    assert res.ownership_verified is True
    assert res.path_unlinked is True
    assert res.released is True
    assert res.descriptor_closed is False


def test_lock_identity_mismatch(lock_dir):
    _, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    lock.acquire()

    # Mutate the file on disk so stat doesn't match fstat
    os.unlink(os.path.join(lock_dir[0], "test.lock"))
    with open(os.path.join(lock_dir[0], "test.lock"), "w") as f:
        f.write("hijacked")

    res = lock.release()
    assert res.ownership_verified is False
    assert res.path_unlinked is False
    assert res.released is False
    assert res.descriptor_closed is True


def test_lock_token_mismatch(lock_dir):
    _, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    lock.acquire()

    # Mutate the token
    os.lseek(lock.lock_fd, 0, os.SEEK_SET)
    os.write(lock.lock_fd, b"wrongtoken")

    res = lock.release()
    assert res.ownership_verified is False
    assert res.path_unlinked is False
    assert res.released is False
    assert res.descriptor_closed is True


def test_lock_attempted_release_multiple_times(lock_dir):
    _, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    lock.acquire()
    res1 = lock.release()
    assert res1.released is True

    res2 = lock.release()
    assert res2.released is False
    assert res2.ownership_verified is False


def test_context_manager(lock_dir):
    _, fd = lock_dir
    with OwnedLock(fd, "test.lock") as lock:
        assert lock.lock_fd is not None
        assert os.path.exists(os.path.join(lock_dir[0], "test.lock"))
    assert not os.path.exists(os.path.join(lock_dir[0], "test.lock"))


def test_partial_token_writes_complete_before_acquisition(lock_dir):
    lock_path, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    original_write = os.write
    writes: list[int] = []

    def short_write(write_fd, data):
        chunk_size = max(1, len(data) // 2)
        writes.append(chunk_size)
        return original_write(write_fd, data[:chunk_size])

    with mock.patch("os.write", side_effect=short_write):
        lock.acquire()

    assert len(writes) > 1
    assert lock.lock_fd is not None
    os.lseek(lock.lock_fd, 0, os.SEEK_SET)
    assert os.read(lock.lock_fd, 1024) == lock.token
    assert (lock_path / "test.lock").read_bytes() == lock.token
    assert lock.release().released is True


def test_zero_progress_write_fails_without_stranding_lock(lock_dir):
    lock_path, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")

    with mock.patch("os.write", return_value=0):
        with pytest.raises(OSError, match="write returned 0 bytes"):
            lock.acquire()

    assert lock.lock_fd is None
    assert lock.token == b""
    assert not (lock_path / "test.lock").exists()


def test_write_failure_cleans_lock_and_allows_retry(lock_dir):
    lock_path, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    original_write = os.write
    failed = False

    def fail_once(write_fd, data):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError(errno.EIO, "write failed")
        return original_write(write_fd, data)

    with mock.patch("os.write", side_effect=fail_once):
        with pytest.raises(OSError, match="write failed"):
            lock.acquire()
        assert lock.lock_fd is None
        assert lock.token == b""
        assert not (lock_path / "test.lock").exists()
        lock.acquire()

    assert lock.release().released is True


def test_fsync_failure_cleans_lock_closes_descriptor_and_allows_retry(lock_dir):
    lock_path, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    original_fsync = os.fsync
    failed = False
    failed_fd = None

    def fail_once(sync_fd):
        nonlocal failed, failed_fd
        if not failed:
            failed = True
            failed_fd = sync_fd
            raise OSError(errno.EIO, "sync failed")
        return original_fsync(sync_fd)

    with mock.patch("os.fsync", side_effect=fail_once):
        with pytest.raises(OSError, match="sync failed"):
            lock.acquire()
        assert lock.lock_fd is None
        assert lock.token == b""
        assert not (lock_path / "test.lock").exists()
        lock.acquire()

    assert failed_fd is not None
    with pytest.raises(OSError):
        os.fstat(failed_fd)
    assert lock.release().released is True


def test_failed_acquisition_cleanup_preserves_primary_error(lock_dir):
    lock_path, fd = lock_dir
    lock = OwnedLock(fd, "test.lock")
    failed_fd = None
    primary_error = OSError(errno.EIO, "primary write failure")

    def fail_write(write_fd, _data):
        nonlocal failed_fd
        failed_fd = write_fd
        raise primary_error

    with (
        mock.patch("os.write", side_effect=fail_write),
        mock.patch("os.unlink", side_effect=OSError(errno.EACCES, "cleanup denied")),
    ):
        with pytest.raises(OSError) as exc_info:
            lock.acquire()

    assert exc_info.value is primary_error
    assert lock.lock_fd is None
    assert lock.token == b""
    assert (lock_path / "test.lock").exists()
    assert failed_fd is not None
    with pytest.raises(OSError):
        os.fstat(failed_fd)

    os.unlink(lock_path / "test.lock")


def test_failed_acquisition_does_not_unlink_replacement_path(lock_dir):
    lock_path, fd = lock_dir
    path = lock_path / "test.lock"
    lock = OwnedLock(fd, "test.lock")

    def replace_then_fail(_sync_fd):
        os.unlink(path)
        path.write_bytes(b"replacement-owner")
        raise OSError(errno.EIO, "sync failed")

    with mock.patch("os.fsync", side_effect=replace_then_fail):
        with pytest.raises(OSError, match="sync failed"):
            lock.acquire()

    assert lock.lock_fd is None
    assert lock.token == b""
    assert path.read_bytes() == b"replacement-owner"


def test_failed_acquisition_does_not_unlink_replacement_symlink(lock_dir):
    lock_path, fd = lock_dir
    path = lock_path / "test.lock"
    replacement_target = lock_path / "replacement-target"
    replacement_target.write_bytes(b"replacement-owner")
    lock = OwnedLock(fd, "test.lock")

    def replace_then_fail(_sync_fd):
        os.unlink(path)
        os.symlink(replacement_target.name, path)
        raise OSError(errno.EIO, "sync failed")

    with mock.patch("os.fsync", side_effect=replace_then_fail):
        with pytest.raises(OSError, match="sync failed"):
            lock.acquire()

    assert lock.lock_fd is None
    assert lock.token == b""
    assert path.is_symlink()
    assert path.read_bytes() == b"replacement-owner"


def test_preexisting_lock_is_never_removed_by_failed_acquisition(lock_dir):
    lock_path, fd = lock_dir
    owner = OwnedLock(fd, "test.lock")
    owner.acquire()
    owner_token = owner.token

    contender = OwnedLock(fd, "test.lock")
    with pytest.raises(LockError, match="Failed to acquire lock"):
        contender.acquire()

    assert contender.lock_fd is None
    assert contender.token == b""
    assert (lock_path / "test.lock").read_bytes() == owner_token
    assert contender.release().released is False
    assert owner.release().released is True
