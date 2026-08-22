import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Callable

from lifeos.registry import Registry
from lifeos.registry.file_tracking import FileTrackingError
from lifeos.facade.models import (
    ToolDescriptor,
    ToolEffect,
)
from lifeos.facade.errors import (
    ToolValidationError,
    ToolConflictError,
    ToolNotFoundError,
    ToolExecutionError,
)
from lifeos.ingestion.orchestration import (
    load_registered_source,
    MissingSourceError,
    UnregisteredSourceError,
    ModifiedSourceError,
    SourceReadError,
    VerifiedRegisteredSource,
)
from lifeos.ingestion.proposals import (
    build_wiki_section_update_proposal,
    build_wiki_proposal,
    persist_wiki_section_update_proposal,
    persist_wiki_proposal,
    InvalidWikiSectionError,
    InvalidWikiTargetError,
    WikiTargetExistsError,
    WikiSectionUnchangedError,
    ProposalAlreadyExistsError,
    ProposalPublicationError,
    validate_wiki_target_path,
)
from lifeos.proposals.schema import generate_proposal_id
from lifeos.ingestion.drafts import WikiProposalContent
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.registry.file_tracking import hash_file_content
from lifeos.vault import VaultAccessError, read_vault_markdown


CREATE_WIKI_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="ingestion.create_wiki_proposal",
    description="Create a reviewable draft wiki proposal from a verified source.",
    effect=ToolEffect.PROPOSAL_PRODUCING,
)

UPDATE_WIKI_SECTION_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="ingestion.update_wiki_section_proposal",
    description="Create a reviewable draft proposal for one existing wiki section.",
    effect=ToolEffect.PROPOSAL_PRODUCING,
)

GENERATOR_ID = "lifeos.facade.external_agent"
GENERATOR_VERSION = "1"
# REQUEST_SCHEMA_VERSION versions the external-agent supplied content request contract.
REQUEST_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class CreateWikiProposalRequest:
    source_path: str
    target_path: str
    title: str
    body: str

    def __post_init__(self) -> None:
        if not isinstance(self.title, str):
            raise TypeError("title must be a string")
        if not self.title or self.title.isspace():
            raise ValueError("title cannot be empty or whitespace-only")
        if self.title != self.title.strip():
            raise ValueError("title cannot have surrounding whitespace")
        
        if not isinstance(self.body, str):
            raise TypeError("body must be a string")
        if not self.body or self.body.isspace():
            raise ValueError("body cannot be empty or whitespace-only")


@dataclass(frozen=True, slots=True)
class CreateWikiProposalResult:
    proposal_id: str
    proposal_path: str
    target_path: str
    status: Literal["draft"]


@dataclass(frozen=True, slots=True)
class UpdateWikiSectionProposalRequest:
    source_path: str
    target_path: str
    heading: str
    body: str

    def __post_init__(self) -> None:
        if not isinstance(self.heading, str):
            raise TypeError("heading must be a string")
        if not self.heading or self.heading.isspace():
            raise ValueError("heading cannot be empty or whitespace-only")
        if self.heading != self.heading.strip():
            raise ValueError("heading cannot have surrounding whitespace")
        if "\n" in self.heading or "\r" in self.heading:
            raise ValueError("heading must be one line")
        if self.heading.startswith("#"):
            raise ValueError("heading must not include Markdown # markers")

        if not isinstance(self.body, str):
            raise TypeError("body must be a string")
        if not self.body or self.body.isspace():
            raise ValueError("body cannot be empty or whitespace-only")


