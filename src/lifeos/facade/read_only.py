from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from lifeos.context import (
    ContextPack,
    ContextSearchError,
    ContextSearchExecutionError,
    build_context_pack,
    lexical_search_report,
)
from lifeos.facade.errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.ingestion.taxonomy import extract_source_taxonomy
from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry.file_tracking import FileTrackingError, validate_vault_path
from lifeos.retrieval import RetrievalError, RetrievalPolicy, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.vault import VaultAccessError, is_markdown_path, read_vault_markdown

if TYPE_CHECKING:
    from lifeos.retrieval.contracts import EmbeddingProvider, RerankingProvider

RetrievalMode = Literal["local", "external"]
_CONTEXT_EMBEDDING_PROVIDER: ContextVar[EmbeddingProvider | None] = ContextVar(
    "lifeos_vault_context_embedding_provider", default=None
)
_CONTEXT_RERANKER: ContextVar[RerankingProvider | None] = ContextVar(
    "lifeos_vault_context_reranker", default=None
)

READ_MARKDOWN_DESCRIPTOR = ToolDescriptor(
    name="vault.read_markdown",
    description="Read the Markdown body of a vault-relative file.",
    effect=ToolEffect.READ_ONLY,
)

WIKI_SEARCH_DESCRIPTOR = ToolDescriptor(
    name="wiki.search",
    description="Search durable wiki Markdown before choosing ingestion targets.",
    effect=ToolEffect.READ_ONLY,
)

VAULT_CONTEXT_DESCRIPTOR = ToolDescriptor(
    name="vault.context",
    description=(
        "Build a bounded reasoning context from explicit focus paths, applicable vault "
        "instructions, and relevant canonical Markdown using healthy hybrid retrieval when "
        "available and deterministic local fallback otherwise."
    ),
    effect=ToolEffect.READ_ONLY,
)


def push_vault_context_providers(
    *,
    embedding_provider: EmbeddingProvider | None,
    reranker: RerankingProvider | None,
) -> tuple[Token[EmbeddingProvider | None], Token[RerankingProvider | None]]:
    """Install provider-neutral retrieval dependencies for one runtime invocation context."""
    return (
        _CONTEXT_EMBEDDING_PROVIDER.set(embedding_provider),
        _CONTEXT_RERANKER.set(reranker),
    )


def reset_vault_context_providers(
    tokens: tuple[Token[EmbeddingProvider | None], Token[RerankingProvider | None]],
) -> None:
    """Restore provider-neutral retrieval dependencies after one runtime invocation."""
    embedding_token, reranker_token = tokens
    _CONTEXT_RERANKER.reset(reranker_token)
    _CONTEXT_EMBEDDING_PROVIDER.reset(embedding_token)


@dataclass(frozen=True, slots=True)
class ReadMarkdownRequest:
    vault_path: str
    allow_protected: bool = False
    mode: RetrievalMode = "local"

    def __post_init__(self) -> None:
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        if self.mode not in {"local", "external"}:
            raise ValueError("mode must be local or external")


@dataclass(frozen=True, slots=True)
class ReadMarkdownResult:
    vault_path: str
    markdown_body: str
    source_tags: tuple[str, ...] = ()
    source_topics: tuple[str, ...] = ()


def read_markdown(
    *,
    vault_root: Path,
    request: ReadMarkdownRequest,
) -> ReadMarkdownResult:
    """Read an allowed Markdown file from the vault, returning only its body."""
    try:
        validate_vault_path(request.vault_path)
    except FileTrackingError as e:
        raise ToolValidationError(f"Invalid vault path: {e}") from e

    if not is_markdown_path(request.vault_path):
        raise ToolValidationError("Only Markdown files (.md) are supported")

    _require_allowed(
        vault_root,
        request.vault_path,
        allow_protected=request.allow_protected,
        mode=request.mode,
    )

    try:
        source = read_vault_markdown(vault_root, request.vault_path)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            raise ToolNotFoundError("Target file not found") from exc
        if exc.code in {"unsafe-symlink", "invalid-path"}:
            raise ToolValidationError("Unsafe vault path") from exc
        if exc.code == "unsafe-file-type":
            raise ToolExecutionError("Target is not a regular file") from exc
        if exc.code == "invalid-utf8":
            raise ToolExecutionError("File is not valid UTF-8") from exc
        raise ToolExecutionError("Failed to read file") from exc

    parsed = parse_markdown_note(source.path, content=source.content)
    taxonomy = extract_source_taxonomy(parsed.frontmatter)

    return ReadMarkdownResult(
        vault_path=request.vault_path,
        markdown_body=parsed.body,
        source_tags=taxonomy.tags,
        source_topics=taxonomy.topics,
    )


