import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest

from lifeos.facade.models import (
    ToolEffect,
)
from lifeos.facade.errors import (
    ToolValidationError,
    ToolConflictError,
    ToolOwnershipConflictError,
    ToolNotFoundError,
    ToolExecutionError,
)
from lifeos.facade.proposal_tools import (
    COMPOUND_WIKI_PROPOSAL_DESCRIPTOR,
    CREATE_WIKI_PROPOSAL_DESCRIPTOR,
    UPDATE_WIKI_SECTION_PROPOSAL_DESCRIPTOR,
    CompoundWikiProposalRequest,
    CreateWikiProposalRequest,
    CreateWikiProposalResult,
    UpdateWikiSectionProposalRequest,
    create_wiki_and_update_section_proposal,
    create_wiki_proposal,
    update_wiki_section_proposal,
)
from lifeos.ingestion.orchestration import (
    MissingSourceError,
    ModifiedSourceError,
    SourceReadError,
    UnregisteredSourceError,
    VerifiedRegisteredSource,
)
from lifeos.ingestion.drafts import SourceSnapshot
from lifeos.ingestion.proposals import (
    InvalidWikiTargetError,
    ProposalAlreadyExistsError,
    ProposalPublicationError,
    WikiProposalDocuments,
    WikiTargetExistsError,
)
from lifeos.registry.file_tracking import FileTrackingError
from lifeos.registry import Registry


def _write_ownership(
    vault_root: Path, owned_files: dict[str, dict[str, str]] | None = None
) -> None:
    system = vault_root / "system"
    system.mkdir(parents=True, exist_ok=True)
    (system / "generated-ownership.json").write_text(
        json.dumps(
            {"schema_version": 1, "owned_files": owned_files or {}},
            sort_keys=True,
        )
    )


def _ownership_entry(
    content: bytes, *, generator_id: str = "lifeos.facade.external_agent"
) -> dict[str, str]:
    return {
        "generator_id": generator_id,
        "generator_version": "1",
        "content_hash": hashlib.sha256(content).hexdigest(),
        "created_at": "2026-08-22T10:00:00Z",
        "updated_at": "2026-08-22T10:00:00Z",
    }


def _registered_source(vault_root: Path, tmp_path: Path) -> Registry:
    source = vault_root / "study" / "source.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"Verified source.\n")
    registry = Registry(tmp_path / "ownership-aware-registry.db")
    registry.initialize()
    from lifeos.registry.file_tracking import register_scan
    from lifeos.scanner import VaultFile

    register_scan(
        registry,
        vault_root,
        [VaultFile(Path("study/source.md"), ".md", source.stat().st_size)],
    )
    return registry

def test_create_wiki_proposal_descriptor() -> None:
    assert CREATE_WIKI_PROPOSAL_DESCRIPTOR.name == "ingestion.create_wiki_proposal"
    assert CREATE_WIKI_PROPOSAL_DESCRIPTOR.effect == ToolEffect.PROPOSAL_PRODUCING


def test_update_wiki_section_proposal_descriptor() -> None:
    assert (
        UPDATE_WIKI_SECTION_PROPOSAL_DESCRIPTOR.name
        == "ingestion.update_wiki_section_proposal"
    )
    assert UPDATE_WIKI_SECTION_PROPOSAL_DESCRIPTOR.effect == ToolEffect.PROPOSAL_PRODUCING


def test_compound_wiki_proposal_descriptor() -> None:
    assert (
        COMPOUND_WIKI_PROPOSAL_DESCRIPTOR.name
        == "ingestion.create_wiki_and_update_section_proposal"
    )
    assert COMPOUND_WIKI_PROPOSAL_DESCRIPTOR.effect == ToolEffect.PROPOSAL_PRODUCING

def test_request_and_result_are_frozen_and_slotted() -> None:
    from dataclasses import fields
    assert {field.name for field in fields(CreateWikiProposalRequest)} == {
        "source_path",
        "target_path",
        "title",
        "body",
    }
    
    req = CreateWikiProposalRequest(source_path="src.md", target_path="wiki/target.md", title="Title", body="body")
    with pytest.raises(AttributeError):
        req.title = "New Title"  # type: ignore
    
    res = CreateWikiProposalResult(proposal_id="1", proposal_path="proposals/1", target_path="wiki/target.md", status="draft")
    with pytest.raises(AttributeError):
        res.proposal_id = "2"  # type: ignore

