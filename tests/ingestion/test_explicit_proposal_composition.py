from __future__ import annotations

import inspect
import json
from pathlib import Path

import lifeos.ingestion._proposal_composition as composition
import lifeos.ingestion._proposals_core as ingestion_core
import lifeos.ingestion.proposals as public_ingestion
from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.provenance import ProvenanceGenerator, extract_provenance
from lifeos.markdown.parser import parse_markdown_note


def _source(path: str, char: str) -> SourceSnapshot:
    return SourceSnapshot(path=path, content_hash="sha256:" + char * 64)


def _generator() -> ProvenanceGenerator:
    return ProvenanceGenerator("lifeos.ingestion.wiki", "1.0", "v1", "test-model")


def _created_page(source: SourceSnapshot) -> str:
    documents = public_ingestion.build_wiki_proposal(
        content=WikiProposalContent(
            title="Creatine",
            body="# Creatine\n\n## Evidence\n\nInitial.\n",
            generator=_generator(),
        ),
        source=source,
        target_path="wiki/concepts/creatine.md",
        proposal_id="prop-20260906T100000Z-abcdef12",
        created_at="2026-09-06T10:00:00Z",
    )
    return json.loads(documents.patches_json)["operations"][0]["new_content"]


def _updated_page(original: str, source: SourceSnapshot, body: str) -> str:
    documents = public_ingestion.build_wiki_section_update_proposal(
        source=source,
        target_path="wiki/concepts/creatine.md",
        target_content=original,
        target_content_hash="sha256:" + "d" * 64,
        heading="Evidence",
        section_body=body,
        generator=_generator(),
        proposal_id="prop-20260906T101000Z-abcdef12",
        created_at="2026-09-06T10:10:00Z",
        expected_generator_id="lifeos.ingestion.wiki",
    )
    return json.loads(documents.patches_json)["operations"][0]["new_content"]


def _provenance_paths(markdown: str) -> tuple[str, ...]:
    parsed = parse_markdown_note(Path("wiki/concepts/creatine.md"), content=markdown)
    provenance = extract_provenance(parsed.frontmatter)
    assert provenance is not None
    return tuple(item.path for item in provenance.sources)


def test_public_module_is_static_facade_over_explicit_composition() -> None:
    assert public_ingestion is not ingestion_core
    assert (
        public_ingestion.build_wiki_section_update_proposal
        is composition.build_wiki_section_update_proposal
    )
    assert (
        public_ingestion.persist_compounding_wiki_proposal
        is composition.persist_compounding_wiki_proposal
    )
    assert public_ingestion._persist_proposal_documents is ingestion_core._persist_proposal_documents


def test_public_builder_and_persistence_signatures_keep_compatibility_shape() -> None:
    build_parameters = inspect.signature(
        public_ingestion.build_wiki_section_update_proposal
    ).parameters
    assert tuple(build_parameters) == ("source", "kwargs")
    assert build_parameters["source"].kind is inspect.Parameter.KEYWORD_ONLY
    assert build_parameters["kwargs"].kind is inspect.Parameter.VAR_KEYWORD

    persist_parameters = inspect.signature(
        public_ingestion.persist_compounding_wiki_proposal
    ).parameters
    assert tuple(persist_parameters) == (
        "proposals_root",
        "documents",
        "runtime_dir",
        "before_publish",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in persist_parameters.values()
    )


def test_interleaved_builds_do_not_leak_provenance_between_invocations() -> None:
    source_a = _source("raw/a.md", "a")
    source_b = _source("raw/b.md", "b")
    source_c = _source("raw/c.md", "c")
    base = _created_page(source_a)

    updated_from_b = _updated_page(base, source_b, "From B.")
    updated_from_c = _updated_page(base, source_c, "From C.")
    updated_from_b_again = _updated_page(base, source_b, "From B again.")

    assert _provenance_paths(updated_from_b) == (source_a.path, source_b.path)
    assert _provenance_paths(updated_from_c) == (source_a.path, source_c.path)
    assert _provenance_paths(updated_from_b_again) == (source_a.path, source_b.path)
