from pathlib import Path

import pytest

import lifeos.retrieval as retrieval
import lifeos.retrieval.coherence_search as legacy_search
import lifeos.retrieval.search as search
from lifeos.retrieval import (
    CancellationToken,
    DeterministicEmbeddingProvider,
    DeterministicReranker,
    HybridRetriever,
    RetrievalIndex,
    RetrievalIndexService,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalScope,
    chunk_markdown_file,
)
from lifeos.vault import read_vault_markdown


def _write(vault: Path, path: str, stable_id: str, body: str) -> None:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nid: {stable_id}\n---\n{body}\n", encoding="utf-8")


def test_public_retriever_and_evidence_imports_resolve_to_single_types(tmp_path: Path) -> None:
    assert HybridRetriever is search.HybridRetriever is legacy_search.HybridRetriever
    assert HybridRetriever.__module__ == "lifeos.retrieval.search"
    assert retrieval.RetrievalEvidence is retrieval.StableRetrievalEvidence
    assert retrieval.RetrievalEvidence is legacy_search.StableRetrievalEvidence
    vault = tmp_path / "vault"
    _write(vault, "wiki/a.md", "note-a", "# Alpha\n\nidentity marker")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=vault / ".lifeos")
    service.rebuild()
    result = (
        HybridRetriever(vault_root=vault, runtime_dir=vault / ".lifeos")
        .search(RetrievalRequest("identity marker"))
        .results[0]
    )
    assert type(result) is retrieval.RetrievalEvidence
    assert result.stable_id == result.to_dict()["stable_id"] == "note-a"


@pytest.mark.parametrize(
    "retriever_type",
    [HybridRetriever, search.HybridRetriever, legacy_search.HybridRetriever],
    ids=["package", "direct", "legacy"],
)
def test_denied_index_rows_cannot_change_ranking_reads_or_provider_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retriever_type: type[HybridRetriever]
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / "runtime" / "node"
    _write(vault, "wiki/a.md", "note-a", "# Alpha\n\nshared marker [[b]]")
    _write(vault, "wiki/b.md", "note-b", "# Beta\n\nshared marker")
    policy = RetrievalPolicy(excluded_prefixes=("excluded",), protected_prefixes=("private",))
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime, policy=policy)
    service.rebuild()
    embedding = DeterministicEmbeddingProvider()
    service.embed_missing(embedding)
    retriever = retriever_type(vault_root=vault, runtime_dir=runtime, policy=policy)
    # Hold the same health snapshot while denied rows arrive in the derived index.
    health = retriever.index_service.health(embedding_provider=embedding)
    monkeypatch.setattr(retriever.index_service, "health", lambda **_kwargs: health)
    reads: list[str] = []
    embedding_inputs: list[tuple[str, ...]] = []
    rerank_inputs: list[tuple[object, ...]] = []
    real_embed = embedding.embed
    reranker = DeterministicReranker({})
    real_rerank = reranker.rerank

    def recording_read(root, path):
        assert path in {"wiki/a.md", "wiki/b.md"}
        reads.append(path)
        return read_vault_markdown(root, path)

    def recording_embed(texts, **kwargs):
        embedding_inputs.append(tuple(texts))
        return real_embed(texts, **kwargs)

    def recording_rerank(query, candidates, **kwargs):
        rerank_inputs.append(tuple(candidates))
        return real_rerank(query, candidates, **kwargs)

    monkeypatch.setattr(search, "read_vault_markdown", recording_read)
    monkeypatch.setattr(embedding, "embed", recording_embed)
    monkeypatch.setattr(reranker, "rerank", recording_rerank)
    request = RetrievalRequest("shared marker", scope=RetrievalScope(pinned_paths=("wiki/a.md",)))
    baseline = retriever.search(request, embedding_provider=embedding, reranker=reranker)
    baseline_reads, baseline_rerank = tuple(reads), tuple(rerank_inputs)
    assert embedding_inputs == [(request.query,)]

    denied = ("private/hidden.md", "excluded/hidden.md", "runtime/node/hidden.md")
    with RetrievalIndex(service.active_path, create=False) as index:
        for number, path in enumerate(denied):
            _write(
                vault, path, f"hidden-{number}", "# Hidden\n\nshared marker [[wiki/a]] [[wiki/b]]"
            )
            note = chunk_markdown_file(read_vault_markdown(vault, path))
            index.replace_note(note)
            index.write_embeddings(
                chunks=note.chunks,
                batch=real_embed(
                    [chunk.text for chunk in note.chunks],
                    timeout_seconds=None,
                    cancellation=CancellationToken(),
                ),
                created_at="fixture",
            )
    reads.clear()
    embedding_inputs.clear()
    rerank_inputs.clear()
    response = retriever.search(
        request,
        embedding_provider=embedding,
        reranker=reranker,
        graph_hints={path: 1.0 for path in denied},
    )
    assert response.to_dict() == baseline.to_dict()
    assert tuple(reads) == baseline_reads
    assert embedding_inputs == [(request.query,)]
    assert tuple(rerank_inputs) == baseline_rerank


def test_nested_query_does_not_share_authorization_or_identity_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/a.md", "note-a", "# Alpha\n\nouter marker")
    _write(vault, "wiki/b.md", "note-b", "# Beta\n\ninner marker")
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    embedding = DeterministicEmbeddingProvider()
    service.embed_missing(embedding)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    real_embed = embedding.embed
    nested = []

    def nested_embed(texts, **kwargs):
        nested.append(
            retriever.search(
                RetrievalRequest("inner marker", scope=RetrievalScope(paths=("wiki/b.md",)))
            )
        )
        return real_embed(texts, **kwargs)

    monkeypatch.setattr(embedding, "embed", nested_embed)
    outer = retriever.search(
        RetrievalRequest("outer marker", scope=RetrievalScope(paths=("wiki/a.md",))),
        embedding_provider=embedding,
    )
    assert len(nested) == 1
    assert [(item.path, item.stable_id) for item in nested[0].results] == [("wiki/b.md", "note-b")]
    assert [(item.path, item.stable_id) for item in outer.results] == [("wiki/a.md", "note-a")]
    assert outer.semantic_state == "available"


def test_move_during_query_embedding_is_rechecked_before_reranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/a.md", "note-a", "# Alpha\n\nshared marker")
    _write(vault, "wiki/b.md", "note-b", "# Beta\n\nshared marker sensitive evidence [[a]]")
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    embedding = DeterministicEmbeddingProvider()
    service.embed_missing(embedding)
    real_embed = embedding.embed
    reranker = DeterministicReranker({})
    real_rerank = reranker.rerank
    reranked: list[str] = []

    def move_during_embedding(texts, **kwargs):
        protected = vault / "private" / "b.md"
        protected.parent.mkdir()
        (vault / "wiki" / "b.md").rename(protected)
        return real_embed(texts, **kwargs)

    def recording_rerank(query, candidates, **kwargs):
        reranked.extend(item.text for item in candidates)
        return real_rerank(query, candidates, **kwargs)

    monkeypatch.setattr(embedding, "embed", move_during_embedding)
    monkeypatch.setattr(reranker, "rerank", recording_rerank)
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("shared marker", scope=RetrievalScope(pinned_paths=("wiki/a.md",))),
        embedding_provider=embedding,
        reranker=reranker,
    )
    assert [(item.path, item.stable_id) for item in response.results] == [("wiki/a.md", "note-a")]
    assert response.results[0].ranking.link == 0.0
    assert reranked and all("sensitive evidence" not in text for text in reranked)
