import sys
import pytest
from pathlib import Path

pytestmark = pytest.mark.anyio

async def test_subprocess_stdio_protocol(tmp_path: Path) -> None:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
    except ImportError:
        pytest.skip("mcp dependency is not installed")

    config_file = tmp_path / "lifeos.yml"
    config_file.write_text("vault_root: .\nruntime_dir: .\nfeatures:\n  graphify: true\n  exports: false\n")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m", "lifeos.mcp",
            "--actor-id", "test-actor",
            "--config", str(config_file),
        ],
        env=None
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            
            assert tool_names == {
                "vault_read_markdown",
                "ingestion_create_wiki_proposal",
                "proposal_submit",
                "proposal_approve",
                "proposal_apply",
            }
