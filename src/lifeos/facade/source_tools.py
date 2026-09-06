"""Provider-neutral facade for preserving and inspecting generic source files."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Mapping

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import (
    AttachmentManifestArtifact,
    AttachmentReference,
    CaptureArtifact,
    CaptureError,
    PrivacyScope,
)
from lifeos.captures.extraction import ExtractionResult, LocalExtractionService
from lifeos.captures.storage import AttachmentStore
from lifeos.facade.errors import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.retrieval import RetrievalError, RetrievalPolicy, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.vault import VaultAccessError, validate_vault_relative_path

SourceAccessMode = Literal["local", "external"]

SOURCE_IMPORT_DESCRIPTOR = ToolDescriptor(
    name="source.import",
    description=(
        "Preserve one trusted local regular file through the canonical Rich Capture "
        "attachment store."
    ),
    effect=ToolEffect.CANONICAL_CAPTURE,
)
SOURCE_INSPECT_DESCRIPTOR = ToolDescriptor(
    name="source.inspect",
    description="Inspect canonical source metadata, integrity, privacy, and local extraction state.",
    effect=ToolEffect.READ_ONLY,
)
SOURCE_EXTRACT_DESCRIPTOR = ToolDescriptor(
    name="source.extract",
    description=(
        "Run or reuse deterministic local extraction for an imported source and publish "
        "only derived output."
    ),
    effect=ToolEffect.DERIVED_WRITE,
)

_CAPTURE_ID = re.compile(r"^cap-\d{8}T\d{6}Z-[a-f0-9]{8}$")
_ATTACHMENT_ID = re.compile(r"^att-[a-f0-9]{16}$")
_PRIVACY_SCOPES = frozenset({"standard", "private", "protected"})
_EXTRACTION_STATUSES = frozenset(
    {"not-requested", "completed", "unavailable", "failed", "cancelled", "stale"}
)


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Stable source identity without attachment-store layout details."""

    capture_id: str
    capture_path: str
    attachment_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, str) or not _CAPTURE_ID.fullmatch(self.capture_id):
            raise ValueError("capture_id must be a canonical capture ID")
        try:
            validated = validate_vault_relative_path(self.capture_path)
        except VaultAccessError as exc:
            raise ValueError("capture_path must be a canonical vault-relative path") from exc
        if (
            validated != self.capture_path
            or not validated.startswith("captures/")
            or not validated.endswith(".md")
        ):
            raise ValueError("capture_path must identify a canonical capture")
        if not isinstance(self.attachment_id, str) or not _ATTACHMENT_ID.fullmatch(
            self.attachment_id
        ):
            raise ValueError("attachment_id must be a canonical attachment ID")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceImportRequest:
    """Trusted local ingress. ``source_path`` is invocation-only and is never returned."""

    source_path: str
    title: str | None = None
    description: str = ""
    privacy_scope: PrivacyScope = "standard"
    sensitive: bool = False
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_path, str)
            or not self.source_path
            or self.source_path != self.source_path.strip()
            or "\x00" in self.source_path
            or not Path(self.source_path).is_absolute()
        ):
            raise ValueError("source_path must be a non-empty absolute local path")
        if self.title is not None and (
            not isinstance(self.title, str) or not self.title.strip()
        ):
            raise ValueError("title must be non-empty when provided")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if self.privacy_scope not in _PRIVACY_SCOPES:
            raise ValueError("privacy_scope must be standard, private, or protected")
        if type(self.sensitive) is not bool:
            raise ValueError("sensitive must be a boolean")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty string")


@dataclass(frozen=True, slots=True)
class SourceInspectRequest:
    source: SourceReference

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceReference):
            raise ValueError("source must be a SourceReference")


@dataclass(frozen=True, slots=True)
class SourceExtractRequest:
    source: SourceReference
    mode: SourceAccessMode = "local"
    allow_protected: bool = False
    max_text_bytes: int = 24_000

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceReference):
            raise ValueError("source must be a SourceReference")
        if self.mode not in {"local", "external"}:
            raise ValueError("mode must be local or external")
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        if type(self.max_text_bytes) is not int or not 1 <= self.max_text_bytes <= 2_000_000:
            raise ValueError("max_text_bytes must be an integer between 1 and 2000000")


@dataclass(frozen=True, slots=True)
class SourceDetails:
    source: SourceReference
    original_filename: str
    media_type: str
    byte_size: int
    content_hash: str
    integrity_status: str
    capture_state: str
    extraction_status: str
    extraction_method: str | None
    extraction_quality: str | None
    privacy_scope: str
    sensitive: bool

    def __post_init__(self) -> None:
        if self.extraction_status not in _EXTRACTION_STATUSES:
            raise ValueError("extraction_status is invalid")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceImportResult:
    details: SourceDetails
    duplicate: bool
    reused_original: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceExtractResult:
    details: SourceDetails
    status: str
    method: str
    method_version: str
    quality: str
    text: str
    metadata: Mapping[str, object] | None
    warning: str
    truncated: bool

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["metadata"] = dict(self.metadata) if self.metadata is not None else None
        return result


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    capture: CaptureArtifact
    reference: AttachmentReference
    manifest: AttachmentManifestArtifact


