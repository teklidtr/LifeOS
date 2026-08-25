from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import lifeos.facade.proposal_tools as proposal_tools
from lifeos.mcp.server import create_mcp_server
from lifeos.registry import Registry, register_scan
from lifeos.scanner import scan_vault


def _server(vault: Path, runtime: Path) -> object:
    registry = Registry(runtime / "registry.db")
    registry.initialize()
    register_scan(registry, vault, scan_vault(vault))
    return create_mcp_server(
        vault_root=vault,
        registry=registry,
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )


def test_mcp_ingestion_rejects_custom_runtime_source_before_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / "raw" / "runtime-node"
    source = runtime / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Runtime source\n\nDisposable bytes.\n", encoding="utf-8")
    (vault / "proposals").mkdir()
    server = _server(vault, runtime)

    source_loads: list[str] = []

    def reject_source_load(*, registry: Registry, vault_root: Path, source_path: str):
        source_loads.append(source_path)
        pytest.fail("runtime source reached byte-loading verification")

    monkeypatch.setattr(proposal_tools, "load_registered_source", reject_source_load)

    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool("ingestion_create_wiki_proposal").fn(
            source_path="raw/runtime-node/source.md",
            title="Should not publish",
            body="Runtime state must not ground canonical knowledge.",
            target_path="wiki/denied-runtime-source.md",
        )

    assert source_loads == []


def test_mcp_ingestion_rejects_protected_update_target_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    source = vault / "raw" / "source.md"
    target = vault / "wiki" / "protected" / "secret.md"
    policy = vault / "system" / "retrieval-policy.yml"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)
    (vault / "proposals").mkdir()
    source.write_text("# Public source\n\nAllowed evidence.\n", encoding="utf-8")
    target.write_text("# Secret\n\n## Facts\nHidden target body.\n", encoding="utf-8")
    policy.write_text(
        "schema_version: 1\nprotected_prefixes:\n  - wiki/protected\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    server = _server(vault, runtime)

    target_reads: list[str] = []
    real_read = proposal_tools.read_vault_markdown

    def reject_protected_read(root: Path, relative_path: str):
        target_reads.append(relative_path)
        if relative_path == "wiki/protected/secret.md":
            pytest.fail("protected update target reached Markdown byte read")
        return real_read(root, relative_path)

    monkeypatch.setattr(proposal_tools, "read_vault_markdown", reject_protected_read)

    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool("ingestion_update_wiki_section_proposal").fn(
            source_path="raw/source.md",
            target_path="wiki/protected/secret.md",
            heading="Facts",
            body="Replacement must not be built from hidden target bytes.",
        )

    assert "wiki/protected/secret.md" not in target_reads
