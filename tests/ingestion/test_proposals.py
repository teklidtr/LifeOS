import json
from pathlib import Path
from unittest import mock
from unittest.mock import patch
from lifeos.registry.file_tracking import FileTrackingError
import os
import pytest
from dataclasses import replace

from lifeos.ingestion.backend import AnalysisResult, SourceSnapshot, WikiPageDraft
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.ingestion.proposals import build_wiki_proposal, persist_wiki_proposal, ProposalPublicationError, validate_wiki_target_path, InvalidWikiTargetError, ProposalAlreadyExistsError, WikiProposalDocuments
from lifeos.markdown.parser import parse_markdown_note
from lifeos.ingestion.provenance import extract_provenance

@pytest.fixture
def sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        draft=WikiPageDraft(
            title="Test Page",
            body="This is a test body.\nIt has multiple lines."
        ),
        generator=ProvenanceGenerator(
            id="test-gen",
            version="1.0",
            prompt_schema_version="v1",
            model_id="test-model"
        )
    )

@pytest.fixture
def sample_source() -> SourceSnapshot:
    return SourceSnapshot(
        path="journal/2026-07-13.md",
        content_hash="sha256:" + "a" * 64  # valid 64 char hash
    )

def test_identical_inputs_produce_identical_bytes(sample_analysis: AnalysisResult, sample_source: SourceSnapshot) -> None:
    prop_id = "prop-20260713T123000Z-abcdef12"
    doc1 = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id=prop_id,
        created_at="2026-07-13T12:00:00Z"
    )
    doc2 = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id=prop_id,
        created_at="2026-07-13T12:00:00Z"
    )
    assert doc1.proposal_markdown == doc2.proposal_markdown
    assert doc1.patches_json == doc2.patches_json

def test_builder_performs_no_writes_and_injects_metadata(sample_analysis: AnalysisResult, sample_source: SourceSnapshot, tmp_path: Path) -> None:
    before_files = list(tmp_path.rglob("*"))
    prop_id = "prop-20260713T123000Z-abcdef12"
    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id=prop_id,
        created_at="2026-07-13T12:30:00Z"
    )
    after_files = list(tmp_path.rglob("*"))
    assert before_files == after_files

    assert doc.proposal_id == prop_id
    assert f"id: {prop_id}".encode() in doc.proposal_markdown
    assert b"created_at: \"2026-07-13T12:30:00Z\"" in doc.proposal_markdown

def test_proposal_and_provenance_use_same_timestamp(sample_analysis: AnalysisResult, sample_source: SourceSnapshot) -> None:
    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )
    assert b"created_at: \"2026-07-13T12:30:00Z\"" in doc.proposal_markdown
    patches = json.loads(doc.patches_json)["operations"]
    candidate_md = patches[0]["new_content"]
    assert "created_at: \"2026-07-13T12:30:00Z\"" in candidate_md

def test_valid_draft_loads_and_omits_review_digest(sample_analysis: AnalysisResult, sample_source: SourceSnapshot, tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir(parents=True)

    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )
    prop_dir = persist_wiki_proposal(proposals_root=proposals_root, documents=doc)

    parsed = parse_markdown_note(prop_dir / "proposal.md")
    assert parsed.frontmatter.get("status") == "draft"
    assert "review_digest" not in parsed.frontmatter

def test_v2_operation_emitted_with_absent_state(sample_analysis: AnalysisResult, sample_source: SourceSnapshot) -> None:
    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )
    patches = json.loads(doc.patches_json)["operations"]
    assert len(patches) == 1
    p = patches[0]
    assert p["op"] == "create_generated_file"
    assert p["target_path"] == "wiki/test.md"
    assert p["expected_target_state"] == "absent"
    assert p["generator_id"] == "test-gen"
    assert p["generator_version"] == "1.0"

def test_candidate_markdown_parses_and_preserves_body(sample_analysis: AnalysisResult, sample_source: SourceSnapshot, tmp_path: Path) -> None:
    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )
    patches = json.loads(doc.patches_json)["operations"]
    md_content = patches[0]["new_content"]

    md_file = tmp_path / "candidate.md"
    md_file.write_text(md_content)

    parsed = parse_markdown_note(md_file)
    assert parsed.frontmatter.get("title") == "Test Page"

    prov = extract_provenance(parsed.frontmatter)
    assert prov is not None
    assert prov.schema_version == 1
    assert len(prov.sources) == 1
    assert prov.sources[0].path == "journal/2026-07-13.md"
    assert prov.sources[0].content_hash == "sha256:" + "a" * 64
    assert prov.generator.id == "test-gen"
    assert prov.generator.version == "1.0"
    assert prov.generator.model_id == "test-model"

    assert parsed.body == "This is a test body.\nIt has multiple lines.\n"
    assert md_content.endswith("\n")

