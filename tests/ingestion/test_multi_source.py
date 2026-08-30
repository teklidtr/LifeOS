import hashlib
import json
from pathlib import Path

import pytest

from lifeos.ingestion._proposals_core import _serialize_wiki_frontmatter
from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.multi_source import (
    MAX_MULTI_SOURCE_PAYLOAD_BYTES,
    MultiSourcePayloadError,
    PreparedBatchCreateMutation,
    PreparedBatchSection,
    PreparedBatchUpdateMutation,
    build_multi_source_wiki_proposal,
    enforce_multi_source_payload_budget,
)
from lifeos.ingestion.provenance import (
    LifeOSProvenance,
    ProvenanceGenerator,
    ProvenanceSource,
    extract_provenance,
    provenance_to_frontmatter_value,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.application import ApplicationError, ApplicationErrorCode, apply_proposal
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.schema import validate_metadata


GENERATOR = ProvenanceGenerator(
    id="lifeos.facade.external_agent",
    version="1",
    prompt_schema_version="4",
    model_id=None,
)
CREATED_AT = "2026-08-30T18:00:00Z"
PROPOSAL_ID = "prop-20260830T180000Z-1234abcd"


def _source(index: int) -> SourceSnapshot:
    return SourceSnapshot(
        path=f"notes/source-{index}.md",
        content_hash=f"sha256:{index:064x}",
    )


def _content(title: str) -> WikiProposalContent:
    return WikiProposalContent(title=title, body="Knowledge body.\n", generator=GENERATOR)


def _approved_metadata():
    return validate_metadata(
        {
            "id": PROPOSAL_ID,
            "schema_version": 1,
            "patch_schema_version": 2,
            "lifecycle_schema_version": 1,
            "title": "Multi-source batch",
            "description": "Approved test batch",
            "status": "approved",
            "risk": "medium",
            "created_at": CREATED_AT,
            "created_by": "agent",
            "submitted_at": "2026-08-30T18:01:00Z",
            "submitted_by": "user",
            "review_digest": f"sha256:{hashlib.sha256(b'review').hexdigest()}",
            "approved_at": "2026-08-30T18:02:00Z",
            "approved_by": "user",
            "rejected_at": None,
            "rejected_by": None,
            "rejection_reason": None,
            "applied_at": None,
            "applied_by": None,
            "related_goals": [],
            "related_sources": ["notes/source-1.md", "notes/source-2.md"],
            "extensions": {},
        }
    )


def test_three_source_sections_become_one_human_patch() -> None:
    sources = (_source(1), _source(2), _source(3))
    original = "# Topic\n\n## One\nold one\n\n## Two\nold two\n\n## Three\nold three\n"
    mutation = PreparedBatchUpdateMutation(
        target_path="wiki/topic.md",
        target_content=original,
        target_content_hash="sha256:" + "a" * 64,
        sections=(
            PreparedBatchSection("One", "new one"),
            PreparedBatchSection("Two", "new two"),
            PreparedBatchSection("Three", "new three"),
        ),
        rationale="Reconcile three independently grounded sections.",
        sources=sources,
    )

    documents = build_multi_source_wiki_proposal(
        sources=sources,
        mutations=(mutation,),
        generator=GENERATOR,
        proposal_id=PROPOSAL_ID,
        created_at=CREATED_AT,
    )
    patch = json.loads(documents.patches_json)

    assert len(patch["operations"]) == 1
    operation = patch["operations"][0]
    assert operation["op"] == "patch_human_file"
    assert operation["target_path"] == "wiki/topic.md"
    assert "new one" in operation["unified_diff"]
    assert "new two" in operation["unified_diff"]
    assert "new three" in operation["unified_diff"]


def test_generated_update_accumulates_only_target_grounding_sources() -> None:
    prior = _source(1)
    relevant = (_source(2), _source(3))
    unrelated = _source(4)
    provenance = LifeOSProvenance(
        schema_version=1,
        sources=(ProvenanceSource(prior.path, prior.content_hash),),
        generator=GENERATOR,
        created_at="2026-08-01T10:00:00Z",
    )
    original = _serialize_wiki_frontmatter(
        {
            "title": "Generated Topic",
            "lifeos_provenance": provenance_to_frontmatter_value(provenance),
        }
    ) + "# Generated Topic\n\n## Evidence\nold\n"
    tag_rationale = "Preserve the reviewed taxonomy justification for this generated update."
    mutation = PreparedBatchUpdateMutation(
        target_path="wiki/generated-topic.md",
        target_content=original,
        target_content_hash="sha256:" + "b" * 64,
        sections=(PreparedBatchSection("Evidence", "reconciled"),),
        rationale="Merge the two sources that support this target.",
        sources=relevant,
        expected_generator_id=GENERATOR.id,
        proposed_tags=("grounded",),
        tag_rationale=tag_rationale,
    )

    documents = build_multi_source_wiki_proposal(
        sources=(prior, *relevant, unrelated),
        mutations=(mutation,),
        generator=GENERATOR,
        proposal_id=PROPOSAL_ID,
        created_at=CREATED_AT,
    )
    operation = json.loads(documents.patches_json)["operations"][0]
    parsed = parse_markdown_note(Path("wiki/generated-topic.md"), content=operation["new_content"])
    result = extract_provenance(parsed.frontmatter)
    proposal = documents.proposal_markdown.decode("utf-8")

    assert operation["op"] == "replace_generated_file"
    assert result is not None
    assert [(item.path, item.content_hash) for item in result.sources] == [
        (prior.path, prior.content_hash),
        (relevant[0].path, relevant[0].content_hash),
        (relevant[1].path, relevant[1].content_hash),
    ]
    assert unrelated.path not in {item.path for item in result.sources}
    assert parsed.frontmatter["tags"] == ["grounded"]
    assert f"tag_rationale: {tag_rationale}" in proposal
    assert f"Tag rationale: {tag_rationale}" in proposal


def test_distinct_targets_keep_distinct_source_subsets_in_review_metadata() -> None:
    sources = (_source(1), _source(2), _source(3))
    mutations = (
        PreparedBatchCreateMutation(
            target_path="wiki/alpha.md",
            content=_content("Alpha"),
            rationale="Alpha uses the first two sources.",
            sources=sources[:2],
        ),
        PreparedBatchCreateMutation(
            target_path="wiki/beta.md",
            content=_content("Beta"),
            rationale="Beta uses only the third source.",
            sources=(sources[2],),
        ),
    )

    documents = build_multi_source_wiki_proposal(
        sources=sources,
        mutations=mutations,
        generator=GENERATOR,
        proposal_id=PROPOSAL_ID,
        created_at=CREATED_AT,
    )
    proposal = documents.proposal_markdown.decode("utf-8")

    assert "target_grounding:" in proposal
    assert "notes/source-1.md" in proposal
    assert "notes/source-2.md" in proposal
    assert "notes/source-3.md" in proposal
    assert proposal.count("target_path: wiki/alpha.md") == 1
    assert proposal.count("target_path: wiki/beta.md") == 1


def test_batch_can_use_more_than_legacy_twelve_targets() -> None:
    source = _source(1)
    mutations = tuple(
        PreparedBatchCreateMutation(
            target_path=f"wiki/topic-{index}.md",
            content=_content(f"Topic {index}"),
            rationale=f"Create reconciled topic {index}.",
            sources=(source,),
        )
        for index in range(13)
    )

    documents = build_multi_source_wiki_proposal(
        sources=(source,),
        mutations=mutations,
        generator=GENERATOR,
        proposal_id=PROPOSAL_ID,
        created_at=CREATED_AT,
    )

    assert len(json.loads(documents.patches_json)["operations"]) == 13


def test_payload_budget_fails_before_persistence(tmp_path: Path) -> None:
    source = _source(1)
    mutation = PreparedBatchCreateMutation(
        target_path="wiki/huge.md",
        content=WikiProposalContent(
            title="Huge",
            body="x" * MAX_MULTI_SOURCE_PAYLOAD_BYTES,
            generator=GENERATOR,
        ),
        rationale="Exercise the bounded review payload.",
        sources=(source,),
    )
    documents = build_multi_source_wiki_proposal(
        sources=(source,),
        mutations=(mutation,),
        generator=GENERATOR,
        proposal_id=PROPOSAL_ID,
        created_at=CREATED_AT,
    )

    with pytest.raises(MultiSourcePayloadError):
        enforce_multi_source_payload_budget(
            vault_root=tmp_path,
            patches_json=documents.patches_json,
        )


def test_stale_target_aborts_all_batch_operations_before_any_publication(tmp_path: Path) -> None:
    sources = (_source(1), _source(2))
    first_original = "# First\n\n## Evidence\nold first\n"
    second_original = "# Second\n\n## Evidence\nold second\n"
    mutations = (
        PreparedBatchUpdateMutation(
            target_path="wiki/first.md",
            target_content=first_original,
            target_content_hash=f"sha256:{hashlib.sha256(first_original.encode()).hexdigest()}",
            sections=(PreparedBatchSection("Evidence", "new first"),),
            rationale="Update the first target.",
            sources=(sources[0],),
        ),
        PreparedBatchUpdateMutation(
            target_path="wiki/second.md",
            target_content=second_original,
            target_content_hash=f"sha256:{hashlib.sha256(second_original.encode()).hexdigest()}",
            sections=(PreparedBatchSection("Evidence", "new second"),),
            rationale="Update the second target.",
            sources=(sources[1],),
        ),
    )
    documents = build_multi_source_wiki_proposal(
        sources=sources,
        mutations=mutations,
        generator=GENERATOR,
        proposal_id=PROPOSAL_ID,
        created_at=CREATED_AT,
    )

    vault_root = tmp_path / "vault"
    wiki = vault_root / "wiki"
    proposal_dir = vault_root / "proposals" / PROPOSAL_ID
    system = vault_root / "system"
    wiki.mkdir(parents=True)
    proposal_dir.mkdir(parents=True)
    system.mkdir(parents=True)
    (wiki / "first.md").write_text(first_original, encoding="utf-8")
    (wiki / "second.md").write_text(second_original, encoding="utf-8")
    (system / "generated-ownership.json").write_text(
        json.dumps({"schema_version": 1, "owned_files": {}}), encoding="utf-8"
    )
    (proposal_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(_approved_metadata(), "Approved batch test.")
    )
    (proposal_dir / "patches.json").write_bytes(documents.patches_json)

    # Simulate an external edit after the draft was reviewed but before application.
    second_changed = "# Second\n\n## Evidence\nchanged outside proposal\n"
    (wiki / "second.md").write_text(second_changed, encoding="utf-8")

    loaded = load_proposal_directory(proposal_dir, proposals_root=vault_root / "proposals")
    assert loaded.proposal is not None
    with pytest.raises(ApplicationError) as error:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="user",
            applied_at="2026-08-30T18:03:00Z",
        )

    assert error.value.code == ApplicationErrorCode.PREFLIGHT_FAILED
    assert (wiki / "first.md").read_text(encoding="utf-8") == first_original
    assert (wiki / "second.md").read_text(encoding="utf-8") == second_changed
