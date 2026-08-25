from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import lifeos.facade.proposal_tools as proposal_tools
from lifeos.mcp.server import create_mcp_server
from lifeos.registry import Registry, register_scan
from lifeos.scanner import scan_vault


def test_mcp_ingestion_rejects_protected_source_before_source_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    protected = vault / "private" / "source.md"
    protected.parent.mkdir(parents=True)
    protected.write_text("# Hidden\n\nProtected source body.\n", encoding="utf-8")
    (vault / "proposals").mkdir()

    runtime = vault / ".lifeos"
    registry = Registry(runtime / "registry.db")
    registry.initialize()
    register_scan(registry, vault, scan_vault(vault))
    server = create_mcp_server(
        vault_root=vault,
        registry=registry,
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )

    source_loads: list[str] = []

    def reject_source_load(*, registry: Registry, vault_root: Path, source_path: str):
        source_loads.append(source_path)
        pytest.fail("protected source reached byte-loading verification")

    monkeypatch.setattr(proposal_tools, "load_registered_source", reject_source_load)

    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool("ingestion_create_wiki_proposal").fn(
            source_path="private/source.md",
            title="Should not publish",
            body="Denied source must not ground a proposal.",
            target_path="wiki/denied.md",
        )

    assert source_loads == []
    assert list((vault / "proposals").iterdir()) == []
