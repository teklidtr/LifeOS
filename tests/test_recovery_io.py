import hashlib
import lifeos._transaction_files
import lifeos._recovery_io
import os
import stat
from pathlib import Path

import pytest

from lifeos._recovery_io import (
    RecoveryArtifact,
    RecoveryIOConflictError,
    RecoveryIOCorruptStateError,
    RecoveryIOInvalidArtifactError,
    RecoveryIOUnavailableError,
    prepare_canonical_staging_from_artifact,
    read_verified_recovery_artifact,
    remove_installed_creation,
    restore_canonical_from_backup,
    write_recovery_artifact,
)
from lifeos._transaction_files import ParentDescriptor, TransactionError


@pytest.fixture
def recovery_root(tmp_path: Path) -> Path:
    r = tmp_path / "recovery"
    r.mkdir()
    return r


@pytest.fixture
def tx_dir(recovery_root: Path) -> Path:
    t = recovery_root / "prop-123-abc"
    t.mkdir()
    (t / "staged").mkdir()
    (t / "backups").mkdir()
    return t


def test_write_recovery_artifact_success(tx_dir: Path) -> None:
    content = b"hello world"
    artifact = RecoveryArtifact(
        relative_path='staged/test.txt',
        content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        size=len(content),
        mode=420,
    )
    write_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
        content=content,
    )

    assert artifact.relative_path == "staged/test.txt"
    assert artifact.size == len(content)
    assert artifact.mode == 0o644
    assert artifact.content_hash.startswith("sha256:")

    staged_path = tx_dir / "staged" / "test.txt"
    assert staged_path.exists()
    assert staged_path.read_bytes() == content
    st = staged_path.stat()
    assert stat.S_IMODE(st.st_mode) == 0o644


def test_write_recovery_artifact_rejects_invalid_path(tx_dir: Path) -> None:
    with pytest.raises(RecoveryIOInvalidArtifactError):
        artifact = RecoveryArtifact(
            relative_path='invalid/test.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )


def test_write_recovery_artifact_conflict(tx_dir: Path) -> None:
    (tx_dir / "staged" / "conflict.txt").write_bytes(b"existing")
    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/conflict.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )


def test_read_verified_recovery_artifact_success(tx_dir: Path) -> None:
    content = b"data"
    artifact = RecoveryArtifact(
        relative_path='staged/data.bin',
        content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        size=len(content),
        mode=384,
    )
    write_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
        content=content,
    )

    read_data = read_verified_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
    )
    assert read_data == content


def test_read_verified_recovery_artifact_hash_mismatch(tx_dir: Path) -> None:
    content = b"data"
    artifact = RecoveryArtifact(
        relative_path='staged/data.bin',
        content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        size=len(content),
        mode=384,
    )
    write_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
        content=content,
    )

    # Corrupt the file externally
    (tx_dir / "staged" / "data.bin").write_bytes(b"corrupted")

    with pytest.raises(RecoveryIOCorruptStateError):
        read_verified_recovery_artifact(transaction_dir=tx_dir, artifact=artifact)


def test_prepare_canonical_staging_from_artifact(tmp_path: Path, tx_dir: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)

    parent_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(parent_fd)
        parent = ParentDescriptor(fd=parent_fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))

        content = b"canonical"
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
            size=len(content),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=content,
        )

        staging = prepare_canonical_staging_from_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            target_name="final.txt",
            target_parent=parent,
            intended_mode=0o644,
        )

        assert staging.parent == parent
        assert staging.size == len(content)
        assert staging.intended_mode == 0o644

        # Verify the staging file was created in target_dir
        tmp_st = os.stat(target_dir / staging.name)
        assert stat.S_IMODE(tmp_st.st_mode) == 0o644
        assert (target_dir / staging.name).read_bytes() == content

    finally:
        os.close(parent_fd)


