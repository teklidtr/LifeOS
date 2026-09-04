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
    provider_path_decision,
)
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import ExperimentArtifactService
from .contracts import ExperimentError

# Backwards-compatible legacy export. Enforcement loads the current vault policy instead.
PROTECTED_ROOTS = frozenset({"diary", "health", "medical", "private", "therapy", "photos"})
_DISCLOSURE = (
    "Only the listed excerpts would be sent to an external provider. Linked content is not "
    "followed automatically. Deterministic analysis remains local."
)


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
    personal_pattern: PersonalPatternContextItem | None = None

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


def _load_policy(vault_root: Path) -> RetrievalPolicy:
    try:
        return load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ExperimentError(
            "invalid_retrieval_policy",
            "Experiment context preview requires a valid retrieval policy.",
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
        raise ExperimentError(
            "invalid_provider_scope",
            "Experiment provider scope contains an invalid vault path.",
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
        raise ExperimentError(
            "invalid_context_budget", "Experiment context byte limits must be positive."
        )
    allowed = tuple(
        dict.fromkeys(str(item).strip() for item in allowed_sensitive_roots if str(item).strip())
    )
    redactions = tuple(sorted({str(item).strip() for item in redact_terms if str(item).strip()}))
    selected = tuple(
        dict.fromkeys(str(item).strip() for item in selected_paths if str(item).strip())
    )
    policy = _load_policy(vault_root)
    experiment_decision = _provider_decision(
        experiment_path,
        allowed_roots=allowed,
        policy=policy,
    )
    if not experiment_decision.allowed:
        return ExperimentContextPreview(
            experiment_path=experiment_decision.path,
            local_analysis_only=True,
            provider_payload_paths=(),
            items=(),
            omissions=(
                ExperimentContextOmission(
                    experiment_decision.path,
                    experiment_decision.reason,
                    _policy_detail(experiment_decision.reason),
                ),
            ),
            total_bytes=0,
            truncated=False,
            disclosure=_DISCLOSURE,
        )
    service = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    artifact = service.load(experiment_decision.path)

    def provider_filter(path: str) -> bool:
        return _provider_decision(path, allowed_roots=allowed, policy=policy).allowed

    pattern_by_path: dict[str, PersonalPatternContextItem] = {}
    auto_pattern_paths: tuple[str, ...] = ()
    pattern_query = " ".join(
        (
            artifact.metadata.title,
            artifact.metadata.description,
            artifact.metadata.protocol.question,
            artifact.metadata.protocol.hypothesis,
        )
    )
    try:
        automatic = build_personal_pattern_context(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            question=pattern_query,
            limit=3,
            mode="external",
            redact_terms=redactions,
            path_filter=provider_filter,
        )
        explicit_pattern_paths = tuple(
            path for path in selected if path.startswith("patterns/")
        )
        explicit_patterns = build_personal_pattern_context(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            question=pattern_query,
            limit=max(1, min(20, len(explicit_pattern_paths) or 1)),
            mode="external",
            allow_protected=True,
            candidate_paths=explicit_pattern_paths,
            explicit_paths=explicit_pattern_paths,
            redact_terms=redactions,
            path_filter=provider_filter,
        )
        for item in (*explicit_patterns.items, *automatic.items):
            pattern_by_path.setdefault(item.pattern_path, item)
        auto_pattern_paths = tuple(
            item.pattern_path
            for item in automatic.items
            if item.pattern_path not in selected
        )
    except PersonalPatternContextError:
        pattern_by_path = {}
        auto_pattern_paths = ()

    candidates = (
        (artifact.path, "canonical experiment explicitly opened"),
        *[(path, "user-selected source") for path in selected],
        *[(path, "relevant personal-pattern evidence") for path in auto_pattern_paths],
    )
    remaining = max_total_bytes
    items: list[ExperimentContextItem] = []
    omissions: list[ExperimentContextOmission] = []
    truncated = False
    for path, reason in candidates:
        decision = _provider_decision(path, allowed_roots=allowed, policy=policy)
        if not decision.allowed:
            omissions.append(
                ExperimentContextOmission(
                    decision.path,
                    decision.reason,
                    _policy_detail(decision.reason),
                )
            )
            continue
        try:
            source = read_vault_markdown(vault_root, decision.path)
        except VaultAccessError as exc:
            omissions.append(
                ExperimentContextOmission(decision.path, "source-unavailable", str(exc))
            )
            continue
        pattern_item = pattern_by_path.get(decision.path)
        context_text = (
            render_personal_pattern_evidence(pattern_item)
            if pattern_item is not None
            else source.content
        )
        visible, applied = _redact(context_text, redactions)
        raw_bytes = len(visible.encode("utf-8"))
        allowance = min(max_item_bytes, remaining)
        if allowance <= 0:
            omissions.append(
                ExperimentContextOmission(
                    path, "context-budget-exhausted", "The bounded context budget was reached."
                )
            )
            truncated = True
            continue
        excerpt, included_bytes, item_truncated = _truncate(visible, allowance)
        truncated = truncated or item_truncated
        item_redactions = (
            *applied,
            *(pattern_item.redactions if pattern_item is not None else ()),
        )
        items.append(
            ExperimentContextItem(
                path=decision.path,
                content_hash="sha256:" + content_hash(source.content),
                inclusion_reason=reason,
                excerpt=excerpt,
                byte_count=raw_bytes,
                included_bytes=included_bytes,
                truncated=item_truncated,
                redactions=item_redactions,
                personal_pattern=pattern_item,
            )
        )
        remaining -= included_bytes
    payload_paths = tuple(item.path for item in items)
    return ExperimentContextPreview(
        experiment_path=artifact.path,
        local_analysis_only=True,
        provider_payload_paths=payload_paths,
        items=tuple(items),
        omissions=tuple(omissions),
        total_bytes=sum(item.included_bytes for item in items),
        truncated=truncated,
        disclosure=_DISCLOSURE,
    )
