from dataclasses import dataclass
from pathlib import Path

from lifeos.registry import Registry
from lifeos.registry.file_tracking import (
    FileRegistrationState,
    compare_registered_file,
    hash_file_content,
    validate_vault_path,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.ingestion.backend import (
    AnalysisBackend,
    AnalysisRequest,
    AnalysisResult,
    SourceSnapshot,
)

@dataclass(frozen=True, slots=True)
class VerifiedRegisteredSource:
    source: SourceSnapshot
    content: bytes

@dataclass(frozen=True, slots=True)
class AnalyzedSource:
    source: SourceSnapshot
    analysis: AnalysisResult

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


class SourceDecodeError(OrchestrationError):
    pass


class SourceParseError(OrchestrationError):
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
        source_bytes = target_file.read_bytes()
    except FileNotFoundError:
        comparison = compare_registered_file(
            registry, source_path, working_tree_hash=None
        )
        if comparison.state == FileRegistrationState.REGISTERED_MISSING:
            raise MissingSourceError(f"Source missing: {source_path}")
        elif comparison.state == FileRegistrationState.UNREGISTERED_MISSING:
            raise UnregisteredSourceError(f"Source missing and unregistered: {source_path}")
        raise OrchestrationError(f"Unexpected missing state: {comparison.state}")
    except OSError as e:
        raise SourceReadError(f"Could not read {source_path}") from e

    raw_hash = hash_file_content(source_bytes)

    comparison = compare_registered_file(
        registry, source_path, working_tree_hash=raw_hash
    )

    if comparison.state == FileRegistrationState.REGISTERED_MODIFIED:
        raise ModifiedSourceError(f"Source modified: {source_path}")
    elif comparison.state == FileRegistrationState.UNREGISTERED_PRESENT:
        raise UnregisteredSourceError(f"Source unregistered: {source_path}")
    elif comparison.state != FileRegistrationState.REGISTERED_UNCHANGED:
        raise OrchestrationError(f"Unexpected comparison state {comparison.state}")

    snapshot = SourceSnapshot(
        path=source_path,
        content_hash=f"sha256:{raw_hash}",
    )
    return VerifiedRegisteredSource(source=snapshot, content=source_bytes)


def analyze_registered_source(
    *,
    registry: Registry,
    vault_root: Path,
    source_path: str,
    backend: AnalysisBackend,
) -> AnalyzedSource:
    verified = load_registered_source(
        registry=registry,
        vault_root=vault_root,
        source_path=source_path,
    )
    
    target_file = vault_root / source_path

    try:
        decoded_text = verified.content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SourceDecodeError("Invalid UTF-8 encoding") from e

    try:
        parsed_note = parse_markdown_note(target_file, content=decoded_text)
    except ValueError as e:
        raise SourceParseError("Failed to parse markdown") from e

    request = AnalysisRequest(
        source=verified.source,
        markdown_body=parsed_note.body,
    )

    analysis = backend.analyze(request)
    return AnalyzedSource(source=verified.source, analysis=analysis)
