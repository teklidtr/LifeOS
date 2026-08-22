import sys
import pytest
from pathlib import Path

from lifeos.mcp.server import LIFEOS_MCP_INSTRUCTIONS

pytestmark = pytest.mark.anyio


async def test_subprocess_stdio_protocol(tmp_path: Path) -> None:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
    except ImportError:
        pytest.skip("mcp dependency is not installed")

    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .\nfeatures:\n  graphify: true\n  exports: false\n"
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "lifeos.mcp",
            "--actor-id",
            "test-actor",
            "--config",
            str(config_file),
        ],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialization = await session.initialize()
            assert initialization.instructions == LIFEOS_MCP_INSTRUCTIONS

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}

            assert tool_names == {
                "registry_refresh",
                "vault_read_markdown",
                "ingestion_create_wiki_proposal",
                "ingestion_create_wiki_and_update_section_proposal",
                "ingestion_update_wiki_section_proposal",
                "proposal_submit",
                "proposal_approve",
                "proposal_apply",
            }

            advertised = {tool.name: tool for tool in tools.tools}
            assert all(tool.description for tool in advertised.values())
            assert advertised["registry_refresh"].annotations.readOnlyHint is False
            assert advertised["registry_refresh"].annotations.destructiveHint is False
            assert advertised["registry_refresh"].annotations.idempotentHint is True
            assert advertised["vault_read_markdown"].annotations.readOnlyHint is True
            assert advertised["ingestion_create_wiki_proposal"].annotations.destructiveHint is False
            assert (
                advertised[
                    "ingestion_create_wiki_and_update_section_proposal"
                ].annotations.destructiveHint
                is False
            )
            assert (
                advertised["ingestion_update_wiki_section_proposal"].annotations.destructiveHint
                is False
            )
            assert advertised["proposal_apply"].annotations.destructiveHint is True
