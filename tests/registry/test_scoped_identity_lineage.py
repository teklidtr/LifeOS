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
