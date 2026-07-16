"""Canonical Markdown persistence for rich captures and attachment manifests."""

from __future__ import annotations

import re
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from lifeos.daily.service import _atomic_write, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

from .contracts import (
    ArtifactLink,
    AttachmentManifest,
    AttachmentManifestArtifact,
    AttachmentReference,
    CaptureArtifact,
    CaptureError,
    CaptureMetadata,
    CaptureState,
    CaptureType,
    LifecycleEvent,
    PrivacyScope,
    ProvenanceRecord,
    attachment_manifest_from_dict,
    capture_metadata_from_dict,
    validate_transition,
)

_CAPTURE_START = "<!-- lifeos:managed:start rich-capture -->"
_CAPTURE_END = "<!-- lifeos:managed:end rich-capture -->"
_CAPTURE_RE = re.compile(re.escape(_CAPTURE_START) + r".*?" + re.escape(_CAPTURE_END), re.S)
_MANIFEST_START = "<!-- lifeos:managed:start attachment-manifest -->"
_MANIFEST_END = "<!-- lifeos:managed:end attachment-manifest -->"
_MANIFEST_RE = re.compile(re.escape(_MANIFEST_START) + r".*?" + re.escape(_MANIFEST_END), re.S)
_CAPTURE_ID_RE = re.compile(r"^cap-(\d{8}T\d{6}Z)-[a-f0-9]{8}$")
_ATTACHMENT_ID_RE = re.compile(r"^att-[a-f0-9]{16}$")


def utc_now(value: datetime | None = None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise CaptureError("invalid_timestamp", "Capture timestamps must include a timezone.")
    return moment.astimezone(timezone.utc)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:64] or "capture"


def capture_path(metadata: CaptureMetadata) -> str:
    match = _CAPTURE_ID_RE.fullmatch(metadata.capture_id)
    if match is None:
        raise CaptureError("invalid_capture", "Capture ID is malformed.")
    return f"captures/{match.group(1)[:4]}/{_slug(metadata.title)}-{metadata.capture_id}.md"


def manifest_path(attachment_id: str) -> str:
    if _ATTACHMENT_ID_RE.fullmatch(attachment_id) is None:
        raise CaptureError("invalid_attachment", "Attachment ID is malformed.")
    return f"attachments/manifests/{attachment_id}.md"


def _render_capture(metadata: CaptureMetadata) -> str:
    lines = [
        _CAPTURE_START, "# Capture summary", "",
        f"**Type:** `{metadata.capture_type}`  ", f"**State:** `{metadata.state}`  ",
        f"**Event time:** {metadata.event_at}  ", f"**Privacy:** `{metadata.privacy_scope}`",
        "", "## Attachments", "",
    ]
    if metadata.attachments:
        lines.extend(f"- [[{item.manifest_path}|{item.original_filename}]] · `{item.media_type}` · {item.byte_size} bytes · `{item.content_hash}`" for item in metadata.attachments)
    else:
        lines.append("- No attachments.")
    lines.extend(["", "## Linked artifacts", ""])
    if metadata.links:
        lines.extend(f"- [[{item.path}|{item.relation}]] · `{item.artifact_type}`" for item in metadata.links)
    else:
        lines.append("- No linked artifacts.")
    lines.extend(["", "## Derived and confirmed values", ""])
    if metadata.derived_values:
        for item in metadata.derived_values:
            value = "unknown" if item.value is None else str(item.value)
            range_text = "" if item.range_low is None and item.range_high is None else f"; range {item.range_low}–{item.range_high}"
            unit = f" {item.unit}" if item.unit else ""
            lines.append(f"- `{item.field_name}`: {value}{unit}{range_text} · `{item.source}` · `{item.confidence}` · `{item.status}`")
    else:
        lines.append("- No derived values.")
    lines.extend(["", "## Processing", "", f"- Extraction: `{metadata.extraction_status}`", f"- Enrichment: `{metadata.enrichment_status}`", _CAPTURE_END])
    return "\n".join(lines)


def _capture_document(metadata: CaptureMetadata, human_body: str) -> str:
    dumped = yaml.safe_dump(metadata.to_frontmatter(), sort_keys=False, allow_unicode=True).rstrip()
    human = human_body.strip("\n") or "## User annotations\n\n"
    return f"---\n{dumped}\n---\n\n{_render_capture(metadata)}\n\n{human}\n"


