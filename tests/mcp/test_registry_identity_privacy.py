from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import lifeos.registry.coherent_tracking as coherent_tracking
from lifeos.mcp.server import create_mcp_server
from lifeos.registry import Registry


def _note(stable_id: str, title: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\nBody\n"


def test_mcp_registry_refresh_does_not_parse_or_disclose_protected_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    public = vault / "wiki" / "public.md"
    protected = vault / "private" / "hidden.md"
    public.parent.mkdir(parents=True)
    protected.parent.mkdir(parents=True)
    (vault / "proposals").mkdir()
    public.write_text(_note("shared-id", "Public"), encoding="utf-8")
    protected.write_text(_note("shared-id", "Hidden"), encoding="utf-8")

    real_parser = coherent_tracking.parse_markdown_note
    parsed_paths: list[Path] = []

    def recording_parser(note_path: Path, *, content: str | None = None):
        parsed_paths.append(note_path)
        assert "private" not in note_path.parts
        return real_parser(note_path, content=content)

    monkeypatch.setattr(coherent_tracking, "parse_markdown_note", recording_parser)
    runtime = vault / ".lifeos"
    registry = Registry(runtime / "registry.db")
    server = create_mcp_server(
        vault_root=vault,
        registry=registry,
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )

    payload = server._tool_manager.get_tool("registry_refresh").fn()

    assert payload["new"] == ["wiki/public.md"]
    assert "private/hidden.md" not in payload["new"]
    assert parsed_paths == [public]
    with registry.connect_read_only() as connection:
        rows = {
            row["vault_path"]: row["stable_id"]
            for row in connection.execute(
                "SELECT vault_path, stable_id FROM files WHERE is_deleted = 0 ORDER BY vault_path"
            ).fetchall()
        }
    assert rows["wiki/public.md"] == "shared-id"
    assert rows["private/hidden.md"] is None

    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)
    refresh = [record for record in activity["records"] if record["tool"] == "registry_refresh"][-1]
    assert "private/hidden.md" not in refresh["changed_paths"]
