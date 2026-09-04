from pathlib import Path
from unittest.mock import MagicMock

from lifeos.mcp.runtime_server import LIFEOS_MCP_INSTRUCTIONS, create_mcp_server


def _tools(tmp_path: Path, *, remote: bool = False):
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
        excluded_core_tools=(
            frozenset({"proposal_approve", "proposal_apply"}) if remote else frozenset()
        ),
    )
    return server, {tool.name: tool for tool in server._tool_manager.list_tools()}


def test_personal_pattern_tools_are_draft_only_and_strict(tmp_path: Path) -> None:
    server, tools = _tools(tmp_path)

    assert "personal_pattern_propose" in tools
    assert "personal_pattern_review_proposal" in tools
    for name in ("personal_pattern_propose", "personal_pattern_review_proposal"):
        annotations = tools[name].annotations
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is False
        assert annotations.openWorldHint is False
        assert tools[name].parameters["additionalProperties"] is False

    assert set(tools["personal_pattern_propose"].parameters["properties"]) == {
        "target_path",
        "pattern_id",
        "title",
        "description",
        "semantic",
        "evidence",
        "allow_protected",
    }
    assert set(tools["personal_pattern_review_proposal"].parameters["properties"]) == {
        "target_path",
        "observed_pattern_hash",
        "semantic",
        "evidence",
        "allow_protected",
    }
    assert server.instructions == LIFEOS_MCP_INSTRUCTIONS
    assert "personal_pattern_propose" in server.instructions
    assert "never establish a user trait" in server.instructions


def test_home_node_keeps_draft_tools_but_removes_approval_and_apply(tmp_path: Path) -> None:
    _, tools = _tools(tmp_path, remote=True)

    assert "personal_pattern_propose" in tools
    assert "personal_pattern_review_proposal" in tools
    assert "proposal_submit" in tools
    assert "proposal_approve" not in tools
    assert "proposal_apply" not in tools
    assert "write_file" not in tools
