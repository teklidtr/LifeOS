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

    (tmp_path / "system").mkdir()
    (tmp_path / "study/driving-licence").mkdir(parents=True)
    (tmp_path / "goals").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "flashcards").mkdir()
    (tmp_path / "proposals").mkdir()
    (tmp_path / "system/instructions.yml").write_text(
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: driving-exam\n"
        "    authority: system\n"
        "    scope: path\n"
        "    priority: 100\n"
        "    text: Prioritize exam-relevant distinctions.\n"
        "    paths: [study/driving-licence/**]\n",
        encoding="utf-8",
    )
    (tmp_path / "study/driving-licence/intersections.md").write_text(
        "---\ntitle: Intersections\ndescription: Driving exam rules\n---\nRight of way.\n",
        encoding="utf-8",
    )
    (tmp_path / "goals/pass-driving-licence.md").write_text(
        "---\n"
        "title: Pass driving licence\n"
        "description: Pass the driving licence exam\n"
        "---\n"
        "Prepare.\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .lifeos\nfeatures:\n  graphify: true\n  exports: false\n"
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
                "vault_context",
                "wiki_search",
                "ingestion_evolve_wiki_proposal",
                "study_evolve_learning_proposal",
                "ingestion_create_wiki_proposal",
                "ingestion_create_wiki_and_update_section_proposal",
                "ingestion_update_wiki_section_proposal",
                "proposal_submit",
                "proposal_approve",
                "proposal_apply",
                "runtime_activity",
            }

            advertised = {tool.name: tool for tool in tools.tools}
            assert all(tool.description for tool in advertised.values())
            assert advertised["registry_refresh"].annotations.readOnlyHint is False
            assert advertised["registry_refresh"].annotations.destructiveHint is False
            assert advertised["registry_refresh"].annotations.idempotentHint is True
            assert advertised["vault_read_markdown"].annotations.readOnlyHint is True
            assert advertised["wiki_search"].annotations.readOnlyHint is True
            assert advertised["vault_context"].annotations.readOnlyHint is True
            assert advertised["study_evolve_learning_proposal"].annotations.destructiveHint is False
            assert advertised["runtime_activity"].annotations.readOnlyHint is True
            assert advertised["ingestion_evolve_wiki_proposal"].annotations.destructiveHint is False
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

            context_result = await session.call_tool(
                "vault_context",
                arguments={
                    "question": "What matters for this exam?",
                    "focus_paths": ["study/driving-licence/intersections.md"],
                    "limit": 6,
                },
            )
            assert context_result.is_error is False
            assert context_result.structured_content is not None
            assert context_result.structured_content["sources"][0]["path"] == (
                "study/driving-licence/intersections.md"
            )
            assert [
                item["id"] for item in context_result.structured_content["instructions"]
            ] == ["driving-exam"]

            activity_result = await session.call_tool(
                "runtime_activity", arguments={"limit": 5}
            )
            assert activity_result.is_error is False
            assert activity_result.structured_content is not None
            records = activity_result.structured_content["records"]
            assert records[-1]["tool"] == "vault_context"
            assert records[-1]["focus_paths"] == [
                "study/driving-licence/intersections.md"
            ]
