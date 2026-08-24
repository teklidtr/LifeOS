"""Stable-note identity projection for hybrid retrieval results."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace

from lifeos.markdown.parser import parse_markdown_note
from lifeos.retrieval.contracts import (
    CancellationToken,
    EmbeddingProvider,
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
from lifeos.vault import VaultAccessError, read_vault_markdown

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

        # Base search already computes index health against the current policy-visible vault.
        # A stale index can still be queried for text evidence, but its build-time uniqueness
        # proof is no longer current. Suppress stable IDs until synchronization restores a
        # healthy identity snapshot rather than doing a second vault-wide scan per query.
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

    def _verified_current_stable_id(
        self,
        *,
        request: RetrievalRequest,
        item: RetrievalEvidence,
        candidate: str | None,
    ) -> str | None:
        """Verify one indexed candidate against only its returned canonical note.

        Build/sync-time duplicate handling proves uniqueness only while index health is current.
        The caller therefore supplies no candidate when the index is stale. For a healthy index,
        search still proves that the result path contains the same candidate ID and exact indexed
        bytes without reopening the mutable SQLite active path or doing another vault-wide scan.
        """
        if candidate is None:
            return None
        if item.path.startswith("conversations/") or item.path.startswith("proposals/"):
            return None
        decision = scope_decision(
            item.path,
            scope=request.scope,
            policy=self.policy,
            mode="local",
        )
        if not decision.allowed:
            return None
        try:
            source = read_vault_markdown(self.vault_root, item.path)
        except VaultAccessError:
            return None
        if "sha256:" + hashlib.sha256(source.content_bytes).hexdigest() != item.source_hash:
            return None
        parsed = parse_markdown_note(source.path, content=source.content)
        current_id = parsed.durable_fields.id
        if current_id is None:
            return None
        return candidate if current_id.strip() == candidate else None


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
