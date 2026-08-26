"""Provider-neutral contracts for bounded, inspectable vault retrieval."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from threading import Event
from typing import Literal, Protocol, runtime_checkable

RetrievalMode = Literal["local", "external"]
ProviderKind = Literal["embedding", "reranker", "generation"]
SupportKind = Literal["direct", "synthesis", "inference"]

_NODE_LOCAL_EXCLUDED_PREFIXES: ContextVar[tuple[str, ...]] = ContextVar(
    "lifeos_node_local_retrieval_excluded_prefixes",
    default=(),
)
_NODE_LOCAL_EXCLUSION_PREDICATES: ContextVar[tuple[Callable[[str], bool], ...]] = ContextVar(
    "lifeos_node_local_retrieval_exclusion_predicates",
    default=(),
)


class RetrievalError(ValueError):
    """Base error for invalid retrieval requests or unavailable derived state."""

    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


class ProviderError(RetrievalError):
    """Provider-neutral adapter failure."""


class CancellationToken:
    """Small cooperative cancellation primitive shared by providers and index jobs."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def checkpoint(self) -> None:
        if self.cancelled:
            raise RetrievalError("cancelled", "The retrieval operation was cancelled.")


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    kind: ProviderKind
    adapter_key: str
    model_key: str
    local_only: bool
    max_batch_size: int
    timeout_supported: bool = True
    cancellation_supported: bool = True
    vector_dimensions: int | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name, value in (("adapter_key", self.adapter_key), ("model_key", self.model_key)):
            if not value.strip():
                raise RetrievalError("invalid_provider", f"{name} must be non-empty.")
        if type(self.max_batch_size) is not int or self.max_batch_size <= 0:
            raise RetrievalError("invalid_provider", "max_batch_size must be positive.")
        if self.vector_dimensions is not None and self.vector_dimensions <= 0:
            raise RetrievalError("invalid_provider", "vector_dimensions must be positive.")
        if self.schema_version != 1:
            raise RetrievalError("unsupported_provider_schema", "Provider schema version is unsupported.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    capabilities: ProviderCapabilities

    def __post_init__(self) -> None:
        dimensions = self.capabilities.vector_dimensions
        if len(self.vectors) == 0:
            return
        expected = dimensions or len(self.vectors[0])
        if expected <= 0 or any(len(vector) != expected for vector in self.vectors):
            raise ProviderError("malformed_provider_output", "Embedding dimensions are inconsistent.")
        for vector in self.vectors:
            if any(not isinstance(value, (int, float)) for value in vector):
                raise ProviderError("malformed_provider_output", "Embedding values must be numeric.")


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    evidence_id: str
    text: str
    base_score: float


@dataclass(frozen=True, slots=True)
class RerankResult:
    evidence_id: str
    score: float


@dataclass(frozen=True, slots=True)
class AnswerEvidence:
    evidence_id: str
    path: str
    heading: str | None
    text: str
    source_hash: str
    chunk_hash: str


@dataclass(frozen=True, slots=True)
class GeneratedParagraph:
    text: str
    citations: tuple[str, ...]
    support: SupportKind


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    paragraphs: tuple[GeneratedParagraph, ...]
    explanation: str
    schema_version: int = 1


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> EmbeddingBatch: ...


@runtime_checkable
class RerankingProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> tuple[RerankResult, ...]: ...


@runtime_checkable
class AnswerProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def generate(
        self,
        query: str,
        evidence: Sequence[AnswerEvidence],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> GeneratedAnswer: ...


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    paths: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    note_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    excluded_paths: tuple[str, ...] = ()
    pinned_paths: tuple[str, ...] = ()
    include_graph: bool = True
    allow_protected: bool = False
    saved_scope: str | None = None

    def __post_init__(self) -> None:
        for values in (self.paths, self.folders, self.excluded_paths, self.pinned_paths):
            for value in values:
                _safe_relative(value, allow_folder=True)
        for values in (self.note_types, self.tags, self.sources):
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise RetrievalError("invalid_scope", "Scope values must be non-empty strings.")
        if self.saved_scope is not None and not self.saved_scope.strip():
            raise RetrievalError("invalid_scope", "saved_scope must be non-empty when provided.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    excluded_prefixes: tuple[str, ...] = ()
    protected_prefixes: tuple[str, ...] = (
        "private",
        "secrets",
        "profile/private",
        "journal/private",
        "health/private",
    )
    external_allowed_prefixes: tuple[str, ...] = ()
    max_external_characters: int = 24_000
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RetrievalError("unsupported_policy_schema", "Retrieval policy schema is unsupported.")
        for values in (
            self.excluded_prefixes,
            self.protected_prefixes,
            self.external_allowed_prefixes,
        ):
            for value in values:
                _safe_relative(value, allow_folder=True)
        if type(self.max_external_characters) is not int or self.max_external_characters <= 0:
            raise RetrievalError("invalid_policy", "max_external_characters must be positive.")


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    path: str
    allowed: bool
    protected: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ProviderDisclosureItem:
    path: str
    heading: str | None
    characters: int
    protected: bool


@dataclass(frozen=True, slots=True)
class ProviderDisclosure:
    mode: RetrievalMode
    adapter_key: str | None
    model_key: str | None
    total_characters: int
    protected_content: bool
    items: tuple[ProviderDisclosureItem, ...]
    allowed: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def push_node_local_excluded_prefixes(
    prefixes: Sequence[str],
) -> Token[tuple[str, ...]]:
    """Temporarily add node-local vault prefixes to every retrieval decision in this context."""
    normalized = tuple(_safe_relative(prefix, allow_folder=True) for prefix in prefixes)
    current = _NODE_LOCAL_EXCLUDED_PREFIXES.get()
    merged = tuple(dict.fromkeys((*current, *normalized)))
    return _NODE_LOCAL_EXCLUDED_PREFIXES.set(merged)


def reset_node_local_excluded_prefixes(token: Token[tuple[str, ...]]) -> None:
    """Restore the prior node-local retrieval exclusion context."""
    _NODE_LOCAL_EXCLUDED_PREFIXES.reset(token)


def push_node_local_exclusion_predicates(
    predicates: Sequence[Callable[[str], bool]],
) -> Token[tuple[Callable[[str], bool], ...]]:
    """Temporarily add filesystem-aware node-local exclusion predicates."""
    current = _NODE_LOCAL_EXCLUSION_PREDICATES.get()
    return _NODE_LOCAL_EXCLUSION_PREDICATES.set((*current, *predicates))


def reset_node_local_exclusion_predicates(
    token: Token[tuple[Callable[[str], bool], ...]],
) -> None:
    """Restore prior filesystem-aware node-local exclusion predicates."""
    _NODE_LOCAL_EXCLUSION_PREDICATES.reset(token)


def scope_decision(
    path: str,
    *,
    scope: RetrievalScope,
    policy: RetrievalPolicy,
    mode: RetrievalMode,
) -> ScopeDecision:
    normalized = _safe_relative(path)
    if _matches_prefix(normalized, policy.excluded_prefixes):
        return ScopeDecision(normalized, False, False, "excluded-by-policy")
    if _matches_prefix(normalized, _NODE_LOCAL_EXCLUDED_PREFIXES.get()):
        return ScopeDecision(normalized, False, False, "excluded-node-local-runtime")
    if any(predicate(normalized) for predicate in _NODE_LOCAL_EXCLUSION_PREDICATES.get()):
        return ScopeDecision(normalized, False, False, "excluded-node-local-runtime")
    if _matches_prefix(normalized, scope.excluded_paths):
        return ScopeDecision(normalized, False, False, "excluded-by-request")
    protected = _matches_prefix(normalized, policy.protected_prefixes)
    if protected and not scope.allow_protected:
        return ScopeDecision(normalized, False, True, "protected-default-deny")
    if mode == "external" and protected:
        if not _matches_prefix(normalized, policy.external_allowed_prefixes):
            return ScopeDecision(normalized, False, True, "protected-external-deny")
    if scope.paths and normalized not in scope.paths:
        return ScopeDecision(normalized, False, protected, "outside-selected-paths")
    if scope.folders and not _matches_prefix(normalized, scope.folders):
        return ScopeDecision(normalized, False, protected, "outside-selected-folders")
    return ScopeDecision(normalized, True, protected, "allowed")


def build_provider_disclosure(
    *,
    evidence: Sequence[AnswerEvidence],
    capabilities: ProviderCapabilities | None,
    scope: RetrievalScope,
    policy: RetrievalPolicy,
) -> ProviderDisclosure:
    if capabilities is None:
        return ProviderDisclosure("local", None, None, 0, False, (), True, "no-provider")
    mode: RetrievalMode = "local" if capabilities.local_only else "external"
    items: list[ProviderDisclosureItem] = []
    allowed = True
    reason = "allowed"
    total = 0
    protected_content = False
    for item in evidence:
        decision = scope_decision(item.path, scope=scope, policy=policy, mode=mode)
        protected_content = protected_content or decision.protected
        count = len(item.text)
        items.append(ProviderDisclosureItem(item.path, item.heading, count, decision.protected))
        total += count
        if not decision.allowed:
            allowed = False
            reason = decision.reason
    if mode == "external" and total > policy.max_external_characters:
        allowed = False
        reason = "external-context-budget-exceeded"
    return ProviderDisclosure(
        mode,
        capabilities.adapter_key,
        capabilities.model_key,
        total,
        protected_content,
        tuple(items),
        allowed,
        reason,
    )


def _matches_prefix(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _safe_relative(value: str, *, allow_folder: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or "\\" in value or "\x00" in value:
        raise RetrievalError("invalid_scope", "Vault paths must be non-empty POSIX paths.")
    normalized = value.strip().strip("/") if allow_folder else value.strip()
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RetrievalError("invalid_scope", f"Path must stay within the vault: {value}")
    return pure.as_posix()


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    query: str
    scope: RetrievalScope = field(default_factory=RetrievalScope)
    limit: int = 8
    context_budget: int = 12_000
    timeout_seconds: float | None = 30.0
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise RetrievalError("invalid_query", "query must be non-empty.")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise RetrievalError("invalid_limit", "limit must be between 1 and 100.")
        if type(self.context_budget) is not int or self.context_budget <= 0:
            raise RetrievalError("invalid_context_budget", "context_budget must be positive.")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise RetrievalError("invalid_timeout", "timeout_seconds must be positive.")
