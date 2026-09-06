import hashlib
import os
from pathlib import Path

import pytest

import lifeos.ownership.manifest as ownership_manifest
from lifeos._transaction_files import TransactionError
from lifeos.ownership import (
    ExternalModificationError,
    GeneratedOwnership,
    ManifestError,
    PathSafetyError,
    PersistenceError,
    UnownedFileError,
)
from lifeos.vault import VaultAccessError


def _vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return vault_root


def _empty_manifest(path: Path) -> None:
    path.write_text('{"schema_version": 1, "owned_files": {}}', encoding="utf-8")


def test_load_rejects_final_manifest_symlink(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    real_manifest = tmp_path / "real-manifest.json"
    _empty_manifest(real_manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.symlink_to(real_manifest)

    with pytest.raises(PathSafetyError, match="Manifest path or parent is a symlink"):
        GeneratedOwnership.load(manifest_path, vault_root)


def test_load_rejects_manifest_parent_symlink(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    _empty_manifest(real_parent / "manifest.json")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(PathSafetyError, match="Manifest path or parent is a symlink"):
        GeneratedOwnership.load(linked_parent / "manifest.json", vault_root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_load_rejects_fifo_manifest_without_blocking(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    os.mkfifo(manifest_path)

    with pytest.raises(PathSafetyError, match="cannot be read safely"):
        GeneratedOwnership.load(manifest_path, vault_root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_owned_target_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")

    target = vault_root / "owned.md"
    target.unlink()
    os.mkfifo(target)

    with pytest.raises(PathSafetyError, match="cannot be inspected safely"):
        ownership.write_generated_file("owned.md", b"v2", "gen", "2")


def test_owned_target_parent_symlink_is_rejected(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    owned_parent = vault_root / "generated"
    owned_parent.mkdir()
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("generated/owned.md", b"v1", "gen", "1")

    real_parent = tmp_path / "replacement"
    real_parent.mkdir()
    (real_parent / "owned.md").write_bytes(b"v1")
    (owned_parent / "owned.md").unlink()
    owned_parent.rmdir()
    owned_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(PathSafetyError, match="Symlinks are not allowed"):
        ownership.write_generated_file("generated/owned.md", b"v2", "gen", "2")


def test_missing_owned_target_retains_regeneration_semantics(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")
    created_at = ownership.entries["owned.md"].created_at

    (vault_root / "owned.md").unlink()
    ownership.write_generated_file("owned.md", b"v2", "gen", "2")

    assert (vault_root / "owned.md").read_bytes() == b"v2"
    assert ownership.entries["owned.md"].created_at == created_at


def test_owned_target_observation_maps_race_to_external_modification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")
    original_observe = ownership_manifest.observe_vault_file

    def racing_observe(root: Path, relative_path: str, **kwargs: object):
        if root == vault_root.resolve() and relative_path == "owned.md":
            raise VaultAccessError(
                "concurrent-change",
                relative_path,
                f"Vault file changed while it was being read: {relative_path}",
            )
        return original_observe(root, relative_path, **kwargs)

    monkeypatch.setattr(ownership_manifest, "observe_vault_file", racing_observe)

    with pytest.raises(ExternalModificationError, match="changed while it was being verified"):
        ownership.write_generated_file("owned.md", b"v2", "gen", "2")


def test_manifest_observation_maps_race_to_manifest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    _empty_manifest(manifest_path)

    def racing_observe(root: Path, relative_path: str, **kwargs: object):
        raise VaultAccessError(
            "concurrent-change",
            relative_path,
            f"Vault file changed while it was being read: {relative_path}",
        )

    monkeypatch.setattr(ownership_manifest, "observe_vault_file", racing_observe)

    with pytest.raises(ManifestError, match="Failed to read manifest file"):
        GeneratedOwnership.load(manifest_path, vault_root)


def test_existing_target_mutation_no_longer_uses_pathname_stream_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")

    def forbidden_stream_hash(_path: Path) -> str:
        raise AssertionError("pathname stream hash must not be used for ownership mutation")

    monkeypatch.setattr(ownership_manifest, "stream_sha256", forbidden_stream_hash)
    ownership.write_generated_file("owned.md", b"v2", "gen", "2")

    assert (vault_root / "owned.md").read_bytes() == b"v2"


def test_version_only_update_revalidates_target_before_manifest_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")
    original_entry = ownership.entries["owned.md"]
    target = vault_root / "owned.md"
    original_observe = ownership._observe_existing_target
    calls = 0

    def racing_observe(rel_path: str):
        nonlocal calls
        observation = original_observe(rel_path)
        calls += 1
        if calls == 1:
            target.write_bytes(b"external")
        return observation

    monkeypatch.setattr(ownership, "_observe_existing_target", racing_observe)

    with pytest.raises(ExternalModificationError, match="changed before manifest update"):
        ownership.write_generated_file("owned.md", b"v1", "gen", "2")

    assert calls == 2
    assert target.read_bytes() == b"external"
    assert ownership.entries["owned.md"] == original_entry
    assert GeneratedOwnership.load(manifest_path, vault_root).entries["owned.md"] == original_entry


def test_replacement_revalidates_target_at_backup_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")
    original_entry = ownership.entries["owned.md"]
    target = vault_root / "owned.md"
    original_backup = ownership_manifest.create_hardlink_backup

    def racing_backup(*args: object, **kwargs: object):
        target.write_bytes(b"external")
        return original_backup(*args, **kwargs)

    monkeypatch.setattr(ownership_manifest, "create_hardlink_backup", racing_backup)

    with pytest.raises(ExternalModificationError, match="changed before backup"):
        ownership.write_generated_file("owned.md", b"v2", "gen", "2")

    assert target.read_bytes() == b"external"
    assert ownership.entries["owned.md"] == original_entry
    assert not list(vault_root.glob(".*.backup"))


def test_manifest_failure_never_rolls_back_over_concurrent_target_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")
    original_entry = ownership.entries["owned.md"]
    target = vault_root / "owned.md"

    def fail_manifest_after_external_edit() -> None:
        target.write_bytes(b"external")
        raise Exception("mock save fail")

    monkeypatch.setattr(ownership, "_save_manifest", fail_manifest_after_external_edit)

    with pytest.raises(PersistenceError, match="rollback failed"):
        ownership.write_generated_file("owned.md", b"v2", "gen", "2")

    assert target.read_bytes() == b"external"
    assert ownership.entries["owned.md"] == original_entry
    assert len(list(vault_root.glob(".*.backup"))) == 1


def test_creation_refuses_target_that_appears_at_publication_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    target = vault_root / "new.md"
    original_publish = ownership_manifest.publish_creation

    def racing_publish(*args: object, **kwargs: object):
        target.write_bytes(b"human")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(ownership_manifest, "publish_creation", racing_publish)

    with pytest.raises(UnownedFileError, match="exists but is unowned"):
        ownership.write_generated_file("new.md", b"generated", "gen", "1")

    assert target.read_bytes() == b"human"
    assert "new.md" not in ownership.entries
    assert not manifest_path.exists()


def test_new_generated_file_respects_process_umask(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    ownership = GeneratedOwnership.load(tmp_path / "manifest.json", vault_root)

    previous_umask = os.umask(0o077)
    try:
        ownership.write_generated_file("private.md", b"private", "gen", "1")
    finally:
        os.umask(previous_umask)

    assert (vault_root / "private.md").stat().st_mode & 0o777 == 0o600


def test_existing_target_parent_deleted_during_update_is_not_recreated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("generated/owned.md", b"v1", "gen", "1")
    parent = vault_root / "generated"
    original_observe = ownership._observe_existing_target

    def deleting_observe(rel_path: str):
        observation = original_observe(rel_path)
        (parent / "owned.md").unlink()
        parent.rmdir()
        return observation

    monkeypatch.setattr(ownership, "_observe_existing_target", deleting_observe)

    with pytest.raises(PathSafetyError, match="cannot be inspected safely"):
        ownership.write_generated_file("generated/owned.md", b"v2", "gen", "2")

    assert not parent.exists()
    assert ownership.entries["generated/owned.md"].content_hash == hashlib.sha256(b"v1").hexdigest()


def test_replacement_publication_failure_preserves_backup_when_target_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")
    original_entry = ownership.entries["owned.md"]
    target = vault_root / "owned.md"

    def failing_publish(*_args: object, **_kwargs: object) -> None:
        target.unlink()
        raise TransactionError("publication failed after original removal")

    monkeypatch.setattr(ownership_manifest, "publish_replacement", failing_publish)

    with pytest.raises(ExternalModificationError, match="changed during mutation"):
        ownership.write_generated_file("owned.md", b"v2", "gen", "2")

    backups = list(vault_root.glob(".*.backup"))
    assert not target.exists()
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"v1"
    assert ownership.entries["owned.md"] == original_entry


def test_backup_transaction_failure_with_unchanged_target_is_persistence_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen", "1")

    def failing_backup(*_args: object, **_kwargs: object):
        raise TransactionError("backup unavailable")

    monkeypatch.setattr(ownership_manifest, "create_hardlink_backup", failing_backup)

    with pytest.raises(PersistenceError, match="Failed to create target backup"):
        ownership.write_generated_file("owned.md", b"v2", "gen", "2")

    assert (vault_root / "owned.md").read_bytes() == b"v1"
