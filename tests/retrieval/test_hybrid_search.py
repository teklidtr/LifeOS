from pathlib import Path

from lifeos.retrieval import (
    CancellationToken,
    DeterministicEmbeddingProvider,
    HybridRetriever,
    RetrievalFixture,
    RetrievalIndexService,
    RetrievalRequest,
    RetrievalScope,
    evaluate_retrieval,
)


def write(root: Path, path: str, content: str) -> None:
    target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")


def setup_vault(tmp_path: Path) -> tuple[Path, Path, RetrievalIndexService]:
    vault = tmp_path / "vault"; vault.mkdir(); runtime = vault / ".lifeos"
    write(vault, "wiki/mitochondria.md", "---\nid: mito\ntype: concept\ntags: [biology]\nsource: textbook\ndate: 2026-01-01\n---\n# Energy\n\nMitochondria produce ATP through oxidative phosphorylation. [[wiki/cell]]")
    write(vault, "wiki/cell.md", "---\nid: cell\ntype: concept\ntags: [biology]\nsource: lecture\ndate: 2026-02-01\n---\n# Organelles\n\nCells contain energy-transforming organelles.")
    write(vault, "wiki/duplicate.md", "# Copy\n\nMitochondria produce ATP through oxidative phosphorylation.")
    write(vault, "journal/run.md", "---\ntype: journal\ntags: [exercise]\ndate: 2026-03-01\n---\n# Run\n\nA calm five kilometre run.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime); service.rebuild()
    return vault, runtime, service


def test_exact_hybrid_ranking_filters_links_and_duplicate_suppression(tmp_path: Path) -> None:
    vault, runtime, _ = setup_vault(tmp_path)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    exact = retriever.search(RetrievalRequest("oxidative phosphorylation", limit=5))
    assert exact.results[0].path == "wiki/mitochondria.md"
    assert exact.results[0].ranking.exact == 1.0
    assert exact.results[0].duplicate_paths == ("wiki/duplicate.md",)
    filtered = retriever.search(RetrievalRequest("energy", scope=RetrievalScope(note_types=("journal",))))
    assert filtered.results == ()
    linked = retriever.search(RetrievalRequest("unrelated words", scope=RetrievalScope(paths=("wiki/mitochondria.md",), pinned_paths=("wiki/mitochondria.md",))))
    assert linked.results and linked.results[0].path == "wiki/mitochondria.md"


def test_semantic_paraphrase_and_irrelevant_similarity_do_not_hide_exact_evidence(tmp_path: Path) -> None:
    vault, runtime, service = setup_vault(tmp_path)
    phrases = {
        "cellular power production": [1, 0, 0, 0],
        "Mitochondria produce ATP through oxidative phosphorylation.": [1, 0, 0, 0],
        "A calm five kilometre run.": [1, 0, 0, 0],
    }
    provider = DeterministicEmbeddingProvider(dimensions=4, phrase_vectors=phrases)
    service.embed_missing(provider)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    semantic = retriever.search(RetrievalRequest("cellular power production"), embedding_provider=provider)
    assert semantic.results[0].path == "wiki/mitochondria.md"
    assert semantic.results[0].ranking.semantic == 1.0
    exact = retriever.search(RetrievalRequest("five kilometre run"), embedding_provider=provider)
    assert exact.results[0].path == "journal/run.md"
    assert exact.results[0].ranking.lexical > 0


def test_metadata_date_source_tag_folder_and_context_budget(tmp_path: Path) -> None:
    vault, runtime, _ = setup_vault(tmp_path)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    scope = RetrievalScope(folders=("wiki",), tags=("biology",), sources=("lecture",), date_from="2026-02-01")
    response = retriever.search(RetrievalRequest("energy organelles", scope=scope, context_budget=12))
    assert [item.path for item in response.results] == ["wiki/cell.md"]
    assert response.context_characters == 12
    assert response.results[0].context_truncated


def test_no_provider_empty_scope_graph_hint_and_deterministic_ties(tmp_path: Path) -> None:
    vault, runtime, _ = setup_vault(tmp_path)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    local = retriever.search(RetrievalRequest("ATP"))
    assert local.semantic_state == "not-configured" and local.results
    empty = retriever.search(RetrievalRequest("nothing", scope=RetrievalScope(paths=("missing.md",))))
    assert empty.state == "no-results"
    graph = retriever.search(RetrievalRequest("nothing"), graph_hints={"wiki/cell.md": 1.0})
    assert graph.results[0].path == "wiki/cell.md"
    first = retriever.search(RetrievalRequest("concept")); second = retriever.search(RetrievalRequest("concept"))
    assert first.to_dict() == second.to_dict()


def test_retrieval_evaluation_reports_separate_regression_metrics(tmp_path: Path) -> None:
    vault, runtime, _ = setup_vault(tmp_path)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    evaluation = evaluate_retrieval((
        RetrievalFixture("exact", RetrievalRequest("oxidative phosphorylation"), ("wiki/mitochondria.md",), k=3),
        RetrievalFixture("empty", RetrievalRequest("xyzzynotfound"), expected_no_answer=True),
    ), run=retriever.search)
    assert evaluation.mean_recall_at_k == 1.0
    assert evaluation.ranking_stability_rate == 1.0
    assert evaluation.reference_validity_rate == 1.0
    assert evaluation.duplicate_suppression_rate == 1.0
    assert evaluation.no_answer_accuracy == 1.0
