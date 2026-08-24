from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

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


def test_mcp_note_identity_tool_is_read_only_and_strict(tmp_path: Path) -> None:
    server = _server(tmp_path / "vault")
    tool = server._tool_manager.get_tool("vault_note_identity")

    assert set(tool.parameters["properties"]) == {"vault_path", "allow_protected"}
    assert tool.parameters["additionalProperties"] is False
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