@dataclass(frozen=True, slots=True)
class UpdateWikiSectionProposalResult:
    proposal_id: str
    proposal_path: str
    target_path: str
    heading: str
    status: Literal["draft"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _random_suffix() -> str:
    return secrets.token_hex(4)


def _load_verified_source(
    *, vault_root: Path, registry: Registry, source_path: str
) -> VerifiedRegisteredSource:
    try:
        return load_registered_source(
            registry=registry,
            vault_root=vault_root,
            source_path=source_path,
        )
    except FileTrackingError as e:
        raise ToolValidationError("Invalid source path") from e
    except UnregisteredSourceError as e:
        raise ToolValidationError("Source is not registered") from e
    except ModifiedSourceError as e:
        raise ToolConflictError("Registered source has changed") from e
    except MissingSourceError as e:
        raise ToolNotFoundError("Registered source is missing") from e
    except SourceReadError as e:
        raise ToolExecutionError("Could not read registered source") from e


def create_wiki_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: CreateWikiProposalRequest,
    clock_fn: Callable[[], datetime] = _utc_now,
    random_suffix_fn: Callable[[], str] = _random_suffix,
) -> CreateWikiProposalResult:
    # 1. Load and verify source
    verified = _load_verified_source(
        vault_root=vault_root,
        registry=registry,
        source_path=request.source_path,
    )

    # 2. Construct LifeOS-owned generator
    generator = ProvenanceGenerator(
        id=GENERATOR_ID,
        version=GENERATOR_VERSION,
        prompt_schema_version=REQUEST_SCHEMA_VERSION,
        model_id=None,
    )

    # 3. Construct bounded proposal content from the external agent fields.
    content = WikiProposalContent(
        title=request.title,
        body=request.body,
        generator=generator,
    )

    # 4. Call clock exactly once
    now = clock_fn()

    # 5. Generate proposal ID
    proposal_id = generate_proposal_id(
        clock_fn=lambda: now,
        random_suffix_fn=random_suffix_fn,
    )

    # 6. Derive canonical created_at
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 7. Build wiki proposal
    try:
        documents = build_wiki_proposal(
            content=content,
            source=verified.source,
            target_path=request.target_path,
            proposal_id=proposal_id,
            created_at=created_at,
        )
    except InvalidWikiTargetError as e:
        raise ToolValidationError("Invalid wiki target path") from e

    # 8. Persist wiki proposal
    proposals_root = vault_root / "proposals"
    try:
        persisted_path = persist_wiki_proposal(
            proposals_root=proposals_root,
            documents=documents,
        )
    except WikiTargetExistsError as e:
        raise ToolConflictError("Wiki target already exists") from e
    except ProposalAlreadyExistsError as e:
        raise ToolConflictError("Draft proposal already exists") from e
    except ProposalPublicationError as e:
        raise ToolExecutionError("Could not publish draft proposal") from e

    # 9. Return vault-relative result
    proposal_path = persisted_path.relative_to(vault_root).as_posix()
    
    return CreateWikiProposalResult(
        proposal_id=proposal_id,
        proposal_path=proposal_path,
        target_path=documents.target_path,
        status="draft",
    )


def update_wiki_section_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: UpdateWikiSectionProposalRequest,
    clock_fn: Callable[[], datetime] = _utc_now,
    random_suffix_fn: Callable[[], str] = _random_suffix,
) -> UpdateWikiSectionProposalResult:
    verified = _load_verified_source(
        vault_root=vault_root,
        registry=registry,
        source_path=request.source_path,
    )

    try:
        target_path = validate_wiki_target_path(request.target_path)
    except (FileTrackingError, InvalidWikiTargetError) as e:
        raise ToolValidationError("Invalid wiki target path") from e

    try:
        target = read_vault_markdown(vault_root, target_path)
    except VaultAccessError as e:
        if e.code == "not-found":
            raise ToolNotFoundError("Wiki target is missing") from e
        if e.code in {"invalid-path", "invalid-extension"}:
            raise ToolValidationError("Invalid wiki target path") from e
        raise ToolExecutionError("Could not read wiki target") from e

    generator = ProvenanceGenerator(
        id=GENERATOR_ID,
        version=GENERATOR_VERSION,
        prompt_schema_version=REQUEST_SCHEMA_VERSION,
        model_id=None,
    )
    now = clock_fn()
    proposal_id = generate_proposal_id(
        clock_fn=lambda: now,
        random_suffix_fn=random_suffix_fn,
    )
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    target_hash = f"sha256:{hash_file_content(target.content_bytes)}"

    try:
        documents = build_wiki_section_update_proposal(
            source=verified.source,
            target_path=target_path,
            target_content=target.content,
            target_content_hash=target_hash,
            heading=request.heading,
            section_body=request.body,
            generator=generator,
            proposal_id=proposal_id,
            created_at=created_at,
        )
    except InvalidWikiSectionError as e:
        raise ToolValidationError("Invalid or ambiguous wiki section") from e
    except WikiSectionUnchangedError as e:
        raise ToolConflictError("Wiki section already has the proposed content") from e

    try:
        persisted_path = persist_wiki_section_update_proposal(
            proposals_root=vault_root / "proposals",
            documents=documents,
        )
    except ProposalAlreadyExistsError as e:
        raise ToolConflictError("Draft proposal already exists") from e
    except ProposalPublicationError as e:
        raise ToolExecutionError("Could not publish draft proposal") from e

    return UpdateWikiSectionProposalResult(
        proposal_id=proposal_id,
        proposal_path=persisted_path.relative_to(vault_root).as_posix(),
        target_path=documents.target_path,
        heading=request.heading,
        status="draft",
    )
