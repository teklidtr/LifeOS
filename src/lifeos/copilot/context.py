"""Bounded, previewable context assembly for goal-to-plan sessions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping

from lifeos.markdown.parser import parse_markdown_note
from lifeos.patterns.context import (
    PersonalPatternContextError,
    build_personal_pattern_context,
    render_personal_pattern_evidence,
)
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

from .contracts import CopilotIndex, GoalRecord, content_hash
from .readiness import GoalReadinessReport, evaluate_goal_readiness

_DEFAULT_SENSITIVE_ROOTS = frozenset(
    {"journal", "health", "medical", "finance", "finances", "relationships", "profile"}
)


class PlanningContextError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PlanningContextPolicy:
    allowed_sensitive_roots: tuple[str, ...] = ()
    sensitive_roots: tuple[str, ...] = tuple(sorted(_DEFAULT_SENSITIVE_ROOTS))
    recent_review_limit: int = 2

    def __post_init__(self) -> None:
        if type(self.recent_review_limit) is not int or self.recent_review_limit < 0:
            raise PlanningContextError("recent_review_limit must be a non-negative integer")
        if not set(self.allowed_sensitive_roots) <= set(self.sensitive_roots):
            raise PlanningContextError("allowed sensitive roots must be declared sensitive roots")


@dataclass(frozen=True, slots=True)
class ContextRedaction:
    label: str
    occurrences: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanningContextItem:
    source_id: str
    path: str
    content_hash: str
    inclusion_reason: str
    excerpt: str
    byte_count: int
    included_bytes: int
    truncated: bool
    redactions: tuple[ContextRedaction, ...]
    freshness: Literal["current", "stale"]
    explicit: bool

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "redactions": [item.to_dict() for item in self.redactions],
        }


@dataclass(frozen=True, slots=True)
class ContextOmission:
    path: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanningContextPack:
    schema_version: int
    goal_id: str
    goal_hash: str
    readiness: GoalReadinessReport
    items: tuple[PlanningContextItem, ...]
    omissions: tuple[ContextOmission, ...]
    total_bytes: int
    truncated: bool
    lexical_only: bool

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "readiness": self.readiness.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "omissions": [item.to_dict() for item in self.omissions],
        }


def build_planning_context(
    *,
    vault_root: Path,
    goal: GoalRecord,
    index: CopilotIndex,
    include_paths: Iterable[str] = (),
    exclude_paths: Iterable[str] = (),
    redact_terms: Iterable[str] = (),
    expected_hashes: Mapping[str, str] | None = None,
    policy: PlanningContextPolicy | None = None,
    max_total_bytes: int = 24_000,
    max_item_bytes: int = 6_000,
) -> PlanningContextPack:
    if type(max_total_bytes) is not int or max_total_bytes <= 0:
        raise PlanningContextError("max_total_bytes must be a positive integer")
    if type(max_item_bytes) is not int or max_item_bytes <= 0:
        raise PlanningContextError("max_item_bytes must be a positive integer")
    policy = policy or PlanningContextPolicy()
    expected_hashes = expected_hashes or {}
    includes = _safe_paths(include_paths, "include_paths")
    excludes = set(_safe_paths(exclude_paths, "exclude_paths"))
    if set(includes) & excludes:
        raise PlanningContextError("a path cannot be both included and excluded")
    redactions = tuple(sorted({term.strip() for term in redact_terms if term.strip()}))
    plans_by_id = {plan.plan_id: plan for plan in index.plans}

    candidates: list[tuple[str, str, bool]] = [(goal.path, "selected goal", False)]
    pattern_by_path = {}
    pattern_context_omissions: list[ContextOmission] = []
    pattern_query = " ".join(
        value
        for value in (
            goal.title,
            goal.description or "",
            goal.why or "",
            goal.desired_change or "",
            *goal.constraints,
        )
        if value
    )
    def pattern_context_path_filter(path: str) -> bool:
        if path in excludes:
            return False
        root = path.split("/", 1)[0]
        return root not in policy.sensitive_roots

    try:
        pattern_context = build_personal_pattern_context(
            vault_root=vault_root,
            runtime_dir=vault_root / ".lifeos",
            question=pattern_query,
            limit=3,
            mode="external",
            explicit_paths=includes,
            redact_terms=redactions,
            path_filter=pattern_context_path_filter,
        )
        pattern_by_path = {item.pattern_path: item for item in pattern_context.items}
        candidates.extend(
            (item.pattern_path, "relevant personal-pattern evidence", False)
            for item in pattern_context.items
        )
    except PersonalPatternContextError as exc:
        pattern_context_omissions.append(
            ContextOmission("patterns", "personal-model-unavailable", str(exc))
        )
    for ref in sorted(goal.active_plan_refs):
        plan = plans_by_id.get(_reference_id(ref))
        if plan is not None:
            candidates.append((plan.path, "goal-linked plan", False))
    candidates.extend(_relevant_reviews(vault_root, goal, limit=policy.recent_review_limit))
    candidates.extend((path, "user-selected supporting note", True) for path in includes)

    seen: set[str] = set()
    ordered: list[tuple[str, str, bool]] = []
    for candidate in candidates:
        if candidate[0] not in seen:
            seen.add(candidate[0])
            ordered.append(candidate)

    items: list[PlanningContextItem] = []
    omissions: list[ContextOmission] = list(pattern_context_omissions)
    remaining = max_total_bytes
    pack_truncated = False
    for path, reason, explicit in ordered:
        if path in excludes:
            omissions.append(ContextOmission(path, "explicitly-excluded", "Excluded by user control."))
            continue
        root = path.split("/", 1)[0]
        if root in policy.sensitive_roots:
            if not explicit:
                omissions.append(
                    ContextOmission(
                        path,
                        "sensitive-default-deny",
                        "Sensitive scopes are not included by automatic routing.",
                    )
                )
                continue
            if root not in policy.allowed_sensitive_roots:
                omissions.append(
                    ContextOmission(
                        path,
                        "sensitive-scope-denied",
                        "Policy does not allow this sensitive scope for planning context.",
                    )
                )
                continue
        try:
            source = read_vault_markdown(vault_root, path)
        except VaultAccessError as exc:
            omissions.append(ContextOmission(path, "source-unavailable", str(exc)))
            continue
        source_hash = content_hash(source.content)
        expected = expected_hashes.get(path)
        freshness: Literal["current", "stale"] = (
            "stale" if expected is not None and expected != source_hash else "current"
        )
        parsed = parse_markdown_note(source.path, content=source.content)
        pattern_item = pattern_by_path.get(path)
        visible = (
            render_personal_pattern_evidence(pattern_item)
            if pattern_item is not None
            else _visible_text(parsed.body, source.content)
        )
        redacted, applied = _apply_redactions(visible, redactions)
        raw_bytes = len(redacted.encode("utf-8"))
        allowance = min(max_item_bytes, remaining)
        if allowance <= 0:
            omissions.append(
                ContextOmission(path, "context-budget-exhausted", "The total context byte limit was reached.")
            )
            pack_truncated = True
            continue
        excerpt, included_bytes, truncated = _truncate_utf8(redacted, allowance)
        if truncated:
            pack_truncated = True
        source_id = parsed.durable_fields.id or f"path-{hashlib.sha256(path.encode()).hexdigest()[:16]}"
        items.append(
            PlanningContextItem(
                source_id=source_id,
                path=path,
                content_hash=source_hash,
                inclusion_reason=reason,
                excerpt=excerpt,
                byte_count=raw_bytes,
                included_bytes=included_bytes,
                truncated=truncated,
                redactions=applied,
                freshness=freshness,
                explicit=explicit,
            )
        )
        remaining -= included_bytes
    return PlanningContextPack(
        schema_version=1,
        goal_id=goal.goal_id,
        goal_hash=goal.content_hash,
        readiness=evaluate_goal_readiness(goal, index=index),
        items=tuple(items),
        omissions=tuple(sorted(omissions, key=lambda item: (item.path, item.reason, item.detail))),
        total_bytes=sum(item.included_bytes for item in items),
        truncated=pack_truncated,
        lexical_only=True,
    )


def _relevant_reviews(
    vault_root: Path, goal: GoalRecord, *, limit: int
) -> list[tuple[str, str, bool]]:
    if limit == 0:
        return []
    try:
        sources = iter_vault_markdown(vault_root, roots=("reviews",))
    except VaultAccessError:
        return []
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_-]+", f"{goal.goal_id} {goal.title}")
        if len(token) >= 3
    }
    scored: list[tuple[int, str]] = []
    for source in sources:
        text = source.content.casefold()
        score = sum(1 for token in tokens if token in text)
        if score:
            scored.append((score, source.path.relative_to(vault_root).as_posix()))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(path, "recent relevant review", False) for _, path in scored[:limit]]


def _safe_paths(values: Iterable[str], name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PlanningContextError(f"{name} must contain non-empty strings")
        path = value.strip()
        if path.startswith("/") or ".." in Path(path).parts or not path.endswith(".md"):
            raise PlanningContextError(f"unsafe context path: {value}")
        result.append(path)
    return tuple(sorted(set(result)))


def _reference_id(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("[[") and cleaned.endswith("]]" ):
        cleaned = cleaned[2:-2].split("|", 1)[0]
    return Path(cleaned).stem


def _visible_text(body: str, full_content: str) -> str:
    text = body.strip()
    return text if text else full_content.strip()


def _apply_redactions(text: str, terms: tuple[str, ...]) -> tuple[str, tuple[ContextRedaction, ...]]:
    result = text
    applied: list[ContextRedaction] = []
    for index, term in enumerate(terms, start=1):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result, count = pattern.subn(f"[REDACTED-{index}]", result)
        if count:
            applied.append(ContextRedaction(label=f"redaction-{index}", occurrences=count))
    return result, tuple(applied)


def _truncate_utf8(text: str, allowance: int) -> tuple[str, int, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= allowance:
        return text, len(encoded), False
    suffix = "\n[TRUNCATED]"
    suffix_bytes = suffix.encode("utf-8")
    body_allowance = max(0, allowance - len(suffix_bytes))
    clipped = encoded[:body_allowance]
    while clipped:
        try:
            prefix = clipped.decode("utf-8")
            break
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    else:
        prefix = ""
    result = prefix + suffix
    return result, len(result.encode("utf-8")), True
