"""Inspectable, bounded privacy controls for optional experiment assistance."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lifeos.daily.service import content_hash
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import ExperimentArtifactService
from .contracts import ExperimentError

PROTECTED_ROOTS = frozenset({"diary", "health", "medical", "private", "therapy", "photos"})


@dataclass(frozen=True, slots=True)
class ExperimentContextItem:
    path: str
    content_hash: str
    inclusion_reason: str
    excerpt: str
    byte_count: int
    included_bytes: int
    truncated: bool
    redactions: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "redactions": [dict(item) for item in self.redactions]}


@dataclass(frozen=True, slots=True)
class ExperimentContextOmission:
    path: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExperimentContextPreview:
    experiment_path: str
    local_analysis_only: bool
    provider_payload_paths: tuple[str, ...]
    items: tuple[ExperimentContextItem, ...]
    omissions: tuple[ExperimentContextOmission, ...]
    total_bytes: int
    truncated: bool
    disclosure: str

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_path": self.experiment_path,
            "local_analysis_only": self.local_analysis_only,
            "provider_payload_paths": list(self.provider_payload_paths),
            "items": [item.to_dict() for item in self.items],
            "omissions": [item.to_dict() for item in self.omissions],
            "total_bytes": self.total_bytes,
            "truncated": self.truncated,
            "disclosure": self.disclosure,
        }


def _redact(text: str, terms: tuple[str, ...]) -> tuple[str, tuple[dict[str, object], ...]]:
    result = text
    applied: list[dict[str, object]] = []
    for index, term in enumerate(terms, 1):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result, count = pattern.subn(f"[REDACTED-{index}]", result)
        if count:
            applied.append({"label": f"redaction-{index}", "occurrences": count})
    return result, tuple(applied)


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


def preview_experiment_context(
    *,
    vault_root: Path,
    runtime_dir: Path,
    experiment_path: str,
    selected_paths: Iterable[str] = (),
    allowed_sensitive_roots: Iterable[str] = (),
    redact_terms: Iterable[str] = (),
    max_item_bytes: int = 8_000,
    max_total_bytes: int = 24_000,
) -> ExperimentContextPreview:
    if max_item_bytes < 1 or max_total_bytes < 1:
        raise ExperimentError("invalid_context_budget", "Experiment context byte limits must be positive.")
    service = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    artifact = service.load(experiment_path)
    allowed = frozenset(str(item).strip() for item in allowed_sensitive_roots if str(item).strip())
    redactions = tuple(sorted({str(item).strip() for item in redact_terms if str(item).strip()}))
    selected = tuple(dict.fromkeys(str(item).strip() for item in selected_paths if str(item).strip()))
    candidates = ((artifact.path, "canonical experiment explicitly opened"), *[(path, "user-selected source") for path in selected])
    remaining = max_total_bytes
    items: list[ExperimentContextItem] = []
    omissions: list[ExperimentContextOmission] = []
    truncated = False
    for path, reason in candidates:
        root = path.split("/", 1)[0]
        if path != artifact.path and root in PROTECTED_ROOTS and root not in allowed:
            omissions.append(ExperimentContextOmission(
                path, "protected-default-deny",
                "Protected content is excluded unless the user explicitly permits its root for this request.",
            ))
            continue
        try:
            source = read_vault_markdown(vault_root, path)
        except VaultAccessError as exc:
            omissions.append(ExperimentContextOmission(path, "source-unavailable", str(exc)))
            continue
        visible, applied = _redact(source.content, redactions)
        raw_bytes = len(visible.encode("utf-8"))
        allowance = min(max_item_bytes, remaining)
        if allowance <= 0:
            omissions.append(ExperimentContextOmission(path, "context-budget-exhausted", "The bounded context budget was reached."))
            truncated = True
            continue
        excerpt, included_bytes, item_truncated = _truncate(visible, allowance)
        truncated = truncated or item_truncated
        items.append(ExperimentContextItem(
            path=path,
            content_hash="sha256:" + content_hash(source.content),
            inclusion_reason=reason,
            excerpt=excerpt,
            byte_count=raw_bytes,
            included_bytes=included_bytes,
            truncated=item_truncated,
            redactions=applied,
        ))
        remaining -= included_bytes
    payload_paths = tuple(item.path for item in items)
    disclosure = (
        "Only the listed excerpts would be sent to an external provider. Linked diary, health, photo, "
        "and other protected notes are not followed automatically. Deterministic analysis remains local."
    )
    return ExperimentContextPreview(
        experiment_path=artifact.path,
        local_analysis_only=True,
        provider_payload_paths=payload_paths,
        items=tuple(items),
        omissions=tuple(omissions),
        total_bytes=sum(item.included_bytes for item in items),
        truncated=truncated,
        disclosure=disclosure,
    )
