from pathlib import Path
import pytest

from lifeos.registry import Registry
from lifeos.registry.file_tracking import register_scan
from lifeos.scanner import VaultFile
from lifeos.ingestion.backend import AnalysisBackend, AnalysisRequest, AnalysisResult, WikiPageDraft
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.ingestion.cli_service import ingest_source, IngestProposalResult
from lifeos.ingestion.proposals import WikiTargetExistsError

class FakeAnalysisBackend(AnalysisBackend):
    def __init__(self, result: AnalysisResult):
        self._result = result

    def analyze(self, request: AnalysisRequest, /) -> AnalysisResult:
        return self._result

def test_ingest_source_creates_draft_proposal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.chdir(vault_root)
    (vault_root / "proposals").mkdir()
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    result = ingest_source(
        vault_root=vault_root,
        registry=registry,
        source_path=source_path,
        target_path="wiki/target.md",
        backend=backend,
        proposal_id="prop-20260714T000000Z-12345678",
        created_at="2026-07-14T00:00:00Z"
    )

    assert isinstance(result, IngestProposalResult)
    assert result.proposal_id == "prop-20260714T000000Z-12345678"
    assert result.target_path == "wiki/target.md"
    assert result.proposal_path == vault_root / "proposals" / result.proposal_id

    assert (result.proposal_path / "proposal.md").exists()
    assert (result.proposal_path / "patches.json").exists()

    # Proposal status remains draft
    with registry.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM proposals WHERE id = ?", (result.proposal_id,))
        row = cursor.fetchone()
        assert row is None  # Not in registry yet, only on disk.
        
    proposal_md = (result.proposal_path / "proposal.md").read_text()
    assert "\nstatus: draft\n" in proposal_md

    # final wiki target remains absent
    assert not (vault_root / "wiki/target.md").exists()

    # source bytes remain unchanged
    assert target_file.read_bytes() == content

    # registry rows remain unchanged for source (still tracked as is)
    from lifeos.registry.file_tracking import compare_registered_file, hash_file_content
    working_tree_hash = hash_file_content(target_file.read_bytes())
    comparison = compare_registered_file(registry, source_path, working_tree_hash=working_tree_hash)
    assert comparison.state.name == "REGISTERED_UNCHANGED"

def test_ingest_source_preserves_target_path_errors(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "proposals").mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "wiki/target.md").write_text("exists")
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    with pytest.raises(WikiTargetExistsError):
        ingest_source(
            vault_root=vault_root,
            registry=registry,
            source_path=source_path,
            target_path="wiki/target.md",
            backend=backend,
            proposal_id="prop-20260714T000000Z-12345678",
            created_at="2026-07-14T00:00:00Z"
        )

def test_existing_proposal_id_not_overwritten(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    proposals_dir = vault_root / "proposals"
    proposals_dir.mkdir()
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    proposal_id = "prop-20260714T000000Z-12345678"
    existing_prop_dir = proposals_dir / proposal_id
    existing_prop_dir.mkdir()
    (existing_prop_dir / "proposal.md").write_text("existing")

    from lifeos.ingestion.proposals import ProposalPublicationError
    with pytest.raises(ProposalPublicationError, match="already exists"):
        ingest_source(
            vault_root=vault_root,
            registry=registry,
            source_path=source_path,
            target_path="wiki/target.md",
            backend=backend,
            proposal_id=proposal_id,
            created_at="2026-07-14T00:00:00Z"
        )
    
    assert (existing_prop_dir / "proposal.md").read_text() == "existing"

def test_publication_failure_leaves_no_partial_proposal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "proposals").mkdir()
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    proposal_id = "prop-20260714T000000Z-12345678"

    from typing import Any
    def mock_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("Simulated disk full")
    
    import lifeos.ingestion.proposals
    monkeypatch.setattr(lifeos.ingestion.proposals, "atomic_write_file_secure", mock_write)
    
    from lifeos.ingestion.proposals import ProposalPublicationError
    with pytest.raises(ProposalPublicationError):
        ingest_source(
            vault_root=vault_root,
            registry=registry,
            source_path=source_path,
            target_path="wiki/target.md",
            backend=backend,
            proposal_id=proposal_id,
            created_at="2026-07-14T00:00:00Z"
        )
    
    assert not (vault_root / "proposals" / proposal_id).exists()

def test_unregistered_source_is_rejected(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    # DO NOT register

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    from lifeos.ingestion.orchestration import UnregisteredSourceError

    with pytest.raises(UnregisteredSourceError):
        ingest_source(
            vault_root=vault_root,
            registry=registry,
            source_path=source_path,
            target_path="wiki/target.md",
            backend=backend,
            proposal_id="prop-unregistered",
            created_at="2026-07-14T00:00:00Z"
        )

def test_modified_source_is_rejected(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])
    
    # Modify the file after registration
    target_file.write_bytes(b"modified")

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    from lifeos.ingestion.orchestration import ModifiedSourceError

    with pytest.raises(ModifiedSourceError):
        ingest_source(
            vault_root=vault_root,
            registry=registry,
            source_path=source_path,
            target_path="wiki/target.md",
            backend=backend,
            proposal_id="prop-modified",
            created_at="2026-07-14T00:00:00Z"
        )

def test_missing_source_is_rejected(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content)

    registry_path = tmp_path / "registry.db"
    registry = Registry(registry_path)
    registry.initialize()
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])
    
    # Delete the file after registration
    target_file.unlink()

    fake_result = AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(id="test", version="1", prompt_schema_version="1", model_id=None)
    )
    backend = FakeAnalysisBackend(result=fake_result)

    from lifeos.ingestion.orchestration import MissingSourceError

    with pytest.raises(MissingSourceError):
        ingest_source(
            vault_root=vault_root,
            registry=registry,
            source_path=source_path,
            target_path="wiki/target.md",
            backend=backend,
            proposal_id="prop-missing",
            created_at="2026-07-14T00:00:00Z"
        )
