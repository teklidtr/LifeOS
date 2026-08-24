from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.registry import (
    FileTrackingError,
    Registry,
    list_registered_stable_identities,
    register_scan,
    resolve_registered_stable_id,
)
from lifeos.scanner import scan_vault


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
    assert [(item.stable_id, item.path) for item in identities] == [
        ("duplicate", "wiki/a.md")
    ]
    with registry.connect_read_only() as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1


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
