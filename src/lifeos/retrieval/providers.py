"""Deterministic provider adapters used for tests and offline operation."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence

from lifeos.retrieval.contracts import (
    AnswerEvidence,
    CancellationToken,
    EmbeddingBatch,
    GeneratedAnswer,
    ProviderCapabilities,
    ProviderError,
    RerankCandidate,
    RerankResult,
)

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class DeterministicEmbeddingProvider:
    """Local hash-vector adapter with optional phrase vectors for deterministic fixtures."""

    def __init__(
        self,
        *,
        dimensions: int = 16,
        phrase_vectors: Mapping[str, Sequence[float]] | None = None,
        adapter_key: str = "deterministic-fixture",
        model_key: str = "hash-vector-v1",
    ) -> None:
        self._dimensions = dimensions
        self._phrases = {key.casefold(): tuple(float(value) for value in vector) for key, vector in (phrase_vectors or {}).items()}
        if dimensions <= 0 or any(len(vector) != dimensions for vector in self._phrases.values()):
            raise ProviderError("invalid_provider", "Fixture vectors must match configured dimensions.")
        self._capabilities = ProviderCapabilities(
            "embedding", adapter_key, model_key, True, 128, vector_dimensions=dimensions
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> EmbeddingBatch:
        if len(texts) > self.capabilities.max_batch_size:
            raise ProviderError("batch_too_large", "Embedding batch exceeds provider capability.")
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            cancellation.checkpoint()
            exact = self._phrases.get(text.casefold())
            if exact is not None:
                vectors.append(_normalize(exact))
                continue
            values = [0.0] * self._dimensions
            for token in _TOKEN.findall(text.casefold()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self._dimensions
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                values[index] += sign
            vectors.append(_normalize(tuple(values)))
        return EmbeddingBatch(tuple(vectors), self.capabilities)


class DeterministicReranker:
    def __init__(self, scores: Mapping[str, float]) -> None:
        self._scores = dict(scores)
        self._capabilities = ProviderCapabilities(
            "reranker", "deterministic-fixture", "score-map-v1", True, 256
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> tuple[RerankResult, ...]:
        del query, timeout_seconds
        results: list[RerankResult] = []
        for candidate in candidates:
            cancellation.checkpoint()
            results.append(RerankResult(candidate.evidence_id, self._scores.get(candidate.evidence_id, candidate.base_score)))
        return tuple(sorted(results, key=lambda item: (-item.score, item.evidence_id)))


class UnavailableEmbeddingProvider:
    def __init__(self) -> None:
        self._capabilities = ProviderCapabilities(
            "embedding", "unavailable", "none", True, 1, vector_dimensions=1
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> EmbeddingBatch:
        del texts, timeout_seconds, cancellation
        raise ProviderError("unavailable_provider", "No embedding provider is configured.")


def _normalize(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return tuple(0.0 for _ in vector)
    return tuple(value / norm for value in vector)

class DeterministicAnswerProvider:
    """Configurable local answer adapter for deterministic fixtures and demos."""

    def __init__(self, answer: GeneratedAnswer, *, local_only: bool = True) -> None:
        if not isinstance(answer, GeneratedAnswer):
            raise ProviderError("invalid_provider", "Deterministic answer must use GeneratedAnswer.")
        self._answer = answer
        self._capabilities = ProviderCapabilities(
            "generation", "deterministic-fixture", "answer-map-v1", local_only, 64
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(
        self,
        query: str,
        evidence: Sequence[AnswerEvidence],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> GeneratedAnswer:
        del query, evidence, timeout_seconds
        cancellation.checkpoint()
        return self._answer


class FailingAnswerProvider:
    """Deterministic provider failure adapter for timeout and malformed-state tests."""

    def __init__(self, code: str = "timeout") -> None:
        self.code = code
        self._capabilities = ProviderCapabilities(
            "generation", "deterministic-fixture", "failure-v1", True, 64
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(
        self,
        query: str,
        evidence: Sequence[AnswerEvidence],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> GeneratedAnswer:
        del query, evidence, timeout_seconds
        cancellation.checkpoint()
        raise ProviderError(self.code, f"Deterministic provider failure: {self.code}.")
