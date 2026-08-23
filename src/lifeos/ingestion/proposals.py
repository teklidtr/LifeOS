"""Public ingestion proposal API with cumulative generated-wiki provenance.

The existing implementation lives in ``_proposals_core``. This module keeps that API
stable while adding source-reference accumulation only to generated-owned wiki updates.
Human-owned patches continue to use the unchanged core behavior.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
import sys
from typing import Any

from lifeos.ingestion import _proposals_core as _core
from lifeos.ingestion._proposals_core import *  # noqa: F403
from lifeos.ingestion.drafts import SourceSnapshot
from lifeos.ingestion.provenance import (
    LifeOSProvenance,
    ProvenanceSource,
    ProvenanceValidationError,
    extract_provenance,
    merge_provenance_sources,
    provenance_to_frontmatter_value,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.patches import ReplaceGeneratedFileV2


_current_source: ContextVar[SourceSnapshot | None] = ContextVar(
    "lifeos_current_provenance_source", default=None
)
_original_build_wiki_section_operation = _core._build_wiki_section_operation


def _accumulate_generated_wiki_provenance(
    target_content: str,
    source: SourceSnapshot,
) -> str:
    parsed = parse_markdown_note(Path("generated-wiki.md"), content=target_content)
    if any(finding.severity == "error" for finding in parsed.findings):
        raise _core.InvalidWikiSectionError("Generated wiki frontmatter is malformed")

    try:
        provenance = extract_provenance(parsed.frontmatter)
    except ProvenanceValidationError as exc:
        raise _core.InvalidWikiSectionError("Generated wiki provenance is malformed") from exc

    # Ownership and provenance are independent. A generated-owned file without the
    # provenance block remains valid and is not silently assigned invented history.
    if provenance is None:
        return target_content

    merged_sources = merge_provenance_sources(
        provenance.sources,
        ProvenanceSource(path=source.path, content_hash=source.content_hash),
    )
    if merged_sources == provenance.sources:
        return target_content

    metadata = dict(parsed.frontmatter)
    metadata["lifeos_provenance"] = provenance_to_frontmatter_value(
        LifeOSProvenance(
            schema_version=provenance.schema_version,
            sources=merged_sources,
            generator=provenance.generator,
            created_at=provenance.created_at,
        )
    )
    return _core._serialize_wiki_frontmatter(metadata) + parsed.body


def _build_wiki_section_operation(*args: Any, **kwargs: Any) -> Any:
    operation = _original_build_wiki_section_operation(*args, **kwargs)
    source = _current_source.get()
    if source is None or not isinstance(operation, ReplaceGeneratedFileV2):
        return operation

    candidate = _accumulate_generated_wiki_provenance(operation.new_content, source)
    if candidate == operation.new_content:
        return operation
    return ReplaceGeneratedFileV2(
        id=operation.id,
        target_path=operation.target_path,
        base_hash=operation.base_hash,
        expected_generator_id=operation.expected_generator_id,
        generator_version=operation.generator_version,
        new_content=candidate,
    )


def _with_source(builder: Any, *, source: SourceSnapshot, **kwargs: Any) -> Any:
    token = _current_source.set(source)
    try:
        return builder(source=source, **kwargs)
    finally:
        _current_source.reset(token)


_original_build_wiki_section_update_proposal = _core.build_wiki_section_update_proposal
_original_build_compound_wiki_proposal = _core.build_compound_wiki_proposal
_original_build_compounding_wiki_proposal = _core.build_compounding_wiki_proposal
_original_build_study_learning_proposal = _core.build_study_learning_proposal


def build_wiki_section_update_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    return _with_source(_original_build_wiki_section_update_proposal, source=source, **kwargs)


def build_compound_wiki_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    return _with_source(_original_build_compound_wiki_proposal, source=source, **kwargs)


def build_compounding_wiki_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    return _with_source(_original_build_compounding_wiki_proposal, source=source, **kwargs)


def build_study_learning_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    return _with_source(_original_build_study_learning_proposal, source=source, **kwargs)


# Core builders resolve this global at call time, so installing the wrapper here covers
# single, compound, compounding, and study wiki updates without changing their public API.
_core._build_wiki_section_operation = _build_wiki_section_operation
_core.build_wiki_section_update_proposal = build_wiki_section_update_proposal
_core.build_compound_wiki_proposal = build_compound_wiki_proposal
_core.build_compounding_wiki_proposal = build_compounding_wiki_proposal
_core.build_study_learning_proposal = build_study_learning_proposal

# Preserve the historical module surface, including globals patched directly by tests.
sys.modules[__name__] = _core
