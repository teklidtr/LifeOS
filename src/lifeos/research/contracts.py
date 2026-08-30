"""Provider-neutral contracts for externally acquired research evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping

RESEARCH_SOURCE_SCHEMA_VERSION = 1
ResearchOriginKind = Literal["query", "conversation", "manual", "other"]


class ResearchError(ValueError):
    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


def _nonblank(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ResearchError("invalid_field", f"{name} must not be blank.", {"field": name})
    return normalized


def _sha256(value: str, name: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ResearchError("invalid_hash", f"{name} must be a sha256 digest.", {"field": name})
    return value


@dataclass(frozen=True, slots=True)
class ResearchAcquisition:
    acquisition_id: str
    captured_at: str
    captured_by: str
    origin_kind: ResearchOriginKind
    research_reason: str
    origin_ref: str | None = None
    research_context: str = ""

    def __post_init__(self) -> None:
        if not self.acquisition_id.startswith("acq-"):
            raise ResearchError("invalid_acquisition", "Research acquisition ID is malformed.")
        _nonblank(self.captured_at, "captured_at")
        _nonblank(self.captured_by, "captured_by")
        _nonblank(self.research_reason, "research_reason")
        if self.origin_kind not in {"query", "conversation", "manual", "other"}:
            raise ResearchError("invalid_origin", "Research origin kind is unsupported.")
        if self.origin_ref is not None:
            _nonblank(self.origin_ref, "origin_ref")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResearchSourceMetadata:
    artifact_id: str
    source_identity: str
    snapshot_hash: str
    source_title: str
    first_captured_at: str
    first_captured_by: str
    acquisitions: tuple[ResearchAcquisition, ...]
    source_locator: str | None = None
    source_author: str | None = None
    source_publisher: str | None = None
    schema_version: int = RESEARCH_SOURCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.artifact_id.startswith("research-"):
            raise ResearchError("invalid_artifact", "Research artifact ID is malformed.")
        _sha256(self.source_identity, "source_identity")
        _sha256(self.snapshot_hash, "snapshot_hash")
        _nonblank(self.source_title, "source_title")
        _nonblank(self.first_captured_at, "first_captured_at")
        _nonblank(self.first_captured_by, "first_captured_by")
        if self.source_locator is not None:
            _nonblank(self.source_locator, "source_locator")
        if self.source_author is not None:
            _nonblank(self.source_author, "source_author")
        if self.source_publisher is not None:
            _nonblank(self.source_publisher, "source_publisher")
        if self.schema_version != RESEARCH_SOURCE_SCHEMA_VERSION:
            raise ResearchError("unsupported_schema", "Research source schema is unsupported.")
        ids = [item.acquisition_id for item in self.acquisitions]
        if len(ids) != len(set(ids)):
            raise ResearchError(
                "duplicate_acquisition",
                "Research source contains duplicate acquisition lineage.",
            )
        if not self.acquisitions:
            raise ResearchError(
                "missing_acquisition",
                "Research source must retain at least one acquisition lineage record.",
            )

    def to_frontmatter(self) -> dict[str, object]:
        return {
            "type": "research-source",
            "research_schema": self.schema_version,
            "artifact_id": self.artifact_id,
            "source_identity": self.source_identity,
            "source_locator": self.source_locator,
            "source_title": self.source_title,
            "source_author": self.source_author,
            "source_publisher": self.source_publisher,
            "snapshot_hash": self.snapshot_hash,
            "first_captured_at": self.first_captured_at,
            "first_captured_by": self.first_captured_by,
            "acquisitions": [item.to_dict() for item in self.acquisitions],
        }


@dataclass(frozen=True, slots=True)
class ResearchSourceArtifact:
    relative_path: str
    content_hash: str
    metadata: ResearchSourceMetadata
    evidence_text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "content_hash": self.content_hash,
            "metadata": self.metadata.to_frontmatter(),
            "evidence_text": self.evidence_text,
        }


@dataclass(frozen=True, slots=True)
class ResearchCaptureResult:
    artifact: ResearchSourceArtifact
    acquisition_id: str
    created: bool
    acquisition_added: bool
