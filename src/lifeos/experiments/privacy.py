"""Inspectable, bounded privacy controls for optional experiment assistance."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lifeos.daily.service import content_hash
from lifeos.patterns.context import (
    PersonalPatternContextError,
    PersonalPatternContextItem,
    build_personal_pattern_context,
    render_personal_pattern_evidence,
)
from lifeos.retrieval.contracts import (
    RetrievalError,
    RetrievalPolicy,
    ScopeDecision,
)
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.retrieval.scope import scope_decision
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import ExperimentArtifactService
from .contracts import ExperimentError

EXPERIMENT_CONTEXT_SCHEMA_VERSION = 1
EXPERIMENT_CONTEXT_MAX_ITEMS = 12
EXPERIMENT_CONTEXT_MAX_CHARS = 24_000


@dataclass(frozen=True, slots=True)
class ExperimentContextItem:
    path: str
    content_hash: str
    excerpt: str
    chars: int
    protected: bool
    personal_pattern: PersonalPatternContextItem | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "excerpt": self.excerpt,
            "chars": self.chars,
            "protected": self.protected,
            "personal_pattern": (
                self.personal_pattern.to_dict()
                if self.personal_pattern is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ExperimentContextPreview:
    schema_version: int
    experiment_path: str
    experiment_content_hash: str
    query: str
    items: tuple[ExperimentContextItem, ...]
    omissions: tuple[str, ...]
    total_chars: int
    truncated: bool
    redactions: tuple[dict[str, object], ...]
    provider_disclosure: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_path": self.experiment_path,
            "experiment_content_hash": self.experiment_content_hash,
            "query": self.query,
            "items": [item.to_dict() for item in self.items],
            "omissions": list(self.omissions),
            "total_chars": self.total_chars,
            "truncated": self.truncated,
            "redactions": [dict(item) for item in self.redactions],
            "provider_disclosure": dict(self.provider_disclosure),
        }


def _excerpt(content: str, *, limit: int) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "…"


def _redact(
    text: str,
    terms: tuple[str, ...],
) -> tuple[str, tuple[dict[str, object], ...]]:
    result = text
    applied: list[dict[str, object]] = []
    for index, term in enumerate(terms, 1):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result, count = pattern.subn(f"[REDACTED-{index}]", result)
        if count:
            applied.append({"label": f"redaction-{index}", "occurrences": count})
    return result, tuple(applied)


def _decision(
    path: str,
    *,
    policy: RetrievalPolicy,
    allow_protected: bool,
) -> ScopeDecision:
    return scope_decision(
        path,
        scope={"allow_protected": allow_protected},
        policy=policy,
        mode="external",
    )


def _provider_disclosure(
    *,
    items: tuple[ExperimentContextItem, ...],
    total_chars: int,
    redactions: tuple[dict[str, object], ...],
) -> dict[str, object]:
    protected = tuple(item.path for item in items if item.protected)
    return {
        "mode": "external-preview",
        "allowed": True,
        "paths": [item.path for item in items],
        "item_count": len(items),
        "total_chars": total_chars,
        "protected_paths": list(protected),
        "redactions": [dict(item) for item in redactions],
    }


def preview_experiment_context(
    *,
    vault_root: Path,
    runtime_dir: Path,
    experiment_path: str,
    include_paths: Iterable[str] = (),
    allow_protected: bool = False,
    redact_terms: Iterable[str] = (),
    max_items: int = EXPERIMENT_CONTEXT_MAX_ITEMS,
    max_chars: int = EXPERIMENT_CONTEXT_MAX_CHARS,
) -> ExperimentContextPreview:
    """Preview exactly what optional experiment assistance may disclose externally."""
    if type(max_items) is not int or not 1 <= max_items <= EXPERIMENT_CONTEXT_MAX_ITEMS:
        raise ExperimentError(
            "invalid_context_limit",
            f"max_items must be between 1 and {EXPERIMENT_CONTEXT_MAX_ITEMS}",
        )
    if type(max_chars) is not int or not 1 <= max_chars <= EXPERIMENT_CONTEXT_MAX_CHARS:
        raise ExperimentError(
            "invalid_context_limit",
            f"max_chars must be between 1 and {EXPERIMENT_CONTEXT_MAX_CHARS}",
        )
    service = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    artifact = service.load(experiment_path)
    query = " ".join(
        part.strip()
        for part in (
            artifact.metadata.title,
            artifact.metadata.description,
            artifact.metadata.protocol.question,
            artifact.metadata.protocol.hypothesis,
            artifact.metadata.category,
        )
        if part and part.strip()
    )
    try:
        policy = load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ExperimentError("invalid_policy", "Retrieval policy is invalid.") from exc
    requested = tuple(
        dict.fromkeys(path.strip() for path in include_paths if path and path.strip())
    )
    redaction_terms = tuple(
        sorted({term.strip() for term in redact_terms if term and term.strip()})
    )
    omissions: list[str] = []
    items: list[ExperimentContextItem] = []
    all_redactions: list[dict[str, object]] = []
    total_chars = 0
    truncated = False

    for path in requested:
        try:
            decision = _decision(
                path,
                policy=policy,
                allow_protected=allow_protected,
            )
        except RetrievalError:
            omissions.append(f"{path}: invalid path")
            continue
        if not decision.allowed:
            omissions.append(f"{path}: {decision.reason}")
            continue
        try:
            source = read_vault_markdown(vault_root, path)
        except VaultAccessError as exc:
            omissions.append(f"{path}: {exc.code}")
            continue
        remaining = max_chars - total_chars
        if remaining <= 0 or len(items) >= max_items:
            truncated = True
            break
        excerpt, applied = _redact(
            _excerpt(source.content, limit=remaining),
            redaction_terms,
        )
        if not excerpt:
            continue
        item = ExperimentContextItem(
            path=path,
            content_hash="sha256:" + content_hash(source.content),
            excerpt=excerpt,
            chars=len(excerpt),
            protected=decision.protected,
        )
        items.append(item)
        total_chars += item.chars
        all_redactions.extend({"path": path, **entry} for entry in applied)

    remaining_items = max_items - len(items)
    remaining_chars = max_chars - total_chars
    if remaining_items > 0 and remaining_chars > 0:
        try:
            pattern_context = build_personal_pattern_context(
                vault_root=vault_root,
                runtime_dir=runtime_dir,
                question=query,
                limit=remaining_items,
                mode="external",
                allow_protected=allow_protected,
                explicit_paths=requested,
                redact_terms=redaction_terms,
            )
        except PersonalPatternContextError as exc:
            omissions.append(f"Personal pattern context unavailable: {exc}")
        else:
            for pattern in pattern_context.items:
                if pattern.pattern_path in requested:
                    continue
                try:
                    decision = _decision(
                        pattern.pattern_path,
                        policy=policy,
                        allow_protected=allow_protected,
                    )
                except RetrievalError:
                    continue
                if not decision.allowed:
                    continue
                remaining_chars = max_chars - total_chars
                if remaining_chars <= 0 or len(items) >= max_items:
                    truncated = True
                    break
                rendered = render_personal_pattern_evidence(pattern)
                excerpt = _excerpt(rendered, limit=remaining_chars)
                if not excerpt:
                    continue
                item = ExperimentContextItem(
                    path=pattern.pattern_path,
                    content_hash=pattern.pattern_content_hash,
                    excerpt=excerpt,
                    chars=len(excerpt),
                    protected=decision.protected,
                    personal_pattern=pattern,
                )
                items.append(item)
                total_chars += item.chars
                all_redactions.extend(
                    {"path": pattern.pattern_path, **entry}
                    for entry in pattern.redactions
                )
            omissions.extend(
                f"{item.path}: {item.detail}"
                for item in pattern_context.omissions
            )
            if pattern_context.truncated:
                truncated = True

    return ExperimentContextPreview(
        schema_version=EXPERIMENT_CONTEXT_SCHEMA_VERSION,
        experiment_path=artifact.path,
        experiment_content_hash=artifact.content_hash,
        query=query,
        items=tuple(items),
        omissions=tuple(omissions),
        total_chars=total_chars,
        truncated=truncated,
        redactions=tuple(all_redactions),
        provider_disclosure=_provider_disclosure(
            items=tuple(items),
            total_chars=total_chars,
            redactions=tuple(all_redactions),
        ),
    )
