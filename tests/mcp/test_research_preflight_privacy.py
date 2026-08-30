from pathlib import Path
from unittest.mock import MagicMock, patch

from lifeos.bootstrap import initialize_vault
from lifeos.facade.registry_tools import RegistryRefreshResult
from lifeos.facade.research_tools import ResearchWikiProposalResult
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.registry import Registry


def test_research_preflight_excludes_internal_artifacts(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    initialize_vault(vault_root)
    runtime_dir = vault_root / ".lifeos"
    runtime_dir.mkdir(exist_ok=True)
    registry = Registry(runtime_dir / "registry.db")
    authorizer = MagicMock()
    authorizer.actor_id = "agent:local"
    server = create_mcp_server(
        vault_root=vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=runtime_dir,
    )

    captured_allow_path = None

    def fake_refresh_registry(*, vault_root, registry, identity_allow_path):
        nonlocal captured_allow_path
        captured_allow_path = identity_allow_path
        return RegistryRefreshResult(
            new=(
                "raw/research/source.md",
                "proposals/internal/proposal.md",
                "conversations/2026/private.md",
            ),
            modified=(),
            unchanged=(),
            deleted=(),
            proposals_indexed=0,
            renamed=(),
        )

    with (
        patch(
            "lifeos.mcp.runtime_server.refresh_registry",
            side_effect=fake_refresh_registry,
        ),
        patch("lifeos.mcp.research_tools.create_research_wiki_proposal") as create_proposal,
    ):
        create_proposal.return_value = ResearchWikiProposalResult(
            proposal_id="prop-20260830T171900Z-abcdef12",
            proposal_path="proposals/prop-20260830T171900Z-abcdef12",
            target_path="wiki/research/result.md",
            status="draft",
        )
        server._tool_manager.get_tool("research_create_wiki_proposal").fn(
            source_path="raw/research/source.md",
            acquisition_id="acq-000000000000000000000000",
            target_path="wiki/research/result.md",
            title="Research result",
            body="Durable synthesis.",
        )

    assert captured_allow_path is not None
    assert captured_allow_path("raw/research/source.md") is True
    assert captured_allow_path("proposals/internal/proposal.md") is False
    assert captured_allow_path("conversations/2026/private.md") is False

    records = server._tool_manager.get_tool("runtime_activity").fn(limit=10)["records"]
    preflight = next(record for record in records if record["tool"] == "ingestion_registry_preflight")
    assert preflight["source_paths"] == ["raw/research/source.md"]
    assert preflight["changed_paths"] == ["raw/research/source.md"]
