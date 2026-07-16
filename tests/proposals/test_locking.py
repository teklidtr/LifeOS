import os
import pytest
from unittest import mock
import errno

from lifeos._owned_lock import OwnedLock


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
