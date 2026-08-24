from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import lifeos.coherence_scoped as coherence_scoped
from lifeos.mcp.runtime_server import create_mcp_server


def _note(stable_id: str, title: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\nBody\n"


def _server(vault: Path, runtime_dir: Path):
    return create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime_dir,
    )


def test_custom_in_vault_runtime_markdown_cannot_ambiguous_canonical_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "wiki" / "note.md"
    runtime_dir = vault / "runtime" / "node-a"
    derived = runtime_dir / "exports" / "public-wiki" / "wiki" / "note.md"
    canonical.parent.mkdir(parents=True)
    derived.parent.mkdir(parents=True)
    canonical.write_text(_note("shared-id", "Canonical"), encoding="utf-8")
    derived.write_text(_note("shared-id", "Derived copy"), encoding="utf-8")

    real_parser = coherence_scoped.parse_markdown_note

    def reject_runtime_read(note_path: Path, *, content: str | None = None):
        assert runtime_dir not in note_path.parents
        return real_parser(note_path, content=content)

    monkeypatch.setattr(coherence_scoped, "parse_markdown_note", reject_runtime_read)
    result = _server(vault, runtime_dir)._tool_manager.get_tool("vault_note_identity").fn(
        vault_path="wiki/note.md"
    )

    assert result["stable_id"] == "shared-id"
    assert result["current_path"] == "wiki/note.md"
    assert result["relocation_safe"] is True


def test_note_identity_lookup_is_visible_in_runtime_activity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime_dir = vault / ".lifeos"
    canonical = vault / "wiki" / "note.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(_note("audit-id", "Audited"), encoding="utf-8")
    server = _server(vault, runtime_dir)

    server._tool_manager.get_tool("vault_note_identity").fn(vault_path="wiki/note.md")
    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)

    matching = [record for record in activity["records"] if record["tool"] == "vault_note_identity"]
    assert matching
    assert matching[-1]["source_paths"] == ["wiki/note.md"]