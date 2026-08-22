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
    ToolOwnershipConflictError,
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
    build_compound_wiki_proposal,
    build_wiki_section_update_proposal,
    build_wiki_proposal,
    persist_compound_wiki_proposal,
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
from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry.file_tracking import hash_file_content
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.ownership import (
    DEFAULT_OWNERSHIP_MANIFEST_PATH,
    GeneratedOwnership,
    ManifestEntry,
    ManifestError,
    PathSafetyError,
)


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

COMPOUND_WIKI_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="ingestion.create_wiki_and_update_section_proposal",
    description=(
        "Create one reviewable draft that adds a wiki page and updates one "
        "existing wiki section."
    ),
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


@dataclass(frozen=True, slots=True)
class CompoundWikiProposalRequest:
    source_path: str
    create_target_path: str
    create_title: str
    create_body: str
    update_target_path: str
    update_heading: str
    update_body: str

    def __post_init__(self) -> None:
        CreateWikiProposalRequest(
            source_path=self.source_path,
            target_path=self.create_target_path,
            title=self.create_title,
            body=self.create_body,
        )
        UpdateWikiSectionProposalRequest(
            source_path=self.source_path,
            target_path=self.update_target_path,
            heading=self.update_heading,
            body=self.update_body,
        )
        if self.create_target_path == self.update_target_path:
            raise ValueError("create and update targets must be different")


@dataclass(frozen=True, slots=True)
class CompoundWikiProposalResult:
    proposal_id: str
    proposal_path: str
    create_target_path: str
    update_target_path: str
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


def _load_generated_ownership(*, vault_root: Path) -> GeneratedOwnership:
    manifest_path = vault_root / DEFAULT_OWNERSHIP_MANIFEST_PATH
    if not manifest_path.exists():
        raise ToolValidationError("Generated ownership manifest is missing")
    try:
        return GeneratedOwnership.load(manifest_path, vault_root)
    except (ManifestError, PathSafetyError) as e:
        raise ToolValidationError("Generated ownership manifest is invalid") from e


def _check_create_target_ownership(
    *,
    vault_root: Path,
    target_path: str,
    ownership: GeneratedOwnership,
) -> None:
    if target_path not in ownership.entries:
        return
    if (vault_root / target_path).exists():
        raise ToolOwnershipConflictError(
            "Wiki target is generated-owned and already exists; use the "
            "section-update ingestion tool"
        )
    raise ToolOwnershipConflictError(
        "Wiki target is missing but retains generated ownership; restore the "
        "file or release ownership before creating it again"
    )


