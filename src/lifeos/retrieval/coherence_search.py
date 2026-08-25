"""Stable-note identity projection for hybrid retrieval results."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.retrieval.contracts import (
    CancellationToken,
    EmbeddingProvider,
    RetrievalError,
    RetrievalPolicy,
    RetrievalRequest,
    RerankingProvider,
    scope_decision,
)
from lifeos.retrieval.models import IndexedChunk, IndexedDocument
from lifeos.retrieval.service import IndexHealth
from lifeos.retrieval.search import (
    HybridRetriever as _BaseHybridRetriever,
    RankingComponents,
    RetrievalEvidence,
    RetrievalResponse,
)
from lifeos.vault import VaultAccessError, read_vault_markdown

_IDENTITY_CAPTURE: ContextVar[dict[str, str | None] | None] = ContextVar(
    "lifeos_retrieval_identity_capture", default=None
)
_STALE_QUERY_PATHS: ContextVar[frozenset[str]] = ContextVar(
    "lifeos_retrieval_stale_query_paths", default=frozenset()
)
_QUERY_HEALTH: ContextVar[IndexHealth | None] = ContextVar(
    "lifeos_retrieval_query_health", default=None
)
_PRE_SCORING_AUTHORIZATION: ContextVar[dict[str, bool] | None] = ContextVar(
    "lifeos_retrieval_pre_scoring_authorization", default=None
)


@dataclass(frozen=True, slots=True)
class StableRetrievalEvidence(RetrievalEvidence):
    """Retrieval evidence that separates durable identity from current filesystem address."""

    stable_id: str | None = None


class HybridRetriever(_BaseHybridRetriever):
    """Hybrid retrieval with conservatively verified relocation-safe identity."""

    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        super().__init__(vault_root=vault_root, runtime_dir=runtime_dir, policy=policy)
        from lifeos.retrieval.coherence_service import (
            RetrievalIndexService as CoherentRetrievalIndexService,
        )

        self.index_service = CoherentRetrievalIndexService(
            vault_root=vault_root, runtime_dir=runtime_dir, policy=self.policy
        )
        try:
            self._runtime_prefix = runtime_exclusion_prefix(
                vault_root, runtime_dir=runtime_dir
            )
        except CoherenceError as exc:
            raise RetrievalError("invalid_runtime_scope", str(exc)) from exc

    def search(
        self,
        request: RetrievalRequest,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankingProvider | None = None,
        graph_hints: Mapping[str, float] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> RetrievalResponse:
        stale_token = _STALE_QUERY_PATHS.set(frozenset())
        health_token = _QUERY_HEALTH.set(None)
        authorization_token = _PRE_SCORING_AUTHORIZATION.set({})
        captured: dict[str, str | None] = {}
        capture_token = _IDENTITY_CAPTURE.set(captured)
        try:
            response = super().search(
                request,
                embedding_provider=embedding_provider,
                reranker=reranker,
                graph_hints=graph_hints,
                cancellation=cancellation,
            )
        finally:
            _IDENTITY_CAPTURE.reset(capture_token)
            _PRE_SCORING_AUTHORIZATION.reset(authorization_token)
            _QUERY_HEALTH.reset(health_token)
            _STALE_QUERY_PATHS.reset(stale_token)

        if not response.results:
            return response

        identity_proof_current = response.index_state == "healthy"
        enriched = tuple(
            _with_stable_id(
                item,
                self._verified_current_stable_id(
                    request=request,
                    item=item,
                    candidate=captured.get(item.path) if identity_proof_current else None,
                ),
            )
            for item in response.results
        )
        return replace(response, results=enriched)

    def _index_health(
        self, *, embedding_provider: EmbeddingProvider | None = None
    ) -> IndexHealth:
        health = super()._index_health(embedding_provider=embedding_provider)
        _QUERY_HEALTH.set(health)
        _STALE_QUERY_PATHS.set(frozenset((*health.orphaned_paths, *health.stale_paths)))
        return health

    def _in_scope(
        self,
        chunk: IndexedChunk,
        document: IndexedDocument,
        request: RetrievalRequest,
    ) -> bool:
        if chunk.path in _STALE_QUERY_PATHS.get():
            return False
        if self._runtime_prefix is not None and chunk.path.startswith(self._runtime_prefix):
            return False
        if not super()._in_scope(chunk, document, request):
            return False

        cache = _PRE_SCORING_AUTHORIZATION.get()
        authorized = cache.get(document.path) if cache is not None else None
        if authorized is None:
            try:
                source = read_vault_markdown(self.vault_root, document.path)
            except VaultAccessError:
                authorized = False
            else:
                current_hash = "sha256:" + hashlib.sha256(source.content_bytes).hexdigest()
                authorized = current_hash == document.content_hash
            if cache is not None:
                cache[document.path] = authorized
        if not authorized:
            return False

        captured = _IDENTITY_CAPTURE.get()
        if captured is not None:
            captured[document.path] = _stable_id(document.document_id)
        return True

    def _authorize_candidates(
        self,
        candidates: list[
            tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]
        ],
        request: RetrievalRequest,
    ) -> list[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]]:
        del request
        authorized = []
        captured = _IDENTITY_CAPTURE.get()
        for candidate in candidates:
            _, document, _, _ = candidate
            try:
                source = read_vault_markdown(self.vault_root, document.path)
            except VaultAccessError:
                continue
            current_hash = "sha256:" + hashlib.sha256(source.content_bytes).hexdigest()
            if current_hash != document.content_hash:
                continue
            if captured is not None:
                captured[document.path] = _stable_id(document.document_id)
            authorized.append(candidate)
        return authorized

    def _verified_current_stable_id(
        self,
        *,
        request: RetrievalRequest,
        item: RetrievalEvidence,
        candidate: str | None,
    ) -> str | None:
        if candidate is None:
            return None
        if item.path.startswith("conversations/") or item.path.startswith("proposals/"):
            return None
        decision = scope_decision(
            item.path, scope=request.scope, policy=self.policy, mode="local"
        )
        if not decision.allowed:
            return None
        return candidate


def _with_stable_id(item: RetrievalEvidence, stable_id: str | None) -> StableRetrievalEvidence:
    return StableRetrievalEvidence(
        evidence_id=item.evidence_id,
        chunk_id=item.chunk_id,
        path=item.path,
        title=item.title,
        heading=item.heading,
        heading_path=item.heading_path,
        start_line=item.start_line,
        end_line=item.end_line,
        block_id=item.block_id,
        text=item.text,
        context_text=item.context_text,
        context_truncated=item.context_truncated,
        source_hash=item.source_hash,
        chunk_hash=item.chunk_hash,
        note_type=item.note_type,
        source=item.source,
        note_date=item.note_date,
        tags=item.tags,
        scope_reason=item.scope_reason,
        matched_terms=item.matched_terms,
        ranking=item.ranking,
        duplicate_paths=item.duplicate_paths,
        stable_id=stable_id,
    )


def _stable_id(document_id: str) -> str | None:
    return document_id[3:] if document_id.startswith("id:") else None
