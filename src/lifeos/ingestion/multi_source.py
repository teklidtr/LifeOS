"""Target-centric multi-source ingestion proposal construction.

Semantic reconciliation happens before this module is called. The deterministic boundary
receives one final desired mutation per target plus the verified source snapshots that ground
that target, and emits one ordinary atomic proposal using the existing proposal engine.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lifeos.ingestion._proposals_core import (
    CompoundingWikiProposalDocuments,
    InvalidWikiSectionError,
    InvalidWikiTargetError,
    WikiSectionUnchangedError,
    _replace_generated_wiki_tags,
    _serialize_wiki_frontmatter,
    replace_wiki_section,
    validate_wiki_target_path,
)
from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.provenance import (
    LifeOSProvenance,
    ProvenanceGenerator,
    ProvenanceSource,
    ProvenanceValidationError,
    extract_provenance,
    merge_provenance_sources,
    provenance_to_frontmatter_value,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import (
    CreateGeneratedFileV2,
    PatchDocumentV2,
    PatchHumanFile,
    ReplaceGeneratedFileV2,
    serialize_patch_json_bytes,
)
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus

MAX_MULTI_SOURCE_SOURCES = 64
MAX_MULTI_SOURCE_TARGETS = 32
MAX_MULTI_SOURCE_PAYLOAD_BYTES = 2 * 1024 * 1024


class MultiSourcePayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedBatchSection:
    heading: str
    body: str


@dataclass(frozen=True, slots=True)
class PreparedBatchCreateMutation:
    target_path: str
    content: WikiProposalContent
    rationale: str
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PreparedBatchUpdateMutation:
    target_path: str
    target_content: str
    target_content_hash: str
    sections: tuple[PreparedBatchSection, ...]
    rationale: str
    sources: tuple[SourceSnapshot, ...]
    expected_generator_id: str | None = None
    proposed_tags: tuple[str, ...] | None = None
    tag_rationale: str | None = None


PreparedBatchMutation = PreparedBatchCreateMutation | PreparedBatchUpdateMutation


def _provenance_source(source: SourceSnapshot) -> ProvenanceSource:
    return ProvenanceSource(
        path=source.path,
        content_hash=source.content_hash,
        acquisition_id=source.acquisition_id,
    )


def _source_record(source: SourceSnapshot) -> dict[str, str]:
    record = {"path": source.path, "content_hash": source.content_hash}
    if source.acquisition_id is not None:
        record["acquisition_id"] = source.acquisition_id
    return record


def _validate_sources(sources: tuple[SourceSnapshot, ...]) -> None:
    if not sources:
        raise InvalidWikiTargetError("Every batch target requires at least one grounding source")
    seen: set[tuple[str, str, str | None]] = set()
    for source in sources:
        key = (source.path, source.content_hash, source.acquisition_id)
        if key in seen:
            raise InvalidWikiTargetError("Target grounding sources must not contain duplicates")
        seen.add(key)


def _generated_create_candidate(
    *,
    mutation: PreparedBatchCreateMutation,
    target_path: str,
    generator: ProvenanceGenerator,
    created_at: str,
) -> str:
    provenance = LifeOSProvenance(
        schema_version=1,
        sources=tuple(_provenance_source(source) for source in mutation.sources),
        generator=generator,
        created_at=created_at,
    )
    from lifeos.wiki.layout import infer_wiki_page_kind

    page_kind = infer_wiki_page_kind(target_path)
    frontmatter: dict[str, object] = {
        "title": mutation.content.title,
        **({"type": page_kind} if page_kind is not None else {}),
        **({"tags": list(mutation.content.tags)} if mutation.content.tags else {}),
        "lifeos_provenance": provenance_to_frontmatter_value(provenance),
    }
    candidate = _serialize_wiki_frontmatter(frontmatter) + mutation.content.body
    return candidate if candidate.endswith("\n") else candidate + "\n"


def _merge_generated_sources(
    *,
    candidate: str,
    sources: tuple[SourceSnapshot, ...],
    generator: ProvenanceGenerator,
    created_at: str,
) -> str:
    parsed = parse_markdown_note(Path("generated-wiki.md"), content=candidate)
    if any(finding.severity == "error" for finding in parsed.findings):
        raise InvalidWikiSectionError("Generated wiki frontmatter is malformed")
    try:
        provenance = extract_provenance(parsed.frontmatter)
    except ProvenanceValidationError as error:
        raise InvalidWikiSectionError("Generated wiki provenance is malformed") from error

    # Preserve the existing single-source compatibility contract: generated ownership alone does
    # not authorize inventing missing provenance history on a legacy generated file.
    if provenance is None:
        return candidate
    merged = provenance.sources
    for source in sources:
        merged = merge_provenance_sources(merged, _provenance_source(source))
    metadata = dict(parsed.frontmatter)
    metadata["lifeos_provenance"] = provenance_to_frontmatter_value(
        LifeOSProvenance(
            schema_version=1,
            sources=merged,
            generator=provenance.generator,
            created_at=provenance.created_at,
        )
    )
    return _serialize_wiki_frontmatter(metadata) + parsed.body


def _build_update_candidate(mutation: PreparedBatchUpdateMutation) -> str:
    if not mutation.sections:
        raise InvalidWikiSectionError("A batch update requires at least one exact section")
    headings: set[str] = set()
    candidate = mutation.target_content
    for section in mutation.sections:
        if section.heading in headings:
            raise InvalidWikiSectionError("A batch target cannot replace the same heading twice")
        headings.add(section.heading)
        candidate = replace_wiki_section(
            target_content=candidate,
            heading=section.heading,
            section_body=section.body,
        )
    if mutation.proposed_tags is not None:
        if mutation.expected_generator_id is None:
            raise InvalidWikiSectionError("Tags cannot be changed on a human-owned wiki target")
        candidate = _replace_generated_wiki_tags(candidate, mutation.proposed_tags)
    return candidate


def build_multi_source_wiki_proposal(
    *,
    sources: tuple[SourceSnapshot, ...],
    mutations: tuple[PreparedBatchMutation, ...],
    generator: ProvenanceGenerator,
    proposal_id: str,
    created_at: str,
) -> CompoundingWikiProposalDocuments:
    """Build one proposal for one logical evidence batch, reconciled by target."""
    if not 1 <= len(sources) <= MAX_MULTI_SOURCE_SOURCES:
        raise InvalidWikiTargetError(
            f"Multi-source ingestion requires 1..{MAX_MULTI_SOURCE_SOURCES} sources"
        )
    source_keys = [(s.path, s.content_hash, s.acquisition_id) for s in sources]
    if len(set(source_keys)) != len(source_keys) or len({s.path for s in sources}) != len(sources):
        raise InvalidWikiTargetError("Multi-source ingestion sources must be distinct")
    if not 1 <= len(mutations) <= MAX_MULTI_SOURCE_TARGETS:
        raise InvalidWikiTargetError(
            f"Multi-source ingestion requires 1..{MAX_MULTI_SOURCE_TARGETS} target mutations"
        )

    batch_by_path = {source.path: source for source in sources}
    operations: list[CreateGeneratedFileV2 | PatchHumanFile | ReplaceGeneratedFileV2] = []
    target_paths: list[str] = []
    create_target_paths: list[str] = []
    grounding: list[dict[str, object]] = []
    seen_targets: set[str] = set()

    for index, mutation in enumerate(mutations, start=1):
        norm_target = validate_wiki_target_path(mutation.target_path)
        if not norm_target.endswith(".md"):
            raise InvalidWikiTargetError("Multi-source wiki targets must be Markdown files")
        if norm_target in seen_targets:
            raise InvalidWikiTargetError(
                f"Multi-source ingestion cannot touch one target twice: {norm_target}"
            )
        if not mutation.rationale.strip() or mutation.rationale != mutation.rationale.strip():
            raise InvalidWikiTargetError("Mutation rationale must be a trimmed non-empty string")
        if len(mutation.rationale) > 500:
            raise InvalidWikiTargetError("Mutation rationale cannot exceed 500 characters")
        _validate_sources(mutation.sources)
        for source in mutation.sources:
            verified = batch_by_path.get(source.path)
            if verified != source:
                raise InvalidWikiTargetError(
                    f"Target grounding source is not the verified batch snapshot: {source.path}"
                )

        seen_targets.add(norm_target)
        target_paths.append(norm_target)
        op_id = f"op-wiki-{index:02d}"
        item: dict[str, object] = {
            "target_path": norm_target,
            "rationale": mutation.rationale,
            "sources": [_source_record(source) for source in mutation.sources],
        }

        if isinstance(mutation, PreparedBatchCreateMutation):
            candidate = _generated_create_candidate(
                mutation=mutation,
                target_path=norm_target,
                generator=generator,
                created_at=created_at,
            )
            operations.append(
                CreateGeneratedFileV2(
                    id=op_id,
                    target_path=norm_target,
                    expected_target_state="absent",
                    generator_id=generator.id,
                    generator_version=generator.version,
                    new_content=candidate,
                )
            )
            create_target_paths.append(norm_target)
            item["kind"] = "create"
            if mutation.content.tag_rationale is not None:
                item["tag_rationale"] = mutation.content.tag_rationale
        else:
            candidate = _build_update_candidate(mutation)
            if mutation.expected_generator_id is not None:
                candidate = _merge_generated_sources(
                    candidate=candidate,
                    sources=mutation.sources,
                    generator=generator,
                    created_at=created_at,
                )
            if candidate == mutation.target_content:
                raise WikiSectionUnchangedError(
                    f"Target already has the proposed content: {norm_target}"
                )
            if mutation.expected_generator_id is not None:
                operations.append(
                    ReplaceGeneratedFileV2(
                        id=op_id,
                        target_path=norm_target,
                        base_hash=mutation.target_content_hash,
                        expected_generator_id=mutation.expected_generator_id,
                        generator_version=generator.version,
                        new_content=candidate,
                    )
                )
            else:
                diff_lines = tuple(
                    difflib.unified_diff(
                        mutation.target_content.splitlines(keepends=True),
                        candidate.splitlines(keepends=True),
                        fromfile=norm_target,
                        tofile=norm_target,
                    )
                )
                operations.append(
                    PatchHumanFile(
                        id=op_id,
                        target_path=norm_target,
                        base_hash=mutation.target_content_hash,
                        unified_diff="".join(diff_lines[2:]),
                    )
                )
            item["kind"] = "update_sections"
            item["headings"] = [section.heading for section in mutation.sections]
            if mutation.tag_rationale is not None:
                item["tag_rationale"] = mutation.tag_rationale
        grounding.append(item)

    document = PatchDocumentV2(
        schema_version=2,
        proposal_id=proposal_id,
        operations=tuple(operations),
    )
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Reconcile {len(sources)} sources into {len(operations)} wiki target(s)",
        description=f"Generated by {generator.id} {generator.version}",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.HIGH if len(operations) > 3 else ProposalRisk.MEDIUM,
        created_at=created_at,
        created_by="agent",
        submitted_at=None,
        submitted_by=None,
        review_digest=None,
        approved_at=None,
        approved_by=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        applied_at=None,
        applied_by=None,
        related_goals=(),
        related_sources=tuple(source.path for source in sources),
        extensions={
            "ingestion": {
                "action": "evolve_wiki_batch",
                "source_count": len(sources),
                "operation_count": len(operations),
                "source_snapshots": [_source_record(source) for source in sources],
                "target_grounding": grounding,
            }
        },
    )
    lines = [
        f"Jointly reconciles {len(sources)} verified source(s) into {len(operations)} target(s).",
        "",
        "Each target is grounded only by the reviewed source subset listed below:",
        "",
    ]
    for index, item in enumerate(grounding, start=1):
        source_records = cast(list[dict[str, str]], item["sources"])
        source_list = ", ".join(f"`{source['path']}`" for source in source_records)
        headings = cast(list[str] | None, item.get("headings"))
        detail = ""
        if headings is not None:
            detail = " sections " + ", ".join(f"`{heading}`" for heading in headings)
        lines.append(
            f"{index}. `{item['target_path']}`{detail} from {source_list}: {item['rationale']}"
        )
        tag_rationale = cast(str | None, item.get("tag_rationale"))
        if tag_rationale is not None:
            lines.append(f"   Tag rationale: {tag_rationale}")
    lines.extend(
        [
            "",
            "The external agent performed semantic reconciliation before this proposal. "
            "LifeOS verifies snapshots, target state, ownership, review history and atomic application.",
        ]
    )
    proposal_markdown = serialize_proposal_markdown(metadata, "\n".join(lines))
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return CompoundingWikiProposalDocuments(
        proposal_id=proposal_id,
        target_paths=tuple(target_paths),
        create_target_paths=tuple(create_target_paths),
        proposal_markdown=proposal_markdown,
        patches_json=serialize_patch_json_bytes(document),
    )


def enforce_multi_source_payload_budget(
    *,
    vault_root: Path,
    patches_json: bytes,
) -> int:
    """Enforce the canonical patch + immutable review snapshot budget before persistence."""
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=vault_root,
        patches_json=patches_json,
    )
    total = len(patches_json) + len(review_json)
    if total > MAX_MULTI_SOURCE_PAYLOAD_BYTES:
        raise MultiSourcePayloadError(
            f"Multi-source patch/review payload exceeds {MAX_MULTI_SOURCE_PAYLOAD_BYTES} bytes"
        )
    return total