def test_model_id_omission_remains_canonical(sample_analysis: AnalysisResult, sample_source: SourceSnapshot) -> None:
    new_gen = replace(sample_analysis.generator, model_id=None)
    new_analysis = replace(sample_analysis, generator=new_gen)

    doc = build_wiki_proposal(
        analysis=new_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )
    patches = json.loads(doc.patches_json)["operations"]
    md_content = patches[0]["new_content"]
    assert "model_id" not in md_content

def test_invalid_target_path_rejected(sample_analysis: AnalysisResult, sample_source: SourceSnapshot) -> None:
    with pytest.raises(ValueError, match="Target path must be within the canonical wiki area"):
        build_wiki_proposal(
            analysis=sample_analysis,
            source=sample_source,
            target_path="journal/test.md",
            proposal_id="prop-20260713T123000Z-abcdef12",
            created_at="2026-07-13T12:30:00Z"
        )

def test_existing_proposal_id_rejected(sample_analysis: AnalysisResult, sample_source: SourceSnapshot, tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir(parents=True)

    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )

    persist_wiki_proposal(proposals_root=proposals_root, documents=doc)

    with pytest.raises(ProposalPublicationError):
        persist_wiki_proposal(proposals_root=proposals_root, documents=doc)

def test_failure_writing_cleans_up(sample_analysis: AnalysisResult, sample_source: SourceSnapshot, tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir(parents=True)

    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )

    with mock.patch("lifeos.ingestion.proposals.atomic_write_file_secure", side_effect=OSError("mock fail")):
        with pytest.raises(ProposalPublicationError):
            persist_wiki_proposal(proposals_root=proposals_root, documents=doc)

    assert not (proposals_root / "prop-20260713T123000Z-abcdef12").exists()

def test_full_lifecycle_workflow(sample_analysis: AnalysisResult, sample_source: SourceSnapshot, tmp_path: Path) -> None:
    vault_root = tmp_path
    proposals_root = vault_root / "proposals"
    proposals_root.mkdir(parents=True)

    doc = build_wiki_proposal(
        analysis=sample_analysis,
        source=sample_source,
        target_path="wiki/test.md",
        proposal_id="prop-20260713T123000Z-abcdef12",
        created_at="2026-07-13T12:30:00Z"
    )

    prop_dir = persist_wiki_proposal(proposals_root=proposals_root, documents=doc)
    assert not (vault_root / "wiki" / "test.md").exists()

    parsed = parse_markdown_note(prop_dir / "proposal.md")
    assert parsed.frontmatter.get("title") == "Create wiki/test.md: Test Page"
    assert parsed.frontmatter.get("status") == "draft"

    # Test full lifecycle
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review, approve_proposal
    from lifeos.proposals.application import apply_proposal

    res = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert res.proposal is not None
    loaded = res.proposal
    assert loaded.metadata.status.value == "draft"

    submit_proposal_for_review(
        loaded,
        proposals_root=proposals_root,
        submitted_by="test",
        submitted_at="2026-07-13T12:35:00Z"
    )
    res = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    loaded = res.proposal
    assert loaded.metadata.status.value == "pending"

    approve_proposal(
        loaded,
        proposals_root=proposals_root,
        approved_by="test",
        approved_at="2026-07-13T12:40:00Z"
    )
    res = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    loaded = res.proposal
    assert loaded.metadata.status.value == "approved"

    lifeos_dir = vault_root / "system"
    lifeos_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = lifeos_dir / "generated-ownership.json"
    manifest_file.write_text('{"schema_version": 1, "owned_files": {}}')

    (vault_root / "wiki").mkdir(parents=True, exist_ok=True)
    apply_proposal(
        loaded,
        vault_root=vault_root,
        applied_by="test",
        applied_at="2026-07-13T12:45:00Z"
    )
    assert (vault_root / "wiki" / "test.md").exists()

    # Reload after application
    res = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    loaded = res.proposal
    assert loaded.metadata.status.value == "applied"

def test_validate_wiki_target_path_accepts_canonical_target():
    assert validate_wiki_target_path("wiki/test.md") == "wiki/test.md"

