"""Canonical Markdown persistence for rich captures and attachment manifests."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from lifeos.daily.service import _atomic_write, content_hash
from lifeos.markdown.parser import parse_markdown_note, replace_managed_block, splice_managed_block
from lifeos.vault import VaultAccessError, VaultMarkdownFile, iter_vault_markdown, read_vault_markdown

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
_MANIFEST_START = "<!-- lifeos:managed:start attachment-manifest -->"
_MANIFEST_END = "<!-- lifeos:managed:end attachment-manifest -->"
_CAPTURE_ID_RE = re.compile(r"^cap-(\d{8}T\d{6}Z)-[a-f0-9]{8}$")
_ATTACHMENT_ID_RE = re.compile(r"^att-[a-f0-9]{16}$")
_RESERVED_SOURCE_ENTRY_PREFIXES = ("capture-mutation:", "capture-mutation-source:")
_RESERVED_ARCHIVE_REASON_PREFIXES = ("merged into", "split into")


def _validate_public_capture_lineage(value: str, *, field: str) -> None:
    normalized = value.strip()
    if field == "source_entry_point":
        reserved = any(normalized.startswith(prefix) for prefix in _RESERVED_SOURCE_ENTRY_PREFIXES)
    elif field == "reason":
        reserved = any(normalized.startswith(prefix) for prefix in _RESERVED_ARCHIVE_REASON_PREFIXES)
    else:
        raise ValueError(f"Unsupported capture lineage field: {field}")
    if reserved:
        raise CaptureError(
            "reserved_capture_lineage",
            f"{field} uses a reserved capture mutation lineage value.",
            {"field": field},
        )


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
        _CAPTURE_START,
        "# Capture summary",
        "",
        f"**Type:** `{metadata.capture_type}`  ",
        f"**State:** `{metadata.state}`  ",
        f"**Event time:** {metadata.event_at}  ",
        f"**Privacy:** `{metadata.privacy_scope}`",
        "",
        "## Attachments",
        "",
    ]
    if metadata.attachments:
        lines.extend(
            f"- [[{item.manifest_path}|{item.original_filename}]] · `{item.media_type}` · {item.byte_size} bytes · `{item.content_hash}`"
            for item in metadata.attachments
        )
    else:
        lines.append("- No attachments.")
    lines.extend(["", "## Linked artifacts", ""])
    if metadata.links:
        lines.extend(
            f"- [[{item.path}|{item.relation}]] · `{item.artifact_type}`" for item in metadata.links
        )
    else:
        lines.append("- No linked artifacts.")
    lines.extend(["", "## Derived and confirmed values", ""])
    if metadata.derived_values:
        for item in metadata.derived_values:
            value = "unknown" if item.value is None else str(item.value)
            range_text = (
                ""
                if item.range_low is None and item.range_high is None
                else f"; range {item.range_low}–{item.range_high}"
            )
            unit = f" {item.unit}" if item.unit else ""
            lines.append(
                f"- `{item.field_name}`: {value}{unit}{range_text} · `{item.source}` · `{item.confidence}` · `{item.status}`"
            )
    else:
        lines.append("- No derived values.")
    lines.extend(
        [
            "",
            "## Processing",
            "",
            f"- Extraction: `{metadata.extraction_status}`",
            f"- Enrichment: `{metadata.enrichment_status}`",
            _CAPTURE_END,
        ]
    )
    return "\n".join(lines)


def _capture_document(metadata: CaptureMetadata, human_body: str) -> str:
    dumped = yaml.safe_dump(metadata.to_frontmatter(), sort_keys=False, allow_unicode=True).rstrip()
    human = human_body.strip("\n") or "## User annotations\n\n"
    return f"---\n{dumped}\n---\n\n{_render_capture(metadata)}\n\n{human}\n"


def _render_manifest(metadata: AttachmentManifest) -> str:
    duplicate = metadata.duplicate_of or "none"
    return "\n".join(
        [
            _MANIFEST_START,
            "# Attachment manifest",
            "",
            f"**Original filename:** {metadata.original_filename}  ",
            f"**Media type:** `{metadata.media_type}`  ",
            f"**Size:** {metadata.byte_size} bytes  ",
            f"**Content hash:** `{metadata.content_hash}`  ",
            f"**Canonical path:** `{metadata.canonical_path}`  ",
            f"**Duplicate of:** `{duplicate}`",
            "",
            "## Processing",
            "",
            f"- Extraction: `{metadata.extraction_status}`",
            f"- Preview: `{metadata.preview_status}`",
            f"- Transcript: `{metadata.transcript_status}`",
            _MANIFEST_END,
        ]
    )


def _manifest_document(metadata: AttachmentManifest, human_body: str) -> str:
    dumped = yaml.safe_dump(metadata.to_frontmatter(), sort_keys=False, allow_unicode=True).rstrip()
    human = human_body.strip("\n") or "## User annotations\n\n"
    return f"---\n{dumped}\n---\n\n{_render_manifest(metadata)}\n\n{human}\n"


def _read_source(vault_root: Path, relative_path: str) -> VaultMarkdownFile:
    try:
        return read_vault_markdown(vault_root, relative_path)
    except VaultAccessError as exc:
        raise CaptureError(exc.code, str(exc), {"path": relative_path}) from exc


def _updated_document(
    source: VaultMarkdownFile, frontmatter: dict[str, object], managed: str
) -> str:
    parsed = parse_markdown_note(source.path, content=source.content)
    try:
        body = replace_managed_block(parsed.body, parsed.managed_blocks[0], managed)
    except ValueError as error:
        raise CaptureError("malformed_artifact", str(error), {"path": source.relative_path}) from error
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{dumped}\n---\n{body}"


def _parse(
    path: Path, relative_path: str, content: str, *, expected_type: str, block_name: str
) -> tuple[dict[str, object], str]:
    parsed = parse_markdown_note(path, content=content)
    error = next((item for item in parsed.findings if item.severity == "error"), None)
    if error is not None:
        raise CaptureError("malformed_artifact", error.message, {"path": relative_path})
    frontmatter = dict(parsed.frontmatter)
    if frontmatter.get("type") != expected_type:
        raise CaptureError("unsupported_artifact", f"The note is not a {expected_type}.")
    matches = [block for block in parsed.managed_blocks if block.name == block_name]
    if len(matches) != 1 or len(parsed.managed_blocks) != 1:
        raise CaptureError(
            "malformed_artifact", f"The managed {expected_type} block must appear exactly once."
        )
    human = splice_managed_block(parsed.body, matches[0], "").strip("\n") + "\n"
    return frontmatter, human


def parse_capture(path: Path, relative_path: str, content: str) -> CaptureArtifact:
    data, human = _parse(
        path, relative_path, content, expected_type="rich-capture", block_name="rich-capture"
    )
    return CaptureArtifact(
        relative_path, "sha256:" + content_hash(content), capture_metadata_from_dict(data), human
    )


def parse_manifest(path: Path, relative_path: str, content: str) -> AttachmentManifestArtifact:
    data, human = _parse(
        path,
        relative_path,
        content,
        expected_type="attachment-manifest",
        block_name="attachment-manifest",
    )
    return AttachmentManifestArtifact(
        relative_path, "sha256:" + content_hash(content), attachment_manifest_from_dict(data), human
    )


@dataclass(frozen=True, slots=True)
class PreparedCapture:
    artifact: CaptureArtifact
    content: str


class CaptureArtifactService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir

    def create(
        self,
        *,
        title: str,
        capture_type: CaptureType,
        description: str = "",
        event_at: datetime | None = None,
        timezone_name: str = "UTC",
        source_entry_point: str = "unknown",
        privacy_scope: PrivacyScope = "standard",
        sensitive: bool = False,
        attachments: tuple[AttachmentReference, ...] = (),
        links: tuple[ArtifactLink, ...] = (),
        tags: tuple[str, ...] = (),
        exclude_from_semantic: bool = False,
        exclude_from_conversations: bool = False,
        exclude_from_reviews: bool = False,
        exclude_from_experiments: bool = False,
        now: datetime | None = None,
    ) -> CaptureArtifact:
        _validate_public_capture_lineage(source_entry_point, field="source_entry_point")
        prepared = self.prepare_create(
            title=title,
            capture_type=capture_type,
            description=description,
            event_at=event_at,
            timezone_name=timezone_name,
            source_entry_point=source_entry_point,
            privacy_scope=privacy_scope,
            sensitive=sensitive,
            attachments=attachments,
            links=links,
            tags=tags,
            exclude_from_semantic=exclude_from_semantic,
            exclude_from_conversations=exclude_from_conversations,
            exclude_from_reviews=exclude_from_reviews,
            exclude_from_experiments=exclude_from_experiments,
            now=now,
        )
        _atomic_write(
            self.vault_root,
            prepared.artifact.path,
            prepared.content,
            expected_hash=None,
            create=True,
        )
        return self.load(prepared.artifact.path)

    def prepare_create(
        self,
        *,
        title: str,
        capture_type: CaptureType,
        description: str = "",
        event_at: datetime | None = None,
        timezone_name: str = "UTC",
        source_entry_point: str = "unknown",
        privacy_scope: PrivacyScope = "standard",
        sensitive: bool = False,
        attachments: tuple[AttachmentReference, ...] = (),
        links: tuple[ArtifactLink, ...] = (),
        tags: tuple[str, ...] = (),
        exclude_from_semantic: bool = False,
        exclude_from_conversations: bool = False,
        exclude_from_reviews: bool = False,
        exclude_from_experiments: bool = False,
        capture_id: str | None = None,
        merged_from: tuple[str, ...] = (),
        split_from: str | None = None,
        human_body: str = "## User annotations\n\n",
        now: datetime | None = None,
    ) -> PreparedCapture:
        moment = utc_now(now)
        event = event_at or moment
        if event.tzinfo is None:
            raise CaptureError("invalid_timestamp", "Event timestamp must include a timezone.")
        selected_capture_id = capture_id or (
            f"cap-{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
        )
        lifecycle = LifecycleEvent(
            f"life-{secrets.token_hex(6)}", None, "captured", moment.isoformat(), "created"
        )
        provenance = ProvenanceRecord(
            "capture", source_entry_point, moment.isoformat(), "Original user capture preserved."
        )
        metadata = CaptureMetadata(
            capture_id=selected_capture_id,
            title=title.strip() or "Untitled capture",
            description=description.strip(),
            capture_type=capture_type,
            state="captured",
            captured_at=moment.isoformat(),
            event_at=event.isoformat(),
            timezone=timezone_name.strip() or "UTC",
            source_entry_point=source_entry_point.strip() or "unknown",
            privacy_scope=privacy_scope,
            sensitive=sensitive,
            tags=tags,
            attachments=attachments,
            links=links,
            provenance=(provenance,),
            lifecycle=(lifecycle,),
            merged_from=merged_from,
            split_from=split_from,
            exclude_from_semantic=exclude_from_semantic,
            exclude_from_conversations=exclude_from_conversations,
            exclude_from_reviews=exclude_from_reviews,
            exclude_from_experiments=exclude_from_experiments,
            created_at=moment.isoformat(),
            updated_at=moment.isoformat(),
        )
        path = capture_path(metadata)
        content = _capture_document(metadata, human_body)
        return PreparedCapture(parse_capture(self.vault_root / path, path, content), content)

    def prepare_transition(
        self,
        artifact: CaptureArtifact,
        target: CaptureState,
        *,
        reason: str = "",
        provenance_record: ProvenanceRecord | None = None,
        now: datetime | None = None,
    ) -> PreparedCapture:
        source = _read_source(self.vault_root, artifact.path)
        current = parse_capture(source.path, source.relative_path, source.content)
        if current.content_hash != artifact.content_hash:
            raise CaptureError(
                "stale_capture",
                "Capture changed after it was opened.",
                {"actual_hash": current.content_hash},
            )
        validate_transition(artifact.metadata.state, target)
        moment = utc_now(now)
        event = LifecycleEvent(
            f"life-{secrets.token_hex(6)}",
            artifact.metadata.state,
            target,
            moment.isoformat(),
            reason.strip(),
        )
        metadata = replace(
            artifact.metadata,
            state=target,
            updated_at=moment.isoformat(),
            lifecycle=(*artifact.metadata.lifecycle, event),
            provenance=(
                artifact.metadata.provenance
                if provenance_record is None
                else (*artifact.metadata.provenance, provenance_record)
            ),
        )
        content = _updated_document(source, metadata.to_frontmatter(), _render_capture(metadata))
        return PreparedCapture(
            parse_capture(self.vault_root / artifact.path, artifact.path, content), content
        )

    def load(self, relative_path: str) -> CaptureArtifact:
        source = _read_source(self.vault_root, relative_path)
        return parse_capture(source.path, source.relative_path, source.content)

    def list(
        self, *, capture_types: frozenset[str] | None = None, states: frozenset[str] | None = None
    ) -> tuple[CaptureArtifact, ...]:
        try:
            sources = iter_vault_markdown(self.vault_root, roots=("captures",))
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return ()
            raise CaptureError(exc.code, str(exc)) from exc
        items = tuple(
            parse_capture(item.path, item.relative_path, item.content) for item in sources
        )
        selected = tuple(
            item
            for item in items
            if (capture_types is None or item.metadata.capture_type in capture_types)
            and (states is None or item.metadata.state in states)
        )
        return tuple(
            sorted(
                selected,
                key=lambda item: (item.metadata.event_at, item.metadata.capture_id),
                reverse=True,
            )
        )

    def save(
        self, artifact: CaptureArtifact, metadata: CaptureMetadata, *, expected_hash: str
    ) -> CaptureArtifact:
        source = _read_source(self.vault_root, artifact.path)
        current = parse_capture(source.path, source.relative_path, source.content)
        if current.content_hash != expected_hash:
            raise CaptureError(
                "stale_capture",
                "Capture changed after it was opened.",
                {"actual_hash": current.content_hash},
            )
        document = _updated_document(source, metadata.to_frontmatter(), _render_capture(metadata))
        parse_capture(self.vault_root / artifact.path, artifact.path, document)
        _atomic_write(
            self.vault_root,
            artifact.path,
            document,
            expected_hash=expected_hash.removeprefix("sha256:"),
            create=False,
        )
        return self.load(artifact.path)

    def update_user_fields(
        self,
        relative_path: str,
        *,
        expected_hash: str,
        title: str | None = None,
        description: str | None = None,
        event_at: str | None = None,
        tags: tuple[str, ...] | None = None,
        location: str | None = None,
        privacy_scope: PrivacyScope | None = None,
        sensitive: bool | None = None,
        now: datetime | None = None,
    ) -> CaptureArtifact:
        artifact = self.load(relative_path)
        moment = utc_now(now)
        metadata = replace(
            artifact.metadata,
            title=title.strip() if title is not None and title.strip() else artifact.metadata.title,
            description=description.strip()
            if description is not None
            else artifact.metadata.description,
            event_at=event_at or artifact.metadata.event_at,
            tags=tags if tags is not None else artifact.metadata.tags,
            location=location if location is not None else artifact.metadata.location,
            privacy_scope=privacy_scope or artifact.metadata.privacy_scope,
            sensitive=artifact.metadata.sensitive if sensitive is None else sensitive,
            updated_at=moment.isoformat(),
        )
        return self.save(artifact, metadata, expected_hash=expected_hash)

    def transition(
        self,
        relative_path: str,
        target: CaptureState,
        *,
        expected_hash: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> CaptureArtifact:
        _validate_public_capture_lineage(reason, field="reason")
        artifact = self.load(relative_path)
        prepared = self.prepare_transition(artifact, target, reason=reason, now=now)
        return self.save(artifact, prepared.artifact.metadata, expected_hash=expected_hash)


class AttachmentManifestService:
    def __init__(self, *, vault_root: Path) -> None:
        self.vault_root = vault_root

    def create(
        self, metadata: AttachmentManifest, *, human_body: str = "## User annotations\n\n"
    ) -> AttachmentManifestArtifact:
        path = manifest_path(metadata.attachment_id)
        document = _manifest_document(metadata, human_body)
        parse_manifest(self.vault_root / path, path, document)
        _atomic_write(
            self.vault_root,
            path,
            document,
            expected_hash=None,
            create=True,
        )
        return self.load(path)

    def load(self, relative_path: str) -> AttachmentManifestArtifact:
        source = _read_source(self.vault_root, relative_path)
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

    def save(
        self,
        artifact: AttachmentManifestArtifact,
        metadata: AttachmentManifest,
        *,
        expected_hash: str,
    ) -> AttachmentManifestArtifact:
        source = _read_source(self.vault_root, artifact.path)
        current = parse_manifest(source.path, source.relative_path, source.content)
        if current.content_hash != expected_hash:
            raise CaptureError(
                "stale_manifest",
                "Attachment manifest changed after it was opened.",
                {"actual_hash": current.content_hash},
            )
        document = _updated_document(source, metadata.to_frontmatter(), _render_manifest(metadata))
        parse_manifest(self.vault_root / artifact.path, artifact.path, document)
        _atomic_write(
            self.vault_root,
            artifact.path,
            document,
            expected_hash=expected_hash.removeprefix("sha256:"),
            create=False,
        )
        return self.load(artifact.path)