def _classify_update_target_ownership(
    *,
    target_path: str,
    target_content: bytes,
    ownership: GeneratedOwnership,
) -> ManifestEntry | None:
    entry = ownership.entries.get(target_path)
    if entry is None:
        return None
    if entry.generator_id != GENERATOR_ID:
        raise ToolOwnershipConflictError(
            "Generated wiki target is owned by a different generator and cannot "
            "be updated by this ingestion tool"
        )
    if entry.content_hash != hash_file_content(target_content):
        raise ToolOwnershipConflictError(
            "Generated wiki target content does not match its ownership record; "
            "restore or explicitly reconcile ownership before ingestion"
        )
    return entry


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

    try:
        target_path = validate_wiki_target_path(request.target_path)
    except (FileTrackingError, InvalidWikiTargetError) as e:
        raise ToolValidationError("Invalid wiki target path") from e
    ownership = _load_generated_ownership(vault_root=vault_root)
    _check_create_target_ownership(
        vault_root=vault_root,
        target_path=target_path,
        ownership=ownership,
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
            target_path=target_path,
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

    ownership = _load_generated_ownership(vault_root=vault_root)
    ownership_entry = ownership.entries.get(target_path)

    try:
        target = read_vault_markdown(vault_root, target_path)
    except VaultAccessError as e:
        if e.code == "not-found":
            if ownership_entry is not None:
                raise ToolOwnershipConflictError(
                    "Wiki target is missing but retains generated ownership; restore "
                    "the file or release ownership before updating it"
                ) from e
            raise ToolNotFoundError("Wiki target is missing") from e
        if e.code in {"invalid-path", "invalid-extension"}:
            raise ToolValidationError("Invalid wiki target path") from e
        raise ToolExecutionError("Could not read wiki target") from e

    ownership_entry = _classify_update_target_ownership(
        target_path=target_path,
        target_content=target.content_bytes,
        ownership=ownership,
    )
    if ownership_entry is None and parse_markdown_note(
        Path(target_path), content=target.content
    ).managed_blocks:
        raise ToolValidationError(
            "Wiki update target contains managed blocks and cannot use a human patch"
        )

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
            expected_generator_id=(
                ownership_entry.generator_id if ownership_entry is not None else None
            ),
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


def create_wiki_and_update_section_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: CompoundWikiProposalRequest,
    clock_fn: Callable[[], datetime] = _utc_now,
    random_suffix_fn: Callable[[], str] = _random_suffix,
) -> CompoundWikiProposalResult:
    verified = _load_verified_source(
        vault_root=vault_root,
        registry=registry,
        source_path=request.source_path,
    )

    try:
        create_target_path = validate_wiki_target_path(request.create_target_path)
        update_target_path = validate_wiki_target_path(request.update_target_path)
    except (FileTrackingError, InvalidWikiTargetError) as e:
        raise ToolValidationError("Invalid wiki target path") from e
    if create_target_path == update_target_path:
        raise ToolValidationError("Create and update targets must be different")

    ownership = _load_generated_ownership(vault_root=vault_root)
    _check_create_target_ownership(
        vault_root=vault_root,
        target_path=create_target_path,
        ownership=ownership,
    )
    update_ownership_entry = ownership.entries.get(update_target_path)

    try:
        update_target = read_vault_markdown(vault_root, update_target_path)
    except VaultAccessError as e:
        if e.code == "not-found":
            if update_ownership_entry is not None:
                raise ToolOwnershipConflictError(
                    "Wiki update target is missing but retains generated ownership; "
                    "restore the file or release ownership before updating it"
                ) from e
            raise ToolNotFoundError("Wiki update target is missing") from e
        if e.code in {"invalid-path", "invalid-extension"}:
            raise ToolValidationError("Invalid wiki update target path") from e
        raise ToolExecutionError("Could not read wiki update target") from e
    update_ownership_entry = _classify_update_target_ownership(
        target_path=update_target_path,
        target_content=update_target.content_bytes,
        ownership=ownership,
    )
    if update_ownership_entry is None and parse_markdown_note(
        Path(update_target_path), content=update_target.content
    ).managed_blocks:
        raise ToolValidationError(
            "Wiki update target contains managed blocks and cannot use a human patch"
        )

    generator = ProvenanceGenerator(
        id=GENERATOR_ID,
        version=GENERATOR_VERSION,
        prompt_schema_version=REQUEST_SCHEMA_VERSION,
        model_id=None,
    )
    content = WikiProposalContent(
        title=request.create_title,
        body=request.create_body,
        generator=generator,
    )
    now = clock_fn()
    proposal_id = generate_proposal_id(
        clock_fn=lambda: now,
        random_suffix_fn=random_suffix_fn,
    )
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_target_hash = f"sha256:{hash_file_content(update_target.content_bytes)}"

    try:
        documents = build_compound_wiki_proposal(
            content=content,
            source=verified.source,
            create_target_path=create_target_path,
            update_target_path=update_target_path,
            update_target_content=update_target.content,
            update_target_content_hash=update_target_hash,
            heading=request.update_heading,
            section_body=request.update_body,
            proposal_id=proposal_id,
            created_at=created_at,
            update_expected_generator_id=(
                update_ownership_entry.generator_id
                if update_ownership_entry is not None
                else None
            ),
        )
    except InvalidWikiSectionError as e:
        raise ToolValidationError("Invalid or ambiguous wiki section") from e
    except InvalidWikiTargetError as e:
        raise ToolValidationError("Invalid wiki target path") from e
    except WikiSectionUnchangedError as e:
        raise ToolConflictError("Wiki section already has the proposed content") from e

    try:
        persisted_path = persist_compound_wiki_proposal(
            proposals_root=vault_root / "proposals",
            documents=documents,
        )
    except WikiTargetExistsError as e:
        raise ToolConflictError("Wiki create target already exists") from e
    except ProposalAlreadyExistsError as e:
        raise ToolConflictError("Draft proposal already exists") from e
    except ProposalPublicationError as e:
        raise ToolExecutionError("Could not publish draft proposal") from e

    return CompoundWikiProposalResult(
        proposal_id=proposal_id,
        proposal_path=persisted_path.relative_to(vault_root).as_posix(),
        create_target_path=documents.create_target_path,
        update_target_path=documents.update_target_path,
        heading=request.update_heading,
        status="draft",
    )