@pytest.mark.parametrize("invalid_title", [
    123, None, ["title"], {"t": "t"}
])
def test_request_rejects_non_string_title(invalid_title: any) -> None:
    with pytest.raises(TypeError, match="title must be a string"):
        CreateWikiProposalRequest(source_path="src", target_path="wiki", title=invalid_title, body="body")

@pytest.mark.parametrize("empty_title", [
    "", "   ", "\n", "\t"
])
def test_request_rejects_empty_or_whitespace_only_title(empty_title: str) -> None:
    with pytest.raises(ValueError, match="title cannot be empty or whitespace-only"):
        CreateWikiProposalRequest(source_path="src", target_path="wiki", title=empty_title, body="body")

@pytest.mark.parametrize("surrounded_title", [
    " Title", "Title ", " Title ", "\nTitle", "Title\n"
])
def test_request_rejects_title_with_surrounding_whitespace(surrounded_title: str) -> None:
    with pytest.raises(ValueError, match="title cannot have surrounding whitespace"):
        CreateWikiProposalRequest(source_path="src", target_path="wiki", title=surrounded_title, body="body")

@pytest.mark.parametrize("invalid_body", [
    123, None, ["body"], {"b": "b"}
])
def test_request_rejects_non_string_body(invalid_body: any) -> None:
    with pytest.raises(TypeError, match="body must be a string"):
        CreateWikiProposalRequest(source_path="src", target_path="wiki", title="Title", body=invalid_body)

@pytest.mark.parametrize("empty_body", [
    "", "   ", "\n", "\t"
])
def test_request_rejects_empty_or_whitespace_only_body(empty_body: str) -> None:
    with pytest.raises(ValueError, match="body cannot be empty or whitespace-only"):
        CreateWikiProposalRequest(source_path="src", target_path="wiki", title="Title", body=empty_body)

def test_request_preserves_body_exactly() -> None:
    req = CreateWikiProposalRequest(source_path="src", target_path="wiki", title="Title", body="  \n Body  \n\r")
    assert req.body == "  \n Body  \n\r"


def test_update_request_is_bounded_to_one_heading_and_body() -> None:
    request = UpdateWikiSectionProposalRequest(
        source_path="study/source.md",
        target_path="wiki/target.md",
        heading="Ekipman notları",
        body="Yeni içerik.",
    )
    assert request.heading == "Ekipman notları"
    assert not hasattr(request, "base_hash")
    assert not hasattr(request, "proposal_id")

    with pytest.raises(ValueError, match="# markers"):
        UpdateWikiSectionProposalRequest(
            "study/source.md", "wiki/target.md", "## Ekipman notları", "Body"
        )
    with pytest.raises(ValueError, match="one line"):
        UpdateWikiSectionProposalRequest(
            "study/source.md", "wiki/target.md", "Ekipman\nnotları", "Body"
        )


def test_compound_request_is_bounded_and_requires_distinct_targets() -> None:
    request = CompoundWikiProposalRequest(
        "study/source.md",
        "wiki/detail.md",
        "Detail",
        "Detailed body",
        "wiki/summary.md",
        "Equipment notes",
        "See [[detail]].",
    )
    assert request.update_heading == "Equipment notes"
    assert not hasattr(request, "base_hash")
    assert not hasattr(request, "proposal_id")

    with pytest.raises(ValueError, match="must be different"):
        CompoundWikiProposalRequest(
            "study/source.md",
            "wiki/same.md",
            "Detail",
            "Detailed body",
            "wiki/same.md",
            "Equipment notes",
            "Replacement",
        )


# Error mappings
def test_file_tracking_error_maps_to_validation_error(tmp_path: Path) -> None:
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source", side_effect=FileTrackingError("msg")):
        with pytest.raises(ToolValidationError, match="Invalid source path") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, FileTrackingError)

