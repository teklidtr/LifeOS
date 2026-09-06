import difflib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.markdown.parser import FenceState, advance_fenced_code_state, parse_markdown_note
from lifeos.wiki.layout import infer_wiki_page_kind
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalStatus,
    ProposalRisk,
)
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import (
    CreateGeneratedFileV2,
    PatchDocumentV2,
    PatchHumanFile,
    ReplaceGeneratedFileV2,
    serialize_patch_json_bytes,
)
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.proposals.publication import (
    ProposalDocuments,
    ProposalPublicationError as SharedProposalPublicationError,
    preflight_proposal_publication,
    publish_proposal_documents,
)
from lifeos.registry.file_tracking import validate_vault_path
from lifeos.ingestion.provenance import (
    provenance_to_frontmatter_value,
    LifeOSProvenance,
    ProvenanceSource,
    ProvenanceGenerator,
)


class WikiTargetExistsError(Exception):
    pass


class ProposalPublicationError(Exception):
    pass


class ProposalAlreadyExistsError(ProposalPublicationError):
    pass


class InvalidWikiTargetError(ValueError):
    pass


class InvalidWikiSectionError(ValueError):
    pass


class WikiSectionUnchangedError(Exception):
    pass


def validate_wiki_target_path(target_path: str) -> str:
    norm_target = str(PurePosixPath(target_path))
    if not norm_target.startswith("wiki/"):
        raise InvalidWikiTargetError(
            f"Target path must be within the canonical wiki area: {target_path}"
        )
    validate_vault_path(target_path)
    return norm_target


def validate_flashcard_target_path(target_path: str) -> str:
    norm_target = str(PurePosixPath(target_path))
    if not norm_target.startswith("flashcards/"):
        raise InvalidWikiTargetError(
            f"Flashcard target path must be within the canonical flashcards area: {target_path}"
        )
    validate_vault_path(target_path)
    if not norm_target.endswith(".md"):
        raise InvalidWikiTargetError("Flashcard targets must be Markdown files")
    return norm_target


@dataclass(frozen=True, slots=True)
class WikiProposalDocuments:
    proposal_id: str
    target_path: str
    proposal_markdown: bytes
    patches_json: bytes


@dataclass(frozen=True, slots=True)
class CompoundWikiProposalDocuments:
    proposal_id: str
    create_target_path: str
    update_target_path: str
    proposal_markdown: bytes
    patches_json: bytes


MAX_COMPOUNDING_WIKI_OPERATIONS = 12


@dataclass(frozen=True, slots=True)
class PreparedWikiCreateMutation:
    target_path: str
    content: WikiProposalContent
    rationale: str


@dataclass(frozen=True, slots=True)
class PreparedWikiSectionUpdateMutation:
    target_path: str
    target_content: str
    target_content_hash: str
    heading: str
    section_body: str
    rationale: str
    expected_generator_id: str | None = None
    proposed_tags: tuple[str, ...] | None = None


PreparedWikiMutation = PreparedWikiCreateMutation | PreparedWikiSectionUpdateMutation


@dataclass(frozen=True, slots=True)
class CompoundingWikiProposalDocuments:
    proposal_id: str
    target_paths: tuple[str, ...]
    create_target_paths: tuple[str, ...]
    proposal_markdown: bytes
    patches_json: bytes


@dataclass(frozen=True, slots=True)
class PreparedFlashcardCreateMutation:
    target_path: str
    card_id: str
    topic: str
    question: str
    answer: str
    rationale: str
    learning_context: str
    knowledge_refs: tuple[str, ...] = ()
    estimated_seconds: int = 30


@dataclass(frozen=True, slots=True)
class StudyLearningProposalDocuments:
    proposal_id: str
    target_paths: tuple[str, ...]
    create_target_paths: tuple[str, ...]
    proposal_markdown: bytes
    patches_json: bytes


class _WikiFrontmatterDumper(yaml.SafeDumper):
    pass


_ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+|$)(.*?)(?:\r?\n)?$")


