from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lifeos.context import build_context_pack
from lifeos.facade.read_only import VaultContextRequest, get_vault_context
from lifeos.retrieval import (
    CancellationToken,
    DeterministicEmbeddingProvider,
    EmbeddingBatch,
    ProviderCapabilities,
    ProviderError,
    RerankCandidate,
    RerankResult,
    RetrievalIndexService,
    RetrievalScope,
)


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class _ExplodingEmbeddingProvider:
    def __init__(self) -> None:
        self._capabilities = ProviderCapabilities(
            kind="embedding",
            adapter_key="exploding-test",
            model_key="never-call-v1",
            local_only=True,
            max_batch_size=8,
            vector_dimensions=4,
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
        raise AssertionError("embedding provider must not be called")


class _RecordingReranker:
    def __init__(self, *, fail_code: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_code = fail_code
        self._capabilities = ProviderCapabilities(
            kind="reranker",
            adapter_key="recording-test",
            model_key="recording-v1",
            local_only=True,
            max_batch_size=256,
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
        cancellation.checkpoint()
        self.calls.append(tuple(item.evidence_id for item in candidates))
        if self.fail_code is not None:
            raise ProviderError(self.fail_code, "deterministic reranker failure")
        return tuple(RerankResult(item.evidence_id, item.base_score) for item in candidates)


def _indexed_vault(tmp_path: Path) -> tuple[Path, Path, DeterministicEmbeddingProvider]:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    _write(
        vault,
        "study/focus.md",
        "---\nid: focus\ntitle: Exam focus\ndescription: Explicit study source.\n---\n"
        "Uncontrolled junction priority rules.",
    )
    _write(
        vault,
        "wiki/mitochondria.md",
        "---\nid: mito\ntitle: Mitochondria\ndescription: Cellular energy mechanisms.\n"
        "type: concept\ntags: [biology]\n---\n"
        "Mitochondria produce ATP through oxidative phosphorylation. [[wiki/cell]]",
    )
    _write(
        vault,
        "wiki/cell.md",
        "---\nid: cell\ntitle: Cell\ndescription: Cell organelles.\ntype: concept\n"
        "tags: [biology]\n---\nCells contain energy-transforming organelles.",
    )
    _write(
        vault,
        "wiki/duplicate.md",
        "---\nid: duplicate\ntitle: Duplicate\ndescription: Duplicate evidence.\n---\n"
        "Mitochondria produce ATP through oxidative phosphorylation.",
    )
    _write(
        vault,
        "private/secret.md",
        "---\nid: secret\ntitle: Secret ATP\ndescription: Protected evidence.\n---\n"
        "Cellular power production secret ATP evidence.",
    )
    _write(
        vault,
        "system/instructions.yml",
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: exam-focus\n"
        "    authority: system\n"
        "    scope: path\n"
        "    priority: 100\n"
        "    text: Prioritize exam-relevant distinctions.\n"
        "    paths: [study/**]\n",
    )
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    provider = DeterministicEmbeddingProvider(
        dimensions=4,
        phrase_vectors={
            "cellular power production": [1, 0, 0, 0],
            "Mitochondria produce ATP through oxidative phosphorylation. [[wiki/cell]]": [
                1,
                0,
                0,
                0,
            ],
        },
    )
    service.embed_missing(provider)
    return vault, runtime, provider


def test_context_pack_uses_hybrid_retrieval_and_keeps_focus_authoritative(tmp_path: Path) -> None:
    vault, runtime, provider = _indexed_vault(tmp_path)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="cellular power production",
        focus_paths=("study/focus.md",),
        limit=3,
        embedding_provider=provider,
    )

    assert pack.sources[0].path == "study/focus.md"
    assert pack.sources[0].retrieval_mode == "focus"
    retrieved = next(source for source in pack.sources if source.path == "wiki/mitochondria.md")
    assert retrieved.retrieval_mode == "hybrid"
    assert "semantic" in retrieved.retrieval_reasons
    assert "wiki/duplicate.md" in retrieved.duplicate_paths
    assert [item.id for item in pack.instructions] == ["exam-focus"]
    assert pack.instructions[0].applicable_sources == ("study/focus.md",)
    assert "private/secret.md" not in {source.path for source in pack.sources}


def test_build_context_pack_uses_default_lifeos_retrieval_runtime(tmp_path: Path) -> None:
    vault, _runtime, _provider = _indexed_vault(tmp_path)

    pack = build_context_pack(vault_root=vault, question="ATP", limit=3)

    assert pack.sources
    assert any(source.retrieval_mode == "hybrid" for source in pack.sources)
    assert any("Semantic retrieval was not configured" in omission for omission in pack.omissions)


def test_context_pack_hybrid_sources_are_deduplicated_and_budgeted_by_note(tmp_path: Path) -> None:
    vault, runtime, provider = _indexed_vault(tmp_path)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP",
        limit=1,
        embedding_provider=provider,
    )

    assert len(pack.sources) == 1
    assert pack.sources[0].retrieval_mode == "hybrid"
    assert "Results were limited to the top 1 sources." in pack.omissions


def test_long_note_chunks_do_not_starve_other_matching_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    long_body = "\n\n".join(f"ATP evidence paragraph {index}." * 80 for index in range(24))
    _write(vault, "wiki/long.md", f"---\ntitle: Long\n---\n{long_body}")
    _write(vault, "wiki/short.md", "---\ntitle: Short\n---\nATP evidence in another note.")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(vault_root=vault, runtime_dir=runtime, question="ATP", limit=2)

    assert {source.path for source in pack.sources} == {"wiki/long.md", "wiki/short.md"}


def test_context_pack_preserves_description_only_lexical_routing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/routing.md",
        "---\ntitle: Routing note\ndescription: quasar-memory routing clue\n---\n"
        "Body intentionally contains unrelated words.",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="quasar-memory",
        limit=3,
    )

    source = next(item for item in pack.sources if item.path == "wiki/routing.md")
    assert source.retrieval_mode == "lexical"
    assert "description" in {evidence.field for evidence in source.score_evidence}