def import_source(
    *,
    vault_root: Path,
    runtime_dir: Path,
    request: SourceImportRequest,
    now: datetime | None = None,
) -> SourceImportResult:
    """Preserve one trusted local file through existing Rich Capture services."""

    source_path = Path(request.source_path)
    captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
    try:
        capture = captures.create(
            title=request.title.strip() if request.title is not None else source_path.name,
            capture_type="attachment",
            description=request.description,
            timezone_name=request.timezone,
            source_entry_point="source.import",
            privacy_scope=request.privacy_scope,
            sensitive=request.sensitive,
            now=now,
        )
        imported = store.import_file(
            source_path,
            capture_source="source.import",
            parent_capture_id=capture.metadata.capture_id,
            now=now,
        )
        capture = store.attach_to_capture(
            capture.path,
            imported.reference,
            expected_hash=capture.content_hash,
            now=now,
        )
        details = _source_details(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            capture=capture,
            reference=imported.reference,
        )
    except CaptureError as exc:
        raise _facade_error(exc) from exc
    return SourceImportResult(details, imported.duplicate, imported.reused_original)


def inspect_source(
    *,
    vault_root: Path,
    runtime_dir: Path,
    request: SourceInspectRequest,
) -> SourceDetails:
    """Inspect source facts without returning original or extracted content."""

    resolved = _resolve_source(vault_root=vault_root, runtime_dir=runtime_dir, source=request.source)
    return _source_details(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        capture=resolved.capture,
        reference=resolved.reference,
    )


def extract_source(
    *,
    vault_root: Path,
    runtime_dir: Path,
    request: SourceExtractRequest,
) -> SourceExtractResult:
    """Run or reuse deterministic extraction under existing retrieval/privacy policy."""

    if request.mode == "external":
        _require_external_access(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            request=request,
        )
        policy = None
    else:
        policy = _load_policy(vault_root)
        _require_path_allowed(
            request.source.capture_path,
            policy=policy,
            allow_protected=request.allow_protected,
        )

    resolved = _resolve_source(vault_root=vault_root, runtime_dir=runtime_dir, source=request.source)
    if request.mode == "local":
        assert policy is not None
        _require_local_access(resolved, policy=policy, allow_protected=request.allow_protected)

    extractor = LocalExtractionService(vault_root=vault_root, runtime_dir=runtime_dir)
    try:
        existing = extractor.load(resolved.reference.attachment_id)
        if existing is None or existing.source_hash != resolved.manifest.metadata.content_hash:
            result = extractor.extract(resolved.manifest.metadata)
            extractor.publish(result)
        else:
            result = existing
    except CaptureError as exc:
        raise _facade_error(exc) from exc

    if request.mode == "external":
        text, truncated = _external_text(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            capture=resolved.capture,
            reference=resolved.reference,
            result=result,
            allow_protected=request.allow_protected,
            max_text_bytes=request.max_text_bytes,
        )
    else:
        text, truncated = _truncate_utf8(result.text, request.max_text_bytes)

    details = _source_details(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        capture=resolved.capture,
        reference=resolved.reference,
    )
    return SourceExtractResult(
        details=details,
        status=result.status,
        method=result.method,
        method_version=result.method_version,
        quality=result.quality,
        text=text,
        metadata=result.metadata,
        warning=result.warning,
        truncated=truncated,
    )


def _resolve_source(
    *,
    vault_root: Path,
    runtime_dir: Path,
    source: SourceReference,
) -> _ResolvedSource:
    captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
    try:
        capture = captures.load(source.capture_path)
        if capture.metadata.capture_id != source.capture_id:
            raise ToolNotFoundError("Source reference no longer identifies the expected capture")
        reference = next(
            (
                item
                for item in capture.metadata.attachments
                if item.attachment_id == source.attachment_id
            ),
            None,
        )
        if reference is None:
            raise ToolNotFoundError("Source attachment is not linked to the capture")
        manifest = store.manifests.load(reference.manifest_path)
        metadata = manifest.metadata
        if (
            metadata.attachment_id != reference.attachment_id
            or metadata.content_hash != reference.content_hash
            or metadata.canonical_path != reference.canonical_path
            or metadata.byte_size != reference.byte_size
            or metadata.media_type != reference.media_type
        ):
            raise ToolExecutionError("Source reference does not match its canonical manifest")
    except (ToolNotFoundError, ToolExecutionError):
        raise
    except CaptureError as exc:
        raise _facade_error(exc) from exc
    return _ResolvedSource(capture, reference, manifest)


