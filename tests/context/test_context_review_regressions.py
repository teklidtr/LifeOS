from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lifeos.context import build_context_pack
from lifeos.retrieval import RetrievalIndexService, RetrievalScope, UnavailableEmbeddingProvider
from lifeos.retrieval.contracts import (
    CancellationToken,
    ProviderCapabilities,
    ProviderError,
    RerankCandidate,
    RerankResult,
)


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _rebuild(vault: Path, runtime: Path) -> None:
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()


class _FailingReranker:
    def __init__(self, *, explode: bool = False) -> None:
        self.called = False
        self.explode = explode
        self._capabilities = ProviderCapabilities(
            "reranker",
            "review-fixture",
            "failure-v1",
            True,
            256,
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
        del query, candidates, timeout_seconds
        cancellation.checkpoint()
        self.called = True
        if self.explode:
            raise AssertionError("reranker must not be called")
        raise ProviderError("timeout", "fixture reranker timed out")


def test_local_explicit_protected_scope_uses_policy_filtered_lexical_fallback(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/public.md",
        "---\ntitle: Public\n---\nOrdinary evidence.\n",
    )
    _write(
        vault,
        "private/secret.md",
        "---\ntitle: Secret\n---\nProtected cobaltneedle evidence.\n",
    )
    _rebuild(vault, runtime)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="cobaltneedle",
        retrieval_scope=RetrievalScope(allow_protected=True),
    )

    assert [source.path for source in pack.sources] == ["private/secret.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"
    assert any("explicit protected scope" in item for item in pack.omissions)


def test_healthy_hybrid_preserves_description_only_lexical_routing_sources(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/route.md",
        "---\ntitle: Route\ndescription: amberbeacon routing clue\n---\n"
        "Body deliberately contains unrelated words.\n",
    )
    _rebuild(vault, runtime)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="amberbeacon",
    )

    assert [source.path for source in pack.sources] == ["wiki/route.md"]
    assert pack.sources[0].retrieval_mode == "lexical"
    assert "hybrid-augmentation" in pack.sources[0].retrieval_reasons


def test_note_budget_is_filled_after_chunk_level_hybrid_results_are_deduplicated(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    sections = "\n".join(
        f"## Section {index}\nneedle evidence segment {index} with unique detail {index}."
        for index in range(30)
    )
    _write(vault, "wiki/a-long.md", f"---\ntitle: Long\n---\n{sections}\n")
    _write(
        vault,
        "wiki/z-other.md",
        "---\ntitle: Other\n---\nneedle evidence from the second note.\n",
    )
    _rebuild(vault, runtime)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="needle",
        limit=2,
    )

    assert {source.path for source in pack.sources} == {
        "wiki/a-long.md",
        "wiki/z-other.md",
    }


def test_caller_path_filter_forces_pre_traversal_lexical_fallback_without_reranker(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/allowed.md", "---\ntitle: Allowed\n---\nneedle allowed evidence.\n")
    _write(vault, "wiki/blocked.md", "---\ntitle: Blocked\n---\nneedle blocked evidence.\n")
    _rebuild(vault, runtime)
    reranker = _FailingReranker(explode=True)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="needle",
        path_filter=lambda path: path == "wiki/allowed.md",
        reranker=reranker,
    )

    assert reranker.called is False
    assert [source.path for source in pack.sources] == ["wiki/allowed.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"
    assert any("caller-scoped path filtering" in item for item in pack.omissions)


def test_instruction_discovery_is_not_narrowed_by_candidate_folder_scope(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/topic/note.md", "---\ntitle: Topic\n---\nscopeword evidence.\n")
    _write(
        vault,
        "system/instructions.yml",
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: global-guidance\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 10\n"
        "    text: Keep global guidance visible.\n",
    )
    _rebuild(vault, runtime)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="scopeword",
        retrieval_scope=RetrievalScope(folders=("wiki/topic",)),
    )

    assert [source.path for source in pack.sources] == ["wiki/topic/note.md"]
    assert [instruction.id for instruction in pack.instructions] == ["global-guidance"]


def test_focus_paths_exhausting_limit_skip_candidate_retrieval(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "study/focus.md", "---\ntitle: Focus\n---\nExplicit focus evidence.\n")

    pack = build_context_pack(
        vault_root=vault,
        question="unrelated query",
        focus_paths=("study/focus.md",),
        limit=1,
        embedding_provider=UnavailableEmbeddingProvider(),
    )

    assert [source.path for source in pack.sources] == ["study/focus.md"]
    assert pack.sources[0].retrieval_mode == "focus"
    assert not any("Hybrid retrieval" in item for item in pack.omissions)
    assert not any("Semantic retrieval" in item for item in pack.omissions)


def test_hybrid_parse_warning_is_omitted_with_diagnostic_instead_of_aborting(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/a-warning.md",
        "---\ntitle: Warning\ndescription: [not, a, string]\n---\nwarningneedle evidence.\n",
    )
    _write(
        vault,
        "wiki/z-good.md",
        "---\ntitle: Good\n---\nwarningneedle evidence from a valid note.\n",
    )
    _rebuild(vault, runtime)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="warningneedle",
        limit=2,
    )

    assert "wiki/a-warning.md" not in {source.path for source in pack.sources}
    assert "wiki/z-good.md" in {source.path for source in pack.sources}
    assert any(item.code == "frontmatter-invalid-type" for item in pack.diagnostics)


def test_reranker_failure_is_reported_as_bounded_degradation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/note.md", "---\ntitle: Note\n---\nneedle evidence.\n")
    _rebuild(vault, runtime)
    reranker = _FailingReranker()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="needle",
        reranker=reranker,
    )

    assert reranker.called is True
    assert pack.sources[0].retrieval_mode == "hybrid"
    assert any("Reranking was timeout" in item for item in pack.omissions)


def test_hybrid_excerpt_keeps_late_matching_evidence_visible(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    prefix = " ".join(f"preface{index}" for index in range(100))
    _write(
        vault,
        "wiki/late.md",
        f"---\ntitle: Late\n---\n{prefix} needle visible evidence after the long preface.\n",
    )
    _rebuild(vault, runtime)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="needle",
    )

    assert pack.sources[0].retrieval_mode == "hybrid"
    assert "needle" in pack.sources[0].excerpt.casefold()