def test_validate_wiki_target_path_rejects_path_outside_wiki():
    with pytest.raises(InvalidWikiTargetError):
        validate_wiki_target_path("other/test.md")

def test_validate_wiki_target_path_rejects_absolute_path():
    with pytest.raises(InvalidWikiTargetError):
        validate_wiki_target_path("/wiki/test.md")

def test_validate_wiki_target_path_rejects_parent_traversal():
    with pytest.raises(FileTrackingError):
        validate_wiki_target_path("wiki/../test.md")

def test_existing_proposal_directory_raises_proposal_already_exists(tmp_path: Path):
    proposals_root = tmp_path / "vault" / "proposals"
    proposals_root.mkdir(parents=True)
    (proposals_root / "existing-id").mkdir()
    
    docs = WikiProposalDocuments(
        proposal_id="existing-id",
        target_path="wiki/target.md",
        proposal_markdown=b"body",
        patches_json=b"{}",
    )
    
    with pytest.raises(ProposalAlreadyExistsError):
        persist_wiki_proposal(proposals_root=proposals_root, documents=docs)

def test_publication_io_failure_raises_proposal_publication_error(tmp_path: Path):
    proposals_root = tmp_path / "vault" / "proposals"
    proposals_root.mkdir(parents=True)
    
    docs = WikiProposalDocuments(
        proposal_id="new-id",
        target_path="wiki/target.md",
        proposal_markdown=b"body",
        patches_json=b"{}",
    )
    
    with patch("lifeos.ingestion.proposals.atomic_write_file_secure", side_effect=OSError("Disk full")):
        with pytest.raises(ProposalPublicationError) as exc:
            persist_wiki_proposal(proposals_root=proposals_root, documents=docs)
        assert "Disk full" in str(exc.value.__cause__)
        assert not (proposals_root / "new-id").exists() # directory should be cleaned up

def test_unexpected_write_programming_error_propagates(tmp_path: Path):
    proposals_root = tmp_path / "vault" / "proposals"
    proposals_root.mkdir(parents=True)
    
    docs = WikiProposalDocuments(
        proposal_id="new-id",
        target_path="wiki/target.md",
        proposal_markdown=b"body",
        patches_json=b"{}",
    )
    
    with patch("lifeos.ingestion.proposals.atomic_write_file_secure", side_effect=TypeError("Expected bytes")):
        with pytest.raises(TypeError, match="Expected bytes"):
            persist_wiki_proposal(proposals_root=proposals_root, documents=docs)
def test_atomic_write_failure_raises_proposal_publication_error(tmp_path: Path):
    proposals_root = tmp_path / "vault" / "proposals"
    proposals_root.mkdir(parents=True)
    
    docs = WikiProposalDocuments(
        proposal_id="new-id-2",
        target_path="wiki/target.md",
        proposal_markdown=b"body",
        patches_json=b"{}",
    )
    
    with patch("lifeos.ingestion.proposals.atomic_write_file_secure", side_effect=OSError("Cannot open")):
        with pytest.raises(ProposalPublicationError) as exc:
            persist_wiki_proposal(proposals_root=proposals_root, documents=docs)
        assert isinstance(exc.value.__cause__, OSError)
        assert not (proposals_root / "new-id-2").exists()

def test_os_open_failure_raises_proposal_publication_error(tmp_path: Path):
    proposals_root = tmp_path / "vault" / "proposals"
    proposals_root.mkdir(parents=True)
    
    docs = WikiProposalDocuments(
        proposal_id="new-id-3",
        target_path="wiki/target.md",
        proposal_markdown=b"body",
        patches_json=b"{}",
    )
    
    # We patch atomic_write to avoid actual filesystem calls during the failure test
    with patch("lifeos.ingestion.proposals.atomic_write_file_secure"):
        original_open = os.open
        def mock_open(path, flags, *args, **kwargs):
            if "new-id-3" in str(path) and getattr(mock_open, "called", False) is False:
                mock_open.called = True
                raise PermissionError("denied")
            return original_open(path, flags, *args, **kwargs)

        with patch("lifeos.ingestion.proposals.os.open", side_effect=mock_open):
            with pytest.raises(ProposalPublicationError) as exc:
                persist_wiki_proposal(proposals_root=proposals_root, documents=docs)
            assert isinstance(exc.value.__cause__, PermissionError)
            assert not (proposals_root / "new-id-3").exists()
