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
from .evidence import (
    EvidenceState,
    NormalizedEvidenceReference,
    PatternEvidenceDiagnostic,
    compute_evidence_fingerprint,
    normalize_evidence_reference,
    resolve_evidence_states,
)

__all__ = [
    "PATTERN_SCHEMA_VERSION",
    "EvidenceRole",
    "EvidenceState",
    "NormalizedEvidenceReference",
    "OriginKind",
    "PatternArtifact",
    "PatternArtifactService",
    "PatternConfidence",
    "PatternError",
    "PatternEvaluation",
    "PatternEvidence",
    "PatternEvidenceDiagnostic",
    "PatternMetadata",
    "PatternOrigin",
    "PatternStatus",
    "compute_evidence_fingerprint",
    "metadata_from_dict",
    "normalize_evidence_reference",
    "parse_pattern",
    "resolve_evidence_states",
    "serialize_pattern",
]
