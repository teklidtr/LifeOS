"""Explicit composition for ingestion proposal building and persistence.

This module owns the cross-cutting ingestion contracts that need source/provenance,
stable target identity, and prepublication checks.  The lower-level proposal builders
remain ordinary functions in ``_proposals_core``; this layer composes them without
ambient state, module replacement, or rebinding imported implementations.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, cast

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import collect_scoped_identity_snapshot, runtime_exclusion_prefix
from lifeos.ingestion._proposals_core import (
    InvalidWikiSectionError,
    ProposalPublicationError,
    WikiTargetExistsError,
    _persist_proposal_documents,
    _serialize_wiki_frontmatter,
    build_compound_wiki_proposal as _core_build_compound_wiki_proposal,
    build_compounding_wiki_proposal as _core_build_compounding_wiki_proposal,
    build_study_learning_proposal as _core_build_study_learning_proposal,
    build_wiki_section_update_proposal as _core_build_wiki_section_update_proposal,
)
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
from lifeos.proposals.patches import (
    PatchDocumentV2,
    PatchOperationV2,
    ReplaceGeneratedFileV2,
    serialize_patch_json_bytes,
    validate_patch_document,
)
from lifeos.proposals.schema import ProposalSchemaError, validate_metadata
from lifeos.proposals.target_identity import (
    ProposalTargetIdentityError,
    with_target_identity_extension,
)
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy


def _accumulate_generated_wiki_provenance(
    target_content: str,
    source: SourceSnapshot,
) -> str:
    parsed = parse_markdown_note(Path("generated-wiki.md"), content=target_content)
    if any(finding.severity == "error" for finding in parsed.findings):
        raise InvalidWikiSectionError("Generated wiki frontmatter is malformed")

    try:
        provenance = extract_provenance(parsed.frontmatter)
    except ProvenanceValidationError as exc:
        raise InvalidWikiSectionError("Generated wiki provenance is malformed") from exc

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
    return _serialize_wiki_frontmatter(metadata) + parsed.body


def _with_explicit_operation_provenance(*, documents: Any, source: SourceSnapshot) -> Any:
    """Attach one invocation's source only to its generated replacement operations."""
    patch = cast(PatchDocumentV2, validate_patch_document(json.loads(documents.patches_json)))
    changed = False
    operations: list[PatchOperationV2] = []
    for operation in patch.operations:
        if isinstance(operation, ReplaceGeneratedFileV2):
            candidate = _accumulate_generated_wiki_provenance(operation.new_content, source)
            if candidate != operation.new_content:
                operation = replace(operation, new_content=candidate)
                changed = True
        operations.append(operation)

    if not changed:
        return documents
    updated_patch = replace(patch, operations=tuple(operations))
    return replace(documents, patches_json=serialize_patch_json_bytes(updated_patch))


def build_wiki_section_update_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    documents = _core_build_wiki_section_update_proposal(source=source, **kwargs)
    return _with_explicit_operation_provenance(documents=documents, source=source)


def build_compound_wiki_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    documents = _core_build_compound_wiki_proposal(source=source, **kwargs)
    return _with_explicit_operation_provenance(documents=documents, source=source)


def build_compounding_wiki_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    documents = _core_build_compounding_wiki_proposal(source=source, **kwargs)
    return _with_explicit_operation_provenance(documents=documents, source=source)


def build_study_learning_proposal(*, source: SourceSnapshot, **kwargs: Any) -> Any:
    documents = _core_build_study_learning_proposal(source=source, **kwargs)
    return _with_explicit_operation_provenance(documents=documents, source=source)


def _replacement_target_paths(patch: Any) -> frozenset[str]:
    return frozenset(
        operation.target_path
        for operation in patch.operations
        if isinstance(getattr(operation, "base_hash", None), str)
        or isinstance(getattr(operation, "expected_content_hash", None), str)
    )


