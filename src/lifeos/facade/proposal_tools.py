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
    MAX_COMPOUNDING_WIKI_OPERATIONS,
    PreparedWikiCreateMutation,
    PreparedWikiSectionUpdateMutation,
    PreparedFlashcardCreateMutation,
    build_compounding_wiki_proposal,
    build_study_learning_proposal,
    build_compound_wiki_proposal,
    build_wiki_section_update_proposal,
    build_wiki_proposal,
    persist_compounding_wiki_proposal,
    persist_study_learning_proposal,
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
    validate_flashcard_target_path,
)
from lifeos.proposals.schema import generate_proposal_id
from lifeos.ingestion.drafts import WikiProposalContent
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.wiki.layout import (
    WikiLayoutError,
    WikiPageKind,
    typed_wiki_target,
)
from lifeos.ingestion.taxonomy import (
    TagValidationError,
    validate_proposed_tags,
    validate_tag_rationale,
)
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

EVOLVE_WIKI_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="ingestion.evolve_wiki_proposal",
    description=(
        "Create one bounded atomic draft containing several agent-selected wiki "
        "creations and exact-section updates."
    ),
    effect=ToolEffect.PROPOSAL_PRODUCING,
)

STUDY_EVOLVE_LEARNING_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="study.evolve_learning_proposal",
    description=(
        "Create one bounded atomic draft from a registered study source, combining "
        "agent-selected wiki evolution with selective generated flashcards."
    ),
    effect=ToolEffect.PROPOSAL_PRODUCING,
)

GENERATOR_ID = "lifeos.facade.external_agent"
GENERATOR_VERSION = "1"
# REQUEST_SCHEMA_VERSION versions the external-agent supplied content request contract.
REQUEST_SCHEMA_VERSION = "4"


@dataclass(frozen=True, slots=True)
class CreateWikiProposalRequest:
    source_path: str
    target_path: str | None
    title: str
    body: str
    tags: tuple[str, ...] = ()
    tag_rationale: str | None = None
    page_kind: WikiPageKind | None = None
    slug: str | None = None

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
        try:
            object.__setattr__(self, "tags", validate_proposed_tags(self.tags))
            object.__setattr__(
                self,
                "tag_rationale",
                validate_tag_rationale(self.tag_rationale),
            )
            if (self.page_kind is None) != (self.slug is None):
                raise WikiLayoutError("page_kind and slug must be supplied together")
            if self.page_kind is not None and self.slug is not None:
                typed_wiki_target(self.page_kind, self.slug)
            if self.target_path is None and self.page_kind is None:
                raise WikiLayoutError("target_path or page_kind+slug is required")
        except (TagValidationError, WikiLayoutError) as error:
            raise ValueError(str(error)) from error


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
    tags: tuple[str, ...] | None = None
    tag_rationale: str | None = None

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
        try:
            if self.tags is not None:
                object.__setattr__(self, "tags", validate_proposed_tags(self.tags))
            object.__setattr__(
                self,
                "tag_rationale",
                validate_tag_rationale(self.tag_rationale),
            )
        except TagValidationError as error:
            raise ValueError(str(error)) from error
        if self.tags is None and self.tag_rationale is not None:
            raise ValueError("tag_rationale requires an explicit tags list")


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
    create_target_path: str | None
    create_title: str
    create_body: str
    update_target_path: str
    update_heading: str
    update_body: str
    create_tags: tuple[str, ...] = ()
    create_tag_rationale: str | None = None
    create_page_kind: WikiPageKind | None = None
    create_slug: str | None = None

    def __post_init__(self) -> None:
        CreateWikiProposalRequest(
            source_path=self.source_path,
            target_path=self.create_target_path,
            title=self.create_title,
            body=self.create_body,
            tags=self.create_tags,
            tag_rationale=self.create_tag_rationale,
            page_kind=self.create_page_kind,
            slug=self.create_slug,
        )
        UpdateWikiSectionProposalRequest(
            source_path=self.source_path,
            target_path=self.update_target_path,
            heading=self.update_heading,
            body=self.update_body,
        )
        if (
            self.create_target_path is not None
            and self.create_target_path == self.update_target_path
        ):
            raise ValueError("create and update targets must be different")
        try:
            object.__setattr__(
                self,
                "create_tags",
                validate_proposed_tags(self.create_tags),
            )
            object.__setattr__(
                self,
                "create_tag_rationale",
                validate_tag_rationale(self.create_tag_rationale),
            )
        except TagValidationError as error:
            raise ValueError(str(error)) from error


