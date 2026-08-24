from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lifeos.ingestion.drafts import SourceSnapshot
from lifeos.ingestion.proposals import (
    ProposalPublicationError,
    build_wiki_section_update_proposal,
    persist_wiki_section_update_proposal,
)
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.proposals import load_proposal_directory, parse_target_identities

PROPOSAL_ID = "prop-20260824T120000Z-1234abcd"


def _hash_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _documents(vault: Path):
    target = vault / "wiki" / "target.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "---\nid: stable-wiki-target\ntype: concept\ntitle: Target\n---\n# Facts\nOld\n"
    target.write_text(content, encoding="utf-8")
    generator = ProvenanceGenerator(
        id="lifeos.test",
        version="1",
        prompt_schema_version="1",
        model_id=None,
    )
    documents = build_wiki_section_update_proposal(
        source=SourceSnapshot(path="raw/source.md", content_hash="sha256:" + "1" * 64),
        target_path="wiki/target.md",
        target_content=content,
        target_content_hash=_hash_bytes(content.encode("utf-8")),
        heading="Facts",
        section_body="New",
        generator=generator,
        proposal_id=PROPOSAL_ID,
        created_at="2026-08-24T12:00:00Z",
    )
    return documents


def test_published_existing_target_binds_identity_into_proposal_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    proposals.mkdir(parents=True)
    documents = _documents(vault)

    proposal_dir = persist_wiki_section_update_proposal(
        proposals_root=proposals,
        documents=documents,
    )
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals).proposal

    assert loaded is not None
    targets = parse_target_identities(loaded.metadata, loaded.patch_document)
    assert len(targets) == 1
    assert targets[0].stable_id == "stable-wiki-target"
    assert targets[0].reviewed_path == "wiki/target.md"


def test_publication_fails_closed_when_target_id_is_duplicated(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    proposals.mkdir(parents=True)
    documents = _documents(vault)
    duplicate = vault / "wiki" / "duplicate.md"
    duplicate.write_text(
        "---\nid: stable-wiki-target\ntype: concept\ntitle: Duplicate\n---\nBody\n",
        encoding="utf-8",
    )

    with pytest.raises(ProposalPublicationError, match="stable identity"):
        persist_wiki_section_update_proposal(
            proposals_root=proposals,
            documents=documents,
        )
