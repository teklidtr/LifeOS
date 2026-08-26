"""Semantic retrieval and evidence-grounded knowledge conversation primitives."""

from . import search as _search
from . import service as _service
from .chunking import chunk_markdown_file, reidentify_note
from .coherence_search import HybridRetriever, StableRetrievalEvidence
from .coherence_service import RetrievalIndexService
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
    RerankCandidate,
    RerankResult,
    RerankingProvider,
    RetrievalError,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalScope,
    ScopeDecision,
    build_provider_disclosure,
    scope_decision,
)
from .evaluation import FixtureResult, RetrievalEvaluation, RetrievalFixture, evaluate_retrieval
from .index import INDEX_SCHEMA_VERSION, RetrievalIndex, StoredEmbedding
from .models import ChunkedNote, IndexedChunk, IndexedDocument
from .policy import load_retrieval_policy
from .providers import (
    DeterministicAnswerProvider,
    DeterministicEmbeddingProvider,
    DeterministicReranker,
    FailingAnswerProvider,
    UnavailableEmbeddingProvider,
)
from .search import RankingComponents, RetrievalEvidence, RetrievalResponse
from .service import IndexHealth, IndexProgress, IndexRecoveryPlan, IndexResult

# Keep direct module imports aligned with the package-level coherence wrappers.
setattr(_search, "HybridRetriever", HybridRetriever)
setattr(_service, "RetrievalIndexService", RetrievalIndexService)

__all__ = [
    "AnswerEvidence",
    "AnswerProvider",
    "CancellationToken",
    "ChunkedNote",
    "DeterministicAnswerProvider",
    "DeterministicEmbeddingProvider",
    "DeterministicReranker",
    "EmbeddingBatch",
    "EmbeddingProvider",
    "FailingAnswerProvider",
    "FixtureResult",
    "GeneratedAnswer",
    "GeneratedParagraph",
    "HybridRetriever",
    "INDEX_SCHEMA_VERSION",
    "IndexHealth",
    "IndexProgress",
    "IndexRecoveryPlan",
    "IndexResult",
    "IndexedChunk",
    "IndexedDocument",
    "ProviderCapabilities",
    "ProviderDisclosure",
    "ProviderError",
    "RankingComponents",
    "RerankCandidate",
    "RerankResult",
    "RerankingProvider",
    "RetrievalError",
    "RetrievalEvaluation",
    "RetrievalEvidence",
    "RetrievalFixture",
    "RetrievalIndex",
    "RetrievalIndexService",
    "RetrievalPolicy",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalScope",
    "ScopeDecision",
    "StableRetrievalEvidence",
    "StoredEmbedding",
    "UnavailableEmbeddingProvider",
    "build_provider_disclosure",
    "chunk_markdown_file",
    "evaluate_retrieval",
    "load_retrieval_policy",
    "reidentify_note",
    "scope_decision",
]
