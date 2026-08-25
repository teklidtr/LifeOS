from __future__ import annotations

from pathlib import Path

from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.proposals import build_wiki_proposal, persist_wiki_proposal
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.proposals import load_proposal_directory
from lifeos.proposals.coherence_validation import preflight_proposal


def test_preflight_rejects_create_target_inside_configured_runtime(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    proposals.mkdir(parents=True)
    runtime = vault / "wiki" / "runtime-node"
    generator = ProvenanceGenerator(
        id="lifeos.test",
        version="1",
        prompt_schema_version="1",
        model_id=None,
    )
    documents = build_wiki_proposal(
        content=WikiProposalContent(
            title="Runtime target",
            body="This draft must never become canonical runtime state.",
            generator=generator,
        ),
        source=SourceSnapshot(path="raw/source.md", content_hash="sha256:" + "1" * 64),
        target_path="wiki/runtime-node/new.md",
        proposal_id="prop-20260825T070000Z-1234abcd",
        created_at="2026-08-25T07:00:00Z",
    )
    proposal_dir = persist_wiki_proposal(proposals_root=proposals, documents=documents)
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals).proposal

    assert loaded is not None
    result = preflight_proposal(loaded, vault_root=vault, runtime_dir=runtime)

    assert result.state == "invalid"
    assert any(finding.code == "target_inside_runtime" for finding in result.findings)
    assert all(operation.state == "invalid" for operation in result.operations)