def _scan_atx_headings(lines: list[str], *, skip_frontmatter: bool) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    in_frontmatter = False
    fence_state: FenceState = None

    for index, line in enumerate(lines):
        clean = line.rstrip("\r\n")
        if skip_frontmatter and index == 0 and clean.lstrip("\ufeff") == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if clean == "---":
                in_frontmatter = False
            continue

        previous_fence = fence_state
        fence_state = advance_fenced_code_state(clean, fence_state)
        if previous_fence != fence_state:
            continue
        if fence_state is not None:
            continue

        match = _ATX_HEADING_RE.match(line)
        if match is None:
            continue
        title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
        headings.append((index, len(match.group(1)), title))

    return headings


def replace_wiki_section(*, target_content: str, heading: str, section_body: str) -> str:
    """Replace one exact ATX-heading section without touching surrounding content."""
    if not isinstance(heading, str) or not heading or heading.isspace():
        raise InvalidWikiSectionError("Heading must be a non-empty string")
    if heading != heading.strip() or "\n" in heading or "\r" in heading:
        raise InvalidWikiSectionError("Heading must be exact and have no surrounding whitespace")
    if heading.startswith("#"):
        raise InvalidWikiSectionError("Heading must not include Markdown # markers")
    if not isinstance(section_body, str) or not section_body or section_body.isspace():
        raise InvalidWikiSectionError("Section body must be a non-empty string")

    lines = target_content.splitlines(keepends=True)
    headings = _scan_atx_headings(lines, skip_frontmatter=True)
    matches = [item for item in headings if item[2] == heading]
    if not matches:
        raise InvalidWikiSectionError(f"Heading was not found: {heading}")
    if len(matches) != 1:
        raise InvalidWikiSectionError(f"Heading is not unique: {heading}")

    heading_index, heading_level, _ = matches[0]
    section_end = len(lines)
    for index, level, _title in headings:
        if index > heading_index and level <= heading_level:
            section_end = index
            break

    normalized_body = section_body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    body_headings = _scan_atx_headings(
        normalized_body.splitlines(keepends=True), skip_frontmatter=False
    )
    if any(level <= heading_level for _index, level, _title in body_headings):
        raise InvalidWikiSectionError("Section body cannot introduce a peer or parent heading")

    heading_line = lines[heading_index]
    if heading_line.endswith("\r\n"):
        newline = "\r\n"
    elif heading_line.endswith("\r"):
        newline = "\r"
    else:
        newline = "\n"
    rendered_body = normalized_body.replace("\n", newline)
    separator = newline + rendered_body + newline
    if section_end < len(lines):
        separator += newline

    prefix = "".join(lines[: heading_index + 1])
    if not heading_line.endswith(("\n", "\r")):
        prefix += newline
    return prefix + separator + "".join(lines[section_end:])


