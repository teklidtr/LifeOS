from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import lifeos.coherence_scoped as coherence_scoped
from lifeos.mcp.runtime_server import create_mcp_server


def _server(vault: Path):
    return create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=vault / ".lifeos",
    )


def test_mcp_note_identity_exposes_stable_id_current_path_and_hash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "moved-here.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\nid: concept-identity\ntype: concept\ntitle: Identity\n---\nBody\n",
        encoding="utf-8",
    )

    server = _server(vault)
    result = server._tool_manager.get_tool("vault_note_identity").fn(
        vault_path="wiki/moved-here.md"
    )

    assert result["stable_id"] == "concept-identity"
    assert result["current_path"] == "wiki/moved-here.md"
    assert result["content_hash"].startswith("sha256:")
    assert result["relocation_safe"] is True


def test_mcp_note_identity_fails_closed_for_duplicate_id(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for name in ("one.md", "two.md"):
        note = vault / "wiki" / name
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\nid: duplicate-concept\ntype: concept\ntitle: Duplicate\n---\nBody\n",
            encoding="utf-8",
        )

    server = _server(vault)
    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool("vault_note_identity").fn(vault_path="wiki/one.md")


def test_public_mcp_identity_does_not_read_or_leak_protected_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    public = vault / "wiki" / "public.md"
    protected = vault / "private" / "hidden.md"
    public.parent.mkdir(parents=True)
    protected.parent.mkdir(parents=True)
    public.write_text(
        "---\nid: shared-id\ntype: concept\ntitle: Public\n---\nPublic body\n",
        encoding="utf-8",
    )
    protected.write_text(
        "---\nid: shared-id\ntype: concept\ntitle: Hidden\n---\nProtected body\n",
        encoding="utf-8",
    )

    real_parser = coherence_scoped.parse_markdown_note

    def reject_protected_read(note_path: Path, *, content: str | None = None):
        assert "private" not in note_path.parts
        return real_parser(note_path, content=content)

    monkeypatch.setattr(coherence_scoped, "parse_markdown_note", reject_protected_read)
    server = _server(vault)
    result = server._tool_manager.get_tool("vault_note_identity").fn(
        vault_path="wiki/public.md"
    )

    assert result["stable_id"] == "shared-id"
    assert result["current_path"] == "wiki/public.md"
    assert result["relocation_safe"] is True


def test_mcp_note_identity_tool_is_read_only_and_strict(tmp_path: Path) -> None:
    server = _server(tmp_path / "vault")
    tool = server._tool_manager.get_tool("vault_note_identity")

    assert set(tool.parameters["properties"]) == {"vault_path", "allow_protected"}
    assert tool.parameters["additionalProperties"] is False
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
