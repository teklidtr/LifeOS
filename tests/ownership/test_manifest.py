from pathlib import Path
from unittest.mock import patch

import pytest

from lifeos.ownership import (
    ExternalModificationError,
    GeneratedOwnership,
    GeneratorMismatchError,
    ManifestError,
    PathSafetyError,
    PersistenceError,
    UnownedFileError,
)
from lifeos._transaction_files import TransactionError
from lifeos.ownership.manifest import stream_sha256


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "manifest.json"


def test_missing_manifest_readonly(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    assert not manifest_path.exists()
    assert not ownership._entries


def test_loading_no_create_dirs(tmp_path: Path, vault_root: Path) -> None:
    manifest_path = tmp_path / "nested" / "manifest.json"
    GeneratedOwnership.load(manifest_path, vault_root)
    assert not (tmp_path / "nested").exists()


def test_new_output_registered(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")

    assert target_abs.exists()
    assert manifest_path.exists()

    reloaded = GeneratedOwnership.load(manifest_path, vault_root)
    assert "test.md" in reloaded._entries


def test_metadata_stored(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")

    entry = ownership._entries["test.md"]
    assert entry.generator_id == "gen1"
    assert entry.generator_version == "1.0"
    assert entry.content_hash == stream_sha256(target_abs)
    assert entry.created_at
    assert entry.updated_at


def test_update_owned_file(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")

    ownership.write_generated_file(target_rel, b"new content", "gen1", "1.1")
    assert target_abs.read_bytes() == b"new content"
    entry = ownership._entries["test.md"]
    assert entry.generator_version == "1.1"


def test_different_generator_rejected(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")

    with pytest.raises(GeneratorMismatchError):
        ownership.write_generated_file(target_rel, b"content2", "gen2", "1.0")


def test_unowned_rejected(manifest_path: Path, vault_root: Path) -> None:
    target_rel = "human.md"
    target_abs = vault_root / target_rel
    target_abs.write_text("human")

    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    with pytest.raises(UnownedFileError):
        ownership.write_generated_file(target_rel, b"gen", "gen1", "1.0")


def test_manually_modified_rejected(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")

    target_abs.write_text("modified")

    with pytest.raises(ExternalModificationError):
        ownership.write_generated_file(target_rel, b"new gen", "gen1", "1.0")


def test_path_safety_rejected(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    with pytest.raises(PathSafetyError):
        ownership.write_generated_file("/absolute/path", b"content", "gen1", "1.0")

    with pytest.raises(PathSafetyError):
        ownership.write_generated_file("../outside.md", b"content", "gen1", "1.0")


def test_malformed_json_rejected(manifest_path: Path, vault_root: Path) -> None:
    manifest_path.write_text("{bad json")
    with pytest.raises(ManifestError, match="Malformed JSON"):
        GeneratedOwnership.load(manifest_path, vault_root)


def test_unsupported_schema_rejected(manifest_path: Path, vault_root: Path) -> None:
    manifest_path.write_text('{"schema_version": 2, "owned_files": {}}')
    with pytest.raises(ManifestError, match="Unsupported schema version"):
        GeneratedOwnership.load(manifest_path, vault_root)


def test_serialization_deterministic(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("b.md", b"b", "gen1", "1")
    ownership.write_generated_file("a.md", b"a", "gen1", "1")

    manifest_path.unlink()

    ownership.write_generated_file("c.md", b"c", "gen1", "1")
    content2 = manifest_path.read_text()
    assert content2.index('"a.md"') < content2.index('"b.md"') < content2.index('"c.md"')


def test_manifest_persistence_atomic(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("test.md", b"content", "gen1", "1.0")
    assert not manifest_path.with_suffix(".tmp").exists()


def test_failed_manifest_preserves_old(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")
    old_manifest_content = manifest_path.read_text()

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mocked fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file("test2.md", b"new", "gen1", "1.0")

    assert manifest_path.read_text() == old_manifest_content


def test_failed_write_no_false_ownership(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"

    with patch("os.replace", side_effect=Exception("write fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file(target_rel, b"content", "gen1", "1.0")

    assert not manifest_path.exists()


def test_independent_manifests(tmp_path: Path, vault_root: Path) -> None:
    m1 = tmp_path / "m1.json"
    m2 = tmp_path / "m2.json"
    o1 = GeneratedOwnership.load(m1, vault_root)
    o2 = GeneratedOwnership.load(m2, vault_root)

    o1.write_generated_file("f1.md", b"1", "gen1", "1")
    assert "f1.md" not in o2._entries


def test_contents_not_in_manifest(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("test.md", b"secretcontent", "gen1", "1")
    assert "secretcontent" not in manifest_path.read_text()


def test_repeated_load_save(manifest_path: Path, vault_root: Path) -> None:
    o1 = GeneratedOwnership.load(manifest_path, vault_root)
    o1.write_generated_file("test.md", b"content", "gen1", "1")

    o2 = GeneratedOwnership.load(manifest_path, vault_root)
    o2.write_generated_file("test.md", b"content2", "gen1", "1")

    o3 = GeneratedOwnership.load(manifest_path, vault_root)
    assert o3._entries["test.md"].content_hash == stream_sha256(vault_root / "test.md")


def test_human_owned_unmodified(manifest_path: Path, vault_root: Path) -> None:
    target_rel = "human.md"
    target_abs = vault_root / target_rel
    target_abs.write_text("human")

    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    with pytest.raises(UnownedFileError):
        ownership.write_generated_file(target_rel, b"gen", "gen1", "1")

    assert target_abs.read_text() == "human"


def test_rollback_existing_target_restored(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock fail")):
        with pytest.raises(PersistenceError, match="changes rolled back"):
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

    assert target_abs.read_bytes() == b"v1"


def test_rollback_new_target_removed(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    assert not target_abs.exists()


def test_rollback_manifest_untouched(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")
    original = manifest_path.read_bytes()

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

    assert manifest_path.read_bytes() == original


def test_rollback_memory_not_advanced(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")
    v1_entry = ownership._entries["test.md"]

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

    assert ownership._entries["test.md"] == v1_entry


def test_duplicate_raw_json_keys(manifest_path: Path, vault_root: Path) -> None:
    manifest_path.write_text('{"schema_version": 1, "owned_files": {"a.md": {}, "a.md": {}}}')
    with pytest.raises(ManifestError, match="Duplicate JSON key"):
        GeneratedOwnership.load(manifest_path, vault_root)


def test_duplicate_normalized_paths_rejected(manifest_path: Path, vault_root: Path) -> None:
    valid_hash = "a" * 64
    manifest_path.write_text(
        '{"schema_version": 1, "owned_files": {"a/b.md": {"generator_id": "1", "generator_version": "1", "content_hash": "'
        + valid_hash
        + '", "created_at": "1", "updated_at": "1"}, "a/./b.md": {"generator_id": "1", "generator_version": "1", "content_hash": "'
        + valid_hash
        + '", "created_at": "1", "updated_at": "1"}}}'
    )
    with pytest.raises(ManifestError, match="Duplicate normalized path"):
        GeneratedOwnership.load(manifest_path, vault_root)


def test_symlink_rejected(manifest_path: Path, vault_root: Path) -> None:
    target_rel = "link.md"
    target_abs = vault_root / target_rel
    real = vault_root / "real.md"
    real.write_text("real")
    target_abs.symlink_to(real)

    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    with pytest.raises(PathSafetyError, match="Symlink"):
        ownership.write_generated_file(target_rel, b"content", "gen1", "1")


def test_streamed_hash(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    with patch("pathlib.Path.read_bytes") as mock_read:
        with pytest.raises(ExternalModificationError):
            target_abs.write_bytes(b"modified externally")
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

        mock_read.assert_not_called()


def test_created_at_preserved(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    c1 = ownership._entries["test.md"].created_at

    ownership.write_generated_file(target_rel, b"v2", "gen1", "2")
    c2 = ownership._entries["test.md"].created_at

    assert c1 == c2


def test_failed_writes_no_timestamp_change(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    u1 = ownership._entries["test.md"].updated_at

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

    assert ownership._entries["test.md"].updated_at == u1


def test_idempotent_same_content_writes(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")
    u1 = ownership._entries["test.md"].updated_at

    ownership.write_generated_file(target_rel, b"v1", "gen1", "2")
    assert ownership._entries["test.md"].generator_version == "2"
    assert ownership._entries["test.md"].updated_at > u1

    u2 = ownership._entries["test.md"].updated_at
    ownership.write_generated_file(target_rel, b"v1", "gen1", "2")
    assert ownership._entries["test.md"].updated_at == u2


def test_generator_metadata_validation(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    with pytest.raises(ManifestError):
        ownership.write_generated_file("t.md", b"c", "", "1")
    with pytest.raises(ManifestError):
        ownership.write_generated_file("t.md", b"c", "gen", "  ")


def test_failed_version_only_update_preserves_state(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")
    v1_entry = ownership._entries["test.md"]

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock fail")):
        with pytest.raises(PersistenceError):
            ownership.write_generated_file(target_rel, b"v1", "gen1", "2")

    assert ownership._entries["test.md"] == v1_entry
    assert ownership._entries["test.md"].generator_version == "1"


def test_manifest_path_symlink_protection(
    manifest_path: Path, vault_root: Path, tmp_path: Path
) -> None:
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym_dir"
    sym_dir.symlink_to(real_dir)

    bad_manifest = sym_dir / "manifest.json"
    with pytest.raises(PathSafetyError, match="Manifest path or parent is a symlink"):
        GeneratedOwnership.load(bad_manifest, vault_root)


def test_rollback_failure_reports_both_errors(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock save fail")):
        with patch(
            "lifeos.ownership.manifest.rollback_replacement",
            side_effect=Exception("mock rollback fail"),
        ):
            with pytest.raises(PersistenceError) as exc_info:
                ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

            assert "mock save fail" in str(exc_info.value)
            assert "mock rollback fail" in str(exc_info.value)


def test_no_leftover_files_on_success(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    assert not list(vault_root.glob("*.tmp"))
    assert not list(manifest_path.parent.glob("*.tmp"))

    ownership.write_generated_file(target_rel, b"v2", "gen1", "2")
    assert not list(vault_root.glob("*.tmp"))
    assert not list(vault_root.glob(".*.backup"))
    assert not list(manifest_path.parent.glob("*.tmp"))


def test_cleanup_failure_does_not_rollback(manifest_path: Path, vault_root: Path) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")
    target_abs = vault_root / target_rel

    with patch(
        "lifeos.ownership.manifest.cleanup_backup",
        side_effect=Exception("mock cleanup fail"),
    ):
        with pytest.raises(
            PersistenceError,
            match="Target and manifest committed successfully, but failed to clean up backup file: mock cleanup fail",
        ):
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

    assert target_abs.read_text() == "v2"
    assert ownership._entries[target_rel].generator_version == "2"


def test_rollback_failure_preserves_backup_and_reports_paths(
    manifest_path: Path, vault_root: Path
) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    with patch.object(ownership, "_save_manifest", side_effect=Exception("mock save fail")):
        with patch(
            "lifeos.ownership.manifest.rollback_replacement",
            side_effect=Exception("mock rollback fail"),
        ):
            with pytest.raises(PersistenceError) as exc_info:
                ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

            err_msg = str(exc_info.value)
            assert "mock save fail" in err_msg
            assert "mock rollback fail" in err_msg
            assert "Backup file preserved at:" in err_msg

            backup_files = list(vault_root.glob(".*.backup"))
            assert len(backup_files) == 1
            assert backup_files[0].exists()


def test_backup_creation_failure_leaves_state_unchanged(
    manifest_path: Path, vault_root: Path
) -> None:
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target_rel = "test.md"
    target_abs = vault_root / target_rel
    ownership.write_generated_file(target_rel, b"v1", "gen1", "1")

    original_entry = ownership._entries[target_rel]

    with patch(
        "lifeos.ownership.manifest.create_hardlink_backup",
        side_effect=TransactionError("mock backup fail"),
    ):
        with pytest.raises(
            PersistenceError, match="Failed to create target backup: mock backup fail"
        ):
            ownership.write_generated_file(target_rel, b"v2", "gen1", "2")

    assert target_abs.read_text() == "v1"
    assert ownership._entries[target_rel] == original_entry
    assert not list(vault_root.glob(".*.backup"))


def test_default_manifest_path() -> None:
    from pathlib import PurePosixPath

    from lifeos.ownership import DEFAULT_OWNERSHIP_MANIFEST_PATH

    assert isinstance(DEFAULT_OWNERSHIP_MANIFEST_PATH, PurePosixPath)
    assert DEFAULT_OWNERSHIP_MANIFEST_PATH == PurePosixPath("system/generated-ownership.json")
    assert not str(DEFAULT_OWNERSHIP_MANIFEST_PATH).startswith(".lifeos")


def test_serialize_generated_ownership_bytes_empty() -> None:
    from lifeos.ownership.manifest import serialize_generated_ownership_bytes

    expected = b'{\n  "owned_files": {},\n  "schema_version": 1\n}'
    assert serialize_generated_ownership_bytes({}) == expected


def test_serialize_generated_ownership_bytes_sorting() -> None:
    from datetime import datetime, timezone

    from lifeos.ownership.manifest import ManifestEntry, serialize_generated_ownership_bytes

    dt = datetime(2026, 7, 13, tzinfo=timezone.utc).isoformat()
    hash_a = "a" * 64
    hash_b = "b" * 64
    entries1 = {
        "b.md": ManifestEntry("gen1", "1", hash_b, dt, dt),
        "a.md": ManifestEntry("gen1", "1", hash_a, dt, dt),
    }
    entries2 = {
        "a.md": ManifestEntry("gen1", "1", hash_a, dt, dt),
        "b.md": ManifestEntry("gen1", "1", hash_b, dt, dt),
    }

    bytes1 = serialize_generated_ownership_bytes(entries1)
    bytes2 = serialize_generated_ownership_bytes(entries2)

    assert bytes1 == bytes2
    assert bytes1.index(b'"a.md"') < bytes1.index(b'"b.md"')


def test_committed_manifest_loads_successfully(tmp_path: Path) -> None:
    from lifeos.ownership import DEFAULT_OWNERSHIP_MANIFEST_PATH

    project_root = Path(__file__).resolve().parent.parent.parent
    committed_manifest = project_root / DEFAULT_OWNERSHIP_MANIFEST_PATH

    ownership = GeneratedOwnership.load(committed_manifest, tmp_path)
    assert not ownership._entries

    from lifeos.ownership.manifest import serialize_generated_ownership_bytes

    assert committed_manifest.read_bytes() == serialize_generated_ownership_bytes({})


def test_pure_byte_parser(tmp_path: Path) -> None:
    from lifeos.ownership.manifest import GeneratedOwnership

    valid_json = b"""{
      "schema_version": 1,
      "owned_files": {
        "a.md": {
          "generator_id": "gen1",
          "generator_version": "1.0",
          "content_hash": "a" * 64,
          "created_at": "2026-07-13T00:00:00+00:00",
          "updated_at": "2026-07-13T00:00:00+00:00"
        }
      }
    }"""
    valid_json = valid_json.replace(b'"a" * 64', b'"' + b"a" * 64 + b'"')

    ownership = GeneratedOwnership.from_bytes(
        valid_json, manifest_path=Path("dummy"), vault_root=tmp_path
    )
    assert "a.md" in ownership._entries
    assert ownership._entries["a.md"].generator_id == "gen1"

    import pytest
    from lifeos.ownership.manifest import ManifestError

    with pytest.raises(ManifestError, match="Malformed JSON"):
        GeneratedOwnership.from_bytes(
            b'{ "invalid": }', manifest_path=Path("dummy"), vault_root=tmp_path
        )

    with pytest.raises(ManifestError, match="Manifest bytes are not valid UTF-8"):
        GeneratedOwnership.from_bytes(b"\xff\xfe", manifest_path=Path("dummy"), vault_root=tmp_path)

    duplicate_json = b"""{
      "schema_version": 1,
      "owned_files": {},
      "owned_files": {}
    }"""
    with pytest.raises(ManifestError, match="Duplicate JSON key found"):
        GeneratedOwnership.from_bytes(
            duplicate_json, manifest_path=Path("dummy"), vault_root=tmp_path
        )