def test_context_pack_falls_back_when_retrieval_index_is_unavailable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    _write(
        vault,
        "wiki/sleep.md",
        "---\ntitle: Sleep\ndescription: Recovery evidence.\n---\nSleep supports recovery.",
    )

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="sleep",
    )

    assert [source.path for source in pack.sources] == ["wiki/sleep.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"
    assert any("lexical fallback" in omission for omission in pack.omissions)


def test_lexical_fallback_keeps_protected_scope_default_deny(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "wiki/public.md",
        "---\ntitle: Public ATP\ndescription: Public evidence.\n---\nShared ATP evidence.",
    )
    _write(
        vault,
        "private/secret.md",
        "---\ntitle: Secret ATP\ndescription: Protected evidence.\n---\nShared ATP evidence secret.",
    )

    pack = build_context_pack(vault_root=vault, question="ATP evidence", limit=8)

    assert [source.path for source in pack.sources] == ["wiki/public.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"
    assert "Protected scopes were excluded from candidate selection by retrieval policy." in pack.omissions


def test_local_protected_scope_uses_canonical_lexical_fallback(tmp_path: Path) -> None:
    vault, runtime, provider = _indexed_vault(tmp_path)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="secret ATP",
        retrieval_scope=RetrievalScope(allow_protected=True),
        embedding_provider=provider,
    )

    secret = next(source for source in pack.sources if source.path == "private/secret.md")
    assert secret.retrieval_mode == "lexical-fallback"
    assert any("explicit protected scope" in omission for omission in pack.omissions)


def test_context_pack_falls_back_when_retrieval_index_is_stale(tmp_path: Path) -> None:
    vault, runtime, _provider = _indexed_vault(tmp_path)
    _write(
        vault,
        "wiki/cell.md",
        "---\nid: cell\ntitle: Cell\ndescription: Updated organelle note.\n---\n"
        "Cells contain ATP-related energy-transforming organelles and new canonical evidence.",
    )

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP",
    )

    assert pack.sources
    assert all(source.retrieval_mode == "lexical-fallback" for source in pack.sources)
    assert any("index was stale" in omission for omission in pack.omissions)


def test_vault_context_facade_uses_default_retrieval_runtime(tmp_path: Path) -> None:
    vault, _runtime, _provider = _indexed_vault(tmp_path)

    pack = get_vault_context(
        vault_root=vault,
        request=VaultContextRequest(question="ATP", limit=3),
    )

    assert pack.sources
    assert any(source.retrieval_mode == "hybrid" for source in pack.sources)
    assert any("Semantic retrieval was not configured" in omission for omission in pack.omissions)


