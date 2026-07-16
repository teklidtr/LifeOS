"""Rich capture domain."""

from .artifact import AttachmentManifestService, CaptureArtifactService
from .visualization import CaptureVisualization, build_capture_visualization
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
    "CaptureVisualization",
    "build_capture_visualization",
]
