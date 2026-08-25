from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import lifeos.registry.coherent_tracking as coherent_tracking
from lifeos.mcp.server import create_mcp_server
from lifeos.registry import Registry, register_scan
from lifeos.scanner import scan_vault


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
    protected.write_text(_note("shared-id", "Hidden"), encoding="utf-8")

    # Seed a broader local registry observation first. The later external refresh must neither
    # open nor disclose those protected facts, but it also must not destroy local lineage that a
    # later trusted refresh may need to recognize a protected-note relocation.
    runtime = vault / ".lifeos"
    registry = Registry(runtime / "registry.db")
    registry.initialize()
    register_scan(registry, vault, scan_vault(vault))
    with registry.connect_read_only() as connection:
        seeded = connection.execute(
            "SELECT stable_id, content_hash, mtime_ns FROM files WHERE vault_path = ?",
            ("private/hidden.md",),
        ).fetchone()
    assert seeded is not None
    assert seeded["stable_id"] == "shared-id"
    assert seeded["content_hash"] is not None
    assert seeded["mtime_ns"] is not None

    public.write_text(_note("shared-id", "Public"), encoding="utf-8")
    real_parser = coherent_tracking.parse_markdown_note
    real_hash = coherent_tracking._base._hash_file
    parsed_paths: list[Path] = []
    hashed_paths: list[Path] = []

    def recording_parser(note_path: Path, *, content: str | None = None):
        parsed_paths.append(note_path)
        assert "private" not in note_path.parts
        return real_parser(note_path, content=content)

    def recording_hash(path: Path, *args, **kwargs):
        hashed_paths.append(path)
        assert "private" not in path.parts
        return real_hash(path, *args, **kwargs)

    monkeypatch.setattr(coherent_tracking, "parse_markdown_note", recording_parser)
    monkeypatch.setattr(coherent_tracking._base, "_hash_file", recording_hash)
    server = create_mcp_server(
        vault_root=vault,
        registry=registry,
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )

    payload = server._tool_manager.get_tool("registry_refresh").fn()

    assert payload["new"] == ["wiki/public.md"]
    assert "private/hidden.md" not in payload["new"]
    assert payload["proposals_indexed"] == 0
    assert parsed_paths == [public]
    assert hashed_paths == [public]
    with registry.connect_read_only() as connection:
        rows = {
            row["vault_path"]: (row["stable_id"], row["content_hash"], row["mtime_ns"])
            for row in connection.execute(
                "SELECT vault_path, stable_id, content_hash, mtime_ns "
                "FROM files WHERE is_deleted = 0 ORDER BY vault_path"
            ).fetchall()
        }
    assert rows["wiki/public.md"][0] == "shared-id"
    assert rows["wiki/public.md"][1] is not None
    assert rows["private/hidden.md"] == (
        "shared-id",
        seeded["content_hash"],
        seeded["mtime_ns"],
    )

    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)
    refresh = [record for record in activity["records"] if record["tool"] == "registry_refresh"][-1]
    assert "private/hidden.md" not in refresh["changed_paths"]
