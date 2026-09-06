"""Canonical, hash-bound persistence for externally acquired research evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import _atomic_write, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, read_vault_markdown

from .contracts import (
    RESEARCH_SOURCE_SCHEMA_VERSION,
    ResearchAcquisition,
    ResearchCaptureResult,
    ResearchError,
    ResearchOriginKind,
    ResearchSourceArtifact,
    ResearchSourceMetadata,
)

_EVIDENCE_START = "<!-- lifeos:research-evidence:start -->"
_EVIDENCE_END = "<!-- lifeos:research-evidence:end -->"


def _moment(value: datetime | None = None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ResearchError(
            "invalid_timestamp", "Research capture timestamps must be timezone-aware."
        )
    return moment.astimezone(timezone.utc)


def _trimmed(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _source_identity(
    *,
    source_locator: str | None,
    source_title: str,
    source_author: str | None,
    source_publisher: str | None,
) -> str:
    locator = _trimmed(source_locator)
    title = source_title.strip()
    author = _trimmed(source_author)
    publisher = _trimmed(source_publisher)
    basis: dict[str, str | None]
    if locator is not None:
        basis = {"kind": "locator", "locator": locator}
    else:
        if not title:
            raise ResearchError(
                "invalid_source_identity",
                "Research evidence without a locator requires a source title.",
            )
        basis = {
            "kind": "metadata",
            "title": title,
            "author": author,
            "publisher": publisher,
        }
    payload = json.dumps(
        basis,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest(payload)


def _artifact_id(source_identity: str, snapshot_hash: str) -> str:
    source_key = source_identity.removeprefix("sha256:")
    snapshot_key = snapshot_hash.removeprefix("sha256:")
    return f"research-{source_key[:12]}-{snapshot_key[:16]}"


def _artifact_path(source_identity: str, snapshot_hash: str) -> str:
    source_key = source_identity.removeprefix("sha256:")
    snapshot_key = snapshot_hash.removeprefix("sha256:")
    return f"raw/research/{source_key[:16]}/{snapshot_key[:32]}.md"


def _acquisition_id(
    *,
    captured_by: str,
    origin_kind: ResearchOriginKind,
    origin_ref: str | None,
    research_reason: str,
    research_context: str,
) -> str:
    payload = json.dumps(
        {
            "captured_by": captured_by.strip(),
            "origin_kind": origin_kind,
            "origin_ref": _trimmed(origin_ref),
            "research_reason": research_reason.strip(),
            "research_context": research_context.strip(),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"acq-{hashlib.sha256(payload).hexdigest()[:24]}"


def _metadata_hash(metadata: ResearchSourceMetadata) -> str:
    payload = json.dumps(
        metadata.to_frontmatter(),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest(payload)


def _document(metadata: ResearchSourceMetadata, evidence_text: str) -> str:
    frontmatter = metadata.to_frontmatter()
    frontmatter["metadata_hash"] = _metadata_hash(metadata)
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    return (
        f"---\n{dumped}\n---\n\n"
        "# Research evidence\n\n"
        f"{_EVIDENCE_START}\n{evidence_text}\n{_EVIDENCE_END}\n"
    )


def _extract_evidence(content: str) -> str:
    start = content.find(_EVIDENCE_START)
    if start < 0:
        raise ResearchError("malformed_artifact", "Research evidence start marker is missing.")
    evidence_start = start + len(_EVIDENCE_START)
    if not content.startswith("\n", evidence_start):
        raise ResearchError("malformed_artifact", "Research evidence start marker is malformed.")
    end = content.rfind(f"\n{_EVIDENCE_END}")
    if end < evidence_start + 1:
        raise ResearchError("malformed_artifact", "Research evidence end marker is missing.")
    return content[evidence_start + 1 : end]


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ResearchError("malformed_artifact", f"{name} must be an object.")
    return value


def _acquisition_from_dict(value: Mapping[str, Any]) -> ResearchAcquisition:
    try:
        return ResearchAcquisition(
            acquisition_id=str(value["acquisition_id"]),
            captured_at=str(value["captured_at"]),
            captured_by=str(value["captured_by"]),
            origin_kind=str(value["origin_kind"]),  # type: ignore[arg-type]
            research_reason=str(value["research_reason"]),
            origin_ref=str(value["origin_ref"]) if value.get("origin_ref") is not None else None,
            research_context=str(value.get("research_context", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ResearchError):
            raise
        raise ResearchError("malformed_artifact", "Research acquisition is malformed.") from exc


def _require_timestamp(value: str, *, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchError(
            "invalid_timestamp",
            f"Research {field} timestamp is malformed.",
            {"field": field},
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ResearchError(
            "invalid_timestamp",
            f"Research {field} timestamp must be UTC and timezone-aware.",
            {"field": field},
        )


def _validate_metadata_identity(
    *,
    relative_path: str,
    metadata: ResearchSourceMetadata,
    stored_metadata_hash: object,
) -> None:
    expected_source_identity = _source_identity(
        source_locator=metadata.source_locator,
        source_title=metadata.source_title,
        source_author=metadata.source_author,
        source_publisher=metadata.source_publisher,
    )
    if metadata.source_identity != expected_source_identity:
        raise ResearchError(
            "identity_mismatch",
            "Research source identity does not match its source metadata.",
            {"path": relative_path},
        )

    for acquisition in metadata.acquisitions:
        _require_timestamp(acquisition.captured_at, field="captured_at")
        expected_acquisition_id = _acquisition_id(
            captured_by=acquisition.captured_by,
            origin_kind=acquisition.origin_kind,
            origin_ref=acquisition.origin_ref,
            research_reason=acquisition.research_reason,
            research_context=acquisition.research_context,
        )
        if acquisition.acquisition_id != expected_acquisition_id:
            raise ResearchError(
                "identity_mismatch",
                "Research acquisition ID does not match its lineage fields.",
                {
                    "path": relative_path,
                    "acquisition_id": acquisition.acquisition_id,
                },
            )

    first = metadata.acquisitions[0]
    _require_timestamp(metadata.first_captured_at, field="first_captured_at")
    if (
        metadata.first_captured_at != first.captured_at
        or metadata.first_captured_by != first.captured_by
    ):
        raise ResearchError(
            "identity_mismatch",
            "Research first-capture metadata does not match the first acquisition.",
            {"path": relative_path},
        )

    if not isinstance(stored_metadata_hash, str):
        raise ResearchError(
            "metadata_mismatch",
            "Research source metadata hash is missing.",
            {"path": relative_path},
        )
    expected_metadata_hash = _metadata_hash(metadata)
    if stored_metadata_hash != expected_metadata_hash:
        raise ResearchError(
            "metadata_mismatch",
            "Research source metadata no longer matches its hash-bound capture record.",
            {"path": relative_path},
        )


def _parse(relative_path: str, source_path: Path, content: str) -> ResearchSourceArtifact:
    parsed = parse_markdown_note(source_path, content=content)
    finding = next((item for item in parsed.findings if item.severity == "error"), None)
    if finding is not None:
        raise ResearchError("malformed_artifact", finding.message, {"path": relative_path})

    frontmatter = dict(parsed.frontmatter)
    if frontmatter.get("type") != "research-source":
        raise ResearchError("unsupported_artifact", "The note is not a research source.")

    try:
        schema = int(frontmatter.get("research_schema", 0))
    except (TypeError, ValueError) as exc:
        raise ResearchError("unsupported_schema", "Research source schema is malformed.") from exc
    if schema != RESEARCH_SOURCE_SCHEMA_VERSION:
        raise ResearchError("unsupported_schema", "Research source schema is unsupported.")

    raw_acquisitions = frontmatter.get("acquisitions", [])
    if not isinstance(raw_acquisitions, list):
        raise ResearchError("malformed_artifact", "Research acquisitions must be a list.")
    acquisitions = tuple(
        _acquisition_from_dict(_mapping(item, "research acquisition")) for item in raw_acquisitions
    )

    try:
        metadata = ResearchSourceMetadata(
            artifact_id=str(frontmatter["artifact_id"]),
            source_identity=str(frontmatter["source_identity"]),
            snapshot_hash=str(frontmatter["snapshot_hash"]),
            source_title=str(frontmatter["source_title"]),
            first_captured_at=str(frontmatter["first_captured_at"]),
            first_captured_by=str(frontmatter["first_captured_by"]),
            acquisitions=acquisitions,
            source_locator=(
                str(frontmatter["source_locator"])
                if frontmatter.get("source_locator") is not None
                else None
            ),
            source_author=(
                str(frontmatter["source_author"])
                if frontmatter.get("source_author") is not None
                else None
            ),
            source_publisher=(
                str(frontmatter["source_publisher"])
                if frontmatter.get("source_publisher") is not None
                else None
            ),
            schema_version=schema,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ResearchError):
            raise
        raise ResearchError("malformed_artifact", "Research source metadata is malformed.") from exc

    _validate_metadata_identity(
        relative_path=relative_path,
        metadata=metadata,
        stored_metadata_hash=frontmatter.get("metadata_hash"),
    )

    evidence_text = _extract_evidence(content)
    actual_snapshot_hash = _digest(evidence_text.encode("utf-8"))
    if actual_snapshot_hash != metadata.snapshot_hash:
        raise ResearchError(
            "snapshot_mismatch",
            "Research evidence bytes no longer match the immutable snapshot hash.",
            {"path": relative_path},
        )

    expected_path = _artifact_path(metadata.source_identity, metadata.snapshot_hash)
    if relative_path != expected_path:
        raise ResearchError(
            "identity_mismatch",
            "Research source path does not match its hash-bound identity.",
            {"path": relative_path, "expected_path": expected_path},
        )

    expected_id = _artifact_id(metadata.source_identity, metadata.snapshot_hash)
    if metadata.artifact_id != expected_id:
        raise ResearchError(
            "identity_mismatch",
            "Research source artifact ID does not match its hash-bound identity.",
            {"path": relative_path},
        )

    return ResearchSourceArtifact(
        relative_path=relative_path,
        content_hash=f"sha256:{content_hash(content)}",
        metadata=metadata,
        evidence_text=evidence_text,
    )


def _same_optional(existing: str | None, incoming: str | None, field: str) -> str | None:
    normalized = _trimmed(incoming)
    if normalized is None:
        return existing
    if existing is None:
        return normalized
    if existing != normalized:
        raise ResearchError(
            "metadata_conflict",
            f"Research source {field} conflicts with the existing hash-bound source identity.",
            {"field": field},
        )
    return existing


class ResearchEvidenceService:
    """Controlled canonical boundary for immutable external evidence snapshots."""

    def __init__(self, *, vault_root: Path) -> None:
        self.vault_root = vault_root

    def load(self, relative_path: str) -> ResearchSourceArtifact:
        try:
            source = read_vault_markdown(self.vault_root, relative_path)
        except VaultAccessError as exc:
            raise ResearchError(exc.code, str(exc), {"path": relative_path}) from exc
        return _parse(source.relative_path, source.path, source.content)

    def capture(
        self,
        *,
        evidence_text: str,
        source_title: str,
        research_reason: str,
        captured_by: str,
        source_locator: str | None = None,
        source_author: str | None = None,
        source_publisher: str | None = None,
        origin_kind: ResearchOriginKind = "query",
        origin_ref: str | None = None,
        research_context: str = "",
        now: datetime | None = None,
    ) -> ResearchCaptureResult:
        if not isinstance(evidence_text, str) or not evidence_text.strip():
            raise ResearchError("invalid_field", "evidence_text must not be blank.")
        title = source_title.strip()
        reason = research_reason.strip()
        actor = captured_by.strip()
        if not title:
            raise ResearchError("invalid_field", "source_title must not be blank.")
        if not reason:
            raise ResearchError("invalid_field", "research_reason must not be blank.")
        if not actor:
            raise ResearchError("invalid_field", "captured_by must not be blank.")
        if origin_kind not in {"query", "conversation", "manual", "other"}:
            raise ResearchError("invalid_origin", "Research origin kind is unsupported.")

        moment = _moment(now)
        captured_at = moment.isoformat()
        locator = _trimmed(source_locator)
        author = _trimmed(source_author)
        publisher = _trimmed(source_publisher)
        ref = _trimmed(origin_ref)
        context = research_context.strip()

        source_identity = _source_identity(
            source_locator=locator,
            source_title=title,
            source_author=author,
            source_publisher=publisher,
        )
        snapshot_hash = _digest(evidence_text.encode("utf-8"))
        artifact_id = _artifact_id(source_identity, snapshot_hash)
        relative_path = _artifact_path(source_identity, snapshot_hash)
        acquisition_id = _acquisition_id(
            captured_by=actor,
            origin_kind=origin_kind,
            origin_ref=ref,
            research_reason=reason,
            research_context=context,
        )
        acquisition = ResearchAcquisition(
            acquisition_id=acquisition_id,
            captured_at=captured_at,
            captured_by=actor,
            origin_kind=origin_kind,
            research_reason=reason,
            origin_ref=ref,
            research_context=context,
        )

        try:
            current = self.load(relative_path)
        except ResearchError as exc:
            if exc.code != "not-found":
                raise
            metadata = ResearchSourceMetadata(
                artifact_id=artifact_id,
                source_identity=source_identity,
                snapshot_hash=snapshot_hash,
                source_title=title,
                source_locator=locator,
                source_author=author,
                source_publisher=publisher,
                first_captured_at=captured_at,
                first_captured_by=actor,
                acquisitions=(acquisition,),
            )
            document = _document(metadata, evidence_text)
            try:
                _atomic_write(
                    self.vault_root,
                    relative_path,
                    document,
                    expected_hash=None,
                    create=True,
                )
            except DailyInteractionError as write_error:
                if write_error.code != "conflict":
                    raise ResearchError(
                        "storage_unavailable",
                        "Research evidence could not be persisted.",
                    ) from write_error
                current = self.load(relative_path)
            else:
                artifact = self.load(relative_path)
                return ResearchCaptureResult(
                    artifact=artifact,
                    acquisition_id=acquisition_id,
                    created=True,
                    acquisition_added=True,
                )

        if current.metadata.source_identity != source_identity:
            raise ResearchError("identity_mismatch", "Existing research source identity changed.")
        if (
            current.metadata.snapshot_hash != snapshot_hash
            or current.evidence_text != evidence_text
        ):
            raise ResearchError(
                "snapshot_mismatch",
                "Existing research source does not match the submitted immutable snapshot.",
            )
        if current.metadata.source_title != title:
            raise ResearchError(
                "metadata_conflict",
                "Research source title conflicts with the existing source snapshot.",
                {"field": "source_title"},
            )

        merged_author = _same_optional(current.metadata.source_author, author, "source_author")
        merged_publisher = _same_optional(
            current.metadata.source_publisher,
            publisher,
            "source_publisher",
        )
        merged_locator = _same_optional(
            current.metadata.source_locator,
            locator,
            "source_locator",
        )

        if any(item.acquisition_id == acquisition_id for item in current.metadata.acquisitions):
            return ResearchCaptureResult(
                artifact=current,
                acquisition_id=acquisition_id,
                created=False,
                acquisition_added=False,
            )

        metadata = replace(
            current.metadata,
            source_locator=merged_locator,
            source_author=merged_author,
            source_publisher=merged_publisher,
            acquisitions=(*current.metadata.acquisitions, acquisition),
        )
        document = _document(metadata, current.evidence_text)
        try:
            _atomic_write(
                self.vault_root,
                relative_path,
                document,
                expected_hash=current.content_hash.removeprefix("sha256:"),
                create=False,
            )
        except DailyInteractionError as exc:
            if exc.code == "stale_write":
                raise ResearchError(
                    "stale_artifact",
                    "Research acquisition lineage changed during capture.",
                    {"path": relative_path},
                ) from exc
            raise ResearchError(
                "storage_unavailable",
                "Research acquisition lineage could not be persisted.",
            ) from exc

        artifact = self.load(relative_path)
        return ResearchCaptureResult(
            artifact=artifact,
            acquisition_id=acquisition_id,
            created=False,
            acquisition_added=True,
        )
