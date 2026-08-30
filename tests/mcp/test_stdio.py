import sys
import pytest
from pathlib import Path

from lifeos.mcp.runtime_server import LIFEOS_MCP_INSTRUCTIONS

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
    (tmp_path / "wiki/right-of-way.md").write_text(
        "---\ntitle: Right of way\n---\nRight of way links to [[driving-safety]].\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki/driving-safety.md").write_text(
        "---\ntitle: Driving safety\n---\nSafety principles.\n",
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
                "vault_list",
                "vault_search",
                "vault_read_many",
                "vault_links",
                "vault_note_identity",
                "research_query_context",
                "research_capture_evidence",
                "research_create_wiki_proposal",
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
            assert advertised["vault_list"].annotations.readOnlyHint is True
            assert advertised["vault_search"].annotations.readOnlyHint is True
            assert advertised["vault_read_many"].annotations.readOnlyHint is True
            assert advertised["vault_links"].annotations.readOnlyHint is True
            assert advertised["vault_note_identity"].annotations.readOnlyHint is True
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

            listing = await session.call_tool(
                "vault_list",
                arguments={"prefix": "study", "limit": 20},
            )
            assert listing.isError is False
            assert listing.structuredContent is not None
            assert any(
                item["path"] == "study/driving-licence/intersections.md"
                for item in listing.structuredContent["entries"]
            )

            search = await session.call_tool(
                "vault_search",
                arguments={"query": "right way", "limit": 10},
            )
            assert search.isError is False
            assert search.structuredContent is not None
            search_paths = [item["path"] for item in search.structuredContent["hits"]]
            assert "study/driving-licence/intersections.md" in search_paths
            assert "wiki/right-of-way.md" in search_paths

            comparison = await session.call_tool(
                "vault_read_many",
                arguments={
                    "paths": [
                        "study/driving-licence/intersections.md",
                        "wiki/right-of-way.md",
                    ],
                    "max_characters": 10_000,
                },
            )
            assert comparison.isError is False
            assert comparison.structuredContent is not None
            assert len(comparison.structuredContent["items"]) == 2

            links = await session.call_tool(
                "vault_links",
                arguments={"path": "wiki/right-of-way.md", "direction": "outgoing"},
            )
            assert links.isError is False
            assert links.structuredContent is not None
            assert links.structuredContent["links"][0]["target_path"] == (
                "wiki/driving-safety.md"
            )

            context_result = await session.call_tool(
                "vault_context",
                arguments={
                    "question": "What matters for this exam?",
                    "focus_paths": ["study/driving-licence/intersections.md"],
                    "limit": 6,
                },
            )
            assert context_result.isError is False
            assert context_result.structuredContent is not None
            assert context_result.structuredContent["sources"][0]["path"] == (
                "study/driving-licence/intersections.md"
            )
            assert [
                item["id"] for item in context_result.structuredContent["instructions"]
            ] == ["driving-exam"]

            activity_result = await session.call_tool(
                "runtime_activity", arguments={"limit": 10}
            )
            assert activity_result.isError is False
            assert activity_result.structuredContent is not None
            records = activity_result.structuredContent["records"]
            assert records[-1]["tool"] == "vault_context"
            assert records[-1]["focus_paths"] == [
                "study/driving-licence/intersections.md"
            ]
