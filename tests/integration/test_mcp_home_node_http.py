import json
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from lifeos.bootstrap import initialize_vault
from lifeos.config import load_config
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.mcp.service import (
    AuthenticatedServiceApp,
    AuthenticatedSubmitAuthorizer,
    ServiceReadiness,
)
from lifeos.proposals.loader import load_proposal_directory
from lifeos.registry import Registry
from lifeos.status import ProposalStatus


@pytest.mark.anyio
async def test_remote_http_client_explores_and_submits_without_local_vault(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    initialize_vault(vault_root)
    source = vault_root / "raw" / "remote-note.md"
    source.write_text("Remote client source material.\n", encoding="utf-8")

    config_path = vault_root / "lifeos.yml"
    config = load_config(config_path)
    registry = Registry(config.runtime_dir / "registry.db")
    registry.initialize()
    readiness = ServiceReadiness(config, config_path)
    authorizer = AuthenticatedSubmitAuthorizer(
        actor_id="remote-integration",
        readiness=readiness,
    )
    mcp = create_mcp_server(
        vault_root=config.vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=config.runtime_dir,
        host="127.0.0.1",
        stateless_http=True,
        json_response=True,
        excluded_core_tools=frozenset({"proposal_approve", "proposal_apply"}),
    )
    mcp_app = mcp.streamable_http_app()
    token = "integration-token-" + "x" * 32
    service_app = AuthenticatedServiceApp(
        mcp_app,
        token=token,
        actor_id="remote-integration",
        readiness=readiness,
    )
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service_app),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    )

    async with mcp.session_manager.run(), http_client:
        async with streamable_http_client(
            "http://127.0.0.1/mcp",
            http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "proposal_submit" in tool_names
                assert "proposal_approve" not in tool_names
                assert "proposal_apply" not in tool_names

                listing = await session.call_tool("vault_list", arguments={"prefix": "raw"})
                assert not listing.isError
                listing_data = json.loads(listing.content[0].text)
                assert any(
                    entry["path"] == "raw/remote-note.md"
                    for entry in listing_data["entries"]
                )

                created = await session.call_tool(
                    "ingestion_create_wiki_proposal",
                    arguments={
                        "source_path": "raw/remote-note.md",
                        "target_path": "wiki/remote-note.md",
                        "title": "Remote Note",
                        "body": "Remote client source material.\n",
                    },
                )
                assert not created.isError
                proposal_id = json.loads(created.content[0].text)["proposal_id"]

                submitted = await session.call_tool(
                    "proposal_submit",
                    arguments={"proposal_id": proposal_id},
                )
                assert not submitted.isError
                assert json.loads(submitted.content[0].text)["status"] == "pending"

                activity = await session.call_tool(
                    "runtime_activity",
                    arguments={"limit": 20},
                )
                assert not activity.isError
                activity_data = json.loads(activity.content[0].text)
                assert any(
                    record["tool"] == "proposal_submit"
                    and record["actor_id"] == "remote-integration"
                    for record in activity_data["records"]
                )

    loaded = load_proposal_directory(
        vault_root / "proposals" / proposal_id,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    assert loaded.metadata.status == ProposalStatus.PENDING
    assert loaded.metadata.submitted_by == "remote-integration"
    assert not (vault_root / "wiki" / "remote-note.md").exists()
