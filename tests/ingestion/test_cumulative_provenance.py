import json
from pathlib import Path

from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.provenance import ProvenanceGenerator, extract_provenance
from lifeos.ingestion.proposals import build_wiki_proposal, build_wiki_section_update_proposal
from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry.provenance import _validate_provenance_frontmatter


def _source(path: str, char: str) -> SourceSnapshot:
    return SourceSnapshot(path=path, content_hash="sha256:" + char * 64)


def _generator() -> ProvenanceGenerator:
    return ProvenanceGenerator("lifeos.ingestion.wiki", "1.0", "v1", "test-model")


def _created_page(source: SourceSnapshot) -> str:
    content = WikiProposalContent(
        title="Creatine",
        body="# Creatine\n\n## Evidence\n\nInitial.\n",
        generator=_generator(),
    )
    documents = build_wiki_proposal(
        content=content,
        source=source,
        target_path="wiki/concepts/creatine.md",
        proposal_id="prop-20260823T190000Z-abcdef12",
        created_at="2026-08-23T19:00:00Z",
    )
    return json.loads(documents.patches_json)["operations"][0]["new_content"]


def _updated_page(original: str, source: SourceSnapshot, body: str) -> str:
    documents = build_wiki_section_update_proposal(
        source=source,
        target_path="wiki/concepts/creatine.md",
        target_content=original,
        target_content_hash="sha256:" + "c" * 64,
        heading="Evidence",
        section_body=body,
        generator=_generator(),
        proposal_id="prop-20260823T191000Z-abcdef12",
        created_at="2026-08-23T19:10:00Z",
        expected_generator_id="lifeos.ingestion.wiki",
    )
    operation = json.loads(documents.patches_json)["operations"][0]
    assert operation["op"] == "replace_generated_file"
    return operation["new_content"]


def _sources(markdown: str) -> list[tuple[str, str]]:
    parsed = parse_markdown_note(Path("wiki/concepts/creatine.md"), content=markdown)
    provenance = extract_provenance(parsed.frontmatter)
    assert provenance is not None
    return [(item.path, item.content_hash) for item in provenance.sources]


def test_generated_wiki_update_accumulates_new_reference() -> None:
    source_a = _source("notes/creatine.md", "a")
    source_b = _source("journal/2026-08-23.md", "b")
    updated = _updated_page(_created_page(source_a), source_b, "Updated from journal.")
    assert _sources(updated) == [
        (source_a.path, source_a.content_hash),
        (source_b.path, source_b.content_hash),
    ]


def test_repeated_identical_source_does_not_duplicate_reference() -> None:
    source = _source("notes/creatine.md", "a")
    updated = _updated_page(_created_page(source), source, "Updated wording.")
    assert _sources(updated) == [(source.path, source.content_hash)]


def test_same_path_changed_hash_keeps_both_historical_snapshots() -> None:
    source_v1 = _source("notes/creatine.md", "a")
    source_v2 = _source("notes/creatine.md", "b")
    updated = _updated_page(_created_page(source_v1), source_v2, "Updated source revision.")
    assert _sources(updated) == [
        (source_v1.path, source_v1.content_hash),
        (source_v2.path, source_v2.content_hash),
    ]


def test_human_owned_update_does_not_gain_provenance() -> None:
    original = "---\ntitle: Human note\n---\n# Human\n\n## Evidence\n\nOld.\n"
    documents = build_wiki_section_update_proposal(
        source=_source("journal/2026-08-23.md", "b"),
        target_path="wiki/human.md",
        target_content=original,
        target_content_hash="sha256:" + "c" * 64,
        heading="Evidence",
        section_body="New.",
        generator=_generator(),
        proposal_id="prop-20260823T191000Z-abcdef12",
        created_at="2026-08-23T19:10:00Z",
    )
    operation = json.loads(documents.patches_json)["operations"][0]
    assert operation["op"] == "patch_human_file"
    assert "lifeos_provenance" not in operation["unified_diff"]


def test_registry_reads_canonical_nested_multi_source_provenance() -> None:
    source_a = _source("notes/creatine.md", "a")
    source_b = _source("journal/2026-08-23.md", "b")
    updated = _updated_page(_created_page(source_a), source_b, "Updated.")
    frontmatter = parse_markdown_note(
        Path("wiki/concepts/creatine.md"), content=updated
    ).frontmatter

    document, sources = _validate_provenance_frontmatter(
        "wiki/concepts/creatine.md", frontmatter["lifeos_provenance"]
    )
    assert document.schema_version == 1
    assert document.generator_id == "lifeos.ingestion.wiki"
    assert [(row.source_path, row.source_hash) for row in sources] == [
        (source_a.path, source_a.content_hash),
        (source_b.path, source_b.content_hash),
    ]
