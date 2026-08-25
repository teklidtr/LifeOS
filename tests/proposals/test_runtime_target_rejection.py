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


def test_publication_rejects_existing_target_inside_configured_runtime(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    proposals.mkdir(parents=True)
    runtime = vault / "wiki" / "runtime-node"
    target = runtime / "target.md"
    target.parent.mkdir(parents=True)
    content = "---\nid: runtime-copy\ntype: concept\ntitle: Runtime copy\n---\n# Facts\nOld\n"
    target.write_text(content, encoding="utf-8")
    target_hash = f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
    generator = ProvenanceGenerator(
        id="lifeos.test",
        version="1",
        prompt_schema_version="1",
        model_id=None,
    )
    documents = build_wiki_section_update_proposal(
        source=SourceSnapshot(path="raw/source.md", content_hash="sha256:" + "1" * 64),
        target_path="wiki/runtime-node/target.md",
        target_content=content,
        target_content_hash=target_hash,
        heading="Facts",
        section_body="New",
        generator=generator,
        proposal_id="prop-20260825T060000Z-1234abcd",
        created_at="2026-08-25T06:00:00Z",
    )

    with pytest.raises(ProposalPublicationError, match="stable identity"):
        persist_wiki_section_update_proposal(
            proposals_root=proposals,
            documents=documents,
            runtime_dir=runtime,
        )

    assert list(proposals.iterdir()) == []
