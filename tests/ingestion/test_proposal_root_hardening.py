from pathlib import Path

import pytest

from lifeos.ingestion.proposals import (
    ProposalPublicationError,
    WikiProposalDocuments,
    persist_wiki_proposal,
)


def test_proposal_publication_rejects_symlinked_root_without_writing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    proposals_root = vault / "proposals"
    proposals_root.symlink_to(outside, target_is_directory=True)
    documents = WikiProposalDocuments(
        proposal_id="proposal-symlink-guard",
        target_path="wiki/example.md",
        proposal_markdown=b"not inspected before root validation",
        patches_json=b"not inspected before root validation",
    )

    with pytest.raises(ProposalPublicationError, match="safe directory"):
        persist_wiki_proposal(proposals_root=proposals_root, documents=documents)

    assert list(outside.iterdir()) == []