def _render_manifest(metadata: AttachmentManifest) -> str:
    duplicate = metadata.duplicate_of or "none"
    return "\n".join([
        _MANIFEST_START, "# Attachment manifest", "",
        f"**Original filename:** {metadata.original_filename}  ", f"**Media type:** `{metadata.media_type}`  ",
        f"**Size:** {metadata.byte_size} bytes  ", f"**Content hash:** `{metadata.content_hash}`  ",
        f"**Canonical path:** `{metadata.canonical_path}`  ", f"**Duplicate of:** `{duplicate}`",
        "", "## Processing", "", f"- Extraction: `{metadata.extraction_status}`", f"- Preview: `{metadata.preview_status}`", f"- Transcript: `{metadata.transcript_status}`",
        _MANIFEST_END,
    ])


def _manifest_document(metadata: AttachmentManifest, human_body: str) -> str:
    dumped = yaml.safe_dump(metadata.to_frontmatter(), sort_keys=False, allow_unicode=True).rstrip()
    human = human_body.strip("\n") or "## User annotations\n\n"
    return f"---\n{dumped}\n---\n\n{_render_manifest(metadata)}\n\n{human}\n"


def _parse(path: Path, relative_path: str, content: str, *, expected_type: str, block_re: re.Pattern[str]) -> tuple[dict[str, object], str]:
    parsed = parse_markdown_note(path, content=content)
    error = next((item for item in parsed.findings if item.severity == "error"), None)
    if error is not None:
        raise CaptureError("malformed_artifact", error.message, {"path": relative_path})
    frontmatter = dict(parsed.frontmatter)
    if frontmatter.get("type") != expected_type:
        raise CaptureError("unsupported_artifact", f"The note is not a {expected_type}.")
    matches = list(block_re.finditer(parsed.body))
    if len(matches) != 1:
        raise CaptureError("malformed_artifact", f"The managed {expected_type} block must appear exactly once.")
    match = matches[0]
    human = (parsed.body[: match.start()] + parsed.body[match.end() :]).strip("\n") + "\n"
    return frontmatter, human


def parse_capture(path: Path, relative_path: str, content: str) -> CaptureArtifact:
    data, human = _parse(path, relative_path, content, expected_type="rich-capture", block_re=_CAPTURE_RE)
    return CaptureArtifact(relative_path, "sha256:" + content_hash(content), capture_metadata_from_dict(data), human)


def parse_manifest(path: Path, relative_path: str, content: str) -> AttachmentManifestArtifact:
    data, human = _parse(path, relative_path, content, expected_type="attachment-manifest", block_re=_MANIFEST_RE)
    return AttachmentManifestArtifact(relative_path, "sha256:" + content_hash(content), attachment_manifest_from_dict(data), human)


