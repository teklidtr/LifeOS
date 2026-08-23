import json
from datetime import datetime, timezone
from pathlib import Path

from lifeos.facade.proposal_tools import (
    EvolveWikiCreateRequest,
    EvolveWikiProposalRequest,
    EvolveWikiUpdateRequest,
    evolve_wiki_proposal,
)
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.lifecycle import approve_proposal, submit_proposal_for_review
from lifeos.proposals.loader import load_proposal_directory
from lifeos.registry import Registry
from lifeos.registry.file_tracking import register_scan
from lifeos.scanner import VaultFile


def _load(proposal_dir: Path, proposals_root: Path):
    result = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert result.proposal is not None
    assert not result.findings
    return result.proposal


def test_agent_directed_compounding_proposal_applies_multiple_emergent_wiki_changes(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    proposals_root = vault_root / "proposals"
    source_dir = vault_root / "raw"
    wiki_root = vault_root / "wiki"
    system_root = vault_root / "system"
    for path in (proposals_root, source_dir, wiki_root, system_root, vault_root / ".lifeos"):
        path.mkdir(parents=True, exist_ok=True)

    (system_root / "generated-ownership.json").write_text(
        json.dumps({"schema_version": 1, "owned_files": {}})
    )
    source = source_dir / "karpathy-note.md"
    source.write_text("Retrieval practice and knowledge compounding are reusable ideas.\n")
    hub = wiki_root / "learning.md"
    hub.write_text("# Learning\n\n## Retrieval\n\nOld summary.\n")

    registry = Registry(tmp_path / "registry.db")
    registry.initialize()
    register_scan(
        registry,
        vault_root,
        [VaultFile(Path("raw/karpathy-note.md"), ".md", source.stat().st_size)],
    )

    draft_result = evolve_wiki_proposal(
        vault_root=vault_root,
        registry=registry,
        request=EvolveWikiProposalRequest(
            source_path="raw/karpathy-note.md",
            creates=(
                EvolveWikiCreateRequest(
                    target_path="wiki/learning/retrieval-practice.md",
                    title="Retrieval Practice",
                    body="Durable source-grounded explanation.",
                    rationale="This idea should accumulate evidence across future sources.",
                ),
                EvolveWikiCreateRequest(
                    target_path="wiki/knowledge-systems/knowledge-compounding.md",
                    title="Knowledge Compounding",
                    body="A durable model for accumulated knowledge.",
                    rationale="This is a reusable concept, not merely a source summary.",
                ),
            ),
            updates=(
                EvolveWikiUpdateRequest(
                    target_path="wiki/learning.md",
                    heading="Retrieval",
                    body="See [[learning/retrieval-practice]] for the accumulated note.",
                    rationale="Reuse the existing learning hub and avoid duplicate summaries.",
                ),
            ),
        ),
        clock_fn=lambda: datetime(2026, 8, 23, 7, 0, tzinfo=timezone.utc),
        random_suffix_fn=lambda: "abcdef12",
    )

    proposal_dir = vault_root / draft_result.proposal_path
    draft = _load(proposal_dir, proposals_root)
    submit_proposal_for_review(
        draft,
        proposals_root=proposals_root,
        submitted_by="reviewer",
        submitted_at="2026-08-23T07:01:00Z",
    )
    pending = _load(proposal_dir, proposals_root)
    approve_proposal(
        pending,
        proposals_root=proposals_root,
        approved_by="reviewer",
        approved_at="2026-08-23T07:02:00Z",
    )
    approved = _load(proposal_dir, proposals_root)
    applied = apply_proposal(
        approved,
        vault_root=vault_root,
        applied_by="reviewer",
        applied_at="2026-08-23T07:03:00Z",
    )

    assert applied.changed_paths == (
        "wiki/learning/retrieval-practice.md",
        "wiki/knowledge-systems/knowledge-compounding.md",
        "wiki/learning.md",
    )
    assert (wiki_root / "learning" / "retrieval-practice.md").exists()
    assert (wiki_root / "knowledge-systems" / "knowledge-compounding.md").exists()
    assert "[[learning/retrieval-practice]]" in hub.read_text()
    assert not (wiki_root / "sources").exists()