@dataclass(frozen=True, slots=True)
class CompoundWikiProposalResult:
    proposal_id: str
    proposal_path: str
    create_target_path: str
    update_target_path: str
    heading: str
    status: Literal["draft"]


def _validate_mutation_rationale(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("rationale must be a string")
    if not value or value.isspace():
        raise ValueError("rationale cannot be empty or whitespace-only")
    if value != value.strip():
        raise ValueError("rationale cannot have surrounding whitespace")
    if len(value) > 500:
        raise ValueError("rationale cannot exceed 500 characters")
    return value


@dataclass(frozen=True, slots=True)
class EvolveWikiCreateRequest:
    target_path: str
    title: str
    body: str
    rationale: str
    tags: tuple[str, ...] = ()
    tag_rationale: str | None = None

    def __post_init__(self) -> None:
        validated = CreateWikiProposalRequest(
            source_path="compat-validation",
            target_path=self.target_path,
            title=self.title,
            body=self.body,
            tags=self.tags,
            tag_rationale=self.tag_rationale,
        )
        object.__setattr__(self, "tags", validated.tags)
        object.__setattr__(self, "tag_rationale", validated.tag_rationale)
        object.__setattr__(self, "rationale", _validate_mutation_rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class EvolveWikiUpdateRequest:
    target_path: str
    heading: str
    body: str
    rationale: str
    tags: tuple[str, ...] | None = None
    tag_rationale: str | None = None

    def __post_init__(self) -> None:
        validated = UpdateWikiSectionProposalRequest(
            source_path="compat-validation",
            target_path=self.target_path,
            heading=self.heading,
            body=self.body,
            tags=self.tags,
            tag_rationale=self.tag_rationale,
        )
        object.__setattr__(self, "tags", validated.tags)
        object.__setattr__(self, "tag_rationale", validated.tag_rationale)
        object.__setattr__(self, "rationale", _validate_mutation_rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class EvolveWikiProposalRequest:
    source_path: str
    creates: tuple[EvolveWikiCreateRequest, ...] = ()
    updates: tuple[EvolveWikiUpdateRequest, ...] = ()

    def __post_init__(self) -> None:
        operation_count = len(self.creates) + len(self.updates)
        if not 1 <= operation_count <= MAX_COMPOUNDING_WIKI_OPERATIONS:
            raise ValueError(
                f"evolve_wiki requires 1..{MAX_COMPOUNDING_WIKI_OPERATIONS} mutations"
            )
        targets = [item.target_path for item in (*self.creates, *self.updates)]
        if len(set(targets)) != len(targets):
            raise ValueError("evolve_wiki mutations must use distinct target paths")


@dataclass(frozen=True, slots=True)
class EvolveWikiProposalResult:
    proposal_id: str
    proposal_path: str
    target_paths: tuple[str, ...]
    operation_count: int
    status: Literal["draft"]


@dataclass(frozen=True, slots=True)
class StudyFlashcardCreateRequest:
    target_path: str
    card_id: str
    topic: str
    question: str
    answer: str
    rationale: str
    learning_context: str
    knowledge_refs: tuple[str, ...] = ()
    estimated_seconds: int = 30

    def __post_init__(self) -> None:
        for field_name in (
            "target_path", "card_id", "topic", "question", "answer", "learning_context"
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{field_name} must be a trimmed non-empty string")
        object.__setattr__(self, "rationale", _validate_mutation_rationale(self.rationale))
        if len(self.learning_context) > 300:
            raise ValueError("learning_context cannot exceed 300 characters")
        if type(self.estimated_seconds) is not int or not 1 <= self.estimated_seconds <= 3600:
            raise ValueError("estimated_seconds must be an integer from 1 to 3600")
        if len(set(self.knowledge_refs)) != len(self.knowledge_refs):
            raise ValueError("knowledge_refs must not contain duplicates")
        for ref in self.knowledge_refs:
            if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
                raise ValueError("knowledge_refs must contain trimmed non-empty strings")


@dataclass(frozen=True, slots=True)
class EvolveStudyLearningProposalRequest:
    source_path: str
    wiki_creates: tuple[EvolveWikiCreateRequest, ...] = ()
    wiki_updates: tuple[EvolveWikiUpdateRequest, ...] = ()
    flashcards: tuple[StudyFlashcardCreateRequest, ...] = ()

    def __post_init__(self) -> None:
        count = len(self.wiki_creates) + len(self.wiki_updates) + len(self.flashcards)
        if not 1 <= count <= MAX_COMPOUNDING_WIKI_OPERATIONS:
            raise ValueError(
                f"study learning evolution requires 1..{MAX_COMPOUNDING_WIKI_OPERATIONS} mutations"
            )
        targets = [
            item.target_path
            for item in (*self.wiki_creates, *self.wiki_updates, *self.flashcards)
        ]
        if len(set(targets)) != len(targets):
            raise ValueError("study learning mutations must use distinct target paths")


@dataclass(frozen=True, slots=True)
class EvolveStudyLearningProposalResult:
    proposal_id: str
    proposal_path: str
    target_paths: tuple[str, ...]
    operation_count: int
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
            "Generated target already exists and retains generated ownership"
        )
    raise ToolOwnershipConflictError(
        "Generated target is missing but retains generated ownership; restore the "
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


def _resolve_create_wiki_target(
    *,
    target_path: str | None,
    page_kind: WikiPageKind | None,
    slug: str | None,
) -> str:
    try:
        if page_kind is None and slug is None:
            if target_path is None:
                raise WikiLayoutError("target_path or page_kind+slug is required")
            return validate_wiki_target_path(target_path)
        if page_kind is None or slug is None:
            raise WikiLayoutError("page_kind and slug must be supplied together")
        derived = typed_wiki_target(page_kind, slug)
        if target_path is None:
            return derived
        explicit = validate_wiki_target_path(target_path)
        if explicit != derived:
            raise WikiLayoutError(
                f"target_path must match the typed wiki target {derived}"
            )
        return derived
    except (FileTrackingError, InvalidWikiTargetError, WikiLayoutError) as error:
        raise ToolValidationError("Invalid wiki target path or typed routing") from error


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

    target_path = _resolve_create_wiki_target(
        target_path=request.target_path,
        page_kind=request.page_kind,
        slug=request.slug,
    )
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
        tags=request.tags,
        tag_rationale=request.tag_rationale,
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
    if request.tags is not None and ownership_entry is None:
        raise ToolValidationError(
            "Ingestion cannot change tags on a human-owned wiki target"
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
            proposed_tags=request.tags,
            tag_rationale=request.tag_rationale,
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

    create_target_path = _resolve_create_wiki_target(
        target_path=request.create_target_path,
        page_kind=request.create_page_kind,
        slug=request.create_slug,
    )
    try:
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
        tags=request.create_tags,
        tag_rationale=request.create_tag_rationale,
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



def evolve_wiki_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: EvolveWikiProposalRequest,
    clock_fn: Callable[[], datetime] = _utc_now,
    random_suffix_fn: Callable[[], str] = _random_suffix,
) -> EvolveWikiProposalResult:
    """Create one reviewed draft for a bounded set of agent-selected wiki changes."""
    verified = _load_verified_source(
        vault_root=vault_root,
        registry=registry,
        source_path=request.source_path,
    )
    ownership = _load_generated_ownership(vault_root=vault_root)
    generator = ProvenanceGenerator(
        id=GENERATOR_ID,
        version=GENERATOR_VERSION,
        prompt_schema_version=REQUEST_SCHEMA_VERSION,
        model_id=None,
    )

    prepared: list[PreparedWikiCreateMutation | PreparedWikiSectionUpdateMutation] = []
    for item in request.creates:
        target_path = _resolve_create_wiki_target(
            target_path=item.target_path,
            page_kind=None,
            slug=None,
        )
        if not target_path.endswith(".md"):
            raise ToolValidationError("Wiki create target must be a Markdown file")
        _check_create_target_ownership(
            vault_root=vault_root,
            target_path=target_path,
            ownership=ownership,
        )
        prepared.append(
            PreparedWikiCreateMutation(
                target_path=target_path,
                content=WikiProposalContent(
                    title=item.title,
                    body=item.body,
                    generator=generator,
                    tags=item.tags,
                    tag_rationale=item.tag_rationale,
                ),
                rationale=item.rationale,
            )
        )

    for item in request.updates:
        try:
            target_path = validate_wiki_target_path(item.target_path)
        except (FileTrackingError, InvalidWikiTargetError) as error:
            raise ToolValidationError("Invalid wiki update target path") from error
        if not target_path.endswith(".md"):
            raise ToolValidationError("Wiki update target must be a Markdown file")
        ownership_entry = ownership.entries.get(target_path)
        try:
            target = read_vault_markdown(vault_root, target_path)
        except VaultAccessError as error:
            if error.code == "not-found":
                if ownership_entry is not None:
                    raise ToolOwnershipConflictError(
                        "Wiki update target is missing but retains generated ownership; "
                        "restore the file or release ownership before updating it"
                    ) from error
                raise ToolNotFoundError("Wiki update target is missing") from error
            if error.code in {"invalid-path", "invalid-extension"}:
                raise ToolValidationError("Invalid wiki update target path") from error
            raise ToolExecutionError("Could not read wiki update target") from error
        ownership_entry = _classify_update_target_ownership(
            target_path=target_path,
            target_content=target.content_bytes,
            ownership=ownership,
        )
        if item.tags is not None and ownership_entry is None:
            raise ToolValidationError(
                "Ingestion cannot change tags on a human-owned wiki target"
            )
        if ownership_entry is None and parse_markdown_note(
            Path(target_path), content=target.content
        ).managed_blocks:
            raise ToolValidationError(
                "Wiki update target contains managed blocks and cannot use a human patch"
            )
        prepared.append(
            PreparedWikiSectionUpdateMutation(
                target_path=target_path,
                target_content=target.content,
                target_content_hash=f"sha256:{hash_file_content(target.content_bytes)}",
                heading=item.heading,
                section_body=item.body,
                rationale=item.rationale,
                expected_generator_id=(
                    ownership_entry.generator_id if ownership_entry is not None else None
                ),
                proposed_tags=item.tags,
            )
        )

    now = clock_fn()
    proposal_id = generate_proposal_id(
        clock_fn=lambda: now,
        random_suffix_fn=random_suffix_fn,
    )
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        documents = build_compounding_wiki_proposal(
            source=verified.source,
            mutations=tuple(prepared),
            generator=generator,
            proposal_id=proposal_id,
            created_at=created_at,
        )
    except (InvalidWikiSectionError, InvalidWikiTargetError) as error:
        raise ToolValidationError(str(error)) from error
    except WikiSectionUnchangedError as error:
        raise ToolConflictError("Wiki section already has the proposed content") from error

    try:
        persisted_path = persist_compounding_wiki_proposal(
            proposals_root=vault_root / "proposals",
            documents=documents,
        )
    except WikiTargetExistsError as error:
        raise ToolConflictError("A proposed wiki create target already exists") from error
    except ProposalAlreadyExistsError as error:
        raise ToolConflictError("Draft proposal already exists") from error
    except ProposalPublicationError as error:
        raise ToolExecutionError("Could not publish draft proposal") from error

    return EvolveWikiProposalResult(
        proposal_id=proposal_id,
        proposal_path=persisted_path.relative_to(vault_root).as_posix(),
        target_paths=documents.target_paths,
        operation_count=len(documents.target_paths),
        status="draft",
    )


def evolve_study_learning_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: EvolveStudyLearningProposalRequest,
    clock_fn: Callable[[], datetime] = _utc_now,
    random_suffix_fn: Callable[[], str] = _random_suffix,
) -> EvolveStudyLearningProposalResult:
    """Create one reviewed study draft spanning wiki knowledge and selected flashcards."""
    verified = _load_verified_source(
        vault_root=vault_root, registry=registry, source_path=request.source_path
    )
    if not verified.source.path.startswith("study/"):
        raise ToolValidationError(
            "Context-aware flashcard evolution requires a registered source under study/"
        )

    ownership = _load_generated_ownership(vault_root=vault_root)
    generator = ProvenanceGenerator(
        id=GENERATOR_ID, version=GENERATOR_VERSION,
        prompt_schema_version=REQUEST_SCHEMA_VERSION, model_id=None,
    )
    prepared_wiki: list[PreparedWikiCreateMutation | PreparedWikiSectionUpdateMutation] = []

    for item in request.wiki_creates:
        target_path = _resolve_create_wiki_target(
            target_path=item.target_path, page_kind=None, slug=None
        )
        _check_create_target_ownership(
            vault_root=vault_root, target_path=target_path, ownership=ownership
        )
        prepared_wiki.append(PreparedWikiCreateMutation(
            target_path=target_path,
            content=WikiProposalContent(
                title=item.title, body=item.body, generator=generator,
                tags=item.tags, tag_rationale=item.tag_rationale,
            ),
            rationale=item.rationale,
        ))

    for item in request.wiki_updates:
        try:
            target_path = validate_wiki_target_path(item.target_path)
        except (FileTrackingError, InvalidWikiTargetError) as error:
            raise ToolValidationError("Invalid wiki update target path") from error
        ownership_entry = ownership.entries.get(target_path)
        try:
            target = read_vault_markdown(vault_root, target_path)
        except VaultAccessError as error:
            if error.code == "not-found":
                if ownership_entry is not None:
                    raise ToolOwnershipConflictError(
                        "Wiki update target is missing but retains generated ownership"
                    ) from error
                raise ToolNotFoundError("Wiki update target is missing") from error
            if error.code in {"invalid-path", "invalid-extension"}:
                raise ToolValidationError("Invalid wiki update target path") from error
            raise ToolExecutionError("Could not read wiki update target") from error
        ownership_entry = _classify_update_target_ownership(
            target_path=target_path, target_content=target.content_bytes, ownership=ownership
        )
        if item.tags is not None and ownership_entry is None:
            raise ToolValidationError(
                "Study ingestion cannot change tags on a human-owned wiki target"
            )
        if ownership_entry is None and parse_markdown_note(
            Path(target_path), content=target.content
        ).managed_blocks:
            raise ToolValidationError(
                "Wiki update target contains managed blocks and cannot use a human patch"
            )
        prepared_wiki.append(PreparedWikiSectionUpdateMutation(
            target_path=target_path, target_content=target.content,
            target_content_hash=f"sha256:{hash_file_content(target.content_bytes)}",
            heading=item.heading, section_body=item.body, rationale=item.rationale,
            expected_generator_id=(
                ownership_entry.generator_id if ownership_entry is not None else None
            ),
            proposed_tags=item.tags,
        ))

    prepared_cards: list[PreparedFlashcardCreateMutation] = []
    for item in request.flashcards:
        try:
            target_path = validate_flashcard_target_path(item.target_path)
            for ref in item.knowledge_refs:
                validate_wiki_target_path(ref)
        except (FileTrackingError, InvalidWikiTargetError) as error:
            raise ToolValidationError("Invalid flashcard target or knowledge reference") from error
        _check_create_target_ownership(
            vault_root=vault_root, target_path=target_path, ownership=ownership
        )
        prepared_cards.append(PreparedFlashcardCreateMutation(
            target_path=target_path, card_id=item.card_id, topic=item.topic,
            question=item.question, answer=item.answer, rationale=item.rationale,
            learning_context=item.learning_context, knowledge_refs=item.knowledge_refs,
            estimated_seconds=item.estimated_seconds,
        ))

    now = clock_fn()
    proposal_id = generate_proposal_id(clock_fn=lambda: now, random_suffix_fn=random_suffix_fn)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        documents = build_study_learning_proposal(
            source=verified.source, wiki_mutations=tuple(prepared_wiki),
            flashcard_mutations=tuple(prepared_cards), generator=generator,
            proposal_id=proposal_id, created_at=created_at,
        )
    except (InvalidWikiSectionError, InvalidWikiTargetError) as error:
        raise ToolValidationError(str(error)) from error
    except WikiSectionUnchangedError as error:
        raise ToolConflictError("Wiki section already has the proposed content") from error

    try:
        persisted_path = persist_study_learning_proposal(
            proposals_root=vault_root / "proposals", documents=documents
        )
    except WikiTargetExistsError as error:
        raise ToolConflictError("A proposed study learning create target already exists") from error
    except ProposalAlreadyExistsError as error:
        raise ToolConflictError("Draft proposal already exists") from error
    except ProposalPublicationError as error:
        raise ToolExecutionError("Could not publish study learning draft") from error

    return EvolveStudyLearningProposalResult(
        proposal_id=proposal_id,
        proposal_path=persisted_path.relative_to(vault_root).as_posix(),
        target_paths=documents.target_paths, operation_count=len(documents.target_paths),
        status="draft",
    )
