from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path

from lifeos.ingestion.drafts import SourceSnapshot
from lifeos.ingestion.taxonomy import extract_source_taxonomy
from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry import Registry
from lifeos.registry.file_tracking import (
    FileRegistrationState,
    compare_registered_file,
    hash_file_content,
    validate_vault_path,
)
from lifeos.research import ResearchError, ResearchEvidenceService
from lifeos.vault import VaultAccessError, read_vault_bytes


_SELECTED_RESEARCH_ACQUISITION: ContextVar[str | None] = ContextVar(
    "lifeos_selected_research_acquisition",
    default=None,
)


@dataclass(frozen=True, slots=True)
class VerifiedRegisteredSource:
    source: SourceSnapshot
    content: bytes


class OrchestrationError(RuntimeError):
    pass


class MissingSourceError(OrchestrationError):
    pass


class UnregisteredSourceError(OrchestrationError):
    pass


class ModifiedSourceError(OrchestrationError):
    pass


class SourceReadError(OrchestrationError):
    pass


def push_research_acquisition_id(acquisition_id: str) -> Token[str | None]:
    if not isinstance(acquisition_id, str) or not acquisition_id.strip():
        raise ValueError("research acquisition_id must be a non-empty string")
    if acquisition_id != acquisition_id.strip():
        raise ValueError("research acquisition_id must not contain surrounding whitespace")
    return _SELECTED_RESEARCH_ACQUISITION.set(acquisition_id)


def reset_research_acquisition_id(token: Token[str | None]) -> None:
    _SELECTED_RESEARCH_ACQUISITION.reset(token)


def _validate_research_source(
    *,
    vault_root: Path,
    source_path: str,
    raw_hash: str,
    acquisition_id: str | None,
) -> str | None:
    is_research_source = source_path.startswith("raw/research/")
    if not is_research_source:
        if acquisition_id is not None:
            raise SourceReadError(
                "Research acquisition selection is only valid for raw/research sources"
            )
        return None

    if acquisition_id is None:
        raise SourceReadError(
            "Research sources require an explicit acquisition_id for durable synthesis"
        )

    try:
        artifact = ResearchEvidenceService(vault_root=vault_root).load(source_path)
    except ResearchError as error:
        raise ModifiedSourceError(
            f"Research source failed immutable evidence validation: {source_path}"
        ) from error

    if artifact.content_hash != f"sha256:{raw_hash}":
        raise ModifiedSourceError(f"Research source changed while being verified: {source_path}")

    if not any(
        acquisition.acquisition_id == acquisition_id
        for acquisition in artifact.metadata.acquisitions
    ):
        raise SourceReadError(
            f"Selected research acquisition is not present in source: {acquisition_id}"
        )
    return acquisition_id


def load_registered_source(
    *,
    registry: Registry,
    vault_root: Path,
    source_path: str,
) -> VerifiedRegisteredSource:
    # Validate before filesystem access. Reuses FileTrackingError per convention.
    validate_vault_path(source_path)

    target_file = vault_root / source_path

    try:
        source_bytes = read_vault_bytes(vault_root, source_path)
    except VaultAccessError as error:
        if error.code == "not-found":
            comparison = compare_registered_file(
                registry,
                source_path,
                working_tree_hash=None,
            )
            if comparison.state == FileRegistrationState.REGISTERED_MISSING:
                raise MissingSourceError(f"Source missing: {source_path}") from error
            if comparison.state == FileRegistrationState.UNREGISTERED_MISSING:
                raise UnregisteredSourceError(
                    f"Source missing and unregistered: {source_path}"
                ) from error
            raise OrchestrationError(f"Unexpected missing state: {comparison.state}") from error
        raise SourceReadError(f"Could not read {source_path}") from error

    raw_hash = hash_file_content(source_bytes)
    comparison = compare_registered_file(
        registry,
        source_path,
        working_tree_hash=raw_hash,
    )

    if comparison.state == FileRegistrationState.REGISTERED_MODIFIED:
        raise ModifiedSourceError(f"Source modified: {source_path}")
    if comparison.state == FileRegistrationState.UNREGISTERED_PRESENT:
        raise UnregisteredSourceError(f"Source unregistered: {source_path}")
    if comparison.state != FileRegistrationState.REGISTERED_UNCHANGED:
        raise OrchestrationError(f"Unexpected comparison state {comparison.state}")

    acquisition_id = _validate_research_source(
        vault_root=vault_root,
        source_path=source_path,
        raw_hash=raw_hash,
        acquisition_id=_SELECTED_RESEARCH_ACQUISITION.get(),
    )

    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        taxonomy = extract_source_taxonomy({})
    else:
        parsed = parse_markdown_note(target_file, content=source_text)
        taxonomy = extract_source_taxonomy(parsed.frontmatter)

    snapshot = SourceSnapshot(
        path=source_path,
        content_hash=f"sha256:{raw_hash}",
        tags=taxonomy.tags,
        topics=taxonomy.topics,
        acquisition_id=acquisition_id,
    )
    return VerifiedRegisteredSource(source=snapshot, content=source_bytes)
