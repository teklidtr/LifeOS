import difflib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import yaml
import shutil
import os
import re

from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
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
    serialize_patch_json_bytes,
)
from lifeos.registry.file_tracking import validate_vault_path
from lifeos.ingestion.provenance import provenance_to_frontmatter_value, LifeOSProvenance, ProvenanceSource, ProvenanceGenerator
from lifeos._atomic_write import atomic_write_file_secure

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
        raise InvalidWikiTargetError(f"Target path must be within the canonical wiki area: {target_path}")
    validate_vault_path(target_path)
    return norm_target

@dataclass(frozen=True, slots=True)
class WikiProposalDocuments:
    proposal_id: str
    target_path: str
    proposal_markdown: bytes
    patches_json: bytes

class _WikiFrontmatterDumper(yaml.SafeDumper):
    pass


_ATX_HEADING_RE = re.compile(
    r"^[ \t]{0,3}(#{1,6})(?:[ \t]+|$)(.*?)(?:\r?\n)?$"
)
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _scan_atx_headings(
    lines: list[str], *, skip_frontmatter: bool
) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    in_frontmatter = False
    in_fence = False
    fence_char = ""
    fence_length = 0

    for index, line in enumerate(lines):
        clean = line.rstrip("\r\n")
        if skip_frontmatter and index == 0 and clean.lstrip("\ufeff") == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if clean == "---":
                in_frontmatter = False
            continue

        fence = _FENCE_RE.match(clean)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
            continue
        if in_fence:
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
        raise InvalidWikiSectionError(
            "Section body cannot introduce a peer or parent heading"
        )

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
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='|')
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
    
    
    # 2. Build canonical provenance
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
    
    # 3. Construct candidate markdown
    frontmatter = {
        "title": content.title,
        "lifeos_provenance": provenance_to_frontmatter_value(provenance),
    }
    candidate_markdown = _serialize_wiki_frontmatter(frontmatter) + content.body
    if not candidate_markdown.endswith("\n"):
        candidate_markdown += "\n"

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
    proposal_markdown_bytes = serialize_proposal_markdown(meta, f"Generates new wiki page at `{norm_target}`.")
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
    doc = PatchDocumentV2(
        schema_version=2,
        proposal_id=proposal_id,
        operations=(patch,)
    )
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
) -> WikiProposalDocuments:
    norm_target = validate_wiki_target_path(target_path)
    candidate = replace_wiki_section(
        target_content=target_content,
        heading=heading,
        section_body=section_body,
    )
    if candidate == target_content:
        raise WikiSectionUnchangedError(f"Section already has the proposed content: {heading}")

    diff_lines = tuple(
        difflib.unified_diff(
            target_content.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=norm_target,
            tofile=norm_target,
        )
    )
    unified_diff = "".join(diff_lines[2:])
    patch = PatchHumanFile(
        id="op-update-wiki-section",
        target_path=norm_target,
        base_hash=target_content_hash,
        unified_diff=unified_diff,
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
            }
        },
    )
    proposal_body = (
        f"Updates the exact `{heading}` section in `{norm_target}` from the registered "
        f"source `{source.path}`. All surrounding target content is preserved."
    )
    proposal_markdown = serialize_proposal_markdown(metadata, proposal_body)
    proposal_markdown = proposal_markdown.replace(b"\nreview_digest: null\n", b"\n")
    return WikiProposalDocuments(
        proposal_id=proposal_id,
        target_path=norm_target,
        proposal_markdown=proposal_markdown,
        patches_json=serialize_patch_json_bytes(document),
    )


def _persist_proposal_documents(
    *, proposals_root: Path, documents: WikiProposalDocuments
) -> Path:
    proposal_dir = proposals_root / documents.proposal_id
    proposal_created = False
    publication_complete = False
    dir_fd = -1

    try:
        try:
            proposal_dir.mkdir(parents=False, exist_ok=False)
            proposal_created = True
        except FileExistsError as e:
            raise ProposalAlreadyExistsError(
                f"Proposal directory already exists: {proposal_dir}"
            ) from e

        try:
            dir_fd = os.open(proposal_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            atomic_write_file_secure(dir_fd, "proposal.md", documents.proposal_markdown)
            atomic_write_file_secure(dir_fd, "patches.json", documents.patches_json)
            publication_complete = True
        except OSError as e:
            raise ProposalPublicationError(f"Failed to write proposal files: {e}") from e
    finally:
        if dir_fd != -1:
            os.close(dir_fd)
        if proposal_created and not publication_complete:
            shutil.rmtree(proposal_dir, ignore_errors=True)

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
    *, proposals_root: Path, documents: WikiProposalDocuments
) -> Path:
    return _persist_proposal_documents(proposals_root=proposals_root, documents=documents)
