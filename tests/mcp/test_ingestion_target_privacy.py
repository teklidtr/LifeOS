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


@pytest.mark.parametrize(
    ("tool_name", "routing", "kwargs"),
    [
        (
            "ingestion_create_wiki_proposal",
            {"page_kind": "concept", "slug": "denied-target"},
            {"title": "Denied", "body": "Denied body"},
        ),
        (
            "ingestion_create_wiki_and_update_section_proposal",
            {"create_page_kind": "concept", "create_slug": "denied-target"},
            {
                "create_title": "Denied",
                "create_body": "Denied body",
                "update_target_path": "wiki/public.md",
                "update_heading": "Summary",
                "update_body": "Replacement",
            },
        ),
    ],
)
def test_typed_create_target_is_authorized_before_registry_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    routing: dict[str, str],
    kwargs: dict[str, str],
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    policy = vault / "system" / "retrieval-policy.yml"
    policy.parent.mkdir()
    policy.write_text(
        "schema_version: 1\nprotected_prefixes: [wiki/concepts]\nexternal_allowed_prefixes: []\n",
        encoding="utf-8",
    )
    server = mcp_server.create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=vault / ".lifeos",
    )
    refresh_calls: list[bool] = []

    def fail_refresh(*args: object, **kwargs: object) -> object:
        refresh_calls.append(True)
        pytest.fail("derived protected target reached registry refresh")

    monkeypatch.setattr(mcp_server, "refresh_registry", fail_refresh)

    with pytest.raises(ToolError, match="Invalid LifeOS tool arguments"):
        server._tool_manager.get_tool(tool_name).fn(
            source_path="raw/source.md",
            **routing,
            **kwargs,
        )

    assert refresh_calls == []
