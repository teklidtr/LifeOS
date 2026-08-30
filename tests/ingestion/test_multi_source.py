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
    mutation = PreparedBatchUpdateMutation(
        target_path="wiki/generated-topic.md",
        target_content=original,
        target_content_hash="sha256:" + "b" * 64,
        sections=(PreparedBatchSection("Evidence", "reconciled"),),
        rationale="Merge the two sources that support this target.",
        sources=relevant,
        expected_generator_id=GENERATOR.id,
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

    assert operation["op"] == "replace_generated_file"
    assert result is not None
    assert [(item.path, item.content_hash) for item in result.sources] == [
        (prior.path, prior.content_hash),
        (relevant[0].path, relevant[0].content_hash),
        (relevant[1].path, relevant[1].content_hash),
    ]
    assert unrelated.path not in {item.path for item in result.sources}


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