class CaptureArtifactService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir

    def create(self, *, title: str, capture_type: CaptureType, description: str = "", event_at: datetime | None = None, timezone_name: str = "UTC", source_entry_point: str = "unknown", privacy_scope: PrivacyScope = "standard", sensitive: bool = False, attachments: tuple[AttachmentReference, ...] = (), links: tuple[ArtifactLink, ...] = (), tags: tuple[str, ...] = (), now: datetime | None = None) -> CaptureArtifact:
        moment = utc_now(now)
        event = event_at or moment
        if event.tzinfo is None:
            raise CaptureError("invalid_timestamp", "Event timestamp must include a timezone.")
        capture_id = f"cap-{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
        lifecycle = LifecycleEvent(f"life-{secrets.token_hex(6)}", None, "captured", moment.isoformat(), "created")
        provenance = ProvenanceRecord("capture", source_entry_point, moment.isoformat(), "Original user capture preserved.")
        metadata = CaptureMetadata(capture_id=capture_id, title=title.strip() or "Untitled capture", description=description.strip(), capture_type=capture_type, state="captured", captured_at=moment.isoformat(), event_at=event.isoformat(), timezone=timezone_name.strip() or "UTC", source_entry_point=source_entry_point.strip() or "unknown", privacy_scope=privacy_scope, sensitive=sensitive, tags=tags, attachments=attachments, links=links, provenance=(provenance,), lifecycle=(lifecycle,), created_at=moment.isoformat(), updated_at=moment.isoformat())
        path = capture_path(metadata)
        _atomic_write(self.vault_root, path, _capture_document(metadata, "## User annotations\n\n"), expected_hash=None, create=True)
        return self.load(path)

    def load(self, relative_path: str) -> CaptureArtifact:
        try:
            source = read_vault_markdown(self.vault_root, relative_path)
        except VaultAccessError as exc:
            raise CaptureError(exc.code, str(exc), {"path": relative_path}) from exc
        return parse_capture(source.path, source.relative_path, source.content)

    def list(self, *, capture_types: frozenset[str] | None = None, states: frozenset[str] | None = None) -> tuple[CaptureArtifact, ...]:
        try:
            sources = iter_vault_markdown(self.vault_root, roots=("captures",))
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return ()
            raise CaptureError(exc.code, str(exc)) from exc
        items = tuple(parse_capture(item.path, item.relative_path, item.content) for item in sources)
        selected = tuple(item for item in items if (capture_types is None or item.metadata.capture_type in capture_types) and (states is None or item.metadata.state in states))
        return tuple(sorted(selected, key=lambda item: (item.metadata.event_at, item.metadata.capture_id), reverse=True))

    def save(self, artifact: CaptureArtifact, metadata: CaptureMetadata, *, expected_hash: str) -> CaptureArtifact:
        current = self.load(artifact.path)
        if current.content_hash != expected_hash:
            raise CaptureError("stale_capture", "Capture changed after it was opened.", {"actual_hash": current.content_hash})
        _atomic_write(self.vault_root, artifact.path, _capture_document(metadata, current.human_body), expected_hash=expected_hash.removeprefix("sha256:"), create=False)
        return self.load(artifact.path)

    def update_user_fields(self, relative_path: str, *, expected_hash: str, title: str | None = None, description: str | None = None, event_at: str | None = None, tags: tuple[str, ...] | None = None, location: str | None = None, privacy_scope: PrivacyScope | None = None, sensitive: bool | None = None, now: datetime | None = None) -> CaptureArtifact:
        artifact = self.load(relative_path)
        moment = utc_now(now)
        metadata = replace(artifact.metadata, title=title.strip() if title is not None and title.strip() else artifact.metadata.title, description=description.strip() if description is not None else artifact.metadata.description, event_at=event_at or artifact.metadata.event_at, tags=tags if tags is not None else artifact.metadata.tags, location=location if location is not None else artifact.metadata.location, privacy_scope=privacy_scope or artifact.metadata.privacy_scope, sensitive=artifact.metadata.sensitive if sensitive is None else sensitive, updated_at=moment.isoformat())
        return self.save(artifact, metadata, expected_hash=expected_hash)

    def transition(self, relative_path: str, target: CaptureState, *, expected_hash: str, reason: str = "", now: datetime | None = None) -> CaptureArtifact:
        artifact = self.load(relative_path)
        validate_transition(artifact.metadata.state, target)
        moment = utc_now(now)
        event = LifecycleEvent(f"life-{secrets.token_hex(6)}", artifact.metadata.state, target, moment.isoformat(), reason.strip())
        metadata = replace(artifact.metadata, state=target, updated_at=moment.isoformat(), lifecycle=(*artifact.metadata.lifecycle, event))
        return self.save(artifact, metadata, expected_hash=expected_hash)


class AttachmentManifestService:
    def __init__(self, *, vault_root: Path) -> None:
        self.vault_root = vault_root

    def create(self, metadata: AttachmentManifest, *, human_body: str = "## User annotations\n\n") -> AttachmentManifestArtifact:
        path = manifest_path(metadata.attachment_id)
        _atomic_write(self.vault_root, path, _manifest_document(metadata, human_body), expected_hash=None, create=True)
        return self.load(path)

    def load(self, relative_path: str) -> AttachmentManifestArtifact:
        try:
            source = read_vault_markdown(self.vault_root, relative_path)
        except VaultAccessError as exc:
            raise CaptureError(exc.code, str(exc), {"path": relative_path}) from exc
        return parse_manifest(source.path, source.relative_path, source.content)

    def list(self) -> tuple[AttachmentManifestArtifact, ...]:
        try:
            sources = iter_vault_markdown(self.vault_root, roots=("attachments",))
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return ()
            raise CaptureError(exc.code, str(exc)) from exc
        return tuple(
            parse_manifest(item.path, item.relative_path, item.content)
            for item in sources
            if item.relative_path.startswith("attachments/manifests/")
        )

    def save(self, artifact: AttachmentManifestArtifact, metadata: AttachmentManifest, *, expected_hash: str) -> AttachmentManifestArtifact:
        current = self.load(artifact.path)
        if current.content_hash != expected_hash:
            raise CaptureError("stale_manifest", "Attachment manifest changed after it was opened.", {"actual_hash": current.content_hash})
        _atomic_write(self.vault_root, artifact.path, _manifest_document(metadata, current.human_body), expected_hash=expected_hash.removeprefix("sha256:"), create=False)
        return self.load(artifact.path)
