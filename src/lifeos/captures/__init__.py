"""Rich capture domain."""

from .artifact import AttachmentManifestService, CaptureArtifactService
from .contracts import (
    ATTACHMENT_SCHEMA_VERSION,
    CAPTURE_SCHEMA_VERSION,
    ArtifactLink,
    AttachmentManifest,
    AttachmentReference,
    CaptureArtifact,
    CaptureError,
    CaptureMetadata,
    DerivedValue,
)

__all__ = [
    "ATTACHMENT_SCHEMA_VERSION",
    "CAPTURE_SCHEMA_VERSION",
    "ArtifactLink",
    "AttachmentManifest",
    "AttachmentManifestService",
    "AttachmentReference",
    "CaptureArtifact",
    "CaptureArtifactService",
    "CaptureError",
    "CaptureMetadata",
    "DerivedValue",
]
