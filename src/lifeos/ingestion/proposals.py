"""Public ingestion proposal API with cumulative provenance and stable target identity.

The existing implementation lives in ``_proposals_core``. This module keeps that API
stable while layering two cross-cutting contracts over existing builders/persistence:
source-reference accumulation for generated-owned wiki updates, and review-bound stable
identity for existing canonical targets. Human-owned patch semantics remain unchanged.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any

from lifeos.coherence import CoherenceError, collect_identity_snapshot
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
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import ReplaceGeneratedFileV2, validate_patch_document
from lifeos.proposals.schema import ProposalSchemaError, validate_metadata
from lifeos.proposals.target_identity import (
    ProposalTargetIdentityError,
    with_target_identity_extension,
)


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


def build_wiki_section_update_proposal(  # type: ignore[no-redef]
    *, source: SourceSnapshot, **kwargs: Any
) -> Any:
    return _with_source(_original_build_wiki_section_update_proposal, source=source, **kwargs)


def build_compound_wiki_proposal(  # type: ignore[no-redef]
    *, source: SourceSnapshot, **kwargs: Any
) -> Any:
    return _with_source(_original_build_compound_wiki_proposal, source=source, **kwargs)


def build_compounding_wiki_proposal(  # type: ignore[no-redef]
    *, source: SourceSnapshot, **kwargs: Any
) -> Any:
    return _with_source(_original_build_compounding_wiki_proposal, source=source, **kwargs)


def build_study_learning_proposal(  # type: ignore[no-redef]
    *, source: SourceSnapshot, **kwargs: Any
) -> Any:
    return _with_source(_original_build_study_learning_proposal, source=source, **kwargs)


def _bind_existing_target_identities(*, proposals_root: Path, documents: Any) -> Any:
    """Bind stable IDs before a draft and its review snapshot become durable proposal state."""
    try:
        proposal_text = documents.proposal_markdown.decode("utf-8")
        parsed = parse_markdown_note(Path("proposal.md"), content=proposal_text)
        if any(finding.severity == "error" for finding in parsed.findings):
            raise ProposalTargetIdentityError("Proposal Markdown is structurally invalid")
        metadata = validate_metadata(dict(parsed.frontmatter))
        patch_data = json.loads(documents.patches_json.decode("utf-8"))
        patch = validate_patch_document(patch_data)
        bound = with_target_identity_extension(
            metadata,
            patch,
            collect_identity_snapshot(proposals_root.parent),
        )
    except (
        CoherenceError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ProposalSchemaError,
        ProposalTargetIdentityError,
        ValueError,
    ) as exc:
        raise _core.ProposalPublicationError(
            "Could not bind stable identity for an existing proposal target"
        ) from exc

    if bound == metadata:
        return documents
    proposal_markdown = serialize_proposal_markdown(bound, parsed.body)
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return replace(documents, proposal_markdown=proposal_markdown)


_original_persist_wiki_section_update_proposal = _core.persist_wiki_section_update_proposal
_original_persist_compound_wiki_proposal = _core.persist_compound_wiki_proposal
_original_persist_compounding_wiki_proposal = _core.persist_compounding_wiki_proposal
_original_persist_study_learning_proposal = _core.persist_study_learning_proposal


def persist_wiki_section_update_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any
) -> Path:
    return _original_persist_wiki_section_update_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
        ),
    )


def persist_compound_wiki_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any
) -> Path:
    return _original_persist_compound_wiki_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
        ),
    )


def persist_compounding_wiki_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any
) -> Path:
    return _original_persist_compounding_wiki_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
        ),
    )


def persist_study_learning_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any
) -> Path:
    return _original_persist_study_learning_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
        ),
    )


# Core builders resolve this global at call time, so installing the wrapper here covers
# single, compound, compounding, and study wiki updates without changing their public API.
_core._build_wiki_section_operation = _build_wiki_section_operation
_core.build_wiki_section_update_proposal = build_wiki_section_update_proposal
_core.build_compound_wiki_proposal = build_compound_wiki_proposal
_core.build_compounding_wiki_proposal = build_compounding_wiki_proposal
_core.build_study_learning_proposal = build_study_learning_proposal

# Existing-target publication is the narrowest point shared by all ingestion update routes.
# Create-only proposals stay intentionally path-oriented.
_core.persist_wiki_section_update_proposal = persist_wiki_section_update_proposal
_core.persist_compound_wiki_proposal = persist_compound_wiki_proposal
_core.persist_compounding_wiki_proposal = persist_compounding_wiki_proposal
_core.persist_study_learning_proposal = persist_study_learning_proposal

# Preserve the historical module surface, including globals patched directly by tests.
sys.modules[__name__] = _core
