from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import lifeos.coherence_scoped as coherence_scoped
from lifeos.mcp.runtime_server import create_mcp_server


def _note(stable_id: str, title: str, body: str = "Body") -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\n{body}\n"


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


def test_custom_runtime_is_excluded_from_all_composed_mcp_exploration(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    runtime_dir = wiki / "runtime-node"
    canonical = wiki / "canonical.md"
    target = wiki / "target.md"
    derived = runtime_dir / "derived.md"
    derived.parent.mkdir(parents=True)
    canonical.write_text(
        _note("canonical-id", "Canonical", "The canonical-visible-marker is allowed."),
        encoding="utf-8",
    )
    target.write_text(_note("target-id", "Target", "Target body."), encoding="utf-8")
    derived.write_text(
        _note(
            "derived-id",
            "Derived",
            "The derived-runtime-only-marker must never escape. [[wiki/target]]",
        ),
        encoding="utf-8",
    )
    server = _server(vault, runtime_dir)

    listing = server._tool_manager.get_tool("vault_list").fn(prefix="wiki")
    assert all(
        not entry["path"].startswith("wiki/runtime-node")
        for entry in listing["entries"]
    )

    search = server._tool_manager.get_tool("vault_search").fn(
        query="derived-runtime-only-marker"
    )
    assert search["hits"] == []

    wiki_search = server._tool_manager.get_tool("wiki_search").fn(
        query="derived-runtime-only-marker"
    )
    assert wiki_search["hits"] == []

    context = server._tool_manager.get_tool("vault_context").fn(
        question="derived-runtime-only-marker"
    )
    assert all(
        not source["path"].startswith("wiki/runtime-node")
        for source in context["sources"]
    )

    links = server._tool_manager.get_tool("vault_links").fn(
        path="wiki/target.md",
        direction="backlinks",
    )
    assert all(
        not link["source_path"].startswith("wiki/runtime-node")
        for link in links["links"]
    )

    with pytest.raises(ToolError):
        server._tool_manager.get_tool("vault_read_markdown").fn(
            vault_path="wiki/runtime-node/derived.md"
        )
