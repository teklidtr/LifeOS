"""Stable-note identity projection for hybrid retrieval results."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path

import lifeos.retrieval.search as _base_search
from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.context.search import lexical_terms
from lifeos.retrieval.contracts import (
    CancellationToken,
    EmbeddingProvider,
    RetrievalError,
    RetrievalPolicy,
    RetrievalRequest,
    RerankingProvider,
    scope_decision,
)
from lifeos.retrieval.index import RetrievalIndex
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
_SCOPED_QUERY_CHUNKS: ContextVar[dict[str, tuple[IndexedChunk, IndexedDocument]] | None] = (
    ContextVar("lifeos_retrieval_scoped_query_chunks", default=None)
)
_PREAUTHORIZED_PATHS: ContextVar[frozenset[str] | None] = ContextVar(
    "lifeos_retrieval_preauthorized_paths", default=None
)
_ROW_AUTHORIZATION: ContextVar[dict[str, bool] | None] = ContextVar(
    "lifeos_retrieval_row_authorization", default=None
)
_AUTHORIZED_SEMANTIC_IDS: ContextVar[set[str] | None] = ContextVar(
    "lifeos_retrieval_authorized_semantic_ids", default=None
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
        try:
            self._runtime_prefix = runtime_exclusion_prefix(vault_root, runtime_dir=runtime_dir)
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
        distinct_paths: bool = False,
    ) -> RetrievalResponse:
        stale_token = _STALE_QUERY_PATHS.set(frozenset())
        health_token = _QUERY_HEALTH.set(None)
        scoped_chunks: dict[str, tuple[IndexedChunk, IndexedDocument]] = {}
        scoped_token = _SCOPED_QUERY_CHUNKS.set(scoped_chunks)
        preauthorized_token = _PREAUTHORIZED_PATHS.set(None)
        row_authorization: dict[str, bool] = {}
        row_authorization_token = _ROW_AUTHORIZATION.set(row_authorization)
        authorized_semantic_ids: set[str] = set()
        semantic_token = _AUTHORIZED_SEMANTIC_IDS.set(authorized_semantic_ids)
        captured: dict[str, str | None] = {}
        capture_token = _IDENTITY_CAPTURE.set(captured)
        try:
            health = self._index_health(embedding_provider=embedding_provider)
            preauthorized = (
                self._preauthorization_paths(
                    request=request,
                    embedding_provider=embedding_provider,
                    graph_hints=graph_hints,
                )
                if health.active_usable
                else frozenset()
            )
            _PREAUTHORIZED_PATHS.set(preauthorized)
            response = super().search(
                request,
                embedding_provider=embedding_provider,
                reranker=reranker,
                graph_hints=graph_hints,
                cancellation=cancellation,
                distinct_paths=distinct_paths,
            )
        finally:
            _IDENTITY_CAPTURE.reset(capture_token)
            _AUTHORIZED_SEMANTIC_IDS.reset(semantic_token)
            _ROW_AUTHORIZATION.reset(row_authorization_token)
            _PREAUTHORIZED_PATHS.reset(preauthorized_token)
            _SCOPED_QUERY_CHUNKS.reset(scoped_token)
            _QUERY_HEALTH.reset(health_token)
            _STALE_QUERY_PATHS.reset(stale_token)

        if embedding_provider is not None and response.semantic_state == "available":
            semantic_state = "available" if authorized_semantic_ids else "missing-embeddings"
            if semantic_state != response.semantic_state:
                response = replace(response, semantic_state=semantic_state)

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

    def _index_health(self, *, embedding_provider: EmbeddingProvider | None = None) -> IndexHealth:
        existing = _QUERY_HEALTH.get()
        if existing is not None:
            return existing
        health = super()._index_health(embedding_provider=embedding_provider)
        _QUERY_HEALTH.set(health)
        _STALE_QUERY_PATHS.set(frozenset((*health.orphaned_paths, *health.stale_paths)))
        return health

    def _preauthorization_paths(
        self,
        *,
        request: RetrievalRequest,
        embedding_provider: EmbeddingProvider | None,
        graph_hints: Mapping[str, float] | None,
    ) -> frozenset[str]:
        """Find rows that can affect this query before any cross-document scoring.

        Indexed metadata may choose which current canonical paths need verification, but only
        descriptor-verified rows are later admitted to semantic/link/ranking computation. This
        keeps the security boundary ahead of cross-document influence without turning every local
        lexical query into an O(vault-size) canonical file read.
        """
        index = RetrievalIndex(self.index_service.active_path, create=False)
        try:
            documents = {item.path: item for item in index.documents()}
            eligible: list[IndexedChunk] = []
            for chunk in index.chunks():
                document = documents[chunk.path]
                if chunk.path in _STALE_QUERY_PATHS.get():
                    continue
                if self._runtime_prefix is not None and chunk.path.startswith(self._runtime_prefix):
                    continue
                if not _BaseHybridRetriever._in_scope(self, chunk, document, request):
                    continue
                eligible.append(chunk)

            selected = set(request.scope.paths) | set(request.scope.pinned_paths)
            provisional_links = _base_search._link_scores(eligible, selected)
            semantic_chunk_ids: set[str] = set()
            if embedding_provider is not None:
                semantic_chunk_ids = {
                    item.chunk_id for item in index.embeddings(embedding_provider.capabilities)
                }

            terms = lexical_terms(request.query)
            query_text = request.query.casefold().strip()
            graph = graph_hints or {}
            paths = set(selected)
            paths.update(provisional_links)
            for chunk in eligible:
                document = documents[chunk.path]
                exact, lexical, _matched = _base_search._lexical_scores(
                    query_text, terms, chunk=chunk, document=document
                )
                metadata = _base_search._metadata_score(terms, chunk, document, request)
                graph_score = max(0.0, min(1.0, float(graph.get(chunk.path, 0.0))))
                if (
                    exact > 0
                    or lexical > 0
                    or metadata > 0
                    or graph_score > 0
                    or chunk.chunk_id in semantic_chunk_ids
                ):
                    paths.add(chunk.path)
            return frozenset(paths)
        finally:
            index.close()

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

        preauthorized = _PREAUTHORIZED_PATHS.get()
        if preauthorized is not None and document.path not in preauthorized:
            return False

        row_authorization = _ROW_AUTHORIZATION.get()
        if row_authorization is not None:
            allowed = row_authorization.get(document.path)
            if allowed is None:
                try:
                    source = read_vault_markdown(self.vault_root, document.path)
                except VaultAccessError:
                    allowed = False
                else:
                    current_hash = "sha256:" + hashlib.sha256(source.content_bytes).hexdigest()
                    allowed = current_hash == document.content_hash
                row_authorization[document.path] = allowed
            if not allowed:
                return False

        scoped = _SCOPED_QUERY_CHUNKS.get()
        if scoped is not None:
            scoped[chunk.chunk_id] = (chunk, document)
        return True

    def _authorize_candidates(
        self,
        candidates: list[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]],
        request: RetrievalRequest,
    ) -> list[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]]:
        scoped = _SCOPED_QUERY_CHUNKS.get() or {}
        scoped_items = tuple(scoped.values())
        scoped_chunks = tuple(chunk for chunk, _document in scoped_items)
        selected = set(request.scope.paths) | set(request.scope.pinned_paths)
        provisional_links = _base_search._link_scores(scoped_chunks, selected)
        support_paths = selected | set(provisional_links)
        candidate_paths = {document.path for _chunk, document, _components, _matched in candidates}
        paths_to_authorize = candidate_paths | support_paths
        documents_by_path = {document.path: document for _chunk, document in scoped_items}

        authorized_paths: set[str] = set()
        captured = _IDENTITY_CAPTURE.get()
        for path in sorted(paths_to_authorize):
            document = documents_by_path.get(path)
            if document is None:
                continue
            try:
                source = read_vault_markdown(self.vault_root, path)
            except VaultAccessError:
                continue
            current_hash = "sha256:" + hashlib.sha256(source.content_bytes).hexdigest()
            if current_hash != document.content_hash:
                continue
            authorized_paths.add(path)
            if captured is not None:
                captured[path] = _stable_id(document.document_id)

        authorized_support_chunks = tuple(
            chunk for chunk, document in scoped_items if document.path in authorized_paths
        )
        current_links = _base_search._link_scores(authorized_support_chunks, selected)
        semantic_ids = _AUTHORIZED_SEMANTIC_IDS.get()
        authorized: list[
            tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]
        ] = []
        for chunk, document, components, matched in candidates:
            if document.path not in authorized_paths:
                continue
            updated = replace(components, link=current_links.get(chunk.path, 0.0))
            if updated.total <= 0:
                continue
            if semantic_ids is not None and updated.semantic > 0:
                semantic_ids.add(chunk.chunk_id)
            authorized.append((chunk, document, updated, matched))

        authorized.sort(
            key=lambda item: (
                -item[2].total,
                item[0].path,
                item[0].heading or "",
                item[0].start_line,
                item[0].chunk_id,
            )
        )
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
        decision = scope_decision(item.path, scope=request.scope, policy=self.policy, mode="local")
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
