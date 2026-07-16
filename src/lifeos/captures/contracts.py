"""Provider-neutral canonical contracts for rich captures and attachments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence

CAPTURE_SCHEMA_VERSION = 1
ATTACHMENT_SCHEMA_VERSION = 1
CaptureType = Literal["meal", "exercise", "attachment", "mixed"]
CaptureState = Literal[
    "captured",
    "processing",
    "needs-review",
    "enriched",
    "linked",
    "completed",
    "failed",
    "archived",
]
AttachmentKind = Literal["original", "user-edited", "generated-derivative"]
ProcessingState = Literal[
    "not-requested",
    "queued",
    "processing",
    "completed",
    "needs-review",
    "unavailable",
    "failed",
    "cancelled",
    "stale",
]
PrivacyScope = Literal["standard", "private", "protected"]
ValueSource = Literal[
    "user-entered",
    "label-derived",
    "database-derived",
    "recipe-calculated",
    "image-estimate",
    "model-estimate",
    "ocr",
    "transcript",
    "imported",
    "unknown",
]
Confidence = Literal["high", "medium", "low", "unknown"]

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "captured": frozenset(
        {"processing", "needs-review", "enriched", "linked", "completed", "failed", "archived"}
    ),
    "processing": frozenset({"needs-review", "enriched", "failed", "captured"}),
    "needs-review": frozenset(
        {"processing", "enriched", "linked", "completed", "failed", "archived"}
    ),
    "enriched": frozenset(
        {"processing", "needs-review", "linked", "completed", "failed", "archived"}
    ),
    "linked": frozenset(
        {"processing", "needs-review", "enriched", "completed", "failed", "archived"}
    ),
    "completed": frozenset({"needs-review", "linked", "archived"}),
    "failed": frozenset({"processing", "needs-review", "captured", "archived"}),
    "archived": frozenset({"needs-review"}),
}


class CaptureError(ValueError):
    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


def _nonblank(value: str, name: str) -> str:
    result = value.strip()
    if not result:
        raise CaptureError("invalid_field", f"{name} must not be blank.", {"field": name})
    return result


def _sha256(value: str, name: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise CaptureError("invalid_hash", f"{name} must be a sha256 digest.", {"field": name})
    return value


def validate_transition(current: CaptureState, target: CaptureState) -> None:
    if target == current:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise CaptureError(
            "invalid_transition",
            f"Capture cannot transition from {current} to {target}.",
            {
                "current": current,
                "target": target,
                "allowed": sorted(_ALLOWED_TRANSITIONS[current]),
            },
        )


@dataclass(frozen=True, slots=True)
class ArtifactLink:
    path: str
    relation: str
    artifact_type: str = "note"
    content_hash: str | None = None

    def __post_init__(self) -> None:
        _nonblank(self.path, "link path")
        _nonblank(self.relation, "link relation")
        _nonblank(self.artifact_type, "artifact type")
        if self.content_hash is not None:
            _sha256(self.content_hash, "link content_hash")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    kind: str
    source: str
    recorded_at: str
    explanation: str = ""
    source_hash: str | None = None

    def __post_init__(self) -> None:
        _nonblank(self.kind, "provenance kind")
        _nonblank(self.source, "provenance source")
        _nonblank(self.recorded_at, "provenance recorded_at")
        if self.source_hash is not None:
            _sha256(self.source_hash, "provenance source_hash")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_id: str
    from_state: str | None
    to_state: CaptureState
    occurred_at: str
    reason: str = ""

    def __post_init__(self) -> None:
        _nonblank(self.event_id, "lifecycle event_id")
        _nonblank(self.occurred_at, "lifecycle occurred_at")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AttachmentReference:
    attachment_id: str
    manifest_path: str
    content_hash: str
    media_type: str
    byte_size: int
    original_filename: str
    canonical_path: str
    relationship: str = "evidence"

    def __post_init__(self) -> None:
        _nonblank(self.attachment_id, "attachment_id")
        _nonblank(self.manifest_path, "manifest_path")
        _sha256(self.content_hash, "attachment content_hash")
        _nonblank(self.media_type, "media_type")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise CaptureError("invalid_attachment", "byte_size must be a non-negative integer.")
        _nonblank(self.original_filename, "original_filename")
        _nonblank(self.canonical_path, "canonical_path")
        _nonblank(self.relationship, "relationship")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DerivedValue:
    field_name: str
    value: object | None
    unit: str | None
    source: ValueSource
    confidence: Confidence = "unknown"
    range_low: float | None = None
    range_high: float | None = None
    assumptions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    status: Literal["suggested", "confirmed", "corrected", "rejected"] = "suggested"

    def __post_init__(self) -> None:
        _nonblank(self.field_name, "derived field_name")
        if (
            self.range_low is not None
            and self.range_high is not None
            and self.range_low > self.range_high
        ):
            raise CaptureError("invalid_range", "range_low must not exceed range_high.")
        if self.source == "unknown" and self.value is not None:
            raise CaptureError("invalid_value", "Unknown values must not carry a value.")
        if self.status == "confirmed" and self.source in {
            "image-estimate",
            "model-estimate",
            "ocr",
            "transcript",
        }:
            # Confirmation is allowed, but source remains visible and never changes to user-entered.
            pass

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaptureMetadata:
    capture_id: str
    title: str
    capture_type: CaptureType
    state: CaptureState
    captured_at: str
    event_at: str
    timezone: str
    source_entry_point: str
    description: str = ""
    privacy_scope: PrivacyScope = "standard"
    sensitive: bool = False
    location: str | None = None
    tags: tuple[str, ...] = ()
    attachments: tuple[AttachmentReference, ...] = ()
    links: tuple[ArtifactLink, ...] = ()
    derived_values: tuple[DerivedValue, ...] = ()
    domain_data: dict[str, object] = field(default_factory=dict)
    extraction_status: ProcessingState = "not-requested"
    enrichment_status: ProcessingState = "not-requested"
    exclude_from_semantic: bool = False
    exclude_from_conversations: bool = False
    exclude_from_reviews: bool = False
    exclude_from_experiments: bool = False
    provenance: tuple[ProvenanceRecord, ...] = ()
    lifecycle: tuple[LifecycleEvent, ...] = ()
    merged_from: tuple[str, ...] = ()
    split_from: str | None = None
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = CAPTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.capture_id.startswith("cap-"):
            raise CaptureError("invalid_capture", "Capture ID is malformed.")
        _nonblank(self.title, "title")
        for name, value in (
            ("captured_at", self.captured_at),
            ("event_at", self.event_at),
            ("timezone", self.timezone),
            ("source_entry_point", self.source_entry_point),
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            _nonblank(value, name)
        if self.schema_version != CAPTURE_SCHEMA_VERSION:
            raise CaptureError("unsupported_schema", "Capture schema version is unsupported.")
        ids = [item.attachment_id for item in self.attachments]
        if len(ids) != len(set(ids)):
            raise CaptureError(
                "duplicate_attachment_reference", "Capture has duplicate attachment references."
            )

    def to_frontmatter(self) -> dict[str, object]:
        return {
            "id": self.capture_id,
            "type": "rich-capture",
            "schema_version": self.schema_version,
            "title": self.title,
            "description": self.description,
            "capture_type": self.capture_type,
            "state": self.state,
            "captured_at": self.captured_at,
            "event_at": self.event_at,
            "timezone": self.timezone,
            "source_entry_point": self.source_entry_point,
            "privacy_scope": self.privacy_scope,
            "sensitive": self.sensitive,
            "location": self.location,
            "tags": list(self.tags),
            "attachments": [item.to_dict() for item in self.attachments],
            "links": [item.to_dict() for item in self.links],
            "derived_values": [item.to_dict() for item in self.derived_values],
            "domain_data": self.domain_data,
            "extraction_status": self.extraction_status,
            "enrichment_status": self.enrichment_status,
            "exclude_from_semantic": self.exclude_from_semantic,
            "exclude_from_conversations": self.exclude_from_conversations,
            "exclude_from_reviews": self.exclude_from_reviews,
            "exclude_from_experiments": self.exclude_from_experiments,
            "provenance": [item.to_dict() for item in self.provenance],
            "lifecycle": [item.to_dict() for item in self.lifecycle],
            "merged_from": list(self.merged_from),
            "split_from": self.split_from,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class CaptureArtifact:
    path: str
    content_hash: str
    metadata: CaptureMetadata
    human_body: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "metadata": self.metadata.to_frontmatter(),
            "human_body": self.human_body,
        }


@dataclass(frozen=True, slots=True)
class AttachmentManifest:
    attachment_id: str
    content_hash: str
    original_filename: str
    canonical_path: str
    media_type: str
    byte_size: int
    capture_source: str
    imported_at: str
    kind: AttachmentKind = "original"
    extraction_status: ProcessingState = "not-requested"
    preview_status: ProcessingState = "not-requested"
    transcript_status: ProcessingState = "not-requested"
    parent_capture_ids: tuple[str, ...] = ()
    duplicate_of: str | None = None
    derived_artifacts: tuple[str, ...] = ()
    provider_processing_disclosures: tuple[dict[str, object], ...] = ()
    redaction_state: Literal["none", "previewed", "redacted"] = "none"
    source_modified_ns: int | None = None
    schema_version: int = ATTACHMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.attachment_id.startswith("att-"):
            raise CaptureError("invalid_attachment", "Attachment ID is malformed.")
        _sha256(self.content_hash, "content_hash")
        _nonblank(self.original_filename, "original_filename")
        _nonblank(self.canonical_path, "canonical_path")
        _nonblank(self.media_type, "media_type")
        _nonblank(self.capture_source, "capture_source")
        _nonblank(self.imported_at, "imported_at")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise CaptureError("invalid_attachment", "byte_size must be a non-negative integer.")
        if self.schema_version != ATTACHMENT_SCHEMA_VERSION:
            raise CaptureError("unsupported_schema", "Attachment schema version is unsupported.")

    def to_frontmatter(self) -> dict[str, object]:
        result = asdict(self)
        result["id"] = result.pop("attachment_id")
        result["type"] = "attachment-manifest"
        return result


@dataclass(frozen=True, slots=True)
class AttachmentManifestArtifact:
    path: str
    content_hash: str
    metadata: AttachmentManifest
    human_body: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "metadata": self.metadata.to_frontmatter(),
            "human_body": self.human_body,
        }


def _sequence(value: object, name: str) -> Sequence[object]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CaptureError("invalid_field", f"{name} must be a list.")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CaptureError("invalid_field", f"{name} must be an object.")
    return value


def capture_metadata_from_dict(data: Mapping[str, Any]) -> CaptureMetadata:
    version = int(data.get("schema_version", 0))
    if version != CAPTURE_SCHEMA_VERSION:
        raise CaptureError(
            "unsupported_schema",
            "Capture schema version is unsupported.",
            {"schema_version": version},
        )
    attachments = tuple(
        AttachmentReference(**dict(_mapping(item, "attachment")))
        for item in _sequence(data.get("attachments"), "attachments")
    )
    links = tuple(
        ArtifactLink(**dict(_mapping(item, "link")))
        for item in _sequence(data.get("links"), "links")
    )
    derived = []
    for item in _sequence(data.get("derived_values"), "derived_values"):
        raw = dict(_mapping(item, "derived value"))
        raw["assumptions"] = tuple(raw.get("assumptions", ()))
        raw["evidence_refs"] = tuple(raw.get("evidence_refs", ()))
        derived.append(DerivedValue(**raw))
    provenance = tuple(
        ProvenanceRecord(**dict(_mapping(item, "provenance")))
        for item in _sequence(data.get("provenance"), "provenance")
    )
    lifecycle = tuple(
        LifecycleEvent(**dict(_mapping(item, "lifecycle")))
        for item in _sequence(data.get("lifecycle"), "lifecycle")
    )
    return CaptureMetadata(
        capture_id=str(data.get("id", "")),
        title=str(data.get("title", "")),
        description=str(data.get("description", "")),
        capture_type=str(data.get("capture_type", "attachment")),  # type: ignore[arg-type]
        state=str(data.get("state", "captured")),  # type: ignore[arg-type]
        captured_at=str(data.get("captured_at", "")),
        event_at=str(data.get("event_at", "")),
        timezone=str(data.get("timezone", "")),
        source_entry_point=str(data.get("source_entry_point", "")),
        privacy_scope=str(data.get("privacy_scope", "standard")),  # type: ignore[arg-type]
        sensitive=bool(data.get("sensitive", False)),
        location=str(data["location"]) if data.get("location") is not None else None,
        tags=tuple(str(item) for item in _sequence(data.get("tags"), "tags")),
        attachments=attachments,
        links=links,
        derived_values=tuple(derived),
        domain_data=dict(_mapping(data.get("domain_data", {}), "domain_data")),
        extraction_status=str(data.get("extraction_status", "not-requested")),  # type: ignore[arg-type]
        enrichment_status=str(data.get("enrichment_status", "not-requested")),  # type: ignore[arg-type]
        exclude_from_semantic=bool(data.get("exclude_from_semantic", False)),
        exclude_from_conversations=bool(data.get("exclude_from_conversations", False)),
        exclude_from_reviews=bool(data.get("exclude_from_reviews", False)),
        exclude_from_experiments=bool(data.get("exclude_from_experiments", False)),
        provenance=provenance,
        lifecycle=lifecycle,
        merged_from=tuple(str(item) for item in _sequence(data.get("merged_from"), "merged_from")),
        split_from=str(data["split_from"]) if data.get("split_from") is not None else None,
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        schema_version=version,
    )


def attachment_manifest_from_dict(data: Mapping[str, Any]) -> AttachmentManifest:
    version = int(data.get("schema_version", 0))
    if version != ATTACHMENT_SCHEMA_VERSION:
        raise CaptureError(
            "unsupported_schema",
            "Attachment schema version is unsupported.",
            {"schema_version": version},
        )
    return AttachmentManifest(
        attachment_id=str(data.get("id", "")),
        content_hash=str(data.get("content_hash", "")),
        original_filename=str(data.get("original_filename", "")),
        canonical_path=str(data.get("canonical_path", "")),
        media_type=str(data.get("media_type", "application/octet-stream")),
        byte_size=int(data.get("byte_size", -1)),
        capture_source=str(data.get("capture_source", "")),
        imported_at=str(data.get("imported_at", "")),
        kind=str(data.get("kind", "original")),  # type: ignore[arg-type]
        extraction_status=str(data.get("extraction_status", "not-requested")),  # type: ignore[arg-type]
        preview_status=str(data.get("preview_status", "not-requested")),  # type: ignore[arg-type]
        transcript_status=str(data.get("transcript_status", "not-requested")),  # type: ignore[arg-type]
        parent_capture_ids=tuple(
            str(item) for item in _sequence(data.get("parent_capture_ids"), "parent_capture_ids")
        ),
        duplicate_of=str(data["duplicate_of"]) if data.get("duplicate_of") is not None else None,
        derived_artifacts=tuple(
            str(item) for item in _sequence(data.get("derived_artifacts"), "derived_artifacts")
        ),
        provider_processing_disclosures=tuple(
            dict(_mapping(item, "disclosure"))
            for item in _sequence(
                data.get("provider_processing_disclosures"), "provider_processing_disclosures"
            )
        ),
        redaction_state=str(data.get("redaction_state", "none")),  # type: ignore[arg-type]
        source_modified_ns=int(data["source_modified_ns"])
        if data.get("source_modified_ns") is not None
        else None,
        schema_version=version,
    )