def test_unregistered_source_error_maps_to_validation_error(tmp_path: Path) -> None:
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source", side_effect=UnregisteredSourceError("msg")):
        with pytest.raises(ToolValidationError, match="Source is not registered") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, UnregisteredSourceError)

def test_modified_source_error_maps_to_conflict_error(tmp_path: Path) -> None:
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source", side_effect=ModifiedSourceError("msg")):
        with pytest.raises(ToolConflictError, match="Registered source has changed") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, ModifiedSourceError)

def test_missing_source_error_maps_to_not_found_error(tmp_path: Path) -> None:
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source", side_effect=MissingSourceError("msg")):
        with pytest.raises(ToolNotFoundError, match="Registered source is missing") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, MissingSourceError)

def test_source_read_error_maps_to_execution_error(tmp_path: Path) -> None:
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source", side_effect=SourceReadError("msg")):
        with pytest.raises(ToolExecutionError, match="Could not read registered source") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, SourceReadError)

def test_invalid_wiki_target_error_maps_to_validation_error(tmp_path: Path) -> None:
    _write_ownership(tmp_path)
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source"), \
         patch("lifeos.facade.proposal_tools.build_wiki_proposal", side_effect=InvalidWikiTargetError("msg")):
        with pytest.raises(ToolValidationError, match="Invalid wiki target path") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, InvalidWikiTargetError)

def test_wiki_target_exists_error_maps_to_conflict_error(tmp_path: Path) -> None:
    _write_ownership(tmp_path)
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source"), \
         patch("lifeos.facade.proposal_tools.build_wiki_proposal"), \
         patch("lifeos.facade.proposal_tools.persist_wiki_proposal", side_effect=WikiTargetExistsError("msg")):
        with pytest.raises(ToolConflictError, match="Wiki target already exists") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, WikiTargetExistsError)

def test_proposal_already_exists_error_maps_to_conflict_error(tmp_path: Path) -> None:
    _write_ownership(tmp_path)
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    with patch("lifeos.facade.proposal_tools.load_registered_source"), \
         patch("lifeos.facade.proposal_tools.build_wiki_proposal"), \
         patch("lifeos.facade.proposal_tools.persist_wiki_proposal", side_effect=ProposalAlreadyExistsError("msg")):
        with pytest.raises(ToolConflictError, match="Draft proposal already exists") as exc_info:
            create_wiki_proposal(vault_root=tmp_path, registry=Registry(tmp_path / "reg.db"), request=req)
        assert isinstance(exc_info.value.__cause__, ProposalAlreadyExistsError)

