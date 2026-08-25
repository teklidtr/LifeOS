from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import lifeos.retrieval.search as base_search
from lifeos.retrieval import HybridRetriever, RetrievalIndexService, RetrievalRequest
from lifeos.retrieval.contracts import (
    CancellationToken,
    ProviderCapabilities,
    RerankCandidate,
    RerankResult,
)


class _RecordingReranker:
    def __init__(self) -> None:
        self.seen: list[tuple[RerankCandidate, ...]] = []
        self._capabilities = ProviderCapabilities(
            kind="reranker",
            adapter_key="test-external",
            model_key="test-reranker",
            local_only=False,
            max_batch_size=100,
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
        del query, timeout_seconds, cancellation
        batch = tuple(candidates)
        self.seen.append(batch)
        return tuple(RerankResult(item.evidence_id, 1.0) for item in batch)


def test_public_note_moved_to_protected_path_never_reaches_reranker(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    marker = "stale-public-secret-marker"
    public = vault / "wiki" / "public.md"
    public.parent.mkdir()
    public.write_text(f"# Public\n\n{marker}\n", encoding="utf-8")

    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    protected = vault / "private" / "secret.md"
    protected.parent.mkdir()
    public.rename(protected)

    reranker = _RecordingReranker()
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest(marker),
        reranker=reranker,
    )

    assert response.index_state == "stale"
    assert response.results == ()
    assert reranker.seen == []


def test_moved_public_note_with_reused_path_never_reaches_reranker(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    marker = "reused-path-secret-marker"
    public = vault / "wiki" / "public.md"
    public.parent.mkdir()
    public.write_text(f"# Public\n\n{marker}\n", encoding="utf-8")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    protected = vault / "private" / "secret.md"
    protected.parent.mkdir()
    public.rename(protected)
    public.write_text("# Unrelated replacement\n", encoding="utf-8")

    reranker = _RecordingReranker()
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest(marker),
        reranker=reranker,
    )

    assert response.index_state == "stale"
    assert response.results == ()
    assert reranker.seen == []


def test_move_after_query_health_snapshot_never_reaches_reranker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    marker = "health-race-secret-marker"
    public = vault / "wiki" / "public.md"
    public.parent.mkdir()
    public.write_text(f"# Public\n\n{marker}\n", encoding="utf-8")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    original_health = retriever.index_service.health
    calls = 0

    def move_after_health(*, embedding_provider=None):
        nonlocal calls
        calls += 1
        health = original_health(embedding_provider=embedding_provider)
        protected = vault / "private" / "secret.md"
        protected.parent.mkdir(exist_ok=True)
        public.rename(protected)
        return health

    monkeypatch.setattr(retriever.index_service, "health", move_after_health)
    reranker = _RecordingReranker()
    response = retriever.search(RetrievalRequest(marker), reranker=reranker)

    assert calls == 1
    assert response.results == ()
    assert reranker.seen == []


def test_move_after_health_is_removed_before_cross_document_scoring(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    wiki = vault / "wiki"
    wiki.mkdir()
    safe = wiki / "safe.md"
    risky = wiki / "risky.md"
    safe.write_text("# Safe\n\nrank-race-marker\n", encoding="utf-8")
    risky.write_text("# Risky\n\n[[Safe]]\nprivate-derived-link\n", encoding="utf-8")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    original_health = retriever.index_service.health

    def move_after_health(*, embedding_provider=None):
        health = original_health(embedding_provider=embedding_provider)
        private = vault / "private"
        private.mkdir(exist_ok=True)
        risky.rename(private / "risky.md")
        return health

    observed_paths: list[tuple[str, ...]] = []
    original_link_scores = base_search._link_scores

    def recording_link_scores(chunks, selected):
        observed_paths.append(tuple(chunk.path for chunk in chunks))
        return original_link_scores(chunks, selected)

    monkeypatch.setattr(retriever.index_service, "health", move_after_health)
    monkeypatch.setattr(base_search, "_link_scores", recording_link_scores)

    response = retriever.search(RetrievalRequest("rank-race-marker"))

    assert observed_paths == [("wiki/safe.md",)]
    assert tuple(item.path for item in response.results) == ("wiki/safe.md",)
