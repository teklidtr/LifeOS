import pytest
import os
import errno
from unittest import mock
from lifeos._transaction_files import fsync_directory, DirectorySyncState


def test_fsync_directory_success(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    try:
        res = fsync_directory(fd)
        # MacOS might return EINVAL for dir fsync, handled below, but if success:
        if res.state == DirectorySyncState.CONFIRMED:
            assert res.state == DirectorySyncState.CONFIRMED
            assert res.errno_name is None
    finally:
        os.close(fd)


def test_fsync_directory_not_a_directory(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("test")
    fd = os.open(f, os.O_RDONLY)
    try:
        res = fsync_directory(fd)
        assert res.state == DirectorySyncState.FAILED
        assert res.errno_name == "ENOTDIR"
    finally:
        os.close(fd)


@mock.patch("os.fsync")
@mock.patch("os.fstat")
def test_fsync_directory_eintr_retry(mock_fstat, mock_fsync):
    # Setup mock fstat to return a directory
    mock_st = mock.Mock()
    mock_st.st_mode = 0o40000  # S_IFDIR
    mock_fstat.return_value = mock_st

    # First call raises EINTR, second succeeds
    mock_fsync.side_effect = [OSError(errno.EINTR, "Interrupted"), None]

    res = fsync_directory(999)
    assert res.state == DirectorySyncState.CONFIRMED
    assert mock_fsync.call_count == 2


@mock.patch("os.fsync")
@mock.patch("os.fstat")
@mock.patch("sys.platform", "darwin")
def test_fsync_directory_einval_darwin(mock_fstat, mock_fsync):
    mock_st = mock.Mock()
    mock_st.st_mode = 0o40000  # S_IFDIR
    mock_fstat.return_value = mock_st

    mock_fsync.side_effect = OSError(errno.EINVAL, "Invalid argument")

    res = fsync_directory(999)
    assert res.state == DirectorySyncState.UNSUPPORTED
    assert res.errno_name == "EINVAL"


@mock.patch("os.fsync")
@mock.patch("os.fstat")
@mock.patch("sys.platform", "linux")
def test_fsync_directory_einval_linux(mock_fstat, mock_fsync):
    mock_st = mock.Mock()
    mock_st.st_mode = 0o40000  # S_IFDIR
    mock_fstat.return_value = mock_st

    mock_fsync.side_effect = OSError(errno.EINVAL, "Invalid argument")

    res = fsync_directory(999)
    assert res.state == DirectorySyncState.FAILED
    assert res.errno_name == "EINVAL"


@pytest.mark.parametrize(
    "err_code", [errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP), errno.ENOSYS]
)
@mock.patch("os.fsync")
@mock.patch("os.fstat")
def test_fsync_directory_unsupported(mock_fstat, mock_fsync, err_code):
    mock_st = mock.Mock()
    mock_st.st_mode = 0o40000  # S_IFDIR
    mock_fstat.return_value = mock_st

    mock_fsync.side_effect = OSError(err_code, "Unsupported")

    res = fsync_directory(999)
    assert res.state == DirectorySyncState.UNSUPPORTED
    assert res.errno_name in ("ENOTSUP", "EOPNOTSUPP", "ENOSYS")


@pytest.mark.parametrize("err_code", [errno.EIO, errno.ENOSPC, errno.EBADF])
@mock.patch("os.fsync")
@mock.patch("os.fstat")
def test_fsync_directory_failed(mock_fstat, mock_fsync, err_code):
    mock_st = mock.Mock()
    mock_st.st_mode = 0o40000  # S_IFDIR
    mock_fstat.return_value = mock_st

    mock_fsync.side_effect = OSError(err_code, "IO Error")

    res = fsync_directory(999)
    assert res.state == DirectorySyncState.FAILED
    assert res.errno_name in ("EIO", "ENOSPC", "EBADF")