@dataclass(frozen=True, slots=True)
class WikiSearchRequest:
    query: str
    limit: int = 8

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be a non-empty string")
        if type(self.limit) is not int or not 1 <= self.limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")


@dataclass(frozen=True, slots=True)
class WikiSearchHit:
    path: str
    title: str
    description: str
    excerpt: str
    score: int


@dataclass(frozen=True, slots=True)
class WikiSearchResult:
    query: str
    hits: tuple[WikiSearchHit, ...]


def search_wiki(
    *,
    vault_root: Path,
    request: WikiSearchRequest,
) -> WikiSearchResult:
    """Search only allowed canonical wiki Markdown with deterministic lexical ranking."""
    policy = _policy(vault_root)
    scope = RetrievalScope()
    try:
        report = lexical_search_report(
            vault_root=vault_root,
            query=request.query,
            limit=request.limit,
            path_prefix="wiki",
            path_filter=lambda path: _allowed(
                path,
                scope=scope,
                policy=policy,
                mode="local",
            ),
        )
    except ContextSearchExecutionError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ContextSearchError as exc:
        raise ToolValidationError(str(exc)) from exc

    return WikiSearchResult(
        query=request.query,
        hits=tuple(
            WikiSearchHit(
                path=item.path,
                title=item.title,
                description=item.description,
                excerpt=item.excerpt,
                score=item.score,
            )
            for item in report.results
        ),
    )


@dataclass(frozen=True, slots=True)
class VaultContextRequest:
    question: str
    focus_paths: tuple[str, ...] = ()
    limit: int = 8
    allow_protected: bool = False
    mode: RetrievalMode = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be a non-empty string")
        if self.question != self.question.strip():
            raise ValueError("question must not contain surrounding whitespace")
        if type(self.limit) is not int or not 1 <= self.limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        if len(self.focus_paths) > 8:
            raise ValueError("focus_paths may contain at most 8 paths")
        if len(set(self.focus_paths)) != len(self.focus_paths):
            raise ValueError("focus_paths must not contain duplicates")
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        if self.mode not in {"local", "external"}:
            raise ValueError("mode must be local or external")
        for path in self.focus_paths:
            if not isinstance(path, str) or not path.strip():
                raise ValueError("focus_paths must contain non-empty strings")
            if path != path.strip():
                raise ValueError("focus_paths must not contain surrounding whitespace")


def get_vault_context(
    *,
    vault_root: Path,
    request: VaultContextRequest,
    runtime_dir: Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: RerankingProvider | None = None,
) -> ContextPack:
    """Build inspectable, policy-aware context without granting mutation authority."""
    scope = RetrievalScope(allow_protected=request.allow_protected)
    resolved_embedding_provider = (
        embedding_provider
        if embedding_provider is not None
        else _CONTEXT_EMBEDDING_PROVIDER.get()
    )
    resolved_reranker = reranker if reranker is not None else _CONTEXT_RERANKER.get()
    try:
        return build_context_pack(
            vault_root=vault_root,
            question=request.question,
            limit=request.limit,
            focus_paths=request.focus_paths,
            runtime_dir=runtime_dir or (vault_root / ".lifeos"),
            retrieval_scope=scope,
            retrieval_mode=request.mode,
            embedding_provider=resolved_embedding_provider,
            reranker=resolved_reranker,
        )
    except ContextSearchExecutionError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ContextSearchError as exc:
        raise ToolValidationError(str(exc)) from exc


def _policy(vault_root: Path) -> RetrievalPolicy:
    try:
        return load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ToolExecutionError("Retrieval policy is invalid") from exc


def _allowed(
    path: str,
    *,
    scope: RetrievalScope,
    policy: RetrievalPolicy,
    mode: RetrievalMode,
) -> bool:
    try:
        return scope_decision(path, scope=scope, policy=policy, mode=mode).allowed
    except RetrievalError:
        return False


def _require_allowed(
    vault_root: Path,
    path: str,
    *,
    allow_protected: bool,
    mode: RetrievalMode,
) -> None:
    policy = _policy(vault_root)
    scope = RetrievalScope(allow_protected=allow_protected)
    try:
        decision = scope_decision(path, scope=scope, policy=policy, mode=mode)
    except RetrievalError as exc:
        raise ToolValidationError("Invalid vault path") from exc
    if not decision.allowed:
        raise ToolValidationError(f"Vault path is not available for retrieval: {decision.reason}")
