"""Stable-note identity projection for hybrid retrieval results."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace

from lifeos.coherence import CoherenceError, IdentitySnapshot
from lifeos.coherence_scoped import collect_scoped_identity_snapshot
from lifeos.retrieval.contracts import (
    CancellationToken,
    EmbeddingProvider,
    RetrievalError,
    RetrievalRequest,
    RerankingProvider,
    scope_decision,
)
from lifeos.retrieval.models import IndexedChunk, IndexedDocument
from lifeos.retrieval.search import (
    HybridRetriever as _BaseHybridRetriever,
    RetrievalEvidence,
    RetrievalResponse,
)

_IDENTITY_CAPTURE: ContextVar[dict[str, str | None] | None] = ContextVar(
    "lifeos_retrieval_identity_capture",
    default=None,
)


@dataclass(frozen=True, slots=True)
class StableRetrievalEvidence(RetrievalEvidence):
    """Retrieval evidence that separates durable identity from current filesystem address."""

    stable_id: str | None = None


class HybridRetriever(_BaseHybridRetriever):
    """Hybrid retrieval with conservatively verified relocation-safe identity."""

    def search(
        self,
        request: RetrievalRequest,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankingProvider | None = None,
        graph_hints: Mapping[str, float] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> RetrievalResponse:
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

        if not response.results:
            return response

        try:
            snapshot = collect_scoped_identity_snapshot(
                self.vault_root,
                allow_path=lambda path: (
                    not path.startswith("conversations/")
                    and not path.startswith("proposals/")
                    and scope_decision(
                        path,
                        scope=request.scope,
                        policy=self.policy,
                        mode="local",
                    ).allowed
                ),
            )
        except (CoherenceError, RetrievalError):
            return replace(
                response,
                results=tuple(_with_stable_id(item, None) for item in response.results),
                diagnostics=(*response.diagnostics, "stable-identity-unavailable"),
            )

        enriched = tuple(
            _with_stable_id(
                item,
                _verified_stable_id(
                    snapshot,
                    path=item.path,
                    source_hash=item.source_hash,
                    candidate=captured.get(item.path),
                ),
            )
            for item in response.results
        )
        return replace(response, results=enriched)

    def _in_scope(
        self,
        chunk: IndexedChunk,
        document: IndexedDocument,
        request: RetrievalRequest,
    ) -> bool:
        allowed = super()._in_scope(chunk, document, request)
        captured = _IDENTITY_CAPTURE.get()
        if allowed and captured is not None:
            captured[document.path] = _stable_id(document.document_id)
        return allowed


def _verified_stable_id(
    snapshot: IdentitySnapshot,
    *,
    path: str,
    source_hash: str,
    candidate: str | None,
) -> str | None:
    if candidate is None:
        return None
    current = snapshot.by_path(path)
    if current is None:
        return None
    if current.stable_id != candidate or current.content_hash != source_hash:
        return None
    return candidate if len(snapshot.by_stable_id(candidate)) == 1 else None


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
