from unittest.mock import patch
import sqlite3
import time
from pathlib import Path

import pytest

from lifeos.registry import Registry
from lifeos.registry.file_tracking import FileTrackingError, register_scan
from lifeos.scanner import VaultFile


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    db_path = tmp_path / "registry.sqlite"
    reg = Registry(db_path)
    reg.initialize()
    return reg


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def get_file_record(registry: Registry, path: str) -> sqlite3.Row | None:
    with registry.connect() as conn:
        return conn.execute("SELECT * FROM files WHERE vault_path = ?", (path,)).fetchone()


def test_new_file(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "test.md"
    file_path.write_text("hello")
    entries = [VaultFile(path=Path("test.md"), file_type=".md", size_bytes=5)]

    result = register_scan(registry, vault_root, entries)

    assert result.new == ["test.md"]
    assert result.modified == []
    assert result.unchanged == []
    assert result.deleted == []

    row = get_file_record(registry, "test.md")
    assert row is not None
    assert row["is_deleted"] == 0
    assert row["content_hash"] == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_unchanged_file(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "test.md"
    file_path.write_text("hello")
    entries = [VaultFile(path=Path("test.md"), file_type=".md", size_bytes=5)]

    register_scan(registry, vault_root, entries)

    time.sleep(0.01)  # Ensure time difference if necessary
    row_before = get_file_record(registry, "test.md")

    result2 = register_scan(registry, vault_root, entries)

    assert result2.unchanged == ["test.md"]
    assert result2.new == []
    assert result2.modified == []

    row_after = get_file_record(registry, "test.md")
    assert row_before is not None and row_after is not None
    assert row_before["first_seen_at"] == row_after["first_seen_at"]
    assert row_after["last_seen_at"] >= row_before["last_seen_at"]


def test_modified_file(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "test.md"
    file_path.write_text("hello")
    entries = [VaultFile(path=Path("test.md"), file_type=".md", size_bytes=5)]
    register_scan(registry, vault_root, entries)

    row_before = get_file_record(registry, "test.md")

    file_path.write_text("world!")
    entries2 = [VaultFile(path=Path("test.md"), file_type=".md", size_bytes=6)]
    result = register_scan(registry, vault_root, entries2)

    assert result.modified == ["test.md"]
    assert result.new == []
    assert result.unchanged == []

    row_after = get_file_record(registry, "test.md")
    assert row_after is not None and row_before is not None
    assert (
        row_after["content_hash"]
        != "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    assert row_after["size_bytes"] == 6
    assert row_before["first_seen_at"] == row_after["first_seen_at"]


def test_deleted_file(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "test.md"
    file_path.write_text("hello")
    register_scan(
        registry, vault_root, [VaultFile(path=Path("test.md"), file_type=".md", size_bytes=5)]
    )

    # Missing in next scan
    result = register_scan(registry, vault_root, [])

    assert result.deleted == ["test.md"]
    row = get_file_record(registry, "test.md")
    assert row is not None
    assert row["is_deleted"] == 1


def test_reappeared_file_is_modified(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "test.md"
    file_path.write_text("hello")
    entry = VaultFile(path=Path("test.md"), file_type=".md", size_bytes=5)

    register_scan(registry, vault_root, [entry])
    register_scan(registry, vault_root, [])  # deleted

    row1 = get_file_record(registry, "test.md")
    assert row1 is not None and row1["is_deleted"] == 1

    result = register_scan(registry, vault_root, [entry])  # reappeared

    assert result.modified == ["test.md"]

    row2 = get_file_record(registry, "test.md")
    assert row2 is not None and row2["is_deleted"] == 0


def test_empty_files_hash_correctly(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "empty.md"
    file_path.write_text("")
    register_scan(
        registry, vault_root, [VaultFile(path=Path("empty.md"), file_type=".md", size_bytes=0)]
    )

    row = get_file_record(registry, "empty.md")
    assert row is not None
    assert row["content_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_binary_files(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "img.png"
    file_path.write_bytes(b"\x00\x01\x02")
    register_scan(
        registry, vault_root, [VaultFile(path=Path("img.png"), file_type=".png", size_bytes=3)]
    )

    row = get_file_record(registry, "img.png")
    assert row is not None
    assert row["content_hash"] == "ae4b3280e56e2faf83f414a6e3dabe9d5fbe18976544c05fed121accb85b53fc"


def test_identical_content_separate_records(registry: Registry, vault_root: Path) -> None:
    (vault_root / "a.md").write_text("same")
    (vault_root / "b.md").write_text("same")
    entries = [
        VaultFile(path=Path("a.md"), file_type=".md", size_bytes=4),
        VaultFile(path=Path("b.md"), file_type=".md", size_bytes=4),
    ]

    result = register_scan(registry, vault_root, entries)
    assert len(result.new) == 2

    with registry.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert count == 2


def test_interrupted_scan_does_not_mark_deleted(registry: Registry, vault_root: Path) -> None:
    (vault_root / "a.md").write_text("a")
    register_scan(
        registry, vault_root, [VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1)]
    )

    # Introduce error
    (vault_root / "b.md").write_text("b")
    with patch("lifeos.registry.file_tracking._hash_file", side_effect=Exception("Failed")):
        with pytest.raises(Exception, match="Failed"):
            register_scan(
                registry, vault_root, [VaultFile(path=Path("b.md"), file_type=".md", size_bytes=1)]
            )

    row = get_file_record(registry, "a.md")
    assert row is not None
    assert row["is_deleted"] == 0  # Should not be deleted


def test_reject_duplicate_paths(registry: Registry, vault_root: Path) -> None:
    entries = [
        VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1),
        VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1),
    ]
    with pytest.raises(FileTrackingError, match="Duplicate normalized path"):
        register_scan(registry, vault_root, entries)


def test_hashing_checks_for_changes(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "a.md"
    file_path.write_text("a")

    def mock_stat(*args, **kwargs):
        # Simulate changing mtime
        class MockStat:
            st_mtime_ns = 1
            st_size = 1

        # Second call returns different mtime
        if getattr(mock_stat, "called", False):
            MockStat.st_mtime_ns = 2
            return MockStat
        mock_stat.called = True
        return MockStat

    with patch.object(Path, "stat", side_effect=mock_stat):
        with pytest.raises(FileTrackingError, match="changed during hashing"):
            register_scan(
                registry, vault_root, [VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1)]
            )


def test_database_failure_rolls_back(registry: Registry, vault_root: Path) -> None:
    (vault_root / "a.md").write_text("a")
    register_scan(
        registry, vault_root, [VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1)]
    )

    (vault_root / "b.md").write_text("b")
    entries = [
        VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1),
        VaultFile(path=Path("b.md"), file_type=".md", size_bytes=1),
    ]

    original_connect = registry.connect

    import contextlib

    @contextlib.contextmanager
    def failing_connect():
        with original_connect() as conn:

            class ConnWrapper:
                def __init__(self, c):
                    self._conn = c

                def execute(self, sql, params=()):
                    if "INSERT INTO files" in sql and "b.md" in params:
                        raise sqlite3.Error("DB error")
                    return self._conn.execute(sql, params)

                @property
                def in_transaction(self):
                    return self._conn.in_transaction

            yield ConnWrapper(conn)

    with patch.object(registry, "connect", side_effect=failing_connect):
        with pytest.raises(sqlite3.Error, match="DB error"):
            register_scan(registry, vault_root, entries)

    # Check that b.md was NOT registered, meaning transaction rolled back
    assert get_file_record(registry, "b.md") is None


def test_raw_file_contents_not_stored(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "test.md"
    secret_content = "SECRET_RAW_CONTENT_NEVER_STORED"
    file_path.write_text(secret_content)
    register_scan(
        registry,
        vault_root,
        [VaultFile(path=Path("test.md"), file_type=".md", size_bytes=len(secret_content))],
    )

    with registry.connect() as conn:
        row = conn.execute("SELECT * FROM files WHERE vault_path = 'test.md'").fetchone()
        for key in row.keys():
            val = row[key]
            if isinstance(val, str):
                assert secret_content not in val


def test_scan_result_ordering_is_deterministic(registry: Registry, vault_root: Path) -> None:
    (vault_root / "b.md").write_text("b")
    (vault_root / "a.md").write_text("a")

    # Input order does not matter
    entries = [
        VaultFile(path=Path("b.md"), file_type=".md", size_bytes=1),
        VaultFile(path=Path("a.md"), file_type=".md", size_bytes=1),
    ]

    result = register_scan(registry, vault_root, entries)
    # Output is deterministically sorted
    assert result.new == ["a.md", "b.md"]


def test_hashing_uses_streamed_reads(registry: Registry, vault_root: Path) -> None:
    file_path = vault_root / "large.md"
    file_path.write_bytes(b"a" * 100000)

    original_open = open
    read_calls = []

    class SpyFile:
        def __init__(self, path, mode):
            self.file = original_open(path, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def read(self, size=-1):
            read_calls.append(size)
            return self.file.read(size)

    with patch("lifeos.registry.file_tracking.open", SpyFile):
        register_scan(
            registry,
            vault_root,
            [VaultFile(path=Path("large.md"), file_type=".md", size_bytes=100000)],
        )

    assert 65536 in read_calls


def test_hash_file_content_equivalence(registry: Registry, vault_root: Path) -> None:
    from lifeos.registry.file_tracking import _hash_file, hash_file_content

    file_path = vault_root / "equivalence.md"
    file_path.write_bytes(b"hello world")
    assert _hash_file(file_path) == hash_file_content(file_path.read_bytes())
