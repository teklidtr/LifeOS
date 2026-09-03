"""Canonical evidence-backed personal-pattern artifacts."""

from .artifact import PatternArtifactService, parse_pattern, serialize_pattern
from .contracts import (
    PATTERN_SCHEMA_VERSION,
    EvidenceRole,
    OriginKind,
    PatternArtifact,
    PatternConfidence,
    PatternError,
    PatternEvaluation,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    PatternStatus,
    metadata_from_dict,
)

__all__ = [
    "PATTERN_SCHEMA_VERSION",
    "EvidenceRole",
    "OriginKind",
    "PatternArtifact",
    "PatternArtifactService",
    "PatternConfidence",
    "PatternError",
    "PatternEvaluation",
    "PatternEvidence",
    "PatternMetadata",
    "PatternOrigin",
    "PatternStatus",
    "metadata_from_dict",
    "parse_pattern",
    "serialize_pattern",
]
