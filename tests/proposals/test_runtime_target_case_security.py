from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.proposals.coherence_validation as coherence_validation
import lifeos.runtime_scope as runtime_scope
from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.proposals import build_wiki_proposal, persist_wiki_proposal
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.proposals import load_proposal_directory


def test_case_alias_runtime_target_uses_filesystem_aware_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    proposals.mkdir(parents=True)
    runtime = vault / "wiki" / "runtime-node"
    runtime.mkdir(parents=True)
    generator = ProvenanceGenerator(
        id="lifeos.test",
        version="1",
        prompt_schema_version="1",
        model_id=None,
    )
    documents = build_wiki_proposal(
        content=WikiProposalContent(
            title="Runtime alias target",
            body="Case aliases of runtime state must stay outside canonical mutation.",
            generator=generator,
        ),
        source=SourceSnapshot(path="raw/source.md", content_hash="sha256:" + "1" * 64),
        target_path="wiki/Runtime-node/new.md",
        proposal_id="prop-20260826T100000Z-1234abcd",
        created_at="2026-08-26T10:00:00Z",
    )
    proposal_dir = persist_wiki_proposal(proposals_root=proposals, documents=documents)
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals).proposal
    assert loaded is not None

    def simulated_case_insensitive_match(
        vault_root: Path,
        *,
        runtime_dir: Path,
        path: str,
    ) -> bool:
        del vault_root, runtime_dir
        return path == "wiki/Runtime-node/new.md"

    def fail_base_preflight(*args: object, **kwargs: object) -> object:
        pytest.fail("filesystem-selected runtime alias reached ordinary preflight")

    monkeypatch.setattr(
        runtime_scope,
        "runtime_path_selects_configured_directory",
        simulated_case_insensitive_match,
    )
    monkeypatch.setattr(
        coherence_validation,
        "_base_preflight_proposal",
        fail_base_preflight,
    )

    result = coherence_validation.preflight_proposal(
        loaded,
        vault_root=vault,
        runtime_dir=runtime,
    )

    assert result.state == "invalid"
    assert any(finding.code == "target_inside_runtime" for finding in result.findings)
    assert all(operation.state == "invalid" for operation in result.operations)