def _represent_string(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if len(data) == 20 and data.endswith("Z") and data[10] == "T":
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_WikiFrontmatterDumper.add_representer(str, _represent_string)


def _serialize_wiki_frontmatter(metadata: dict[str, Any]) -> str:
    rendered = yaml.dump(
        metadata,
        Dumper=_WikiFrontmatterDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    if not rendered.endswith("\n"):
        rendered += "\n"
    return f"---\n{rendered}---\n"


def _format_taxonomy(values: tuple[str, ...]) -> str:
    return (
        ", ".join("`" + value.replace("`", "\\`") + "`" for value in values)
        if values
        else "_(none)_"
    )


def _taxonomy_review(
    *,
    source: SourceSnapshot,
    proposed_tags: tuple[str, ...],
    rationale: str | None,
) -> str:
    return (
        "\n\n## Tag review\n\n"
        f"- Source `tags`: {_format_taxonomy(source.tags)}\n"
        f"- Source `topics`: {_format_taxonomy(source.topics)}\n"
        f"- Proposed canonical wiki `tags`: {_format_taxonomy(proposed_tags)}\n"
        f"- Agent rationale: {rationale or '_(not provided)_'}\n\n"
        "Source taxonomy is input evidence; only the reviewed proposed wiki tags become canonical."
    )


def _replace_generated_wiki_tags(target_content: str, tags: tuple[str, ...]) -> str:
    parsed = parse_markdown_note(Path("generated-wiki.md"), content=target_content)
    if any(finding.severity == "error" for finding in parsed.findings):
        raise InvalidWikiSectionError("Generated wiki frontmatter is malformed")
    metadata = dict(parsed.frontmatter)
    if tags:
        metadata["tags"] = list(tags)
    else:
        metadata.pop("tags", None)
    return _serialize_wiki_frontmatter(metadata) + parsed.body


def _build_generated_wiki_candidate(
    *,
    content: WikiProposalContent,
    source: SourceSnapshot,
    target_path: str,
    created_at: str,
) -> str:
    provenance = LifeOSProvenance(
        schema_version=1,
        sources=(ProvenanceSource(path=source.path, content_hash=source.content_hash),),
        generator=ProvenanceGenerator(
            id=content.generator.id,
            version=content.generator.version,
            prompt_schema_version=content.generator.prompt_schema_version,
            model_id=content.generator.model_id,
        ),
        created_at=created_at,
    )
    page_kind = infer_wiki_page_kind(target_path)
    frontmatter = {
        "title": content.title,
        **({"type": page_kind} if page_kind is not None else {}),
        **({"tags": list(content.tags)} if content.tags else {}),
        "lifeos_provenance": provenance_to_frontmatter_value(provenance),
    }
    candidate = _serialize_wiki_frontmatter(frontmatter) + content.body
    return candidate if candidate.endswith("\n") else candidate + "\n"


def _build_generated_flashcard_candidate(
    *,
    mutation: PreparedFlashcardCreateMutation,
    source: SourceSnapshot,
    generator: ProvenanceGenerator,
    created_at: str,
) -> str:
    provenance = LifeOSProvenance(
        schema_version=1,
        sources=(ProvenanceSource(path=source.path, content_hash=source.content_hash),),
        generator=generator,
        created_at=created_at,
    )
    source_refs = tuple(dict.fromkeys((source.path, *mutation.knowledge_refs)))
    frontmatter = {
        "id": mutation.card_id,
        "type": "flashcard",
        "status": "active",
        "topic": mutation.topic,
        "question": mutation.question,
        "answer": mutation.answer,
        "due": created_at[:10],
        "estimated_seconds": mutation.estimated_seconds,
        "source_refs": list(source_refs),
        "learning_context": mutation.learning_context,
        "selection_rationale": mutation.rationale,
        "lifeos_provenance": provenance_to_frontmatter_value(provenance),
    }
    return _serialize_wiki_frontmatter(frontmatter)


def _build_wiki_section_operation(
    *,
    target_path: str,
    target_content: str,
    target_content_hash: str,
    heading: str,
    section_body: str,
    generator: ProvenanceGenerator,
    expected_generator_id: str | None,
    proposed_tags: tuple[str, ...] | None = None,
) -> PatchHumanFile | ReplaceGeneratedFileV2:
    candidate = replace_wiki_section(
        target_content=target_content,
        heading=heading,
        section_body=section_body,
    )
    if proposed_tags is not None:
        if expected_generator_id is None:
            raise InvalidWikiSectionError("Tags cannot be changed on a human-owned wiki target")
        candidate = _replace_generated_wiki_tags(candidate, proposed_tags)
    if candidate == target_content:
        raise WikiSectionUnchangedError(f"Section already has the proposed content: {heading}")
    if expected_generator_id is not None:
        return ReplaceGeneratedFileV2(
            id="op-update-wiki-section",
            target_path=target_path,
            base_hash=target_content_hash,
            expected_generator_id=expected_generator_id,
            generator_version=generator.version,
            new_content=candidate,
        )
    diff_lines = tuple(
        difflib.unified_diff(
            target_content.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=target_path,
            tofile=target_path,
        )
    )
    return PatchHumanFile(
        id="op-update-wiki-section",
        target_path=target_path,
        base_hash=target_content_hash,
        unified_diff="".join(diff_lines[2:]),
    )


def build_wiki_proposal(
    *,
    content: WikiProposalContent,
    source: SourceSnapshot,
    target_path: str,
    proposal_id: str,
    created_at: str,
) -> WikiProposalDocuments:
    # 1. Validate target
    norm_target = validate_wiki_target_path(target_path)

    # 2. Construct generated candidate Markdown with canonical provenance.
    candidate_markdown = _build_generated_wiki_candidate(
        content=content,
        source=source,
        target_path=norm_target,
        created_at=created_at,
    )

    # 4. Construct Proposal metadata
    # The proposal title identifies the proposed wiki target or draft title
    proposal_title = f"Create {target_path}: {content.title}"
    meta = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=proposal_title,
        description=f"Generated by {content.generator.id} {content.generator.version}",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.LOW,
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
        related_sources=(source.path,),
        extensions={},
    )

    # 5. Serialize proposal markdown
    proposal_body = f"Generates new wiki page at `{norm_target}`." + _taxonomy_review(
        source=source,
        proposed_tags=content.tags,
        rationale=content.tag_rationale,
    )
    proposal_markdown_bytes = serialize_proposal_markdown(meta, proposal_body)
    proposal_markdown_bytes = proposal_markdown_bytes.replace(b"\nreview_digest: null\n", b"\n")

    # 6. Construct and serialize patch
    patch = CreateGeneratedFileV2(
        id="op-create-wiki-page",
        target_path=norm_target,
        expected_target_state="absent",
        generator_id=content.generator.id,
        generator_version=content.generator.version,
        new_content=candidate_markdown,
    )
    doc = PatchDocumentV2(schema_version=2, proposal_id=proposal_id, operations=(patch,))
    patches_json_bytes = serialize_patch_json_bytes(doc)

    return WikiProposalDocuments(
        proposal_id=proposal_id,
        target_path=norm_target,
        proposal_markdown=proposal_markdown_bytes,
        patches_json=patches_json_bytes,
    )


def build_wiki_section_update_proposal(
    *,
    source: SourceSnapshot,
    target_path: str,
    target_content: str,
    target_content_hash: str,
    heading: str,
    section_body: str,
    generator: ProvenanceGenerator,
    proposal_id: str,
    created_at: str,
    expected_generator_id: str | None = None,
    proposed_tags: tuple[str, ...] | None = None,
    tag_rationale: str | None = None,
) -> WikiProposalDocuments:
    norm_target = validate_wiki_target_path(target_path)
    patch = _build_wiki_section_operation(
        target_path=norm_target,
        target_content=target_content,
        target_content_hash=target_content_hash,
        heading=heading,
        section_body=section_body,
        generator=generator,
        expected_generator_id=expected_generator_id,
        proposed_tags=proposed_tags,
    )
    document = PatchDocumentV2(
        schema_version=2,
        proposal_id=proposal_id,
        operations=(patch,),
    )
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Update {norm_target}: {heading}",
        description=f"Generated by {generator.id} {generator.version}",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.MEDIUM,
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
        related_sources=(source.path,),
        extensions={
            "ingestion": {
                "action": "update_wiki_section",
                "source_hash": source.content_hash,
                "target_path": norm_target,
                "heading": heading,
                **({"target_ownership": "generated"} if expected_generator_id is not None else {}),
            }
        },
    )
    if proposed_tags is None:
        change_summary = "All surrounding target content is preserved."
    else:
        change_summary = (
            "The reviewed canonical tags are updated in the same generated-file "
            "replacement; body content outside the selected section is preserved."
        )
    proposal_body = (
        f"Updates the exact `{heading}` section in `{norm_target}` from the registered "
        f"source `{source.path}`. {change_summary}"
    )
    if proposed_tags is not None:
        proposal_body += _taxonomy_review(
            source=source,
            proposed_tags=proposed_tags,
            rationale=tag_rationale,
        )
    proposal_markdown = serialize_proposal_markdown(metadata, proposal_body)
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return WikiProposalDocuments(
        proposal_id=proposal_id,
        target_path=norm_target,
        proposal_markdown=proposal_markdown,
        patches_json=serialize_patch_json_bytes(document),
    )