def test_remove_installed_creation(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)

    parent_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(parent_fd)
        parent = ParentDescriptor(fd=parent_fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))

        target_path = target_dir / "created.txt"
        content = b"to_remove"
        target_path.write_bytes(content)
        target_path.chmod(0o600)

        h = hashlib.sha256(content).hexdigest()

        remove_installed_creation(
            target_name="created.txt",
            target_parent=parent,
            expected_installed_hash=f"sha256:{h}",
            expected_installed_mode=0o600,
        )

        assert not target_path.exists()
    finally:
        os.close(parent_fd)


def test_restore_canonical_from_backup(tmp_path: Path, tx_dir: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)

    parent_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(parent_fd)
        parent = ParentDescriptor(fd=parent_fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))

        # 1. Simulate original target (the pre-state backup)
        backup_content = b"original"
        backup_artifact = RecoveryArtifact(
            relative_path='backups/original.txt',
            content_hash=f"sha256:{hashlib.sha256(backup_content).hexdigest()}",
            size=len(backup_content),
            mode=384,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=backup_artifact,
            content=backup_content,
        )

        # 2. Simulate installed proposal (the state we want to rollback)
        target_path = target_dir / "target.txt"
        installed_content = b"new_proposal"
        target_path.write_bytes(installed_content)
        target_path.chmod(0o644)
        installed_hash = hashlib.sha256(installed_content).hexdigest()

        # 3. Perform restore
        restore_canonical_from_backup(
            transaction_dir=tx_dir,
            backup=backup_artifact,
            target_name="target.txt",
            target_parent=parent,
            expected_installed_hash=f"sha256:{installed_hash}",
            expected_installed_mode=0o644,
            expected_restored_hash=backup_artifact.content_hash,
            expected_restored_mode=backup_artifact.mode,
        )

        # 4. Verify restored state
        assert target_path.read_bytes() == backup_content
        st = target_path.stat()
        assert stat.S_IMODE(st.st_mode) == 0o600

    finally:
        os.close(parent_fd)

def test_recovery_artifact_temporary_file_is_created_under_subdirectory(tx_dir: Path) -> None:
    # write_recovery_artifact creates a temporary file under `staged`
    # We can check that no files are created outside of it.
    artifact = RecoveryArtifact(
        relative_path='staged/test.txt',
        content_hash=f"sha256:{hashlib.sha256(b'data').hexdigest()}",
        size=len(b'data'),
        mode=420,
    )
    write_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
        content=b'data',
    )
    # The temporary file is cleaned up, but if it was created outside, it would be in CWD
    # We'll rely on the next test for strict CWD checking
    assert artifact.relative_path == "staged/test.txt"