def _source_details(
    *,
    vault_root: Path,
    runtime_dir: Path,
    capture: CaptureArtifact,
    reference: AttachmentReference,
) -> SourceDetails:
    store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
    extractor = LocalExtractionService(vault_root=vault_root, runtime_dir=runtime_dir)
    try:
        audit = store.audit(reference.attachment_id)
        extraction = extractor.load(reference.attachment_id)
    except CaptureError as exc:
        raise _facade_error(exc) from exc
    if extraction is None:
        extraction_status = "not-requested"
        extraction_method = None
        extraction_quality = None
    elif extraction.source_hash != reference.content_hash:
        extraction_status = "stale"
        extraction_method = extraction.method
        extraction_quality = extraction.quality
    else:
        extraction_status = extraction.status
        extraction_method = extraction.method
        extraction_quality = extraction.quality
    return SourceDetails(
        source=SourceReference(capture.metadata.capture_id, capture.path, reference.attachment_id),
        original_filename=reference.original_filename,
        media_type=reference.media_type,
        byte_size=reference.byte_size,
        content_hash=reference.content_hash,
        integrity_status=audit.status,
        capture_state=capture.metadata.state,
        extraction_status=extraction_status,
        extraction_method=extraction_method,
        extraction_quality=extraction_quality,
        privacy_scope=capture.metadata.privacy_scope,
        sensitive=capture.metadata.sensitive,
    )


def _load_policy(vault_root: Path) -> RetrievalPolicy:
    try:
        return load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ToolExecutionError("Retrieval policy is invalid") from exc


def _require_path_allowed(
    path: str,
    *,
    policy: RetrievalPolicy,
    allow_protected: bool,
) -> None:
    try:
        decision = scope_decision(
            path,
            scope=RetrievalScope(allow_protected=allow_protected),
            policy=policy,
            mode="local",
        )
    except RetrievalError as exc:
        raise ToolValidationError("Source reference contains an invalid vault path") from exc
    if not decision.allowed:
        raise ToolAuthorizationError(
            f"Source content is not available in this mode: {decision.reason}"
        )


def _require_local_access(
    resolved: _ResolvedSource,
    *,
    policy: RetrievalPolicy,
    allow_protected: bool,
) -> None:
    if (
        resolved.capture.metadata.privacy_scope == "protected"
        or resolved.capture.metadata.sensitive
    ) and not allow_protected:
        raise ToolAuthorizationError("Protected source content requires explicit request scope")
    _require_path_allowed(
        resolved.reference.manifest_path,
        policy=policy,
        allow_protected=allow_protected,
    )
    _require_path_allowed(
        resolved.reference.canonical_path,
        policy=policy,
        allow_protected=allow_protected,
    )


def _require_external_access(
    *,
    vault_root: Path,
    runtime_dir: Path,
    request: SourceExtractRequest,
) -> None:
    from lifeos.captures.privacy import preview_capture_context

    try:
        preview = preview_capture_context(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            capture_path=request.source.capture_path,
            selected_attachment_ids=(request.source.attachment_id,),
            requested_operations=("source-extract",),
            external_processing_intent=True,
            allow_sensitive_capture=request.allow_protected,
            max_item_bytes=request.max_text_bytes,
            max_total_bytes=request.max_text_bytes,
        )
    except CaptureError as exc:
        raise _facade_error(exc) from exc
    if not any(item.attachment_id == request.source.attachment_id for item in preview.items):
        raise ToolAuthorizationError("Source content is not available for external disclosure")


def _external_text(
    *,
    vault_root: Path,
    runtime_dir: Path,
    capture: CaptureArtifact,
    reference: AttachmentReference,
    result: ExtractionResult,
    allow_protected: bool,
    max_text_bytes: int,
) -> tuple[str, bool]:
    if not result.text:
        return "", False
    from lifeos.captures.privacy import preview_capture_context

    try:
        preview = preview_capture_context(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            capture_path=capture.path,
            selected_attachment_ids=(reference.attachment_id,),
            requested_operations=("source-extract",),
            external_processing_intent=True,
            allow_sensitive_capture=allow_protected,
            max_item_bytes=max_text_bytes,
            max_total_bytes=max_text_bytes,
        )
    except CaptureError as exc:
        raise _facade_error(exc) from exc
    item = next(
        (
            candidate
            for candidate in preview.items
            if candidate.attachment_id == reference.attachment_id
            and candidate.kind == "derived-extracted-text"
        ),
        None,
    )
    if item is None:
        raise ToolAuthorizationError("Extracted source text is not available for external disclosure")
    return item.excerpt, item.truncated


def _truncate_utf8(text: str, limit: int) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    clipped = raw[:limit]
    while clipped:
        try:
            return clipped.decode("utf-8"), True
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return "", True


def _facade_error(error: CaptureError) -> Exception:
    if error.code in {"file_changed", "attachment_changed", "stale_capture", "stale_manifest"}:
        return ToolConflictError("Source changed during the operation")
    if error.code in {"attachment_open_failed", "not-found"}:
        return ToolNotFoundError("Source file or canonical source artifact was not found")
    if error.code in {
        "unsupported_file",
        "invalid_attachment",
        "invalid_attachment_path",
        "invalid_capture",
        "invalid_field",
        "invalid_hash",
    }:
        return ToolValidationError("Source was rejected by the canonical capture boundary")
    if error.code == "oversized_for_extraction":
        return ToolExecutionError("Source exceeds the deterministic extraction limit")
    return ToolExecutionError("Source operation failed")