def test_proposal_publication_error_maps_to_execution_error(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    registry = Registry(tmp_path / "registry.db")
    registry.initialize()

    src_path = vault_root / "src.md"
    src_path.write_bytes(b"content")

    from lifeos.registry.file_tracking import register_scan
    from lifeos.scanner import VaultFile

    register_scan(registry, vault_root, [VaultFile(path=Path("src.md"), file_type=".md", size_bytes=len(b"content"))])
    
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    
    def mock_clock() -> datetime:
        return datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
    def mock_random() -> str:
        return "abcdef12"
    
    import os
    original_open = os.open
    def mock_open(path, flags, *args, **kwargs):
        if "prop-20250101T120000Z-abcdef12" in str(path) and getattr(mock_open, "called", False) is False:
            mock_open.called = True
            raise PermissionError("denied")
        return original_open(path, flags, *args, **kwargs)

    with patch("lifeos.ingestion.proposals.os.open", side_effect=mock_open):
        with pytest.raises(ToolExecutionError, match="Could not publish draft proposal") as exc_info:
            create_wiki_proposal(
                vault_root=vault_root,
                registry=registry,
                request=req,
                clock_fn=mock_clock,
                random_suffix_fn=mock_random
            )
        
        # Verify the cause chain
        cause1 = exc_info.value.__cause__
        assert isinstance(cause1, ProposalPublicationError)
        cause2 = cause1.__cause__
        assert isinstance(cause2, PermissionError)
        
        # Verify the partial directory is cleaned up
        assert not (vault_root / "proposals" / "prop-20250101T120000Z-abcdef12").exists()

def test_facade_uses_verified_source_without_decoding_or_parsing_it(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _write_ownership(vault_root)
    registry = Registry(tmp_path / "registry.db")
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    
    with patch("lifeos.facade.proposal_tools.load_registered_source") as mock_load, \
         patch("lifeos.facade.proposal_tools.build_wiki_proposal") as mock_build, \
         patch("lifeos.facade.proposal_tools.persist_wiki_proposal") as mock_persist, \
         patch("lifeos.facade.proposal_tools.generate_proposal_id", return_value="id"):
         
        mock_load.return_value = VerifiedRegisteredSource(
            source=SourceSnapshot("src.md", "hash"),
            content=b"content"
        )
        mock_persist.return_value = vault_root / "proposals" / "id"
        mock_build.return_value = WikiProposalDocuments("id", "wiki/target.md", b"doc", b"patch")
        
        create_wiki_proposal(vault_root=vault_root, registry=registry, request=req)
        assert mock_build.call_args.kwargs["source"] == SourceSnapshot("src.md", "hash")

def test_real_happy_path_facade(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    registry = Registry(tmp_path / "registry.db")
    registry.initialize()
    
    src_path = vault_root / "src.md"
    src_path.write_bytes(b"content")
    
    from lifeos.registry.file_tracking import hash_file_content, register_scan
    from lifeos.scanner import VaultFile
    
    register_scan(registry, vault_root, [VaultFile(path=Path("src.md"), file_type=".md", size_bytes=len(b"content"))])
    content_hash = hash_file_content(b"content")

    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    
    frozen_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    def mock_clock() -> datetime:
        return frozen_time

    def mock_random() -> str:
        return "abcdef12"
    
    # We test that request exposes no internal fields
    assert not hasattr(req, "proposal_id")
    assert not hasattr(req, "timestamp")
    assert not hasattr(req, "hash")
    assert not hasattr(req, "provenance")
    assert not hasattr(req, "model")
    
    result = create_wiki_proposal(
        vault_root=vault_root, 
        registry=registry, 
        request=req,
        clock_fn=mock_clock,
        random_suffix_fn=mock_random
    )
    
    assert result.status == "draft"
    assert result.target_path == "wiki/target.md"
    assert not (vault_root / "wiki/target.md").exists()
    assert result.proposal_path == f"proposals/{result.proposal_id}"
    assert result.proposal_id == "prop-20250101T120000Z-abcdef12"
    
    prop_dir = vault_root / result.proposal_path
    assert (prop_dir / "proposal.md").exists()
    assert (prop_dir / "patches.json").exists()
    
    assert src_path.read_bytes() == b"content"
    
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.markdown.parser import parse_markdown_note
    
    loaded = load_proposal_directory(prop_dir, proposals_root=vault_root / "proposals")
    assert not loaded.findings
    assert loaded.proposal.metadata.status.value == "draft"
    
    ops = loaded.proposal.patch_document.operations
    assert len(ops) == 1
    create_op = ops[0]
    assert create_op.op == "create_generated_file"
    assert create_op.generator_id == "lifeos.facade.external_agent"
    assert create_op.generator_version == "1"
    
    parsed = parse_markdown_note(
        Path("wiki/target.md"),
        content=create_op.new_content,
    )
    prov = parsed.frontmatter["lifeos_provenance"]
    assert prov["generator"]["id"] == "lifeos.facade.external_agent"
    assert prov["generator"]["version"] == "1"
    assert "model_id" not in prov["generator"]
    assert prov["sources"][0]["path"] == "src.md"
    assert prov["sources"][0]["content_hash"] == f"sha256:{content_hash}"
    assert prov["schema_version"] == 1
    assert prov["created_at"] == "2025-01-01T12:00:00Z"


def test_real_happy_path_updates_one_existing_wiki_section(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    (vault_root / "study").mkdir()
    _write_ownership(vault_root)
    registry = Registry(tmp_path / "registry.db")
    registry.initialize()

    source_bytes = b"Verified equipment source.\n"
    target_bytes = (
        "---\nid: first-aid\n---\n\n# İlk Yardım\n\n"
        "## Ekipman notları\n\nEski.\n\n## Güvenlik\n\nKorunur.\n"
    ).encode()
    (vault_root / "study" / "source.md").write_bytes(source_bytes)
    target_path = vault_root / "wiki" / "ilk-yardim.md"
    target_path.write_bytes(target_bytes)

    from lifeos.registry.file_tracking import hash_file_content, register_scan
    from lifeos.scanner import VaultFile

    register_scan(
        registry,
        vault_root,
        [
            VaultFile(Path("study/source.md"), ".md", len(source_bytes)),
            VaultFile(Path("wiki/ilk-yardim.md"), ".md", len(target_bytes)),
        ],
    )
    result = update_wiki_section_proposal(
        vault_root=vault_root,
        registry=registry,
        request=UpdateWikiSectionProposalRequest(
            "study/source.md",
            "wiki/ilk-yardim.md",
            "Ekipman notları",
            "Yeni doğrulanmış liste.",
        ),
        clock_fn=lambda: datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        random_suffix_fn=lambda: "abcdef12",
    )

    assert result.status == "draft"
    assert result.heading == "Ekipman notları"
    assert target_path.read_bytes() == target_bytes

    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.unified_diff import apply_diff

    loaded = load_proposal_directory(
        vault_root / result.proposal_path,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    assert loaded.metadata.related_sources == ("study/source.md",)
    operation = loaded.patch_document.operations[0]
    assert operation.op == "patch_human_file"
    assert operation.base_hash == f"sha256:{hash_file_content(target_bytes)}"
    candidate = apply_diff(target_bytes.decode(), operation.unified_diff)
    assert "## Ekipman notları\n\nYeni doğrulanmış liste." in candidate
    assert "## Güvenlik\n\nKorunur." in candidate


def test_real_happy_path_creates_compound_wiki_draft(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    (vault_root / "study").mkdir()
    _write_ownership(vault_root)
    registry = Registry(tmp_path / "registry.db")
    registry.initialize()

    source_bytes = b"Verified equipment source.\n"
    update_bytes = (
        "# First Aid\n\n## Equipment notes\n\nOld.\n\n## Safety\n\nKeep.\n"
    ).encode()
    (vault_root / "study" / "source.md").write_bytes(source_bytes)
    update_path = vault_root / "wiki" / "first-aid.md"
    update_path.write_bytes(update_bytes)

    from lifeos.registry.file_tracking import hash_file_content, register_scan
    from lifeos.scanner import VaultFile

    register_scan(
        registry,
        vault_root,
        [
            VaultFile(Path("study/source.md"), ".md", len(source_bytes)),
            VaultFile(Path("wiki/first-aid.md"), ".md", len(update_bytes)),
        ],
    )
    result = create_wiki_and_update_section_proposal(
        vault_root=vault_root,
        registry=registry,
        request=CompoundWikiProposalRequest(
            "study/source.md",
            "wiki/equipment.md",
            "Equipment",
            "Verified detailed list.",
            "wiki/first-aid.md",
            "Equipment notes",
            "See [[equipment]] for the verified list.",
        ),
        clock_fn=lambda: datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        random_suffix_fn=lambda: "abcdef12",
    )

    assert result.status == "draft"
    assert not (vault_root / "wiki" / "equipment.md").exists()
    assert update_path.read_bytes() == update_bytes

    from lifeos.proposals.loader import load_proposal_directory

    loaded = load_proposal_directory(
        vault_root / result.proposal_path,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    assert [operation.op for operation in loaded.patch_document.operations] == [
        "create_generated_file",
        "patch_human_file",
    ]
    assert loaded.patch_document.operations[1].base_hash == (
        f"sha256:{hash_file_content(update_bytes)}"
    )


def test_compound_draft_rejects_managed_update_target_without_persisting(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    (vault_root / "study").mkdir()
    _write_ownership(vault_root)
    source = vault_root / "study" / "source.md"
    source.write_text("Verified source.\n")
    target = vault_root / "wiki" / "summary.md"
    target.write_text(
        "# Summary\n\n## Equipment\n\n"
        "<!-- lifeos:managed:start equipment -->\nOld.\n"
        "<!-- lifeos:managed:end equipment -->\n"
    )
    registry = Registry(tmp_path / "registry.db")
    registry.initialize()

    from lifeos.registry.file_tracking import register_scan
    from lifeos.scanner import VaultFile

    register_scan(
        registry,
        vault_root,
        [VaultFile(Path("study/source.md"), ".md", source.stat().st_size)],
    )

    with pytest.raises(ToolValidationError, match="contains managed blocks"):
        create_wiki_and_update_section_proposal(
            vault_root=vault_root,
            registry=registry,
            request=CompoundWikiProposalRequest(
                "study/source.md",
                "wiki/detail.md",
                "Detail",
                "Detailed body",
                "wiki/summary.md",
                "Equipment",
                "Replacement",
            ),
        )
    assert list((vault_root / "proposals").iterdir()) == []


def test_update_rejects_missing_heading_without_persisting(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    (vault_root / "study").mkdir()
    _write_ownership(vault_root)
    source = vault_root / "study" / "source.md"
    target = vault_root / "wiki" / "target.md"
    source.write_text("Source.\n")
    target.write_text("# Note\n")
    registry = Registry(tmp_path / "registry.db")
    registry.initialize()

    from lifeos.registry.file_tracking import register_scan
    from lifeos.scanner import VaultFile

    register_scan(
        registry,
        vault_root,
        [
            VaultFile(Path("study/source.md"), ".md", source.stat().st_size),
            VaultFile(Path("wiki/target.md"), ".md", target.stat().st_size),
        ],
    )

    with pytest.raises(ToolValidationError, match="Invalid or ambiguous"):
        update_wiki_section_proposal(
            vault_root=vault_root,
            registry=registry,
            request=UpdateWikiSectionProposalRequest(
                "study/source.md", "wiki/target.md", "Missing", "New"
            ),
        )
    assert list((vault_root / "proposals").iterdir()) == []


def test_create_rejects_orphaned_ownership_without_persisting(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    registry = _registered_source(vault_root, tmp_path)
    _write_ownership(
        vault_root,
        {"wiki/missing.md": _ownership_entry(b"previous generated content\n")},
    )

    with pytest.raises(
        ToolOwnershipConflictError,
        match="missing but retains generated ownership.*restore.*release ownership",
    ):
        create_wiki_proposal(
            vault_root=vault_root,
            registry=registry,
            request=CreateWikiProposalRequest(
                "study/source.md", "wiki/missing.md", "Missing", "Replacement body"
            ),
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_generated_owned_section_update_emits_valid_generated_replacement(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    registry = _registered_source(vault_root, tmp_path)
    target_content = b"# Note\n\n## Selected\n\nOld.\n\n## Keep\n\nSame.\n"
    target = vault_root / "wiki" / "generated.md"
    target.write_bytes(target_content)
    _write_ownership(
        vault_root,
        {"wiki/generated.md": _ownership_entry(target_content)},
    )

    result = update_wiki_section_proposal(
        vault_root=vault_root,
        registry=registry,
        request=UpdateWikiSectionProposalRequest(
            "study/source.md", "wiki/generated.md", "Selected", "New."
        ),
        clock_fn=lambda: datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc),
        random_suffix_fn=lambda: "abcdef12",
    )

    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.validation import preflight_proposal

    loaded = load_proposal_directory(
        vault_root / result.proposal_path,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    operation = loaded.patch_document.operations[0]
    assert operation.op == "replace_generated_file"
    assert operation.expected_generator_id == "lifeos.facade.external_agent"
    assert operation.new_content == target_content.decode().replace("Old.", "New.")
    assert preflight_proposal(loaded, vault_root=vault_root).state == "valid"


def test_compound_generated_owned_update_emits_two_valid_operations(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    registry = _registered_source(vault_root, tmp_path)
    target_content = b"# Summary\n\n## Equipment\n\nOld.\n\n## Keep\n\nSame.\n"
    target = vault_root / "wiki" / "summary.md"
    target.write_bytes(target_content)
    _write_ownership(
        vault_root,
        {"wiki/summary.md": _ownership_entry(target_content)},
    )

    result = create_wiki_and_update_section_proposal(
        vault_root=vault_root,
        registry=registry,
        request=CompoundWikiProposalRequest(
            "study/source.md",
            "wiki/detail.md",
            "Detail",
            "Detailed body.",
            "wiki/summary.md",
            "Equipment",
            "See [[detail]].",
        ),
        clock_fn=lambda: datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc),
        random_suffix_fn=lambda: "abcdef12",
    )

    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.validation import preflight_proposal

    loaded = load_proposal_directory(
        vault_root / result.proposal_path,
        proposals_root=vault_root / "proposals",
    ).proposal
    assert loaded is not None
    assert [operation.op for operation in loaded.patch_document.operations] == [
        "create_generated_file",
        "replace_generated_file",
    ]
    assert preflight_proposal(loaded, vault_root=vault_root).state == "valid"


@pytest.mark.parametrize(
    ("generator_id", "target_content", "manifest_content", "message"),
    [
        (
            "another.generator",
            b"# Note\n\n## Selected\n\nOld.\n",
            b"# Note\n\n## Selected\n\nOld.\n",
            "different generator",
        ),
        (
            "lifeos.facade.external_agent",
            b"# Note\n\n## Selected\n\nChanged outside ownership.\n",
            b"# Note\n\n## Selected\n\nOld.\n",
            "does not match its ownership record",
        ),
    ],
)
def test_generated_update_rejects_unsafe_ownership_without_persisting(
    tmp_path: Path,
    generator_id: str,
    target_content: bytes,
    manifest_content: bytes,
    message: str,
) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    registry = _registered_source(vault_root, tmp_path)
    (vault_root / "wiki" / "generated.md").write_bytes(target_content)
    _write_ownership(
        vault_root,
        {
            "wiki/generated.md": _ownership_entry(
                manifest_content, generator_id=generator_id
            )
        },
    )

    with pytest.raises(ToolOwnershipConflictError, match=message):
        update_wiki_section_proposal(
            vault_root=vault_root,
            registry=registry,
            request=UpdateWikiSectionProposalRequest(
                "study/source.md", "wiki/generated.md", "Selected", "New."
            ),
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_missing_ownership_manifest_prevents_draft(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "proposals").mkdir(parents=True)
    (vault_root / "wiki").mkdir()
    registry = _registered_source(vault_root, tmp_path)

    with pytest.raises(ToolValidationError, match="ownership manifest is missing"):
        create_wiki_proposal(
            vault_root=vault_root,
            registry=registry,
            request=CreateWikiProposalRequest(
                "study/source.md", "wiki/new.md", "New", "Body"
            ),
        )

    assert list((vault_root / "proposals").iterdir()) == []

def test_verify_identity_and_time_generation(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _write_ownership(vault_root)
    registry = Registry(tmp_path / "registry.db")
    req = CreateWikiProposalRequest("src.md", "wiki/target.md", "Title", "Body")
    
    frozen_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    clock_calls = 0
    def mock_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return frozen_time
        
    random_calls = 0
    def mock_random() -> str:
        nonlocal random_calls
        random_calls += 1
        return "abcdef12"
        
    with patch("lifeos.facade.proposal_tools.load_registered_source") as mock_load, \
         patch("lifeos.facade.proposal_tools.build_wiki_proposal") as mock_build, \
         patch("lifeos.facade.proposal_tools.persist_wiki_proposal") as _:
         
        mock_load.return_value = VerifiedRegisteredSource(
            source=SourceSnapshot("src.md", "hash"),
            content=b"content"
        )
        mock_build.return_value = WikiProposalDocuments("id", "wiki/target.md", b"doc", b"patch")
        
        create_wiki_proposal(
            vault_root=vault_root, 
            registry=registry, 
            request=req,
            clock_fn=mock_clock,
            random_suffix_fn=mock_random
        )
        
        assert clock_calls == 1
        assert random_calls == 1
        
        # Check build_wiki_proposal was called with the generated proposal_id and timestamp
        mock_build.assert_called_once()
        kwargs = mock_build.call_args.kwargs
        assert kwargs["proposal_id"] == "prop-20250101T120000Z-abcdef12"
        assert kwargs["created_at"] == "2025-01-01T12:00:00Z"