def build_compound_wiki_proposal(
    *,
    content: WikiProposalContent,
    source: SourceSnapshot,
    create_target_path: str,
    update_target_path: str,
    update_target_content: str,
    update_target_content_hash: str,
    heading: str,
    section_body: str,
    proposal_id: str,
    created_at: str,
    update_expected_generator_id: str | None = None,
) -> CompoundWikiProposalDocuments:
    norm_create_target = validate_wiki_target_path(create_target_path)
    norm_update_target = validate_wiki_target_path(update_target_path)
    if norm_create_target == norm_update_target:
        raise InvalidWikiTargetError("Create and update targets must be different")

    candidate_markdown = _build_generated_wiki_candidate(
        content=content,
        source=source,
        target_path=norm_create_target,
        created_at=created_at,
    )
    create_patch = CreateGeneratedFileV2(
        id="op-create-wiki-page",
        target_path=norm_create_target,
        expected_target_state="absent",
        generator_id=content.generator.id,
        generator_version=content.generator.version,
        new_content=candidate_markdown,
    )
    section_patch = _build_wiki_section_operation(
        target_path=norm_update_target,
        target_content=update_target_content,
        target_content_hash=update_target_content_hash,
        heading=heading,
        section_body=section_body,
        generator=content.generator,
        expected_generator_id=update_expected_generator_id,
    )
    document = PatchDocumentV2(
        schema_version=2,
        proposal_id=proposal_id,
        operations=(create_patch, section_patch),
    )
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=(
            f"Create {norm_create_target}: {content.title}; update {norm_update_target}: {heading}"
        ),
        description=f"Generated by {content.generator.id} {content.generator.version}",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.MEDIUM,
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
        related_sources=(source.path,),
        extensions={
            "ingestion": {
                "action": "create_wiki_and_update_section",
                "source_hash": source.content_hash,
                "create_target_path": norm_create_target,
                "update_target_path": norm_update_target,
                "heading": heading,
                **(
                    {"update_target_ownership": "generated"}
                    if update_expected_generator_id is not None
                    else {}
                ),
            }
        },
    )
    proposal_body = (
        f"Creates the detailed wiki page `{norm_create_target}` and updates the exact "
        f"`{heading}` section in `{norm_update_target}` from the registered source "
        f"`{source.path}`. Both changes remain one atomic proposal."
        + _taxonomy_review(
            source=source,
            proposed_tags=content.tags,
            rationale=content.tag_rationale,
        )
    )
    proposal_markdown = serialize_proposal_markdown(metadata, proposal_body)
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return CompoundWikiProposalDocuments(
        proposal_id=proposal_id,
        create_target_path=norm_create_target,
        update_target_path=norm_update_target,
        proposal_markdown=proposal_markdown,
        patches_json=serialize_patch_json_bytes(document),
    )


