"""Evidence-grounded research capture contracts and persistence."""

from .artifact import ResearchEvidenceService
from .contracts import (
    RESEARCH_SOURCE_SCHEMA_VERSION,
    ResearchAcquisition,
    ResearchCaptureResult,
    ResearchError,
    ResearchOriginKind,
    ResearchSourceArtifact,
    ResearchSourceMetadata,
)

__all__ = [
    "RESEARCH_SOURCE_SCHEMA_VERSION",
    "ResearchAcquisition",
    "ResearchCaptureResult",
    "ResearchError",
    "ResearchEvidenceService",
    "ResearchOriginKind",
    "ResearchSourceArtifact",
    "ResearchSourceMetadata",
]
