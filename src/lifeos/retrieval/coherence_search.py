"""Stable-note identity projection for hybrid retrieval results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from lifeos.retrieval.contracts import (
    CancellationToken,
    EmbeddingProvider,
    RetrievalRequest,
    RerankingProvider,
)
from lifeos.retrieval.index import RetrievalIndex
from lifeos.retrieval.search import (
    HybridRetriever as _BaseHybridRetriever,
    RetrievalEvidence,
    RetrievalResponse,
)


@dataclass(frozen=True, slots=True)
class StableRetrievalEvidence(RetrievalEvidence):
    """Retrieval evidence that separates durable identity from current filesystem address."""

    stable_id: str | None = None


class HybridRetriever(_BaseHybridRetriever):
    """Hybrid retrieval with relocation-safe identity exposed beside the current path."""

    def search(
        self,
        request: RetrievalRequest,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankingProvider | None = None,
        graph_hints: Mapping[str, float] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> RetrievalResponse:
        response = super().search(
            request,
            embedding_provider=embedding_provider,
            reranker=reranker,
            graph_hints=graph_hints,
            cancellation=cancellation,
        )
        if not response.results:
            return response

        index = RetrievalIndex(self.index_service.active_path, create=False)
        try:
            documents = {document.path: document for document in index.documents()}
            enriched = tuple(
                StableRetrievalEvidence(
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
                    stable_id=_stable_id(documents[item.path].document_id),
                )
                for item in response.results
            )
        finally:
            index.close()
        return replace(response, results=enriched)


def _stable_id(document_id: str) -> str | None:
    return document_id[3:] if document_id.startswith("id:") else None
