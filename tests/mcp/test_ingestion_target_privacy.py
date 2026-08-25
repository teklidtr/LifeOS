from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import lifeos.facade.proposal_tools as proposal_tools
import lifeos.mcp.server as mcp_server


def test_protected_update_target_is_rejected_before_registry_or_target_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    server = mcp_server.create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )

    refresh_calls: list[bool] = []
    target_reads: list[str] = []

    def fail_refresh(*args: object, **kwargs: object) -> object:
        refresh_calls.append(True)
        pytest.fail("protected target reached registry ingestion preflight")

    def fail_target_read(vault_root: Path, vault_path: str) -> object:
        del vault_root
        target_reads.append(vault_path)
        pytest.fail("protected target reached facade Markdown read")

    monkeypatch.setattr(mcp_server, "refresh_registry", fail_refresh)
    monkeypatch.setattr(proposal_tools, "read_vault_markdown", fail_target_read)

    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool("ingestion_update_wiki_section_proposal").fn(
            source_path="raw/source.md",
            target_path="private/target.md",
            heading="Summary",
            body="Replacement that must never inspect protected bytes.",
        )

    assert refresh_calls == []
    assert target_reads == []
