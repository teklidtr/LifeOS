"""Facade contract for one atomic multi-source knowledge-ingestion batch."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, NoReturn, cast

from lifeos.facade.errors import (
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolOwnershipConflictError,
    ToolValidationError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.facade.proposal_tools import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    REQUEST_SCHEMA_VERSION,
    _check_create_target_ownership,
    _classify_update_target_ownership,
    _load_generated_ownership,
    _load_verified_source,
    _resolve_create_wiki_target,
    _validate_mutation_rationale,
)
from lifeos.ingestion.drafts import SourceSnapshot, WikiProposalContent
from lifeos.ingestion.multi_source import (
    MAX_MULTI_SOURCE_SOURCES,
    MAX_MULTI_SOURCE_TARGETS,
    MultiSourcePayloadError,
    PreparedBatchCreateMutation,
    PreparedBatchSection,
    PreparedBatchUpdateMutation,
    build_multi_source_wiki_proposal,
    enforce_multi_source_payload_budget,
)
from lifeos.ingestion.orchestration import VerifiedRegisteredSource
from lifeos.ingestion.proposals import (
    InvalidWikiSectionError,
    InvalidWikiTargetError,
    ProposalAlreadyExistsError,
    ProposalPublicationError,
    WikiSectionUnchangedError,
    WikiTargetExistsError,
    persist_compounding_wiki_proposal,
    validate_wiki_target_path,
)
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.markdown.parser import parse_markdown_note
from lifeos.ownership import GeneratedOwnership
from lifeos.registry import Registry
from lifeos.registry.file_tracking import FileTrackingError, hash_file_content
from lifeos.proposals.review_snapshot import ReviewSnapshotError
from lifeos.proposals.schema import generate_proposal_id
from lifeos.proposals.target_identity import ProposalTargetStaleError
from lifeos.vault import VaultAccessError, read_vault_markdown


EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="ingestion.evolve_wiki_batch_proposal",
    description=(
        "Create one target-reconciled draft from several jointly reasoned registered sources."
    ),
    effect=ToolEffect.PROPOSAL_PRODUCING,
)


@dataclass(frozen=True, slots=True)
class BatchSourceSnapshotRequest:
    path: str
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or self.path != self.path.strip():
            raise ValueError("source snapshot path must be a trimmed non-empty string")
        if (
            not isinstance(self.content_hash, str)
            or not self.content_hash.startswith("sha256:")
            or len(self.content_hash) != 71
            or any(char not in "0123456789abcdef" for char in self.content_hash[7:])
        ):
            raise ValueError("source snapshot content_hash must be sha256:<64 lowercase hex>")


@dataclass(frozen=True, slots=True)
class BatchWikiSectionRequest:
    heading: str
    body: str

    def __post_init__(self) -> None:
        if not isinstance(self.heading, str) or not self.heading.strip():
            raise ValueError("heading must be a non-empty string")
        if self.heading != self.heading.strip() or "\n" in self.heading or "\r" in self.heading:
            raise ValueError("heading must be one trimmed line")
        if self.heading.startswith("#"):
            raise ValueError("heading must not include Markdown # markers")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ValueError("body must be a non-empty string")


@dataclass(frozen=True, slots=True)
class BatchWikiCreateRequest:
    target_path: str
    title: str
    body: str
    rationale: str
    source_paths: tuple[str, ...]
    tags: tuple[str, ...] = ()
    tag_rationale: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip() or self.title != self.title.strip():
            raise ValueError("title must be a trimmed non-empty string")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ValueError("body must be a non-empty string")
        object.__setattr__(self, "rationale", _validate_mutation_rationale(self.rationale))
        if not self.source_paths or len(set(self.source_paths)) != len(self.source_paths):
            raise ValueError("source_paths must contain distinct grounding sources")
        from lifeos.facade.proposal_tools import CreateWikiProposalRequest

        validated = CreateWikiProposalRequest(
            source_path="batch-validation",
            target_path=self.target_path,
            title=self.title,
            body=self.body,
            tags=self.tags,
            tag_rationale=self.tag_rationale,
        )
        object.__setattr__(self, "tags", validated.tags)
        object.__setattr__(self, "tag_rationale", validated.tag_rationale)


@dataclass(frozen=True, slots=True)
class BatchWikiUpdateRequest:
    target_path: str
    sections: tuple[BatchWikiSectionRequest, ...]
    rationale: str
    source_paths: tuple[str, ...]
    tags: tuple[str, ...] | None = None
    tag_rationale: str | None = None

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("sections must contain at least one exact section replacement")
        headings = [section.heading for section in self.sections]
        if len(set(headings)) != len(headings):
            raise ValueError("sections must not repeat a heading")
        object.__setattr__(self, "rationale", _validate_mutation_rationale(self.rationale))
        if not self.source_paths or len(set(self.source_paths)) != len(self.source_paths):
            raise ValueError("source_paths must contain distinct grounding sources")
        from lifeos.facade.proposal_tools import UpdateWikiSectionProposalRequest

        first = self.sections[0]
        validated = UpdateWikiSectionProposalRequest(
            source_path="batch-validation",
            target_path=self.target_path,
            heading=first.heading,
            body=first.body,
            tags=self.tags,
            tag_rationale=self.tag_rationale,
        )
        object.__setattr__(self, "tags", validated.tags)
        object.__setattr__(self, "tag_rationale", validated.tag_rationale)


@dataclass(frozen=True, slots=True)
class EvolveWikiBatchProposalRequest:
    source_snapshots: tuple[BatchSourceSnapshotRequest, ...]
    creates: tuple[BatchWikiCreateRequest, ...] = ()
    updates: tuple[BatchWikiUpdateRequest, ...] = ()

    @property
    def source_paths(self) -> tuple[str, ...]:
        return tuple(snapshot.path for snapshot in self.source_snapshots)

    def __post_init__(self) -> None:
        if not 1 <= len(self.source_snapshots) <= MAX_MULTI_SOURCE_SOURCES:
            raise ValueError(
                f"multi-source ingestion requires 1..{MAX_MULTI_SOURCE_SOURCES} source snapshots"
            )
        if len(set(self.source_paths)) != len(self.source_snapshots):
            raise ValueError("source snapshot paths must be distinct")
        target_count = len(self.creates) + len(self.updates)
        if not 1 <= target_count <= MAX_MULTI_SOURCE_TARGETS:
            raise ValueError(
                f"multi-source ingestion requires 1..{MAX_MULTI_SOURCE_TARGETS} targets"
            )
        targets = [item.target_path for item in self.creates]
        targets.extend(item.target_path for item in self.updates)
        if len(set(targets)) != len(targets):
            raise ValueError("batch mutations must be reconciled to distinct target paths")
        allowed = set(self.source_paths)
        for create_item in self.creates:
            missing = [path for path in create_item.source_paths if path not in allowed]
            if missing:
                raise ValueError("target grounding source must belong to the requested batch")
        for update_item in self.updates:
            missing = [path for path in update_item.source_paths if path not in allowed]
            if missing:
                raise ValueError("target grounding source must belong to the requested batch")


@dataclass(frozen=True, slots=True)
class EvolveWikiBatchProposalResult:
    proposal_id: str
    proposal_path: str
    target_paths: tuple[str, ...]
    operation_count: int
    status: Literal["draft"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _random_suffix() -> str:
    return secrets.token_hex(4)


def _grounding_sources(
    paths: tuple[str, ...], snapshots: dict[str, SourceSnapshot]
) -> tuple[SourceSnapshot, ...]:
    try:
        return tuple(snapshots[path] for path in paths)
    except KeyError as error:
        raise ToolValidationError("Target grounding contains an unverified source") from error


def _load_observed_sources(
    *,
    vault_root: Path,
    registry: Registry,
    expected: tuple[BatchSourceSnapshotRequest, ...],
) -> tuple[VerifiedRegisteredSource, ...]:
    verified: list[VerifiedRegisteredSource] = []
    for snapshot in expected:
        item = _load_verified_source(
            vault_root=vault_root,
            registry=registry,
            source_path=snapshot.path,
        )
        if item.source.content_hash != snapshot.content_hash:
            raise ToolConflictError(
                "A registered batch source no longer matches the version read during exploration"
            )
        verified.append(item)
    return tuple(verified)


def _read_update_target(
    *,
    vault_root: Path,
    target_path: str,
    ownership: GeneratedOwnership,
) -> tuple[str, bytes, str | None]:
    try:
        normalized = validate_wiki_target_path(target_path)
    except (FileTrackingError, InvalidWikiTargetError) as error:
        raise ToolValidationError("Invalid wiki update target path") from error
    ownership_entry = ownership.entries.get(normalized)
    try:
        target = read_vault_markdown(vault_root, normalized)
    except VaultAccessError as error:
        if error.code == "not-found":
            if ownership_entry is not None:
                raise ToolOwnershipConflictError(
                    "Wiki update target is missing but retains generated ownership; restore "
                    "the file or release ownership before updating it"
                ) from error
            raise ToolNotFoundError("Wiki update target is missing") from error
        if error.code in {"invalid-path", "invalid-extension"}:
            raise ToolValidationError("Invalid wiki update target path") from error
        raise ToolExecutionError("Could not read wiki update target") from error
    ownership_entry = _classify_update_target_ownership(
        target_path=normalized,
        target_content=target.content_bytes,
        ownership=ownership,
    )
    if ownership_entry is None and parse_markdown_note(
        Path(normalized), content=target.content
    ).managed_blocks:
        raise ToolValidationError(
            "Wiki update target contains managed blocks and cannot use a human patch"
        )
    return (
        target.content,
        target.content_bytes,
        ownership_entry.generator_id if ownership_entry is not None else None,
    )


def _map_review_snapshot_error(error: ReviewSnapshotError) -> NoReturn:
    if error.code == "stale_base_hash":
        raise ToolConflictError("A batch target changed before proposal publication") from error
    raise ToolExecutionError("Could not build multi-source review snapshot") from error


def _map_publication_error(error: ProposalPublicationError) -> NoReturn:
    if isinstance(error.__cause__, ProposalTargetStaleError):
        raise ToolConflictError("A batch target changed before proposal publication") from error
    raise ToolExecutionError("Could not publish multi-source draft proposal") from error


def evolve_wiki_batch_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: EvolveWikiBatchProposalRequest,
    runtime_dir: Path | None = None,
    clock_fn: Callable[[], datetime] = _utc_now,
    random_suffix_fn: Callable[[], str] = _random_suffix,
) -> EvolveWikiBatchProposalResult:
    """Verify a whole batch and persist at most one operation for each reconciled target."""
    verified = _load_observed_sources(
        vault_root=vault_root,
        registry=registry,
        expected=request.source_snapshots,
    )
    snapshots = {item.source.path: item.source for item in verified}
    ownership = _load_generated_ownership(vault_root=vault_root)
    generator = ProvenanceGenerator(
        id=GENERATOR_ID,
        version=GENERATOR_VERSION,
        prompt_schema_version=REQUEST_SCHEMA_VERSION,
        model_id=None,
    )
    prepared: list[PreparedBatchCreateMutation | PreparedBatchUpdateMutation] = []

    for create_item in request.creates:
        target_path = _resolve_create_wiki_target(
            target_path=create_item.target_path,
            page_kind=None,
            slug=None,
        )
        _check_create_target_ownership(
            vault_root=vault_root,
            target_path=target_path,
            ownership=ownership,
        )
        prepared.append(
            PreparedBatchCreateMutation(
                target_path=target_path,
                content=WikiProposalContent(
                    title=create_item.title,
                    body=create_item.body,
                    generator=generator,
                    tags=create_item.tags,
                    tag_rationale=create_item.tag_rationale,
                ),
                rationale=create_item.rationale,
                sources=_grounding_sources(create_item.source_paths, snapshots),
            )
        )

    for update_item in request.updates:
        content, content_bytes, expected_generator_id = _read_update_target(
            vault_root=vault_root,
            target_path=update_item.target_path,
            ownership=ownership,
        )
        if update_item.tags is not None and expected_generator_id is None:
            raise ToolValidationError("Ingestion cannot change tags on a human-owned wiki target")
        prepared.append(
            PreparedBatchUpdateMutation(
                target_path=update_item.target_path,
                target_content=content,
                target_content_hash=f"sha256:{hash_file_content(content_bytes)}",
                sections=tuple(
                    PreparedBatchSection(heading=section.heading, body=section.body)
                    for section in update_item.sections
                ),
                rationale=update_item.rationale,
                sources=_grounding_sources(update_item.source_paths, snapshots),
                expected_generator_id=expected_generator_id,
                proposed_tags=update_item.tags,
                tag_rationale=update_item.tag_rationale,
            )
        )

    now = clock_fn()
    proposal_id = generate_proposal_id(clock_fn=lambda: now, random_suffix_fn=random_suffix_fn)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        documents = build_multi_source_wiki_proposal(
            sources=tuple(item.source for item in verified),
            mutations=tuple(prepared),
            generator=generator,
            proposal_id=proposal_id,
            created_at=created_at,
        )
        enforce_multi_source_payload_budget(
            vault_root=vault_root,
            patches_json=documents.patches_json,
        )
    except ReviewSnapshotError as error:
        _map_review_snapshot_error(error)
    except (InvalidWikiSectionError, InvalidWikiTargetError, MultiSourcePayloadError) as error:
        raise ToolValidationError(str(error)) from error
    except WikiSectionUnchangedError as error:
        raise ToolConflictError("A batch target already has the proposed content") from error

    def verify_sources_before_publish() -> None:
        final_verified = _load_observed_sources(
            vault_root=vault_root,
            registry=registry,
            expected=request.source_snapshots,
        )
        if tuple(item.source for item in final_verified) != tuple(item.source for item in verified):
            raise ToolConflictError("A registered batch source changed before proposal publication")

    persist_batch = cast(Callable[..., Path], persist_compounding_wiki_proposal)
    try:
        persisted = persist_batch(
            proposals_root=vault_root / "proposals",
            documents=documents,
            runtime_dir=runtime_dir,
            before_publish=verify_sources_before_publish,
        )
    except ReviewSnapshotError as error:
        _map_review_snapshot_error(error)
    except WikiTargetExistsError as error:
        raise ToolConflictError("A proposed batch create target already exists") from error
    except ProposalAlreadyExistsError as error:
        raise ToolConflictError("Draft proposal already exists") from error
    except ProposalPublicationError as error:
        _map_publication_error(error)

    return EvolveWikiBatchProposalResult(
        proposal_id=proposal_id,
        proposal_path=persisted.relative_to(vault_root).as_posix(),
        target_paths=documents.target_paths,
        operation_count=len(documents.target_paths),
        status="draft",
    )
