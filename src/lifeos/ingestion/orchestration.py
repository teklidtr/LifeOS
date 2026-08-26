from dataclasses import dataclass
from pathlib import Path

from lifeos.registry import Registry
from lifeos.registry.file_tracking import (
    FileRegistrationState,
    compare_registered_file,
    hash_file_content,
    validate_vault_path,
)
from lifeos.ingestion.drafts import SourceSnapshot
from lifeos.ingestion.taxonomy import extract_source_taxonomy
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, read_vault_bytes


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
                registry, source_path, working_tree_hash=None
            )
            if comparison.state == FileRegistrationState.REGISTERED_MISSING:
                raise MissingSourceError(f"Source missing: {source_path}") from error
            if comparison.state == FileRegistrationState.UNREGISTERED_MISSING:
                raise UnregisteredSourceError(
                    f"Source missing and unregistered: {source_path}"
                ) from error
            raise OrchestrationError(
                f"Unexpected missing state: {comparison.state}"
            ) from error
        raise SourceReadError(f"Could not read {source_path}") from error

    raw_hash = hash_file_content(source_bytes)

    comparison = compare_registered_file(
        registry, source_path, working_tree_hash=raw_hash
    )

    if comparison.state == FileRegistrationState.REGISTERED_MODIFIED:
        raise ModifiedSourceError(f"Source modified: {source_path}")
    if comparison.state == FileRegistrationState.UNREGISTERED_PRESENT:
        raise UnregisteredSourceError(f"Source unregistered: {source_path}")
    if comparison.state != FileRegistrationState.REGISTERED_UNCHANGED:
        raise OrchestrationError(f"Unexpected comparison state {comparison.state}")

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
    )
    return VerifiedRegisteredSource(source=snapshot, content=source_bytes)
