"""Approved rich-capture text representations for retrieval and conversations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from lifeos.retrieval.chunking import chunk_markdown_file
from lifeos.retrieval.models import ChunkedNote
from lifeos.vault import VaultMarkdownFile

from .contracts import CaptureArtifact, CaptureError
from .extraction import ExtractionResult


@dataclass(frozen=True, slots=True)
class CaptureTextRepresentation:
    capture_id: str
    capture_path: str
    capture_hash: str
    text: str
    representation_kinds: tuple[str, ...]
    attachment_ids: tuple[str, ...]
    stale: bool
    metadata: dict[str, object]
    exclude_from_conversations: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaptureConversationEvidence:
    evidence_id: str
    capture_path: str
    capture_hash: str
    attachment_ids: tuple[str, ...]
    representation_kinds: tuple[str, ...]
    text: str
    stale: bool
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_capture_representation(
    capture: CaptureArtifact,
    *,
    extractions: tuple[ExtractionResult, ...] = (),
    include_derived: bool = True,
) -> CaptureTextRepresentation:
    if capture.metadata.exclude_from_semantic:
        raise CaptureError("semantic_excluded", "Capture is excluded from semantic retrieval.")
    if capture.metadata.privacy_scope == "protected" or capture.metadata.sensitive:
        raise CaptureError(
            "protected_semantic_denied",
            "Protected or sensitive captures are excluded from semantic retrieval by default.",
        )
    lines = [capture.metadata.title]
    kinds = ["user-description"]
    if capture.metadata.description:
        lines.append(capture.metadata.description)
    for value in capture.metadata.derived_values:
        if not include_derived or value.status not in {"confirmed", "corrected"}:
            continue
        lines.append(
            f"Confirmed field {value.field_name}: {value.value} {value.unit or ''} (source: {value.source})."
        )
        kinds.append(f"confirmed:{value.source}")
    stale = False
    approved_ids = {item.attachment_id for item in capture.metadata.attachments}
    for result in extractions:
        if result.attachment_id not in approved_ids:
            continue
        if result.source_hash != next(
            item.content_hash
            for item in capture.metadata.attachments
            if item.attachment_id == result.attachment_id
        ):
            stale = True
            continue
        if result.status == "stale":
            stale = True
            continue
        if result.status == "completed" and result.text:
            lines.append(
                f"[{result.method} extracted text from {result.attachment_id}]\n{result.text}"
            )
            kinds.append(result.method)
    return CaptureTextRepresentation(
        capture.metadata.capture_id,
        capture.path,
        capture.content_hash,
        "\n\n".join(line for line in lines if line.strip()),
        tuple(dict.fromkeys(kinds)),
        tuple(item.attachment_id for item in capture.metadata.attachments),
        stale,
        {
            "capture_type": capture.metadata.capture_type,
            "event_at": capture.metadata.event_at,
            "privacy_scope": capture.metadata.privacy_scope,
            "attachment_types": sorted({item.media_type for item in capture.metadata.attachments}),
            "linked_artifact_types": sorted(
                {item.artifact_type for item in capture.metadata.links}
            ),
        },
        exclude_from_conversations=capture.metadata.exclude_from_conversations,
    )


def chunk_capture_representation(
    representation: CaptureTextRepresentation, *, indexed_at: datetime | None = None
) -> ChunkedNote:
    frontmatter = {
        "id": representation.capture_id,
        "type": "rich-capture-evidence",
        "title": representation.text.splitlines()[0] if representation.text else "Capture evidence",
        "source": "rich-capture",
        "tags": ["rich-capture"],
        "capture_metadata": representation.metadata,
        "capture_hash": representation.capture_hash,
        "representation_kinds": list(representation.representation_kinds),
        "attachment_ids": list(representation.attachment_ids),
        "stale": representation.stale,
        "exclude_from_conversations": representation.exclude_from_conversations,
    }
    content = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n# Approved capture evidence\n\n{representation.text}\n"
    source = VaultMarkdownFile(
        representation.capture_path, Path(representation.capture_path), content, content.encode()
    )
    return chunk_markdown_file(source, indexed_at=indexed_at or datetime.now(timezone.utc))


def conversation_evidence(representation: CaptureTextRepresentation) -> CaptureConversationEvidence:
    if representation.exclude_from_conversations:
        raise CaptureError(
            "conversation_excluded",
            "Capture is excluded from knowledge conversations.",
        )
    return CaptureConversationEvidence(
        f"capture:{representation.capture_id}",
        representation.capture_path,
        representation.capture_hash,
        representation.attachment_ids,
        representation.representation_kinds,
        representation.text,
        representation.stale,
        "Evidence contains only approved user text, confirmed fields, and explicitly supplied extracted text. Representation kinds remain visible.",
    )
