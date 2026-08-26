from __future__ import annotations

from pathlib import Path

from lifeos.registry import Registry, register_scan, resolve_registered_stable_id
from lifeos.scanner import scan_vault


def _note(stable_id: str, title: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\nBody\n"


def test_scoped_refresh_preserves_hidden_identity_for_later_trusted_relocation(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    private = vault / "private"
    private.mkdir(parents=True)
    old_path = private / "old.md"
    new_path = private / "new.md"
    old_path.write_text(_note("private-id", "Private"), encoding="utf-8")

    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    register_scan(registry, vault, scan_vault(vault))
    with registry.connect_read_only() as connection:
        original = connection.execute(
            "SELECT id, content_hash FROM files WHERE stable_id = 'private-id'"
        ).fetchone()
    assert original is not None

    def deny_private(path: str) -> bool:
        return not path.startswith("private/")

    register_scan(
        registry,
        vault,
        scan_vault(vault),
        identity_allow_path=deny_private,
    )
    with registry.connect_read_only() as connection:
        after_scoped = connection.execute(
            "SELECT id, stable_id, content_hash FROM files WHERE vault_path = 'private/old.md'"
        ).fetchone()
    assert after_scoped is not None
    assert after_scoped["id"] == original["id"]
    assert after_scoped["stable_id"] == "private-id"
    assert after_scoped["content_hash"] == original["content_hash"]

    old_path.rename(new_path)
    register_scan(
        registry,
        vault,
        scan_vault(vault),
        identity_allow_path=deny_private,
    )

    result = register_scan(registry, vault, scan_vault(vault))
    resolved = resolve_registered_stable_id(registry, "private-id")

    assert resolved is not None
    assert resolved.path == "private/new.md"
    assert ("private/old.md", "private/new.md") in result.renamed
    with registry.connect_read_only() as connection:
        relocated = connection.execute(
            "SELECT id FROM files WHERE stable_id = 'private-id' AND is_deleted = 0"
        ).fetchone()
    assert relocated is not None
    assert relocated["id"] == original["id"]


def test_identity_entering_visible_scope_reuses_trusted_lineage_on_unscoped_refresh(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    private = vault / "private"
    wiki = vault / "wiki"
    private.mkdir(parents=True)
    wiki.mkdir(parents=True)
    old_path = private / "old.md"
    new_path = wiki / "new.md"
    old_path.write_text(_note("cross-scope-id", "Cross scope"), encoding="utf-8")

    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    register_scan(registry, vault, scan_vault(vault))
    with registry.connect() as connection:
        original = connection.execute(
            "SELECT id FROM files WHERE stable_id = 'cross-scope-id'"
        ).fetchone()
        assert original is not None
        original_id = int(original["id"])
        connection.execute(
            "INSERT INTO source_versions (source_id, version_hash, original_file_id) "
            "VALUES (?, ?, ?)",
            ("cross-scope-source", "version-1", original_id),
        )
        connection.commit()

    old_path.rename(new_path)

    def deny_private(path: str) -> bool:
        return not path.startswith("private/")

    scoped = register_scan(
        registry,
        vault,
        scan_vault(vault),
        identity_allow_path=deny_private,
    )
    assert scoped.renamed == []
    with registry.connect_read_only() as connection:
        hidden = connection.execute(
            "SELECT id, stable_id, is_deleted FROM files WHERE id = ?",
            (original_id,),
        ).fetchone()
        visible = connection.execute(
            "SELECT id, stable_id, is_deleted FROM files WHERE vault_path = 'wiki/new.md'"
        ).fetchone()
        source_version = connection.execute(
            "SELECT original_file_id FROM source_versions WHERE source_id = 'cross-scope-source'"
        ).fetchone()
    assert hidden is not None
    assert hidden["stable_id"] == "cross-scope-id"
    assert hidden["is_deleted"] == 1
    assert visible is not None
    assert visible["id"] != original_id
    assert visible["stable_id"] is None
    assert visible["is_deleted"] == 0
    assert source_version is not None
    assert source_version["original_file_id"] == original_id

    result = register_scan(registry, vault, scan_vault(vault))

    assert ("private/old.md", "wiki/new.md") in result.renamed
    resolved = resolve_registered_stable_id(registry, "cross-scope-id")
    assert resolved is not None
    assert resolved.path == "wiki/new.md"
    with registry.connect_read_only() as connection:
        active = connection.execute(
            "SELECT id, stable_id FROM files WHERE vault_path = 'wiki/new.md' AND is_deleted = 0"
        ).fetchone()
        source_version = connection.execute(
            "SELECT original_file_id FROM source_versions WHERE source_id = 'cross-scope-source'"
        ).fetchone()
        provisional = connection.execute(
            "SELECT is_deleted FROM files WHERE id != ? AND vault_path LIKE '.lifeos/registry-tombstones/%wiki/new.md'",
            (original_id,),
        ).fetchone()
    assert active is not None
    assert active["id"] == original_id
    assert active["stable_id"] == "cross-scope-id"
    assert source_version is not None
    assert source_version["original_file_id"] == original_id
    assert provisional is not None
    assert provisional["is_deleted"] == 1
