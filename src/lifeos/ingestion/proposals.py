"""Public ingestion proposal API with cumulative provenance and stable target identity.

The existing implementation lives in ``_proposals_core``. This module keeps that API
stable while layering cross-cutting contracts over existing builders/persistence:
source-reference accumulation for generated-owned wiki updates, review-bound stable
identity for existing canonical targets, and descriptor-bound proposal publication.
Human-owned patch semantics remain unchanged.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from typing import Any

from lifeos._atomic_write import atomic_write_file_secure
from lifeos._secure_io import SecureIOError, open_directory_secure
from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import collect_scoped_identity_snapshot, runtime_exclusion_prefix
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
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.proposals.schema import ProposalSchemaError, validate_metadata
from lifeos.proposals.target_identity import (
    ProposalTargetIdentityError,
    with_target_identity_extension,
)
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy


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
    """Bind stable IDs before a draft and its review snapshot become durable proposal state.

    Identity discovery applies path policy before unrelated Markdown is opened. Only exact
    replacement targets carried by the reviewed patch may opt into protected local scope; an
    unrelated protected or excluded note cannot affect publication merely because it shares an
    ID with a public target. ``runtime_dir`` is threaded explicitly when the caller has resolved
    configuration outside the vault so disposable custom-runtime exports never become identity
    candidates through the in-vault config fallback.
    """
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
        raise _core.ProposalPublicationError(
            "Could not bind stable identity for an existing proposal target"
        ) from exc

    if bound == metadata:
        return documents
    proposal_markdown = serialize_proposal_markdown(bound, parsed.body)
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return replace(documents, proposal_markdown=proposal_markdown)


def _raise_existing_create_target(*, proposals_root: Path, target_paths: tuple[str, ...]) -> None:
    """Preserve the core persistence contract before inspecting proposal payload bytes."""
    vault_root = proposals_root.parent
    for target_path in target_paths:
        if (vault_root / target_path).exists():
            raise _core.WikiTargetExistsError(f"Target path already exists: {target_path}")


_original_persist_wiki_section_update_proposal = _core.persist_wiki_section_update_proposal
_original_persist_compound_wiki_proposal = _core.persist_compound_wiki_proposal
_original_persist_compounding_wiki_proposal = _core.persist_compounding_wiki_proposal
_original_persist_study_learning_proposal = _core.persist_study_learning_proposal


def persist_wiki_section_update_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    return _original_persist_wiki_section_update_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
            runtime_dir=runtime_dir,
        ),
    )


def persist_compound_wiki_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    _raise_existing_create_target(
        proposals_root=proposals_root,
        target_paths=(documents.create_target_path,),
    )
    return _original_persist_compound_wiki_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
            runtime_dir=runtime_dir,
        ),
    )


def persist_compounding_wiki_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    _raise_existing_create_target(
        proposals_root=proposals_root,
        target_paths=tuple(documents.create_target_paths),
    )
    return _original_persist_compounding_wiki_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
            runtime_dir=runtime_dir,
        ),
    )


def persist_study_learning_proposal(  # type: ignore[no-redef]
    *, proposals_root: Path, documents: Any, runtime_dir: Path | None = None
) -> Path:
    _raise_existing_create_target(
        proposals_root=proposals_root,
        target_paths=tuple(documents.create_target_paths),
    )
    return _original_persist_study_learning_proposal(
        proposals_root=proposals_root,
        documents=_bind_existing_target_identities(
            proposals_root=proposals_root,
            documents=documents,
            runtime_dir=runtime_dir,
        ),
    )


def _secure_persist_proposal_documents(*, proposals_root: Path, documents: Any) -> Path:
    """Publish proposal artifacts through one no-follow directory descriptor."""
    proposal_id = str(documents.proposal_id)
    if (
        not proposal_id
        or proposal_id in {".", ".."}
        or "/" in proposal_id
        or "\\" in proposal_id
    ):
        raise _core.ProposalPublicationError("Proposal id is not safe for publication")

    proposals_fd = -1
    proposal_fd = -1
    proposal_created = False
    publication_complete = False
    proposal_dir = proposals_root / proposal_id

    try:
        try:
            proposals_fd = open_directory_secure(proposals_root)
        except SecureIOError as exc:
            raise _core.ProposalPublicationError(
                "Proposal root is not a safe directory"
            ) from exc

        try:
            os.mkdir(proposal_id, mode=0o755, dir_fd=proposals_fd)
            proposal_created = True
        except FileExistsError as exc:
            raise _core.ProposalAlreadyExistsError(
                f"Proposal directory already exists: {proposal_dir}"
            ) from exc

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= getattr(os, "O_NOFOLLOW")
        proposal_fd = os.open(proposal_id, flags, dir_fd=proposals_fd)

        atomic_write_file_secure(proposal_fd, "proposal.md", documents.proposal_markdown)
        atomic_write_file_secure(proposal_fd, "patches.json", documents.patches_json)
        review_json = build_review_snapshot_bytes_from_patches(
            vault_root=proposals_root.parent,
            patches_json=documents.patches_json,
        )
        atomic_write_file_secure(proposal_fd, "review.json", review_json)
        publication_complete = True
    except OSError as exc:
        raise _core.ProposalPublicationError(f"Failed to write proposal files: {exc}") from exc
    finally:
        if proposal_created and not publication_complete:
            if proposal_fd != -1:
                for filename in ("proposal.md", "patches.json", "review.json"):
                    try:
                        os.unlink(filename, dir_fd=proposal_fd)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass
            if proposals_fd != -1:
                try:
                    os.rmdir(proposal_id, dir_fd=proposals_fd)
                except OSError:
                    pass
        if proposal_fd != -1:
            os.close(proposal_fd)
        if proposals_fd != -1:
            os.close(proposals_fd)

    return proposal_dir


_core._build_wiki_section_operation = _build_wiki_section_operation
_core.build_wiki_section_update_proposal = build_wiki_section_update_proposal
_core.build_compound_wiki_proposal = build_compound_wiki_proposal
_core.build_compounding_wiki_proposal = build_compounding_wiki_proposal
_core.build_study_learning_proposal = build_study_learning_proposal
_core._persist_proposal_documents = _secure_persist_proposal_documents
_core.persist_wiki_section_update_proposal = persist_wiki_section_update_proposal
_core.persist_compound_wiki_proposal = persist_compound_wiki_proposal
_core.persist_compounding_wiki_proposal = persist_compounding_wiki_proposal
_core.persist_study_learning_proposal = persist_study_learning_proposal

sys.modules[__name__] = _core