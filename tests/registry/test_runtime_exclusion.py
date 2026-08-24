from __future__ import annotations

from pathlib import Path

from lifeos.registry import Registry, list_registered_stable_identities, register_scan
from lifeos.scanner import scan_vault


def _note(stable_id: str, title: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\nBody\n"


def test_custom_in_vault_registry_runtime_is_not_canonical_scan_input(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "wiki" / "note.md"
    runtime_dir = vault / "runtime" / "node-a"
    derived = runtime_dir / "exports" / "public-wiki" / "wiki" / "note.md"
    canonical.parent.mkdir(parents=True)
    derived.parent.mkdir(parents=True)
    canonical.write_text(_note("shared-id", "Canonical"), encoding="utf-8")
    derived.write_text(_note("shared-id", "Derived copy"), encoding="utf-8")

    registry = Registry(runtime_dir / "registry.db")
    registry.initialize()
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.new == ["wiki/note.md"]
    identities = list_registered_stable_identities(registry)
    assert [(identity.stable_id, identity.path) for identity in identities] == [
        ("shared-id", "wiki/note.md")
    ]
    with registry.connect_read_only() as connection:
        paths = [
            row["vault_path"]
            for row in connection.execute(
                "SELECT vault_path FROM files WHERE is_deleted = 0 ORDER BY vault_path"
            ).fetchall()
        ]
    assert paths == ["wiki/note.md"]