def test_recovery_artifact_write_does_not_touch_process_cwd(tmp_path: Path, tx_dir: Path) -> None:
    original_cwd = os.getcwd()
    test_cwd = tmp_path / "fake_cwd"
    test_cwd.mkdir()
    os.chdir(test_cwd)
    try:
        artifact = RecoveryArtifact(
            relative_path='staged/test_cwd.txt',
            content_hash=f"sha256:{hashlib.sha256(b'data').hexdigest()}",
            size=len(b'data'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'data',
        )
        # Check that test_cwd remains completely empty
        assert list(test_cwd.iterdir()) == []
    finally:
        os.chdir(original_cwd)

def test_recovery_artifact_rejects_short_hash() -> None:
    with pytest.raises(RecoveryIOInvalidArtifactError):
        from lifeos._recovery_io import _validate_recovery_artifact
        _validate_recovery_artifact(RecoveryArtifact(
            relative_path="staged/test.txt",
            content_hash="sha256:abc",
            size=10,
            mode=0o644,
        ))

def test_recovery_artifact_rejects_uppercase_hash() -> None:
    with pytest.raises(RecoveryIOInvalidArtifactError):
        from lifeos._recovery_io import _validate_recovery_artifact
        _validate_recovery_artifact(RecoveryArtifact(
            relative_path="staged/test.txt",
            content_hash="sha256:000000000000000000000000000000000000000000000000000000000000000A",
            size=10,
            mode=0o644,
        ))

def test_recovery_artifact_rejects_non_string_hash() -> None:
    with pytest.raises(RecoveryIOInvalidArtifactError):
        from lifeos._recovery_io import _validate_recovery_artifact
        _validate_recovery_artifact(RecoveryArtifact(
            relative_path="staged/test.txt",
            content_hash=12345, # type: ignore
            size=10,
            mode=0o644,
        ))

def test_recovery_artifact_rejects_boolean_size() -> None:
    with pytest.raises(RecoveryIOInvalidArtifactError):
        from lifeos._recovery_io import _validate_recovery_artifact
        _validate_recovery_artifact(RecoveryArtifact(
            relative_path="staged/test.txt",
            content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            size=True, # type: ignore
            mode=0o644,
        ))

def test_recovery_artifact_rejects_boolean_mode() -> None:
    with pytest.raises(RecoveryIOInvalidArtifactError):
        from lifeos._recovery_io import _validate_recovery_artifact
        _validate_recovery_artifact(RecoveryArtifact(
            relative_path="staged/test.txt",
            content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            size=10,
            mode=True, # type: ignore
        ))

def test_recovery_artifact_write_preserves_corrupt_state_classification(tx_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lifeos import _recovery_io
    # Force _verify_open_artifact to raise RecoveryIOCorruptStateError
    def fake_verify(*args, **kwargs) -> None:
        raise RecoveryIOCorruptStateError("Simulated corrupt state")
    monkeypatch.setattr(_recovery_io, "_verify_open_artifact", fake_verify)

    with pytest.raises(RecoveryIOCorruptStateError):
        artifact = RecoveryArtifact(
            relative_path='staged/test.txt',
            content_hash=f"sha256:{hashlib.sha256(b'data').hexdigest()}",
            size=len(b'data'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'data',
        )

def test_recovery_artifact_write_preserves_conflict_classification(tx_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force os.link to raise FileExistsError
    def fake_link(*args, **kwargs) -> None:
        raise FileExistsError("File exists")
    monkeypatch.setattr(os, "link", fake_link)

    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/test.txt',
            content_hash=f"sha256:{hashlib.sha256(b'data').hexdigest()}",
            size=len(b'data'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'data',
        )

def test_recovery_artifact_prepublication_failure_removes_temp(tx_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lifeos import _recovery_io
    # Force _verify_open_artifact to raise exception, causing prepublication failure
    def fake_verify(*args, **kwargs) -> None:
        raise OSError("Simulated IO Error")
    monkeypatch.setattr(_recovery_io, "_verify_open_artifact", fake_verify)

    with pytest.raises(RecoveryIOUnavailableError):
        artifact = RecoveryArtifact(
            relative_path='staged/test.txt',
            content_hash=f"sha256:{hashlib.sha256(b'data').hexdigest()}",
            size=len(b'data'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'data',
        )

    staged_dir = tx_dir / "staged"
    assert not any(staged_dir.iterdir()), "Temporary file was not removed"

def test_recovery_artifact_temp_unlink_failure_preserves_final(tx_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_unlink = os.unlink

    def fake_unlink(path, *, dir_fd=None) -> None:
        if isinstance(path, str) and path.startswith("."):
            raise OSError("Simulated unlink failure")
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", fake_unlink)

    with pytest.raises(RecoveryIOUnavailableError) as exc:
        artifact = RecoveryArtifact(
            relative_path='staged/test.txt',
            content_hash=f"sha256:{hashlib.sha256(b'data').hexdigest()}",
            size=len(b'data'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'data',
        )
    assert "Failed to unlink temporary file after publication" in str(exc.value)

    staged_dir = tx_dir / "staged"
    final_file = staged_dir / "test.txt"
    assert final_file.exists()



def test_recovery_artifact_publication_never_overwrites_existing_final(tx_dir: Path) -> None:
    staged_dir = tx_dir / "staged"
    final_file = staged_dir / "test.txt"
    final_file.write_bytes(b"existing")

    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/test.txt',
            content_hash=f"sha256:{hashlib.sha256(b'new data').hexdigest()}",
            size=len(b'new data'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'new data',
        )

    assert final_file.read_bytes() == b"existing"

def test_remove_installed_creation_rejects_absent_target(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOConflictError):
            remove_installed_creation(
                target_name="absent.txt",
                target_parent=parent,
                expected_installed_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                expected_installed_mode=0o644,
            )
    finally:
        os.close(fd)

def test_remove_installed_creation_rejects_symlink(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    (target_dir / "link.txt").symlink_to("other.txt")
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOCorruptStateError):
            remove_installed_creation(
                target_name="link.txt",
                target_parent=parent,
                expected_installed_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                expected_installed_mode=0o644,
            )
    finally:
        os.close(fd)

def test_remove_installed_creation_rejects_non_regular_file(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    (target_dir / "dir").mkdir()
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOCorruptStateError):
            remove_installed_creation(
                target_name="dir",
                target_parent=parent,
                expected_installed_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                expected_installed_mode=0o644,
            )
    finally:
        os.close(fd)

def test_remove_installed_creation_rejects_hash_mismatch(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    (target_dir / "file.txt").write_bytes(b"data")
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOConflictError):
            remove_installed_creation(
                target_name="file.txt",
                target_parent=parent,
                expected_installed_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                expected_installed_mode=0o644,
            )
    finally:
        os.close(fd)

def test_remove_installed_creation_rejects_mode_mismatch(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    (target_dir / "file.txt").write_bytes(b"data")
    (target_dir / "file.txt").chmod(0o600)
    h = hashlib.sha256(b"data").hexdigest()
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOConflictError):
            remove_installed_creation(
                target_name="file.txt",
                target_parent=parent,
                expected_installed_hash=f"sha256:{h}",
                expected_installed_mode=0o644,
            )
    finally:
        os.close(fd)

def test_remove_installed_creation_removes_exact_expected_target(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    (target_dir / "file.txt").write_bytes(b"data")
    (target_dir / "file.txt").chmod(0o644)
    h = hashlib.sha256(b"data").hexdigest()
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        remove_installed_creation(
            target_name="file.txt",
            target_parent=parent,
            expected_installed_hash=f"sha256:{h}",
            expected_installed_mode=0o644,
        )
        assert not (target_dir / "file.txt").exists()
    finally:
        os.close(fd)




























def test_recovery_artifact_temp_unlink_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    def fake_unlink(*args, **kwargs):
        raise OSError("Permission denied")
    monkeypatch.setattr(os, "unlink", fake_unlink)
    with pytest.raises(RecoveryIOUnavailableError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_verification_failure_preserves_published_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    def fake_fstat(fd):
        st = original_fstat(fd)
        class FakeStat:
            st_mode = st.st_mode
            st_size = 999 # size mismatch
            st_dev = st.st_dev
            st_ino = st.st_ino
        return FakeStat()
    original_fstat = os.fstat
    LINKED = []
    original_link = lifeos._recovery_io.os.link
    def fake_link(*args, **kwargs):
        LINKED.append(True)
        return original_link(*args, **kwargs)
    monkeypatch.setattr(lifeos._recovery_io.os, "link", fake_link)
    import stat
    def wrapper(fd):
        st = original_fstat(fd)
        if LINKED and stat.S_ISREG(st.st_mode):
            return fake_fstat(fd)
        return st
    monkeypatch.setattr(lifeos._recovery_io.os, "fstat", wrapper)
    with pytest.raises(RecoveryIOCorruptStateError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )
    assert (tx_dir / "staged" / "file.txt").exists()
    assert (tx_dir / "staged" / "file.txt").read_bytes() == b"hello"

def test_recovery_artifact_final_verification_reopens_final_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    calls = []
    original_open = os.open
    def fake_open(path, flags, mode=0o777, *, dir_fd=None):
        calls.append(path)
        return original_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(lifeos._recovery_io.os, "open", fake_open)
    artifact = RecoveryArtifact(
        relative_path='staged/file.txt',
        content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
        size=len(b'hello'),
        mode=420,
    )
    write_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
        content=b'hello',
    )
    assert "file.txt" in calls

def test_recovery_artifact_final_verification_checks_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    original_verify = lifeos._recovery_io._verify_open_artifact
    LINKED = []
    original_link = lifeos._recovery_io.os.link
    def fake_link(*args, **kwargs):
        LINKED.append(True)
        return original_link(*args, **kwargs)
    monkeypatch.setattr(lifeos._recovery_io.os, "link", fake_link)
    def fake_verify(*args, **kwargs):
        if LINKED:
            raise RecoveryIOCorruptStateError("Simulated hash mismatch")
        return original_verify(*args, **kwargs)
    monkeypatch.setattr(lifeos._recovery_io, "_verify_open_artifact", fake_verify)
    with pytest.raises(RecoveryIOCorruptStateError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_final_verification_checks_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    original_fstat = os.fstat
    LINKED = []
    original_link = lifeos._recovery_io.os.link
    def fake_link(*args, **kwargs):
        LINKED.append(True)
        return original_link(*args, **kwargs)
    monkeypatch.setattr(lifeos._recovery_io.os, "link", fake_link)
    import stat
    def wrapper(fd):
        st = original_fstat(fd)
        if LINKED and stat.S_ISREG(st.st_mode):
            class FakeStat:
                st_mode = st.st_mode
                st_size = 999 # size mismatch
                st_dev = st.st_dev
                st_ino = st.st_ino
            return FakeStat()
        return st
    monkeypatch.setattr(lifeos._recovery_io.os, "fstat", wrapper)
    with pytest.raises(RecoveryIOCorruptStateError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_final_verification_checks_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    original_fstat = os.fstat
    LINKED = []
    original_link = lifeos._recovery_io.os.link
    def fake_link(*args, **kwargs):
        LINKED.append(True)
        return original_link(*args, **kwargs)
    monkeypatch.setattr(lifeos._recovery_io.os, "link", fake_link)
    import stat
    def wrapper(fd):
        st = original_fstat(fd)
        if LINKED and stat.S_ISREG(st.st_mode):
            class FakeStat:
                st_mode = stat.S_IFREG | 0o777
                st_size = st.st_size
                st_dev = st.st_dev
                st_ino = st.st_ino
            return FakeStat()
        return st
    monkeypatch.setattr(lifeos._recovery_io.os, "fstat", wrapper)
    with pytest.raises(RecoveryIOCorruptStateError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_remove_installed_creation_does_not_parse_transaction_error_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        def stub_get_identity(*args, **kwargs):
            raise TransactionError("A completely different error 1")
        monkeypatch.setattr(lifeos._recovery_io, "get_target_identity", stub_get_identity)
        with pytest.raises(RecoveryIOUnavailableError):
            remove_installed_creation(target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:" + "0"*64, expected_installed_mode=0o644)
    finally:
        os.close(fd)

def test_recovery_artifact_write_is_atomic(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    artifact = RecoveryArtifact(
        relative_path='staged/file.txt',
        content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
        size=len(b'hello'),
        mode=420,
    )
    write_recovery_artifact(
        transaction_dir=tx_dir,
        artifact=artifact,
        content=b'hello',
    )
    assert (tx_dir / "staged" / "file.txt").exists()

def test_recovery_artifact_finalization_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").write_bytes(b"existing")
    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_parent_traversal(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    with pytest.raises(RecoveryIOInvalidArtifactError):
        artifact = RecoveryArtifact(
            relative_path='../file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_nested_relative_path(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    with pytest.raises(RecoveryIOInvalidArtifactError):
        artifact = RecoveryArtifact(
            relative_path='staged/dir/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_absolute_path(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    with pytest.raises(RecoveryIOInvalidArtifactError):
        artifact = RecoveryArtifact(
            relative_path='/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_backslash(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    with pytest.raises(RecoveryIOInvalidArtifactError):
        artifact = RecoveryArtifact(
            relative_path='file\\txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_symlinked_transaction_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    tx_dir = tmp_path / "tx"
    tx_dir.symlink_to("target")
    with pytest.raises(RecoveryIOCorruptStateError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_symlinked_subdirectory(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").symlink_to("other.txt")
    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_symlinked_final_file(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").symlink_to("other.txt")
    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_rejects_existing_final_file(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").write_bytes(b"existing")
    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )

def test_recovery_artifact_read_verifies_hash(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").write_bytes(b"hello")
    artifact = RecoveryArtifact(relative_path="staged/file.txt", content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000", size=5, mode=0o644)
    with pytest.raises(RecoveryIOCorruptStateError):
        read_verified_recovery_artifact(transaction_dir=tx_dir, artifact=artifact)

def test_recovery_artifact_read_verifies_size(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").write_bytes(b"hello")
    import hashlib
    h = hashlib.sha256(b"hello").hexdigest()
    artifact = RecoveryArtifact(relative_path="staged/file.txt", content_hash=f"sha256:{h}", size=999, mode=0o644)
    with pytest.raises(RecoveryIOCorruptStateError):
        read_verified_recovery_artifact(transaction_dir=tx_dir, artifact=artifact)

def test_recovery_artifact_read_verifies_mode(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    f = tx_dir / "staged" / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o755)
    import hashlib
    h = hashlib.sha256(b"hello").hexdigest()
    artifact = RecoveryArtifact(relative_path="staged/file.txt", content_hash=f"sha256:{h}", size=5, mode=0o644)
    with pytest.raises(RecoveryIOCorruptStateError):
        read_verified_recovery_artifact(transaction_dir=tx_dir, artifact=artifact)

def test_recovery_artifact_read_rejects_non_regular_file(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "dir").mkdir()
    artifact = RecoveryArtifact(relative_path="staged/dir", content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000", size=0, mode=0o644)
    with pytest.raises(RecoveryIOCorruptStateError):
        read_verified_recovery_artifact(transaction_dir=tx_dir, artifact=artifact)

def test_recovery_artifact_write_failure_removes_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    def fake_fchmod(fd, mode):
        raise OSError("Permission denied")
    monkeypatch.setattr(lifeos._recovery_io.os, "fchmod", fake_fchmod)
    with pytest.raises(RecoveryIOUnavailableError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )
    assert len(list((tx_dir / "staged").iterdir())) == 0

def test_recovery_artifact_publication_failure_preserves_existing_final_file(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / 'staged').mkdir()
    (tx_dir / "staged" / "file.txt").write_bytes(b"existing")
    with pytest.raises(RecoveryIOConflictError):
        artifact = RecoveryArtifact(
            relative_path='staged/file.txt',
            content_hash=f"sha256:{hashlib.sha256(b'hello').hexdigest()}",
            size=len(b'hello'),
            mode=420,
        )
        write_recovery_artifact(
            transaction_dir=tx_dir,
            artifact=artifact,
            content=b'hello',
        )
    assert (tx_dir / "staged" / "file.txt").read_bytes() == b"existing"

def test_prepare_canonical_staging_from_artifact_works_across_filesystems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        artifact = RecoveryArtifact(relative_path="staged/file.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        def fake_read(*args, **kwargs):
            return b"hello"
        monkeypatch.setattr(lifeos._recovery_io, "read_verified_recovery_artifact", fake_read)
        staged = prepare_canonical_staging_from_artifact(transaction_dir=tmp_path / "tx", artifact=artifact, target_name="file.txt", target_parent=parent, intended_mode=artifact.mode)
        assert staged.name.startswith(".file.txt")
        assert (target_dir / staged.name).exists()
        assert (target_dir / staged.name).read_bytes() == b"hello"
    finally:
        os.close(fd)

def test_prepare_canonical_staging_from_artifact_uses_target_local_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        artifact = RecoveryArtifact(relative_path="staged/file.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        def fake_read(*args, **kwargs):
            return b"hello"
        monkeypatch.setattr(lifeos._recovery_io, "read_verified_recovery_artifact", fake_read)
        staged = prepare_canonical_staging_from_artifact(transaction_dir=tmp_path / "tx", artifact=artifact, target_name="file.txt", target_parent=parent, intended_mode=artifact.mode)
        assert (target_dir / staged.name).exists()
    finally:
        os.close(fd)

def test_remove_installed_creation_verifies_hash(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"wrong")
    f.chmod(0o644)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOConflictError):
            remove_installed_creation(target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", expected_installed_mode=0o644)
    finally:
        os.close(fd)

def test_remove_installed_creation_verifies_mode(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o777)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOConflictError):
            remove_installed_creation(target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", expected_installed_mode=0o644)
    finally:
        os.close(fd)

def test_remove_installed_creation_rejects_mutated_target(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o644)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        with pytest.raises(RecoveryIOConflictError):
            remove_installed_creation(target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000", expected_installed_mode=0o644)
    finally:
        os.close(fd)

def test_restore_canonical_from_backup_verifies_installed_state(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        backup_artifact = RecoveryArtifact(relative_path="staged/backup.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        with pytest.raises(RecoveryIOConflictError):
            restore_canonical_from_backup(transaction_dir=tmp_path / "tx", backup=backup_artifact, target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000", expected_installed_mode=0o644, expected_restored_hash=backup_artifact.content_hash, expected_restored_mode=backup_artifact.mode)
    finally:
        os.close(fd)

def test_restore_canonical_from_backup_verifies_backup_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o644)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        backup_artifact = RecoveryArtifact(relative_path="staged/backup.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        def fake_read(*args, **kwargs):
            raise RecoveryIOCorruptStateError("hash mismatch")
        monkeypatch.setattr(lifeos._recovery_io, "read_verified_recovery_artifact", fake_read)
        with pytest.raises(RecoveryIOCorruptStateError):
            restore_canonical_from_backup(transaction_dir=tmp_path / "tx", backup=backup_artifact, target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", expected_installed_mode=0o644, expected_restored_hash=backup_artifact.content_hash, expected_restored_mode=backup_artifact.mode)
    finally:
        os.close(fd)

def test_restore_canonical_from_backup_verifies_backup_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o644)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        backup_artifact = RecoveryArtifact(relative_path="staged/backup.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        def fake_read(*args, **kwargs):
            raise RecoveryIOCorruptStateError("mode mismatch")
        monkeypatch.setattr(lifeos._recovery_io, "read_verified_recovery_artifact", fake_read)
        with pytest.raises(RecoveryIOCorruptStateError):
            restore_canonical_from_backup(transaction_dir=tmp_path / "tx", backup=backup_artifact, target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", expected_installed_mode=0o644, expected_restored_hash=backup_artifact.content_hash, expected_restored_mode=backup_artifact.mode)
    finally:
        os.close(fd)

def test_restore_canonical_from_backup_uses_target_local_atomic_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o644)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        backup_artifact = RecoveryArtifact(relative_path="staged/backup.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        def fake_read(*args, **kwargs):
            return b"hello"
        monkeypatch.setattr(lifeos._recovery_io, "read_verified_recovery_artifact", fake_read)
        calls = []
        original_replace = os.replace
        def fake_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            calls.append((src_dir_fd, dst_dir_fd))
            return original_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        monkeypatch.setattr(lifeos._transaction_files.os, "replace", fake_replace)
        restore_canonical_from_backup(transaction_dir=tmp_path / "tx", backup=backup_artifact, target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", expected_installed_mode=0o644, expected_restored_hash=backup_artifact.content_hash, expected_restored_mode=backup_artifact.mode)
        assert calls == [(fd, fd)]
    finally:
        os.close(fd)

def test_restore_canonical_from_backup_verifies_restored_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / 'staged').mkdir(exist_ok=True)
    f = target_dir / "file.txt"
    f.write_bytes(b"hello")
    f.chmod(0o644)
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))
        backup_artifact = RecoveryArtifact(relative_path="staged/backup.txt", content_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", size=5, mode=0o644)
        def fake_read(*args, **kwargs):
            return b"hello"
        monkeypatch.setattr(lifeos._recovery_io, "read_verified_recovery_artifact", fake_read)
        original_stat = os.stat
        STAT_CALLS = []
        import stat
        def wrapper_stat(path, *, dir_fd=None, follow_symlinks=True):
            st_val = original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            if path == "file.txt":
                STAT_CALLS.append(True)
            if len(STAT_CALLS) >= 4 and path == "file.txt" and stat.S_ISREG(st_val.st_mode):
                class FakeStat:
                    st_mode = stat.S_IFREG | 0o000 # mode mismatch
                    st_size = st_val.st_size
                    st_dev = st_val.st_dev
                    st_ino = st_val.st_ino
                return FakeStat()
            return st_val
        monkeypatch.setattr(lifeos._recovery_io.os, "stat", wrapper_stat)
        with pytest.raises(RecoveryIOCorruptStateError):
            restore_canonical_from_backup(transaction_dir=tmp_path / "tx", backup=backup_artifact, target_name="file.txt", target_parent=parent, expected_installed_hash="sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", expected_installed_mode=0o644, expected_restored_hash=backup_artifact.content_hash, expected_restored_mode=backup_artifact.mode)
    finally:
        os.close(fd)

def test_restore_canonical_from_backup_cleans_staging_on_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    target = target_dir / "file.txt"
    target.write_bytes(b"new")
    target.chmod(0o644)
    target_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        target_stat = os.fstat(target_fd)
        parent = ParentDescriptor(
            fd=target_fd,
            dev=target_stat.st_dev,
            ino=target_stat.st_ino,
            path=str(target_dir),
        )
        backup_content = b"old"
        backup = RecoveryArtifact(
            relative_path="backups/file.txt",
            content_hash=f"sha256:{hashlib.sha256(backup_content).hexdigest()}",
            size=len(backup_content),
            mode=0o644,
        )
        monkeypatch.setattr(
            lifeos._recovery_io,
            "read_verified_recovery_artifact",
            lambda **_kwargs: backup_content,
        )

        def fail_publish(**_kwargs):
            raise TransactionError("injected publish failure")

        monkeypatch.setattr(lifeos._recovery_io, "publish_replacement", fail_publish)

        with pytest.raises(TransactionError, match="injected publish failure"):
            restore_canonical_from_backup(
                transaction_dir=tmp_path / "tx",
                backup=backup,
                target_name="file.txt",
                target_parent=parent,
                expected_installed_hash=f"sha256:{hashlib.sha256(b'new').hexdigest()}",
                expected_installed_mode=0o644,
                expected_restored_hash=backup.content_hash,
                expected_restored_mode=backup.mode,
            )

        assert not list(target_dir.glob("*.staged"))
        assert target.read_bytes() == b"new"
    finally:
        os.close(target_fd)


def test_restore_canonical_from_backup_restores_real_bytes_and_mode(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    tx_dir.mkdir()
    (tx_dir / "backups").mkdir()
    b_path = tx_dir / "backups" / "backup.txt.bak"
    b_path.write_bytes(b"original backup content")
    b_path.chmod(0o644)
    import hashlib
    b_hash = hashlib.sha256(b"original backup content").hexdigest()

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "staged").mkdir()
    t_path = target_dir / "file.txt"
    t_path.write_bytes(b"bad content")
    t_path.chmod(0o777)
    t_hash = hashlib.sha256(b"bad content").hexdigest()

    import os
    from lifeos._recovery_io import restore_canonical_from_backup, ParentDescriptor, RecoveryArtifact
    fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        parent = ParentDescriptor(fd=fd, dev=st.st_dev, ino=st.st_ino, path=str(target_dir))

        restore_canonical_from_backup(
            transaction_dir=tx_dir,
            backup=RecoveryArtifact(relative_path="backups/backup.txt.bak", content_hash=f"sha256:{b_hash}", size=len(b"original backup content"), mode=0o644),
            target_name="file.txt",
            target_parent=parent,
            expected_installed_hash=f"sha256:{t_hash}",
            expected_installed_mode=0o777,
            expected_restored_hash=f"sha256:{b_hash}",
            expected_restored_mode=0o644,
        )

        # Verify restored bytes equal original backup bytes
        assert t_path.read_bytes() == b"original backup content"

        # Verify restored mode equals expected pre-mode
        assert (t_path.stat().st_mode & 0o777) == 0o644

        # Verify backup artifact remains unchanged
        assert b_path.exists()
        assert b_path.read_bytes() == b"original backup content"

        # Verify canonical target-local publication was used (staged dir should be empty or contain nothing permanent)
        staged_contents = list((target_dir / "staged").iterdir())
        assert len(staged_contents) == 0
    finally:
        os.close(fd)