def test_context_pack_hybrid_retrieval_respects_protected_scope(tmp_path: Path) -> None:
    vault, runtime, provider = _indexed_vault(tmp_path)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="cellular power production secret ATP",
        limit=8,
        retrieval_scope=RetrievalScope(allow_protected=False),
        embedding_provider=provider,
    )

    assert "private/secret.md" not in {source.path for source in pack.sources}
    assert "Protected scopes were excluded from candidate selection by retrieval policy." in pack.omissions


def test_external_protected_scope_uses_policy_allowlisted_lexical_fallback(
    tmp_path: Path,
) -> None:
    vault, runtime, provider = _indexed_vault(tmp_path)
    _write(
        vault,
        "system/retrieval-policy.yml",
        "schema_version: 1\nexternal_allowed_prefixes: [private]\n",
    )

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="secret ATP",
        retrieval_scope=RetrievalScope(allow_protected=True),
        retrieval_mode="external",
        embedding_provider=provider,
    )

    secret = next(source for source in pack.sources if source.path == "private/secret.md")
    assert secret.retrieval_mode == "lexical-fallback"
    assert any("explicit protected scope" in omission for omission in pack.omissions)


def test_caller_path_filter_falls_back_before_any_reranker_disclosure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/allowed.md", "---\ntitle: Allowed\n---\nATP evidence allowed.")
    _write(vault, "wiki/blocked.md", "---\ntitle: Blocked\n---\nATP evidence blocked.")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()
    reranker = _RecordingReranker()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP evidence",
        path_filter=lambda path: path != "wiki/blocked.md",
        reranker=reranker,
    )

    assert reranker.calls == []
    assert {source.path for source in pack.sources} == {"wiki/allowed.md"}
    assert any("caller-scoped path filtering" in omission for omission in pack.omissions)


def test_instruction_loading_is_not_narrowed_by_candidate_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/selected.md", "---\ntitle: Selected\n---\nATP selected evidence.")
    _write(
        vault,
        "system/instructions.yml",
        "schema_version: 1\ninstructions:\n"
        "  - id: global-rule\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 10\n"
        "    text: Keep global guidance.\n",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP",
        retrieval_scope=RetrievalScope(paths=("wiki/selected.md",)),
    )

    assert [item.id for item in pack.instructions] == ["global-rule"]
    assert [source.path for source in pack.sources] == ["wiki/selected.md"]


def test_focus_paths_exhausting_limit_skip_provider_work(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "study/focus.md", "---\ntitle: Focus\n---\nExplicit source.")

    pack = build_context_pack(
        vault_root=vault,
        question="unrelated query",
        focus_paths=("study/focus.md",),
        limit=1,
        embedding_provider=_ExplodingEmbeddingProvider(),
    )

    assert [source.path for source in pack.sources] == ["study/focus.md"]


def test_hybrid_selected_parse_findings_are_omitted_not_fatal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/warning.md",
        "---\ntitle: Warning\ndescription: [not, a, string]\n---\nATP warning evidence.",
    )
    _write(vault, "wiki/clean.md", "---\ntitle: Clean\n---\nATP clean evidence.")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(vault_root=vault, runtime_dir=runtime, question="ATP", limit=3)

    assert "wiki/warning.md" not in {source.path for source in pack.sources}
    assert "wiki/clean.md" in {source.path for source in pack.sources}
    assert any(item.source_path == "wiki/warning.md" for item in pack.diagnostics)


def test_reranker_degradation_is_reported_without_failing_context(tmp_path: Path) -> None:
    vault, runtime, _provider = _indexed_vault(tmp_path)
    reranker = _RecordingReranker(fail_code="timeout")

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP",
        reranker=reranker,
    )

    assert pack.sources
    assert reranker.calls
    assert any("Reranking was timeout" in omission for omission in pack.omissions)


def test_hybrid_excerpt_keeps_visible_matching_evidence(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    body = ("unrelated filler " * 40) + "needleterm visible evidence " + ("tail filler " * 40)
    _write(vault, "wiki/long.md", f"---\ntitle: Long\n---\n{body}")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="needleterm",
        limit=2,
    )

    source = next(item for item in pack.sources if item.path == "wiki/long.md")
    assert "needleterm" in source.excerpt
