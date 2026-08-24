from __future__ import annotations

from pathlib import Path

from lifeos.registry import Registry, register_scan, resolve_registered_stable_id
from lifeos.scanner import scan_vault


def _note(stable_id: str, body: str) -> str:
    return f"---\nid: {stable_id}\ntype: wiki\ntitle: Example\n---\n{body}\n"


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def test_delayed_reappearance_reports_last_canonical_path_not_tombstone(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    reused_path = wiki / "note.md"
    reused_path.write_text(_note("note-a", "A"), encoding="utf-8")
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    # Confirm A deleted, then let another identity reuse A's former path. This parks A's
    # historical registry row outside the live path namespace while preserving its lineage.
    reused_path.unlink()
    register_scan(registry, vault, scan_vault(vault))
    reused_path.write_text(_note("note-b", "B"), encoding="utf-8")
    register_scan(registry, vault, scan_vault(vault))

    # B disappears while a delayed synchronized copy of A arrives at a different path.
    reused_path.unlink()
    restored_path = wiki / "restored-a.md"
    restored_path.write_text(_note("note-a", "A"), encoding="utf-8")
    result = register_scan(registry, vault, scan_vault(vault))

    assert result.renamed == [("wiki/note.md", "wiki/restored-a.md")]
    assert all(".lifeos/registry-tombstones/" not in path for pair in result.renamed for path in pair)
    restored = resolve_registered_stable_id(registry, "note-a")
    assert restored is not None
    assert restored.path == "wiki/restored-a.md"
    assert resolve_registered_stable_id(registry, "note-b") is None