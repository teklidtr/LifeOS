from pathlib import Path
from unittest.mock import MagicMock

from lifeos.bootstrap import initialize_vault
from lifeos.markdown.parser import parse_markdown_note
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.proposals.loader import load_proposal_directory
from lifeos.registry import Registry
from lifeos.registry.file_tracking import hash_file_content
from lifeos.research import ResearchEvidenceService
from lifeos.runtime.activity import push_activity_actor, reset_activity_actor


def _server(tmp_path: Path):
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
    return vault_root, registry, server


def _vault_files(vault_root: Path, prefix: str) -> set[str]:
    root = vault_root / prefix
    if not root.exists():
        return set()
    return {
        path.relative_to(vault_root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_research_tool_schemas_preserve_read_write_and_actor_boundaries(tmp_path: Path) -> None:
    _vault_root, _registry, server = _server(tmp_path)
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    query = tools["research_query_context"]
    capture = tools["research_capture_evidence"]

    assert query.annotations.readOnlyHint is True
    assert query.annotations.destructiveHint is False
    assert query.annotations.idempotentHint is True
    assert set(query.parameters["properties"]) == {"query", "focus_paths", "limit"}
    assert query.parameters["additionalProperties"] is False

    assert capture.annotations.readOnlyHint is False
    assert capture.annotations.destructiveHint is False
    assert capture.annotations.idempotentHint is True
    assert set(capture.parameters["properties"]) == {
        "evidence_text",
        "source_title",
        "research_reason",
        "source_locator",
        "source_author",
        "source_publisher",
        "origin_kind",
        "origin_ref",
        "research_context",
    }
    assert "captured_by" not in capture.parameters["properties"]
    assert capture.parameters["additionalProperties"] is False


def test_research_query_context_is_zero_write_by_default(tmp_path: Path) -> None:
    vault_root, _registry, server = _server(tmp_path)
    existing = vault_root / "wiki" / "existing.md"
    existing.write_text(
        "---\ntitle: Existing evidence\ndescription: Durable answer already represented.\n---\n\n"
        "Insulin sensitivity changes glucose handling.\n",
        encoding="utf-8",
    )
    raw_before = _vault_files(vault_root, "raw")
    proposals_before = _vault_files(vault_root, "proposals")

    result = server._tool_manager.get_tool("research_query_context").fn(
        query="insulin sensitivity glucose",
        focus_paths=["wiki/existing.md"],
        limit=8,
    )

    assert result["persistence"] == "none"
    assert result["decision_authority"] == "external-agent"
    assert any(item["path"] == "wiki/existing.md" for item in result["context_sources"])
    assert _vault_files(vault_root, "raw") == raw_before
    assert _vault_files(vault_root, "proposals") == proposals_before


def test_research_capture_uses_trusted_local_actor_and_dedupes(tmp_path: Path) -> None:
    vault_root, _registry, server = _server(tmp_path)
    tool = server._tool_manager.get_tool("research_capture_evidence")
    arguments = {
        "evidence_text": "Selected external evidence.",
        "source_title": "External source",
        "source_locator": "https://example.test/source",
        "source_author": "Source Author",
        "research_reason": "The existing vault lacks direct evidence for this claim.",
        "origin_kind": "query",
        "origin_ref": "query:insulin-1",
        "research_context": "Chosen to close the material evidence gap.",
    }

    first = tool.fn(**arguments)
    second = tool.fn(**arguments)
    artifact = ResearchEvidenceService(vault_root=vault_root).load(first["source_path"])

    assert first["created"] is True
    assert first["acquisition_added"] is True
    assert second["created"] is False
    assert second["acquisition_added"] is False
    assert second["source_path"] == first["source_path"]
    assert artifact.metadata.first_captured_by == "agent:local"
    assert artifact.metadata.source_author == "Source Author"
    assert len(artifact.metadata.acquisitions) == 1


def test_authenticated_request_actor_overrides_local_fallback(tmp_path: Path) -> None:
    vault_root, _registry, server = _server(tmp_path)
    token = push_activity_actor("agent:remote")
    try:
        result = server._tool_manager.get_tool("research_capture_evidence").fn(
            evidence_text="Remote selected evidence.",
            source_title="Remote source",
            source_locator="https://example.test/remote",
            research_reason="Remote query exposed a material evidence gap.",
        )
    finally:
        reset_activity_actor(token)

    artifact = ResearchEvidenceService(vault_root=vault_root).load(result["source_path"])
    assert artifact.metadata.first_captured_by == "agent:remote"


def test_no_durable_novelty_can_finish_after_capture_without_proposal(tmp_path: Path) -> None:
    vault_root, _registry, server = _server(tmp_path)
    proposals_before = _vault_files(vault_root, "proposals")

    server._tool_manager.get_tool("research_capture_evidence").fn(
        evidence_text="Evidence confirms what the durable wiki already says.",
        source_title="Confirmatory source",
        source_locator="doi:10.0000/confirmatory",
        research_reason="Check whether the existing durable statement still has external support.",
    )

    assert _vault_files(vault_root, "proposals") == proposals_before


def test_captured_research_source_enters_normal_ingestion_provenance(tmp_path: Path) -> None:
    vault_root, _registry, server = _server(tmp_path)
    capture = server._tool_manager.get_tool("research_capture_evidence").fn(
        evidence_text="A reusable external comparison that is not yet represented.",
        source_title="Comparison source",
        source_locator="https://example.test/comparison",
        source_author="External Researcher",
        research_reason="The query needs a reusable comparison absent from the vault.",
        origin_kind="conversation",
        origin_ref="conv-20260830T154000Z-abcd1234#turn-003",
        research_context="Agent judged the comparison durable after checking existing wiki knowledge.",
    )

    proposal = server._tool_manager.get_tool("ingestion_create_wiki_proposal").fn(
        source_path=capture["source_path"],
        target_path="wiki/research/comparison.md",
        title="Research comparison",
        body="A reusable comparison grounded in the captured external evidence.",
    )

    loaded = load_proposal_directory(
        vault_root / proposal["proposal_path"],
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    operation = loaded.patch_document.operations[0]
    assert operation.op == "create_generated_file"
    parsed = parse_markdown_note(Path(operation.target_path), content=operation.new_content)
    provenance = parsed.frontmatter["lifeos_provenance"]["sources"][0]
    source_bytes = (vault_root / capture["source_path"]).read_bytes()
    raw_artifact = ResearchEvidenceService(vault_root=vault_root).load(capture["source_path"])

    assert provenance["path"] == capture["source_path"]
    assert provenance["content_hash"] == f"sha256:{hash_file_content(source_bytes)}"
    assert raw_artifact.metadata.snapshot_hash == capture["snapshot_hash"]
    assert raw_artifact.metadata.acquisitions[0].origin_ref == (
        "conv-20260830T154000Z-abcd1234#turn-003"
    )
    assert not (vault_root / "wiki" / "research" / "comparison.md").exists()

    activity = server._tool_manager.get_tool("runtime_activity").fn(limit=10)["records"]
    ingestion_index = next(
        index
        for index, record in enumerate(activity)
        if record["tool"] == "ingestion_create_wiki_proposal"
    )
    preflight = activity[ingestion_index - 1]
    assert preflight["tool"] == "ingestion_registry_preflight"
    assert preflight["source_paths"] == [capture["source_path"]]
