from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lifeos.coherence_scoped import collect_scoped_identity_snapshot
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.retrieval import RetrievalIndex, RetrievalIndexService
from lifeos.vault import read_vault_markdown


def _note(stable_id: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: Uppercase\n---\nBody\n"


def test_uppercase_markdown_path_matches_scanner_identity_contract(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "Note.MD"
    note.parent.mkdir(parents=True)
    note.write_text(_note("uppercase-id"), encoding="utf-8")
    runtime = vault / ".lifeos"

    source = read_vault_markdown(vault, "wiki/Note.MD")
    assert source.relative_path == "wiki/Note.MD"

    snapshot = collect_scoped_identity_snapshot(
        vault,
        allow_path=lambda _path: True,
        runtime_dir=runtime,
    )
    identity = snapshot.by_path("wiki/Note.MD")
    assert identity is not None
    assert identity.stable_id == "uppercase-id"

    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    result = service.rebuild()
    assert result.status == "complete"
    with RetrievalIndex(service.active_path, create=False) as index:
        document = index.document_by_path("wiki/Note.MD")
    assert document is not None
    assert document.document_id == "id:uppercase-id"

    server = create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )
    listed = server._tool_manager.get_tool("vault_list").fn(prefix="wiki")
    assert {entry["path"] for entry in listed["entries"] if entry["kind"] == "file"} == {
        "wiki/Note.MD"
    }
    exposed = server._tool_manager.get_tool("vault_note_identity").fn(
        vault_path="wiki/Note.MD"
    )
    assert exposed["stable_id"] == "uppercase-id"
    assert exposed["current_path"] == "wiki/Note.MD"
