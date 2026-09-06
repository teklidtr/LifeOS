import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from lifeos.facade.consequential_tools import ApplyProposalResult
from lifeos.facade.exploration import (
    VaultListResult,
    VaultPathEntry,
    VaultReadManyResult,
)
from lifeos.facade.proposal_tools import CreateWikiProposalResult, EvolveWikiProposalResult
from lifeos.facade.research_tools import ResearchEvidenceCaptureResult
from lifeos.mcp.runtime_server import create_mcp_server
from lifeos.mcp.tool_contracts import build_mcp_tool, serialize_authoritative_output


def test_shared_input_builder_preserves_strictness_aliases_defaults_and_annotations() -> None:
    def coercive_tool(model_dump: str = "kept", limit: int = 8) -> str:
        return f"{model_dump}:{limit}"

    annotations = ToolAnnotations(
        title="Contract probe",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    coercive = build_mcp_tool(
        coercive_tool,
        name="contract_probe",
        description="Probe the shared input contract builder.",
        annotations=annotations,
        strict_inputs=False,
    )

    assert coercive.annotations == annotations
    assert coercive.parameters["additionalProperties"] is False
    assert "model_dump" in coercive.parameters["properties"]
    assert "field_model_dump" not in coercive.parameters["properties"]
    assert coercive.parameters["properties"]["model_dump"]["default"] == "kept"
    assert coercive.parameters["properties"]["limit"]["default"] == 8
    parsed = coercive.fn_metadata.arg_model.model_validate({"model_dump": "changed", "limit": "9"})
    assert parsed.model_dump_one_level() == {"model_dump": "changed", "limit": 9}
    with pytest.raises(ValidationError):
        coercive.fn_metadata.arg_model.model_validate({"unexpected": "field"})

    def strict_tool(allow_protected: bool = False, limit: int = 8) -> str:
        return f"{allow_protected}:{limit}"

    strict = build_mcp_tool(
        strict_tool,
        name="strict_contract_probe",
        description="Probe strict input behavior.",
        annotations=annotations,
        strict_inputs=True,
    )
    assert strict.parameters["additionalProperties"] is False
    with pytest.raises(ValidationError):
        strict.fn_metadata.arg_model.model_validate({"allow_protected": "yes"})
    with pytest.raises(ValidationError):
        strict.fn_metadata.arg_model.model_validate({"limit": "8"})
    with pytest.raises(ValidationError):
        strict.fn_metadata.arg_model.model_validate({"limit": True})

    with pytest.raises(ValueError, match="output_model_name requires output_type"):
        build_mcp_tool(
            strict_tool,
            name="invalid_output_name_probe",
            description="Reject a legacy output name without an authoritative type.",
            annotations=annotations,
            strict_inputs=True,
            output_model_name="LegacyMCPResult",
        )


def test_named_read_output_schemas_preserve_legacy_names_and_nested_refs(tmp_path: Path) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    list_schema = tools["vault_list"].output_schema
    assert list_schema is not None
    assert list_schema["title"] == "VaultListMCPResult"
    assert list_schema["required"] == ["prefix", "entries", "truncated", "next_after"]
    assert list_schema["properties"]["entries"]["items"] == {
        "$ref": "#/$defs/VaultPathEntryMCPResult"
    }
    assert list_schema["$defs"]["VaultPathEntryMCPResult"]["required"] == ["path", "kind"]
    assert list_schema["$defs"]["VaultPathEntryMCPResult"]["properties"]["kind"]["enum"] == [
        "file",
        "folder",
    ]

    read_many_schema = tools["vault_read_many"].output_schema
    assert read_many_schema is not None
    assert read_many_schema["title"] == "VaultReadManyMCPResult"
    assert read_many_schema["required"] == ["items", "total_characters", "truncated"]
    assert read_many_schema["properties"]["items"]["items"] == {
        "$ref": "#/$defs/VaultReadItemMCPResult"
    }
    assert read_many_schema["$defs"]["VaultReadItemMCPResult"]["required"] == [
        "path",
        "markdown_body",
        "title",
        "content_hash",
        "truncated",
    ]

    wiki_schema = tools["wiki_search"].output_schema
    assert wiki_schema is not None
    assert wiki_schema["title"] == "WikiSearchMCPResult"
    assert wiki_schema["required"] == ["query", "hits"]
    assert wiki_schema["properties"]["hits"]["items"] == {"$ref": "#/$defs/WikiSearchHitMCPResult"}
    assert wiki_schema["$defs"]["WikiSearchHitMCPResult"]["required"] == [
        "path",
        "title",
        "description",
        "excerpt",
        "score",
    ]


def test_named_proposal_output_schemas_preserve_legacy_names_and_status_literals(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    expected = {
        "ingestion_create_wiki_proposal": ("CreateWikiProposalMCPResult", "draft"),
        "ingestion_update_wiki_section_proposal": (
            "UpdateWikiSectionProposalMCPResult",
            "draft",
        ),
        "ingestion_create_wiki_and_update_section_proposal": (
            "CompoundWikiProposalMCPResult",
            "draft",
        ),
        "ingestion_evolve_wiki_proposal": ("EvolveWikiProposalMCPResult", "draft"),
        "ingestion_evolve_wiki_batch_proposal": ("EvolveWikiProposalMCPResult", "draft"),
        "study_evolve_learning_proposal": ("StudyLearningProposalMCPResult", "draft"),
        "proposal_submit": ("SubmitProposalMCPResult", "pending"),
        "proposal_approve": ("ApproveProposalMCPResult", "approved"),
        "proposal_apply": ("ApplyProposalMCPResult", "applied"),
        "research_capture_evidence": ("ResearchCaptureMCPResult", None),
        "research_create_wiki_proposal": ("CreateWikiProposalMCPResult", "draft"),
    }

    for tool_name, (schema_title, status_literal) in expected.items():
        schema = tools[tool_name].output_schema
        assert schema is not None
        assert schema["title"] == schema_title
        if status_literal is not None:
            assert schema["properties"]["status"]["const"] == status_literal

    assert (
        tools["ingestion_evolve_wiki_batch_proposal"].output_schema
        == tools["ingestion_evolve_wiki_proposal"].output_schema
    )
    capture_schema = tools["research_capture_evidence"].output_schema
    assert capture_schema is not None
    assert capture_schema["required"] == [
        "artifact_id",
        "source_path",
        "snapshot_hash",
        "acquisition_id",
        "created",
        "acquisition_added",
    ]


def test_named_read_outputs_preserve_direct_dicts_and_structured_wire_content(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "topic.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntitle: Topic\ndescription: Durable topic\n---\nretrieval practice\n",
        encoding="utf-8",
    )
    server = create_mcp_server(
        vault_root=vault,
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    cases = (
        ("vault_list", {"prefix": "wiki"}, "entries"),
        ("vault_read_many", {"paths": ["wiki/topic.md"]}, "items"),
        ("wiki_search", {"query": "retrieval"}, "hits"),
    )
    for name, arguments, collection_key in cases:
        direct = tools[name].fn(**arguments)
        assert isinstance(direct, dict)
        assert direct[collection_key]

        converted = tools[name].fn_metadata.convert_result(direct)
        assert isinstance(converted, tuple)
        text_content, structured = converted
        assert structured == direct
        assert len(text_content) == 1
        assert json.loads(text_content[0].text) == direct


def test_authoritative_output_name_override_preserves_direct_and_wire_shape() -> None:
    result = EvolveWikiProposalResult(
        proposal_id="prop-1",
        proposal_path="proposals/prop-1",
        target_paths=("wiki/a.md", "wiki/b.md"),
        operation_count=2,
        status="draft",
    )

    def proposal_probe() -> dict[str, object]:
        return serialize_authoritative_output(
            result,
            output_type=EvolveWikiProposalResult,
            output_model_name="LegacyProposalMCPResult",
        )

    tool = build_mcp_tool(
        proposal_probe,
        name="proposal_probe",
        description="Probe authoritative proposal output serialization.",
        annotations=ToolAnnotations(
            title="Proposal probe",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        strict_inputs=False,
        output_type=EvolveWikiProposalResult,
        output_model_name="LegacyProposalMCPResult",
    )

    direct = tool.fn()
    assert direct == {
        "proposal_id": "prop-1",
        "proposal_path": "proposals/prop-1",
        "target_paths": ["wiki/a.md", "wiki/b.md"],
        "operation_count": 2,
        "status": "draft",
    }
    assert tool.output_schema is not None
    assert tool.output_schema["title"] == "LegacyProposalMCPResult"

    converted = tool.fn_metadata.convert_result(direct)
    assert isinstance(converted, tuple)
    text_content, structured = converted
    assert structured == direct
    assert len(text_content) == 1
    assert json.loads(text_content[0].text) == direct


def test_authoritative_output_revalidates_invalid_nested_literals() -> None:
    malformed = VaultListResult(
        prefix=None,
        entries=(
            VaultPathEntry(
                path="wiki/topic.md",
                kind="not-a-kind",  # type: ignore[arg-type]
            ),
        ),
        truncated=False,
        next_after=None,
    )

    with pytest.raises(ValidationError):
        serialize_authoritative_output(malformed, output_type=VaultListResult)


def test_authoritative_output_rejects_coercible_scalar_values() -> None:
    malformed_bool = VaultListResult(
        prefix=None,
        entries=(),
        truncated="false",  # type: ignore[arg-type]
        next_after=None,
    )
    malformed_int = VaultReadManyResult(
        items=(),
        total_characters=True,
        truncated=False,
    )
    malformed_proposal = EvolveWikiProposalResult(
        proposal_id="prop-1",
        proposal_path="proposals/prop-1",
        target_paths=("wiki/a.md",),
        operation_count=True,
        status="draft",
    )
    malformed_capture = ResearchEvidenceCaptureResult(
        artifact_id="research-1",
        source_path="raw/research/source.md",
        snapshot_hash="sha256:" + "1" * 64,
        acquisition_id="acq-1",
        created="false",  # type: ignore[arg-type]
        acquisition_added=False,
    )

    with pytest.raises(ValidationError):
        serialize_authoritative_output(malformed_bool, output_type=VaultListResult)
    with pytest.raises(ValidationError):
        serialize_authoritative_output(malformed_int, output_type=VaultReadManyResult)
    with pytest.raises(ValidationError):
        serialize_authoritative_output(malformed_proposal, output_type=EvolveWikiProposalResult)
    with pytest.raises(ValidationError):
        serialize_authoritative_output(
            malformed_capture,
            output_type=ResearchEvidenceCaptureResult,
            output_model_name="ResearchCaptureMCPResult",
        )


def test_authoritative_proposal_output_rejects_invalid_status_and_sequence_shape() -> None:
    malformed_status = CreateWikiProposalResult(
        proposal_id="prop-1",
        proposal_path="proposals/prop-1",
        target_path="wiki/topic.md",
        status="pending",  # type: ignore[arg-type]
    )
    malformed_paths = ApplyProposalResult(
        proposal_id="prop-1",
        status="applied",
        changed_paths=["wiki/topic.md"],  # type: ignore[arg-type]
    )

    with pytest.raises(ValidationError):
        serialize_authoritative_output(malformed_status, output_type=CreateWikiProposalResult)
    with pytest.raises(ValidationError):
        serialize_authoritative_output(malformed_paths, output_type=ApplyProposalResult)


def test_runtime_sanitizes_invalid_authoritative_output(tmp_path: Path) -> None:
    malformed = VaultListResult(
        prefix=None,
        entries=(
            VaultPathEntry(
                path="wiki/private-detail.md",
                kind="not-a-kind",  # type: ignore[arg-type]
            ),
        ),
        truncated=False,
        next_after=None,
    )
    server = create_mcp_server(
        vault_root=tmp_path / "vault",
        registry=MagicMock(),
        authorizer=MagicMock(),
        runtime_dir=tmp_path / ".lifeos",
    )

    with patch("lifeos.mcp.exploration_tools.list_vault_paths", return_value=malformed):
        with pytest.raises(ToolError, match="Internal LifeOS error") as exc_info:
            server._tool_manager.get_tool("vault_list").fn()

    assert "private-detail" not in str(exc_info.value)
    assert "not-a-kind" not in str(exc_info.value)
