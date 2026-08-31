"""Inspectable, bounded privacy previews for optional rich-capture processing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lifeos.daily.service import content_hash
from lifeos.retrieval.contracts import (
    RetrievalError,
    RetrievalPolicy,
    ScopeDecision,
    provider_path_decision,
)
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import CaptureArtifactService, manifest_path
from .contracts import CaptureError
from .extraction import LocalExtractionService
from .storage import AttachmentStore

# Backwards-compatible legacy module export. Enforcement loads the current vault policy instead.
PROTECTED_ROOTS = frozenset({"diary", "health", "medical", "private", "therapy", "photos"})
_DISCLOSURE = (
    "Only the listed text excerpts or explicitly selected original files would be sent. "
    "Linked notes are not traversed automatically, and previewing this disclosure does not "
    "upload anything."
)


@dataclass(frozen=True, slots=True)
class CapturePayloadItem:
    path: str
    kind: str
    content_hash: str
    inclusion_reason: str
    transfer: str
    byte_count: int
    included_bytes: int
    truncated: bool
    excerpt: str = ""
    attachment_id: str | None = None
    media_type: str | None = None
    redactions: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "redactions": [dict(item) for item in self.redactions]}


@dataclass(frozen=True, slots=True)
class CapturePayloadOmission:
    path: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaptureContextPreview:
    capture_path: str
    requested_operations: tuple[str, ...]
    external_processing_intent: bool
    local_analysis_only: bool
    provider_payload_paths: tuple[str, ...]
    items: tuple[CapturePayloadItem, ...]
    omissions: tuple[CapturePayloadOmission, ...]
    total_bytes: int
    truncated: bool
    disclosure: str

    def to_dict(self) -> dict[str, object]:
        return {
            "capture_path": self.capture_path,
            "requested_operations": list(self.requested_operations),
            "external_processing_intent": self.external_processing_intent,
            "local_analysis_only": self.local_analysis_only,
            "provider_payload_paths": list(self.provider_payload_paths),
            "items": [item.to_dict() for item in self.items],
            "omissions": [item.to_dict() for item in self.omissions],
            "total_bytes": self.total_bytes,
            "truncated": self.truncated,
            "disclosure": self.disclosure,
        }


def _redact(text: str, terms: tuple[str, ...]) -> tuple[str, tuple[dict[str, object], ...]]:
    visible = text
    applied: list[dict[str, object]] = []
    for index, term in enumerate(terms, 1):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        visible, count = pattern.subn(f"[REDACTED-{index}]", visible)
        if count:
            applied.append({"label": f"redaction-{index}", "occurrences": count})
    return visible, tuple(applied)


def _truncate(text: str, limit: int) -> tuple[str, int, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, len(raw), False
    clipped = raw[:limit]
    while clipped:
        try:
            return clipped.decode("utf-8"), len(clipped), True
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return "", 0, True


def _load_policy(vault_root: Path) -> RetrievalPolicy:
    try:
        return load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise CaptureError(
            "invalid_retrieval_policy",
            "Capture context preview requires a valid retrieval policy.",
            {"reason": exc.code},
        ) from exc


def _provider_decision(
    path: str,
    *,
    allowed_roots: tuple[str, ...],
    policy: RetrievalPolicy,
) -> ScopeDecision:
    try:
        return provider_path_decision(
            path,
            allowed_protected_prefixes=allowed_roots,
            policy=policy,
        )
    except RetrievalError as exc:
        raise CaptureError(
            "invalid_provider_scope",
            "Capture provider scope contains an invalid vault path.",
            {"path": path, "reason": exc.code},
        ) from exc


def _policy_detail(reason: str) -> str:
    return {
        "excluded-by-policy": "The canonical retrieval policy excludes this path.",
        "excluded-node-local-runtime": "The active runtime policy excludes this path.",
        "protected-default-deny": ("Protected content requires explicit per-operation path scope."),
        "protected-external-deny": (
            "The canonical retrieval policy does not permit external disclosure of this path."
        ),
    }.get(reason, "The canonical retrieval policy does not permit this path.")


def preview_capture_context(
    *,
    vault_root: Path,
    runtime_dir: Path,
    capture_path: str,
    selected_attachment_ids: Iterable[str] = (),
    selected_paths: Iterable[str] = (),
    requested_operations: Iterable[str] = (),
    external_processing_intent: bool = False,
    allow_sensitive_capture: bool = False,
    allowed_sensitive_roots: Iterable[str] = (),
    redact_terms: Iterable[str] = (),
    max_item_bytes: int = 8_000,
    max_total_bytes: int = 24_000,
) -> CaptureContextPreview:
    if max_item_bytes < 1 or max_total_bytes < 1:
        raise CaptureError(
            "invalid_context_budget", "Capture context byte limits must be positive."
        )
    operations = tuple(
        dict.fromkeys(str(item).strip() for item in requested_operations if str(item).strip())
    )
    selected_ids = tuple(
        dict.fromkeys(str(item).strip() for item in selected_attachment_ids if str(item).strip())
    )
    selected_notes = tuple(
        dict.fromkeys(str(item).strip() for item in selected_paths if str(item).strip())
    )
    allowed_roots = tuple(
        dict.fromkeys(str(item).strip() for item in allowed_sensitive_roots if str(item).strip())
    )
    redactions = tuple(sorted({str(item).strip() for item in redact_terms if str(item).strip()}))
    policy = _load_policy(vault_root)
    capture_decision = _provider_decision(
        capture_path,
        allowed_roots=(capture_path,) if allow_sensitive_capture else (),
        policy=policy,
    )
    if not capture_decision.allowed:
        return CaptureContextPreview(
            capture_decision.path,
            operations,
            external_processing_intent,
            not external_processing_intent,
            (),
            (),
            (
                CapturePayloadOmission(
                    capture_decision.path,
                    capture_decision.reason,
                    _policy_detail(capture_decision.reason),
                ),
            ),
            0,
            False,
            _DISCLOSURE,
        )
    captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
    extractor = LocalExtractionService(vault_root=vault_root, runtime_dir=runtime_dir)
    artifact = captures.load(capture_decision.path)
    omissions: list[CapturePayloadOmission] = []
    items: list[CapturePayloadItem] = []
    remaining = max_total_bytes
    any_truncated = False

    protected_capture = (
        artifact.metadata.privacy_scope == "protected" or artifact.metadata.sensitive
    )
    if not external_processing_intent:
        omissions.append(
            CapturePayloadOmission(
                artifact.path,
                "explicit-processing-intent-required",
                "Saving a capture never authorizes external processing.",
            )
        )
    elif protected_capture and not allow_sensitive_capture:
        omissions.append(
            CapturePayloadOmission(
                artifact.path,
                "protected-default-deny",
                "Protected or sensitive captures require explicit scope for this operation.",
            )
        )
    else:
        user_text, applied = _redact(artifact.metadata.description, redactions)
        excerpt, included, truncated = _truncate(user_text, min(max_item_bytes, remaining))
        items.append(
            CapturePayloadItem(
                artifact.path,
                "user-authored-capture-text",
                artifact.content_hash,
                "canonical capture explicitly selected",
                "text",
                len(user_text.encode("utf-8")),
                included,
                truncated,
                excerpt=excerpt,
                redactions=applied,
            )
        )
        remaining -= included
        any_truncated = any_truncated or truncated

    attached = {item.attachment_id: item for item in artifact.metadata.attachments}
    for attachment_id in selected_ids:
        reference = attached.get(attachment_id)
        if reference is None:
            omissions.append(
                CapturePayloadOmission(
                    attachment_id,
                    "attachment-not-linked",
                    "The selected attachment is not linked to this capture.",
                )
            )
            continue
        if not external_processing_intent:
            omissions.append(
                CapturePayloadOmission(
                    reference.canonical_path,
                    "explicit-processing-intent-required",
                    "The original file remains local until this operation is explicitly requested.",
                )
            )
            continue
        if protected_capture and not allow_sensitive_capture:
            omissions.append(
                CapturePayloadOmission(
                    reference.canonical_path,
                    "protected-default-deny",
                    "Protected attachment bytes are excluded by default.",
                )
            )
            continue
        attachment_manifest_path = manifest_path(attachment_id)
        if reference.manifest_path != attachment_manifest_path:
            omissions.append(
                CapturePayloadOmission(
                    reference.manifest_path,
                    "attachment-reference-mismatch",
                    "The capture reference does not identify the attachment's canonical manifest.",
                )
            )
            continue
        manifest_decision = _provider_decision(
            attachment_manifest_path,
            allowed_roots=(attachment_manifest_path,) if allow_sensitive_capture else (),
            policy=policy,
        )
        if not manifest_decision.allowed:
            omissions.append(
                CapturePayloadOmission(
                    manifest_decision.path,
                    manifest_decision.reason,
                    _policy_detail(manifest_decision.reason),
                )
            )
            continue
        manifest = store.manifests.load(manifest_decision.path)
        attachment_decision = _provider_decision(
            manifest.metadata.canonical_path,
            allowed_roots=(manifest.metadata.canonical_path,) if allow_sensitive_capture else (),
            policy=policy,
        )
        if not attachment_decision.allowed:
            omissions.append(
                CapturePayloadOmission(
                    attachment_decision.path,
                    attachment_decision.reason,
                    _policy_detail(attachment_decision.reason),
                )
            )
            continue
        if (
            manifest.metadata.attachment_id != reference.attachment_id
            or manifest.metadata.canonical_path != reference.canonical_path
            or manifest.metadata.content_hash != reference.content_hash
            or manifest.metadata.byte_size != reference.byte_size
            or manifest.metadata.media_type != reference.media_type
        ):
            omissions.append(
                CapturePayloadOmission(
                    reference.canonical_path,
                    "attachment-reference-mismatch",
                    "The capture reference does not match its canonical attachment manifest.",
                )
            )
            continue
        audit = store._audit_manifest(manifest.metadata)
        if audit.status != "ok":
            omissions.append(
                CapturePayloadOmission(
                    reference.canonical_path, f"attachment-{audit.status}", audit.details
                )
            )
            continue
        extraction = extractor.load(attachment_id)
        if (
            extraction is not None
            and extraction.status == "completed"
            and extraction.source_hash == reference.content_hash
            and extraction.text
        ):
            visible, applied = _redact(extraction.text, redactions)
            allowance = min(max_item_bytes, remaining)
            excerpt, included, truncated = _truncate(visible, max(allowance, 0))
            items.append(
                CapturePayloadItem(
                    reference.canonical_path,
                    "derived-extracted-text",
                    reference.content_hash,
                    f"approved {extraction.method} output",
                    "text",
                    len(visible.encode("utf-8")),
                    included,
                    truncated,
                    excerpt=excerpt,
                    attachment_id=attachment_id,
                    media_type=reference.media_type,
                    redactions=applied,
                )
            )
            remaining -= included
            any_truncated = any_truncated or truncated
            continue
        transfer = (
            "original-binary"
            if any(
                operation in {"ocr", "image-description", "transcription", "document-analysis"}
                for operation in operations
            )
            else "metadata-only"
        )
        included = reference.byte_size if transfer == "original-binary" else 0
        if transfer == "original-binary" and included > remaining:
            omissions.append(
                CapturePayloadOmission(
                    reference.canonical_path,
                    "context-budget-exceeded",
                    "The original file exceeds the bounded provider payload budget.",
                )
            )
            any_truncated = True
            continue
        items.append(
            CapturePayloadItem(
                reference.canonical_path,
                "original-attachment",
                reference.content_hash,
                "attachment explicitly selected",
                transfer,
                reference.byte_size,
                included,
                False,
                attachment_id=attachment_id,
                media_type=reference.media_type,
            )
        )
        remaining -= included

    for path in selected_notes:
        if not external_processing_intent:
            omissions.append(
                CapturePayloadOmission(
                    path,
                    "explicit-processing-intent-required",
                    "Selected notes remain local without explicit processing intent.",
                )
            )
            continue
        note_decision = _provider_decision(path, allowed_roots=allowed_roots, policy=policy)
        if not note_decision.allowed:
            omissions.append(
                CapturePayloadOmission(
                    note_decision.path,
                    note_decision.reason,
                    _policy_detail(note_decision.reason),
                )
            )
            continue
        try:
            source = read_vault_markdown(vault_root, note_decision.path)
        except VaultAccessError as exc:
            omissions.append(
                CapturePayloadOmission(note_decision.path, "source-unavailable", str(exc))
            )
            continue
        visible, applied = _redact(source.content, redactions)
        allowance = min(max_item_bytes, remaining)
        if allowance <= 0:
            omissions.append(
                CapturePayloadOmission(
                    path, "context-budget-exhausted", "The bounded context budget was reached."
                )
            )
            any_truncated = True
            continue
        excerpt, included, truncated = _truncate(visible, allowance)
        items.append(
            CapturePayloadItem(
                note_decision.path,
                "user-selected-note",
                "sha256:" + content_hash(source.content),
                "note explicitly selected for this operation",
                "text",
                len(visible.encode("utf-8")),
                included,
                truncated,
                excerpt=excerpt,
                redactions=applied,
            )
        )
        remaining -= included
        any_truncated = any_truncated or truncated

    payload_paths = tuple(item.path for item in items)
    return CaptureContextPreview(
        artifact.path,
        operations,
        external_processing_intent,
        not external_processing_intent,
        payload_paths,
        tuple(items),
        tuple(omissions),
        sum(item.included_bytes for item in items),
        any_truncated,
        _DISCLOSURE,
    )