def build_compounding_wiki_proposal(
    *,
    source: SourceSnapshot,
    mutations: tuple[PreparedWikiMutation, ...],
    generator: ProvenanceGenerator,
    proposal_id: str,
    created_at: str,
) -> CompoundingWikiProposalDocuments:
    """Build one bounded, inspectable proposal that may touch several wiki notes."""
    if not 1 <= len(mutations) <= MAX_COMPOUNDING_WIKI_OPERATIONS:
        raise InvalidWikiTargetError(
            f"Compounding ingestion requires 1..{MAX_COMPOUNDING_WIKI_OPERATIONS} mutations"
        )

    operations: list[CreateGeneratedFileV2 | PatchHumanFile | ReplaceGeneratedFileV2] = []
    target_paths: list[str] = []
    create_target_paths: list[str] = []
    review_items: list[dict[str, str]] = []
    seen_targets: set[str] = set()

    for index, mutation in enumerate(mutations, start=1):
        norm_target = validate_wiki_target_path(mutation.target_path)
        if not norm_target.endswith(".md"):
            raise InvalidWikiTargetError("Compounding wiki targets must be Markdown files")
        if norm_target in seen_targets:
            raise InvalidWikiTargetError(
                f"Compounding ingestion cannot touch one target twice: {norm_target}"
            )
        if not isinstance(mutation.rationale, str) or not mutation.rationale.strip():
            raise InvalidWikiTargetError("Every compounding mutation requires a rationale")
        if mutation.rationale != mutation.rationale.strip() or len(mutation.rationale) > 500:
            raise InvalidWikiTargetError(
                "Mutation rationale must be trimmed and at most 500 characters"
            )
        seen_targets.add(norm_target)
        target_paths.append(norm_target)
        op_id = f"op-wiki-{index:02d}"

        if isinstance(mutation, PreparedWikiCreateMutation):
            candidate = _build_generated_wiki_candidate(
                content=mutation.content,
                source=source,
                target_path=norm_target,
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
            review_items.append(
                {
                    "kind": "create",
                    "target_path": norm_target,
                    "rationale": mutation.rationale,
                }
            )
            continue

        operation = _build_wiki_section_operation(
            target_path=norm_target,
            target_content=mutation.target_content,
            target_content_hash=mutation.target_content_hash,
            heading=mutation.heading,
            section_body=mutation.section_body,
            generator=generator,
            expected_generator_id=mutation.expected_generator_id,
            proposed_tags=mutation.proposed_tags,
        )
        # Give every operation a proposal-unique stable id rather than the helper's
        # single-operation compatibility id.
        if isinstance(operation, ReplaceGeneratedFileV2):
            operation = ReplaceGeneratedFileV2(
                id=op_id,
                target_path=operation.target_path,
                base_hash=operation.base_hash,
                expected_generator_id=operation.expected_generator_id,
                generator_version=operation.generator_version,
                new_content=operation.new_content,
            )
        else:
            operation = PatchHumanFile(
                id=op_id,
                target_path=operation.target_path,
                base_hash=operation.base_hash,
                unified_diff=operation.unified_diff,
            )
        operations.append(operation)
        review_items.append(
            {
                "kind": "update_section",
                "target_path": norm_target,
                "heading": mutation.heading,
                "rationale": mutation.rationale,
            }
        )

    document = PatchDocumentV2(
        schema_version=2,
        proposal_id=proposal_id,
        operations=tuple(operations),
    )
    risk = ProposalRisk.MEDIUM if len(operations) <= 3 else ProposalRisk.HIGH
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Evolve wiki from {source.path} ({len(operations)} changes)",
        description=f"Generated by {generator.id} {generator.version}",
        status=ProposalStatus.DRAFT,
        risk=risk,
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
        related_sources=(source.path,),
        extensions={
            "ingestion": {
                "action": "evolve_wiki",
                "source_hash": source.content_hash,
                "operation_count": len(operations),
                "mutations": review_items,
            }
        },
    )
    lines = [
        f"Proposes {len(operations)} durable wiki change(s) from the registered source "
        f"`{source.path}`.",
        "",
        "The external agent selected these targets after inspecting existing knowledge:",
        "",
    ]
    for index, item in enumerate(review_items, start=1):
        if item["kind"] == "create":
            lines.append(f"{index}. Create `{item['target_path']}`: {item['rationale']}")
        else:
            lines.append(
                f"{index}. Update `{item['target_path']}` section `{item['heading']}`: "
                f"{item['rationale']}"
            )
    lines.extend(
        [
            "",
            "Folder names are agent-selected organization, not a LifeOS ontology. "
            "All changes remain one reviewed atomic proposal.",
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


def build_study_learning_proposal(
    *,
    source: SourceSnapshot,
    wiki_mutations: tuple[PreparedWikiMutation, ...],
    flashcard_mutations: tuple[PreparedFlashcardCreateMutation, ...],
    generator: ProvenanceGenerator,
    proposal_id: str,
    created_at: str,
) -> StudyLearningProposalDocuments:
    """Build one bounded study draft spanning durable knowledge and retrieval practice."""
    total = len(wiki_mutations) + len(flashcard_mutations)
    if not 1 <= total <= MAX_COMPOUNDING_WIKI_OPERATIONS:
        raise InvalidWikiTargetError(
            f"Study learning evolution requires 1..{MAX_COMPOUNDING_WIKI_OPERATIONS} mutations"
        )

    operations: list[CreateGeneratedFileV2 | PatchHumanFile | ReplaceGeneratedFileV2] = []
    target_paths: list[str] = []
    create_target_paths: list[str] = []
    review_lines: list[str] = []
    review_items: list[dict[str, str]] = []
    seen: set[str] = set()

    for mutation in wiki_mutations:
        norm_target = validate_wiki_target_path(mutation.target_path)
        if not norm_target.endswith(".md"):
            raise InvalidWikiTargetError("Study wiki targets must be Markdown files")
        if norm_target in seen:
            raise InvalidWikiTargetError(
                f"Study evolution cannot touch one target twice: {norm_target}"
            )
        rationale = mutation.rationale
        if (
            not isinstance(rationale, str)
            or not rationale.strip()
            or rationale != rationale.strip()
            or len(rationale) > 500
        ):
            raise InvalidWikiTargetError(
                "Every study mutation needs a trimmed rationale of at most 500 characters"
            )
        seen.add(norm_target)
        target_paths.append(norm_target)
        op_id = f"op-study-{len(operations) + 1:02d}"
        if isinstance(mutation, PreparedWikiCreateMutation):
            candidate = _build_generated_wiki_candidate(
                content=mutation.content,
                source=source,
                target_path=norm_target,
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
            review_lines.append(f"Create wiki `{norm_target}`: {rationale}")
            review_items.append(
                {"kind": "wiki_create", "target_path": norm_target, "rationale": rationale}
            )
        else:
            operation = _build_wiki_section_operation(
                target_path=norm_target,
                target_content=mutation.target_content,
                target_content_hash=mutation.target_content_hash,
                heading=mutation.heading,
                section_body=mutation.section_body,
                generator=generator,
                expected_generator_id=mutation.expected_generator_id,
                proposed_tags=mutation.proposed_tags,
            )
            if isinstance(operation, ReplaceGeneratedFileV2):
                operation = ReplaceGeneratedFileV2(
                    id=op_id,
                    target_path=operation.target_path,
                    base_hash=operation.base_hash,
                    expected_generator_id=operation.expected_generator_id,
                    generator_version=operation.generator_version,
                    new_content=operation.new_content,
                )
            else:
                operation = PatchHumanFile(
                    id=op_id,
                    target_path=operation.target_path,
                    base_hash=operation.base_hash,
                    unified_diff=operation.unified_diff,
                )
            operations.append(operation)
            review_lines.append(
                f"Update wiki `{norm_target}` section `{mutation.heading}`: {rationale}"
            )
            review_items.append(
                {
                    "kind": "wiki_update_section",
                    "target_path": norm_target,
                    "heading": mutation.heading,
                    "rationale": rationale,
                }
            )

    for flashcard_mutation in flashcard_mutations:
        norm_target = validate_flashcard_target_path(flashcard_mutation.target_path)
        if norm_target in seen:
            raise InvalidWikiTargetError(
                f"Study evolution cannot touch one target twice: {norm_target}"
            )
        for field_name in (
            "card_id",
            "topic",
            "question",
            "answer",
            "rationale",
            "learning_context",
        ):
            value = getattr(flashcard_mutation, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise InvalidWikiTargetError(
                    f"Flashcard {field_name} must be a trimmed non-empty string"
                )
        if (
            len(flashcard_mutation.rationale) > 500
            or len(flashcard_mutation.learning_context) > 300
        ):
            raise InvalidWikiTargetError("Flashcard rationale/context exceeds the bounded size")
        if (
            type(flashcard_mutation.estimated_seconds) is not int
            or not 1 <= flashcard_mutation.estimated_seconds <= 3600
        ):
            raise InvalidWikiTargetError("Flashcard estimated_seconds must be 1..3600")
        for ref in flashcard_mutation.knowledge_refs:
            validate_wiki_target_path(ref)
        seen.add(norm_target)
        target_paths.append(norm_target)
        create_target_paths.append(norm_target)
        op_id = f"op-study-{len(operations) + 1:02d}"
        candidate = _build_generated_flashcard_candidate(
            mutation=flashcard_mutation, source=source, generator=generator, created_at=created_at
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
        review_lines.append(
            f"Create flashcard `{norm_target}` ({flashcard_mutation.learning_context}): {flashcard_mutation.rationale}"
        )
        review_items.append(
            {
                "kind": "flashcard_create",
                "target_path": norm_target,
                "learning_context": flashcard_mutation.learning_context,
                "rationale": flashcard_mutation.rationale,
            }
        )

    document = PatchDocumentV2(
        schema_version=2, proposal_id=proposal_id, operations=tuple(operations)
    )
    risk = ProposalRisk.MEDIUM if total <= 3 else ProposalRisk.HIGH
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Evolve study learning from {source.path} ({total} changes)",
        description=f"Generated by {generator.id} {generator.version}",
        status=ProposalStatus.DRAFT,
        risk=risk,
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
        related_sources=(source.path,),
        extensions={
            "ingestion": {
                "action": "evolve_study_learning",
                "source_hash": source.content_hash,
                "operation_count": total,
                "mutations": review_items,
            }
        },
    )
    body = [
        f"Proposes {total} learning change(s) from the registered study source `{source.path}`.",
        "",
        "The external agent selected durable wiki changes and retrieval-practice cards "
        "using vault context:",
        "",
    ]
    body.extend(f"{index}. {line}" for index, line in enumerate(review_lines, start=1))
    body.extend(
        [
            "",
            "LifeOS validates bounded mutations and provenance; the agent, not deterministic code, "
            "decides what is pedagogically important for the inferred learning context.",
        ]
    )
    proposal_markdown = serialize_proposal_markdown(metadata, "\n".join(body))
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return StudyLearningProposalDocuments(
        proposal_id=proposal_id,
        target_paths=tuple(target_paths),
        create_target_paths=tuple(create_target_paths),
        proposal_markdown=proposal_markdown,
        patches_json=serialize_patch_json_bytes(document),
    )


def _raise_ingestion_publication_error(
    *, error: SharedProposalPublicationError, proposal_dir: Path
) -> None:
    if error.code == "proposal_exists":
        raise ProposalAlreadyExistsError(
            f"Proposal directory already exists: {proposal_dir}"
        ) from error
    if error.code == "unsafe_proposal_id":
        raise ProposalPublicationError("Proposal id is not safe for publication") from error
    if error.code == "unsafe_proposals_root":
        raise ProposalPublicationError("Proposal root is not a safe directory") from error
    raise ProposalPublicationError(f"Failed to write proposal files: {error}") from error


def _persist_proposal_documents(
    *,
    proposals_root: Path,
    documents: (
        WikiProposalDocuments
        | CompoundWikiProposalDocuments
        | CompoundingWikiProposalDocuments
        | StudyLearningProposalDocuments
    ),
) -> Path:
    proposal_id = str(documents.proposal_id)
    proposal_dir = proposals_root / proposal_id
    if proposals_root.name != "proposals":
        raise ProposalPublicationError("Proposal root must be the canonical proposals directory")
    try:
        preflight_proposal_publication(vault_root=proposals_root.parent, proposal_id=proposal_id)
    except SharedProposalPublicationError as error:
        _raise_ingestion_publication_error(error=error, proposal_dir=proposal_dir)

    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=proposals_root.parent,
        patches_json=documents.patches_json,
    )
    try:
        publish_proposal_documents(
            vault_root=proposals_root.parent,
            proposal_id=proposal_id,
            documents=ProposalDocuments(
                documents.proposal_markdown, documents.patches_json, review_json
            ),
        )
    except SharedProposalPublicationError as error:
        _raise_ingestion_publication_error(error=error, proposal_dir=proposal_dir)
    return proposal_dir


def persist_wiki_proposal(
    *,
    proposals_root: Path,
    documents: WikiProposalDocuments,
) -> Path:
    # Advisory existence check (using proposals_root.parent to reach vault root)
    vault_root = proposals_root.parent
    if (vault_root / documents.target_path).exists():
        raise WikiTargetExistsError(f"Target path already exists: {documents.target_path}")

    return _persist_proposal_documents(proposals_root=proposals_root, documents=documents)


def persist_wiki_section_update_proposal(
    *,
    proposals_root: Path,
    documents: WikiProposalDocuments,
    runtime_dir: Path | None = None,
) -> Path:
    return _persist_proposal_documents(proposals_root=proposals_root, documents=documents)


def persist_compound_wiki_proposal(
    *,
    proposals_root: Path,
    documents: CompoundWikiProposalDocuments,
    runtime_dir: Path | None = None,
) -> Path:
    vault_root = proposals_root.parent
    if (vault_root / documents.create_target_path).exists():
        raise WikiTargetExistsError(f"Target path already exists: {documents.create_target_path}")
    return _persist_proposal_documents(proposals_root=proposals_root, documents=documents)


def persist_compounding_wiki_proposal(
    *,
    proposals_root: Path,
    documents: CompoundingWikiProposalDocuments,
    runtime_dir: Path | None = None,
) -> Path:
    vault_root = proposals_root.parent
    for target_path in documents.create_target_paths:
        if (vault_root / target_path).exists():
            raise WikiTargetExistsError(f"Target path already exists: {target_path}")
    return _persist_proposal_documents(proposals_root=proposals_root, documents=documents)


def persist_study_learning_proposal(
    *,
    proposals_root: Path,
    documents: StudyLearningProposalDocuments,
    runtime_dir: Path | None = None,
) -> Path:
    vault_root = proposals_root.parent
    for target_path in documents.create_target_paths:
        if (vault_root / target_path).exists():
            raise WikiTargetExistsError(f"Target path already exists: {target_path}")
    return _persist_proposal_documents(proposals_root=proposals_root, documents=documents)
