from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.retrieval import RetrievalIndexService


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_vault_context_uses_configured_runtime_and_exposes_additive_provenance(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    _write(
        vault,
        "wiki/energy.md",
        "---\nid: energy\ntitle: Energy\ndescription: Cellular energy evidence.\n---\n"
        "ATP production depends on cellular energy pathways.",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    server = create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=runtime,
    )
    tool = server._tool_manager.get_tool("vault_context")

    result = tool.fn(question="ATP production", limit=3)

    assert set(tool.parameters["properties"]) == {
        "question",
        "focus_paths",
        "limit",
        "allow_protected",
    }
    assert "hybrid retrieval" in tool.description
    assert "initial map" in tool.description
    assert result["sources"]
    source = result["sources"][0]
    assert source["path"] == "wiki/energy.md"
    assert source["retrieval_mode"] == "hybrid"
    assert "lexical" in source["retrieval_reasons"] or "exact" in source["retrieval_reasons"]
    assert source["ranking"]
    assert source["duplicate_paths"] == []
    assert any("Semantic retrieval was not configured" in item for item in result["omissions"])
