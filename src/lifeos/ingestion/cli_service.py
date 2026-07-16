from dataclasses import dataclass
from pathlib import Path

from lifeos.registry import Registry
from lifeos.ingestion.backend import AnalysisBackend
from lifeos.ingestion.orchestration import analyze_registered_source
from lifeos.ingestion.proposals import build_wiki_proposal, persist_wiki_proposal

@dataclass(frozen=True, slots=True)
class IngestProposalResult:
    proposal_id: str
    proposal_path: Path
    target_path: str

def ingest_source(
    *,
    vault_root: Path,
    registry: Registry,
    source_path: str,
    target_path: str,
    backend: AnalysisBackend,
    proposal_id: str,
    created_at: str,
) -> IngestProposalResult:
    analyzed = analyze_registered_source(
        registry=registry,
        vault_root=vault_root,
        source_path=source_path,
        backend=backend,
    )
    
    docs = build_wiki_proposal(
        analysis=analyzed.analysis,
        source=analyzed.source,
        target_path=target_path,
        proposal_id=proposal_id,
        created_at=created_at,
    )
    
    proposal_path = persist_wiki_proposal(
        proposals_root=vault_root / "proposals",
        documents=docs,
    )
    
    return IngestProposalResult(
        proposal_id=proposal_id,
        proposal_path=proposal_path,
        target_path=target_path,
    )
