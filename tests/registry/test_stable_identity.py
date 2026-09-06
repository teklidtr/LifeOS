from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import lifeos.registry.coherent_tracking as coherent_tracking
from lifeos.registry import (
    FileTrackingError,
    Registry,
    list_registered_stable_identities,
    register_scan,
    resolve_registered_stable_id,
)
from lifeos.scanner import VaultFile, scan_vault


def _note(stable_id: str | None, body: str = "Body\n") -> str:
    identifier = f"id: {stable_id}\n" if stable_id is not None else ""
    return f"---\n{identifier}type: wiki\ntitle: Example\n---\n{body}"


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def test_registry_recognizes_pure_relocation_by_stable_id(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    source = vault / "wiki" / "old.md"
    source.write_text(_note("wiki-example"), encoding="utf-8")
    registry = _registry(tmp_path)

    register_scan(registry, vault, scan_vault(vault))
    with registry.connect_read_only() as connection:
        original_row_id = connection.execute(
            "SELECT id FROM files WHERE vault_path = 'wiki/old.md'"
        ).fetchone()["id"]

    source.rename(vault / "wiki" / "new.md")
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.renamed == [("wiki/old.md", "wiki/new.md")]
    assert result.deleted == []
    assert result.new == []
    resolved = resolve_registered_stable_id(registry, "wiki-example")
    assert resolved is not None
    assert resolved.path == "wiki/new.md"
    with registry.connect_read_only() as connection:
        current_row_id = connection.execute(
            "SELECT id FROM files WHERE vault_path = 'wiki/new.md'"
        ).fetchone()["id"]
    assert current_row_id == original_row_id


def test_registry_reports_relocation_plus_modification(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    source = vault / "wiki" / "old.md"
    source.write_text(_note("wiki-example", "Original\n"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    source.unlink()
    (vault / "wiki" / "new.md").write_text(
        _note("wiki-example", "Synchronized edit\n"), encoding="utf-8"
    )
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.renamed == [("wiki/old.md", "wiki/new.md")]
    assert result.modified == ["wiki/new.md"]
    assert result.deleted == []


def test_registry_reconciles_deleted_destination_before_relocation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    source = wiki / "a.md"
    destination = wiki / "b.md"
    source.write_text(_note("note-a"), encoding="utf-8")
    destination.write_text(_note("note-b"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    with registry.connect_read_only() as connection:
        displaced_row_id = connection.execute(
            "SELECT id FROM files WHERE stable_id = 'note-b'"
        ).fetchone()["id"]

    destination.unlink()
    source.rename(destination)
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.renamed == [("wiki/a.md", "wiki/b.md")]
    assert result.deleted == []
    resolved = resolve_registered_stable_id(registry, "note-a")
    assert resolved is not None
    assert resolved.path == "wiki/b.md"
    assert resolve_registered_stable_id(registry, "note-b") is None
    with registry.connect_read_only() as connection:
        displaced = connection.execute(
            "SELECT vault_path, stable_id, is_deleted FROM files WHERE id = ?",
            (displaced_row_id,),
        ).fetchone()
    assert displaced["is_deleted"] == 1
    assert displaced["stable_id"] == "note-b"
    assert displaced["vault_path"].startswith(".lifeos/registry-tombstones/")


def test_registry_preserves_both_row_identities_when_notes_swap_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    path_a = wiki / "a.md"
    path_b = wiki / "b.md"
    content_a = _note("note-a", "A\n")
    content_b = _note("note-b", "B\n")
    path_a.write_text(content_a, encoding="utf-8")
    path_b.write_text(content_b, encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    with registry.connect() as connection:
        rows = {
            row["stable_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, stable_id FROM files WHERE stable_id IS NOT NULL"
            ).fetchall()
        }
        connection.execute(
            "INSERT INTO source_versions (source_id, version_hash, original_file_id) "
            "VALUES (?, ?, ?)",
            ("source-a", "hash-a", rows["note-a"]),
        )
        connection.execute(
            "INSERT INTO source_versions (source_id, version_hash, original_file_id) "
            "VALUES (?, ?, ?)",
            ("source-b", "hash-b", rows["note-b"]),
        )
        connection.commit()

    path_a.write_text(content_b, encoding="utf-8")
    path_b.write_text(content_a, encoding="utf-8")
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.renamed == [
        ("wiki/a.md", "wiki/b.md"),
        ("wiki/b.md", "wiki/a.md"),
    ]
    with registry.connect_read_only() as connection:
        current = {
            row["stable_id"]: (row["id"], row["vault_path"])
            for row in connection.execute(
                "SELECT id, stable_id, vault_path FROM files WHERE is_deleted = 0"
            ).fetchall()
        }
        source_rows = {
            row["source_id"]: row["original_file_id"]
            for row in connection.execute(
                "SELECT source_id, original_file_id FROM source_versions"
            ).fetchall()
        }
    assert current["note-a"] == (rows["note-a"], "wiki/b.md")
    assert current["note-b"] == (rows["note-b"], "wiki/a.md")
    assert source_rows == {"source-a": rows["note-a"], "source-b": rows["note-b"]}


def test_new_identity_can_reuse_path_after_old_identity_was_confirmed_deleted(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    path = wiki / "note.md"
    path.write_text(_note("old-id"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    path.unlink()
    register_scan(registry, vault, scan_vault(vault))
    path.write_text(_note("new-id"), encoding="utf-8")
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.new == ["wiki/note.md"]
    new_identity = resolve_registered_stable_id(registry, "new-id")
    assert new_identity is not None
    assert new_identity.path == "wiki/note.md"
    assert resolve_registered_stable_id(registry, "old-id") is None
    with registry.connect_read_only() as connection:
        old_row = connection.execute(
            "SELECT vault_path, stable_id, is_deleted FROM files WHERE stable_id = 'old-id'"
        ).fetchone()
    assert old_row["is_deleted"] == 1
    assert old_row["vault_path"].startswith(".lifeos/registry-tombstones/")


def test_binary_scan_capture_discards_attachment_bytes() -> None:
    capture, _prefix = coherent_tracking._capture_for(
        VaultFile(path=Path("captures/large.pdf"), file_type=".pdf", size_bytes=10_000_000)
    )

    assert not isinstance(capture.chunks, list)
    capture.chunks.append(b"x" * 1_000_000)
    assert not isinstance(capture.chunks, list)


def test_duplicate_stable_ids_abort_refresh_before_registry_mutation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "a.md").write_text(_note("duplicate"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    (vault / "wiki" / "b.md").write_text(_note("duplicate"), encoding="utf-8")
    with pytest.raises(FileTrackingError, match="Ambiguous stable note id"):
        register_scan(registry, vault, scan_vault(vault))

    identities = list_registered_stable_identities(registry)
    assert [(item.stable_id, item.path) for item in identities] == [("duplicate", "wiki/a.md")]
    with registry.connect_read_only() as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1


def test_proposal_frontmatter_id_does_not_collide_with_note_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    proposal_dir = vault / "proposals" / "proposal-1"
    proposal_dir.mkdir(parents=True)
    (vault / "wiki" / "note.md").write_text(_note("shared-id"), encoding="utf-8")
    (proposal_dir / "proposal.md").write_text(_note("shared-id"), encoding="utf-8")
    registry = _registry(tmp_path)

    register_scan(registry, vault, scan_vault(vault))

    identities = list_registered_stable_identities(registry)
    assert [(item.stable_id, item.path) for item in identities] == [("shared-id", "wiki/note.md")]


def test_registry_derives_id_and_hash_from_same_file_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    path = vault / "wiki" / "note.md"
    original = _note("old-id", "Original bytes\n").encode()
    replacement = _note("new-id", "Replacement bytes\n").encode()
    path.write_bytes(original)
    registry = _registry(tmp_path)
    real_parser = coherent_tracking.parse_markdown_note

    def parse_then_mutate(note_path: Path, *, content: str | None = None):
        parsed = real_parser(note_path, content=content)
        path.write_bytes(replacement)
        return parsed

    monkeypatch.setattr(coherent_tracking, "parse_markdown_note", parse_then_mutate)
    register_scan(registry, vault, scan_vault(vault))

    resolved = resolve_registered_stable_id(registry, "old-id")
    assert resolved is not None
    assert resolved.content_hash == hashlib.sha256(original).hexdigest()
    assert resolve_registered_stable_id(registry, "new-id") is None


def test_removing_stable_id_is_identity_change_and_rolls_back(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    path = vault / "wiki" / "note.md"
    path.write_text(_note("wiki-example"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    path.write_text(_note(None), encoding="utf-8")
    with pytest.raises(FileTrackingError, match="Stable note identity changed in place"):
        register_scan(registry, vault, scan_vault(vault))

    resolved = resolve_registered_stable_id(registry, "wiki-example")
    assert resolved is not None
    assert resolved.path == "wiki/note.md"


def test_changing_stable_id_is_identity_change_and_rolls_back(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    path = vault / "wiki" / "note.md"
    path.write_text(_note("old-id"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    path.write_text(_note("new-id"), encoding="utf-8")
    with pytest.raises(FileTrackingError, match="Stable note identity changed in place"):
        register_scan(registry, vault, scan_vault(vault))

    assert resolve_registered_stable_id(registry, "old-id") is not None
    assert resolve_registered_stable_id(registry, "new-id") is None


def test_legacy_note_can_gain_stable_id_during_explicit_migration(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    path = vault / "wiki" / "legacy.md"
    path.write_text(_note(None), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    path.write_text(_note("migrated-id"), encoding="utf-8")
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.modified == ["wiki/legacy.md"]
    resolved = resolve_registered_stable_id(registry, "migrated-id")
    assert resolved is not None
    assert resolved.path == "wiki/legacy.md"
