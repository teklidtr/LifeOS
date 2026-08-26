from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import lifeos.registry.coherent_tracking as coherent_tracking
from lifeos.registry import FileTrackingError, Registry, register_scan
from lifeos.scanner import scan_vault
from lifeos.vault import VaultAccessError


def _note(stable_id: str) -> str:
    return f"---\nid: {stable_id}\ntype: wiki\ntitle: Example\n---\nBody\n"


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def _assert_registry_empty(registry: Registry) -> None:
    with registry.connect_read_only() as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0


def test_unscoped_registry_rejects_symlink_replacement_after_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "note.md"
    target.write_text(_note("canonical-id"), encoding="utf-8")
    entries = scan_vault(vault)

    outside = tmp_path / "outside.md"
    outside.write_text(_note("outside-id"), encoding="utf-8")
    target.unlink()
    target.symlink_to(outside)

    registry = _registry(tmp_path)
    with pytest.raises(FileTrackingError, match="safely open registry file"):
        register_scan(registry, vault, entries)

    _assert_registry_empty(registry)


def test_scoped_registry_maps_unstable_vault_observation_to_scan_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "note.md"
    target.write_text(_note("canonical-id"), encoding="utf-8")
    entries = scan_vault(vault)
    registry = _registry(tmp_path)

    def unstable_observation(*_args, **_kwargs):
        raise VaultAccessError(
            "concurrent-change",
            "wiki/note.md",
            "Vault file changed while it was being read: wiki/note.md",
        )

    monkeypatch.setattr(coherent_tracking, "observe_vault_file", unstable_observation)

    with pytest.raises(FileTrackingError, match="changed during scoped hashing"):
        register_scan(
            registry,
            vault,
            entries,
            identity_allow_path=lambda _path: True,
        )

    _assert_registry_empty(registry)


def test_large_markdown_scan_hashes_full_file_but_parses_only_frontmatter_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "large.md"
    content = (
        "---\nid: large-note\ntype: wiki\ntitle: Large\n---\n"
        + ("body-data\n" * 200_000)
    ).encode("utf-8")
    target.write_bytes(content)
    entries = scan_vault(vault)
    registry = _registry(tmp_path)

    original_parse = coherent_tracking.parse_markdown_note
    parsed_sizes: list[int] = []

    def record_identity_parse(path: Path, *, content: str | None = None):
        assert content is not None
        parsed_sizes.append(len(content.encode("utf-8")))
        return original_parse(path, content=content)

    monkeypatch.setattr(coherent_tracking, "parse_markdown_note", record_identity_parse)

    register_scan(registry, vault, entries)

    assert parsed_sizes
    assert max(parsed_sizes) < 1024
    with registry.connect_read_only() as connection:
        row = connection.execute(
            "SELECT stable_id, content_hash, size_bytes FROM files WHERE vault_path = ?",
            ("wiki/large.md",),
        ).fetchone()
    assert row is not None
    assert row["stable_id"] == "large-note"
    assert row["content_hash"] == hashlib.sha256(content).hexdigest()
    assert row["size_bytes"] == len(content)
