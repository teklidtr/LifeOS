from pathlib import Path

from lifeos.registry import Registry
from lifeos.registry.file_tracking import register_scan
from lifeos.scanner import VaultFile


def test_register_scan_handles_unhashable_frontmatter_without_mutating_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    path = vault_root / "malformed.md"
    content = "---\nid: should-not-be-trusted\n? [left, right]\n: value\n---\nHuman body"
    path.write_text(content, encoding="utf-8")

    registry = Registry(tmp_path / "registry.sqlite")
    registry.initialize()
    entry = VaultFile(
        path=Path("malformed.md"),
        file_type=".md",
        size_bytes=len(content.encode("utf-8")),
    )

    result = register_scan(registry, vault_root, [entry])

    assert result.new == ["malformed.md"]
    assert path.read_text(encoding="utf-8") == content
    with registry.connect_read_only() as conn:
        row = conn.execute(
            "SELECT stable_id FROM files WHERE vault_path = ?",
            ("malformed.md",),
        ).fetchone()
    assert row is not None
    assert row["stable_id"] is None
