"""Semantic retrieval and evidence-grounded knowledge conversation primitives."""

from .contracts import (
    AnswerEvidence,
    AnswerProvider,
    CancellationToken,
    EmbeddingBatch,
    EmbeddingProvider,
    GeneratedAnswer,
    GeneratedParagraph,
    ProviderCapabilities,
    ProviderDisclosure,
    ProviderError,
    RetrievalError,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalScope,
    RerankCandidate,
    RerankResult,
    RerankingProvider,
    ScopeDecision,
    build_provider_disclosure,
    scope_decision,
)
from .chunking import chunk_markdown_file, reidentify_note
from .index import INDEX_SCHEMA_VERSION, RetrievalIndex, StoredEmbedding
from .models import ChunkedNote, IndexedChunk, IndexedDocument
from .policy import load_retrieval_policy
from .service import IndexHealth, IndexProgress, IndexResult, RetrievalIndexService
from .providers import DeterministicEmbeddingProvider, DeterministicReranker, UnavailableEmbeddingProvider

__all__ = [
    "AnswerEvidence",
    "AnswerProvider",
    "ChunkedNote",
    "CancellationToken",
    "INDEX_SCHEMA_VERSION",
    "IndexHealth",
    "IndexProgress",
    "IndexResult",
    "IndexedChunk",
    "IndexedDocument",
    "DeterministicEmbeddingProvider",
    "DeterministicReranker",
    "EmbeddingBatch",
    "EmbeddingProvider",
    "GeneratedAnswer",
    "GeneratedParagraph",
    "ProviderCapabilities",
    "ProviderDisclosure",
    "ProviderError",
    "RetrievalError",
    "RetrievalIndex",
    "RetrievalIndexService",
    "RetrievalPolicy",
    "RetrievalRequest",
    "RetrievalScope",
    "RerankCandidate",
    "RerankResult",
    "RerankingProvider",
    "ScopeDecision",
    "StoredEmbedding",
    "UnavailableEmbeddingProvider",
    "build_provider_disclosure",
    "chunk_markdown_file",
    "load_retrieval_policy",
    "reidentify_note",
    "scope_decision",
]