def _bind_existing_target_identities(
    *,
    proposals_root: Path,
    documents: Any,
    runtime_dir: Path | None = None,
) -> Any:
    """Bind stable IDs before a draft and its review snapshot become durable proposal state."""
    try:
        proposal_text = documents.proposal_markdown.decode("utf-8")
        parsed = parse_markdown_note(Path("proposal.md"), content=proposal_text)
        if any(finding.severity == "error" for finding in parsed.findings):
            raise ProposalTargetIdentityError("Proposal Markdown is structurally invalid")
        metadata = validate_metadata(dict(parsed.frontmatter))
        patch_data = json.loads(documents.patches_json.decode("utf-8"))
        patch = validate_patch_document(patch_data)
        vault_root = proposals_root.parent
        reviewed_paths = _replacement_target_paths(patch)
        runtime_prefix = runtime_exclusion_prefix(vault_root, runtime_dir=runtime_dir)
        if runtime_prefix is not None:
            runtime_targets = sorted(
                path for path in reviewed_paths if path.startswith(runtime_prefix)
            )
            if runtime_targets:
                raise ProposalTargetIdentityError(
                    "Existing proposal target is inside configured runtime state: "
                    + ", ".join(runtime_targets)
                )
        policy = load_retrieval_policy(vault_root)

        def allow_identity_path(path: str) -> bool:
            if path.startswith("conversations/") or path.startswith("proposals/"):
                return False
            return scope_decision(
                path,
                scope=RetrievalScope(allow_protected=path in reviewed_paths),
                policy=policy,
                mode="local",
            ).allowed

        snapshot = collect_scoped_identity_snapshot(
            vault_root,
            allow_path=allow_identity_path,
            runtime_dir=runtime_dir,
        )
        bound = with_target_identity_extension(metadata, patch, snapshot)
    except (
        CoherenceError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ProposalSchemaError,
        ProposalTargetIdentityError,
        RetrievalError,
        ValueError,
    ) as exc:
        raise ProposalPublicationError(
            "Could not bind stable identity for an existing proposal target"
        ) from exc

    if bound == metadata:
        return documents
    proposal_markdown = serialize_proposal_markdown(bound, parsed.body)
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return replace(documents, proposal_markdown=proposal_markdown)


def _raise_existing_create_target(*, proposals_root: Path, target_paths: tuple[str, ...]) -> None:
    vault_root = proposals_root.parent
    for target_path in target_paths:
        if (vault_root / target_path).exists():
            raise WikiTargetExistsError(f"Target path already exists: {target_path}")


def persist_wiki_section_update_proposal(
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    bound_documents = _bind_existing_target_identities(
        proposals_root=proposals_root,
        documents=documents,
        runtime_dir=runtime_dir,
    )
    return _persist_proposal_documents(proposals_root=proposals_root, documents=bound_documents)


def persist_compound_wiki_proposal(
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    target_paths = (documents.create_target_path,)
    _raise_existing_create_target(proposals_root=proposals_root, target_paths=target_paths)
    bound_documents = _bind_existing_target_identities(
        proposals_root=proposals_root,
        documents=documents,
        runtime_dir=runtime_dir,
    )
    _raise_existing_create_target(proposals_root=proposals_root, target_paths=target_paths)
    return _persist_proposal_documents(proposals_root=proposals_root, documents=bound_documents)


def persist_compounding_wiki_proposal(
    *,
    proposals_root: Path,
    documents: Any,
    runtime_dir: Path | None = None,
    before_publish: Callable[[], None] | None = None,
) -> Path:
    target_paths = tuple(documents.create_target_paths)
    _raise_existing_create_target(proposals_root=proposals_root, target_paths=target_paths)
    bound_documents = _bind_existing_target_identities(
        proposals_root=proposals_root,
        documents=documents,
        runtime_dir=runtime_dir,
    )
    if before_publish is not None:
        before_publish()
    _raise_existing_create_target(proposals_root=proposals_root, target_paths=target_paths)
    return _persist_proposal_documents(proposals_root=proposals_root, documents=bound_documents)


def persist_study_learning_proposal(
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    target_paths = tuple(documents.create_target_paths)
    _raise_existing_create_target(proposals_root=proposals_root, target_paths=target_paths)
    bound_documents = _bind_existing_target_identities(
        proposals_root=proposals_root,
        documents=documents,
        runtime_dir=runtime_dir,
    )
    _raise_existing_create_target(proposals_root=proposals_root, target_paths=target_paths)
    return _persist_proposal_documents(proposals_root=proposals_root, documents=bound_documents)
