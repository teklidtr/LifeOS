from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from lifeos.context import build_context_pack
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.read_only import VaultContextRequest, get_vault_context
from lifeos.retrieval import (
    CancellationToken,
    DeterministicEmbeddingProvider,
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


def _chunk_heavy_vault(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    paragraphs = [
        f"ATP evidence paragraph {index}. " + (f"unique-{index} ATP evidence detail. " * 45)
        for index in range(24)
    ]
    _write(vault, "wiki/long.md", "---\ntitle: Long\n---\n" + "\n\n".join(paragraphs))
    _write(
        vault,
        "wiki/short.md",
        "---\ntitle: Short\n---\nATP evidence in a distinct short note.",
    )
    return vault, runtime


class _RecordingReranker:
    def __init__(self, *, local_only: bool, fail_on_call: int | None = None) -> None:
        self.calls: list[int] = []
        self.fail_on_call = fail_on_call
        self._capabilities = ProviderCapabilities(
            kind="reranker",
            adapter_key="recording-review",
            model_key="recording-v1",
            local_only=local_only,
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
        self.calls.append(sum(len(item.text) for item in candidates))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise ProviderError("timeout", "deterministic second-pass failure")
        return tuple(RerankResult(item.evidence_id, item.base_score) for item in candidates)


def test_external_reranker_disclosure_budget_is_not_reopened_across_retries(
    tmp_path: Path,
) -> None:
    vault, runtime = _chunk_heavy_vault(tmp_path)
    _write(
        vault,
        "system/retrieval-policy.yml",
        "schema_version: 1\nmax_external_characters: 80000\n",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()
    reranker = _RecordingReranker(local_only=False)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP evidence",
        limit=2,
        reranker=reranker,
    )

    assert {source.path for source in pack.sources} == {"wiki/long.md", "wiki/short.md"}
    assert len(reranker.calls) == 1
    assert reranker.calls[0] <= 80_000
    assert any("limited to the first hybrid pass" in item for item in pack.omissions)


def test_metadata_scope_is_honored_by_lexical_fallback(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "wiki/allowed.md",
        "---\ntitle: Allowed\ntype: concept\ntags: [biology]\nsource: lecture\n"
        "date: 2026-02-10\n---\nATP scoped evidence.",
    )
    _write(
        vault,
        "wiki/outside.md",
        "---\ntitle: Outside\ntype: concept\ntags: [exercise]\nsource: lecture\n"
        "date: 2026-02-10\n---\nATP scoped evidence.",
    )

    pack = build_context_pack(
        vault_root=vault,
        question="ATP scoped evidence",
        retrieval_scope=RetrievalScope(
            note_types=("concept",),
            tags=("biology",),
            sources=("lecture",),
            date_from="2026-02-01",
            date_to="2026-02-28",
        ),
    )

    assert [source.path for source in pack.sources] == ["wiki/allowed.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"


def test_metadata_scope_blocks_lexical_augmentation_on_healthy_index(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/allowed.md",
        "---\ntitle: Allowed\ntype: concept\ntags: [biology]\n---\nATP hybrid evidence.",
    )
    _write(
        vault,
        "wiki/outside.md",
        "---\ntitle: Outside\ntype: journal\ntags: [exercise]\n"
        "description: ATP routing clue\n---\nUnrelated body words.",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP",
        retrieval_scope=RetrievalScope(note_types=("concept",), tags=("biology",)),
    )

    assert [source.path for source in pack.sources] == ["wiki/allowed.md"]


def test_later_retry_degradation_is_reported(tmp_path: Path) -> None:
    vault, runtime = _chunk_heavy_vault(tmp_path)
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()
    reranker = _RecordingReranker(local_only=True, fail_on_call=2)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP evidence",
        limit=2,
        reranker=reranker,
    )

    assert len(reranker.calls) >= 2
    assert any("Reranking was timeout" in item for item in pack.omissions)


def test_semantic_only_source_preserves_canonical_description(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    body = "Oxidative phosphorylation produces ATP."
    _write(
        vault,
        "wiki/energy.md",
        "---\ntitle: Energy\ndescription: Canonical routing description.\n---\n" + body,
    )
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    provider = DeterministicEmbeddingProvider(
        dimensions=4,
        phrase_vectors={
            "cellular power production": [1, 0, 0, 0],
            body: [1, 0, 0, 0],
        },
    )
    service.embed_missing(provider)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="cellular power production",
        embedding_provider=provider,
    )

    source = next(item for item in pack.sources if item.path == "wiki/energy.md")
    assert source.retrieval_mode == "hybrid"
    assert "semantic" in source.retrieval_reasons
    assert source.description == "Canonical routing description."
    assert "Matching sources do not provide routing descriptions." not in pack.evidence_gaps


def test_focus_note_remains_available_for_link_ranking(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "study/focus.md",
        "---\ntitle: Focus\n---\nPlanning context links to [[wiki/linked]].",
    )
    _write(
        vault,
        "wiki/linked.md",
        "---\ntitle: Linked\n---\nCompletely separate material with no query terms.",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="unrelated query tokens",
        focus_paths=("study/focus.md",),
        limit=2,
    )

    assert [source.path for source in pack.sources] == ["study/focus.md", "wiki/linked.md"]
    assert "link" in pack.sources[1].retrieval_reasons


def test_invalid_retrieval_policy_remains_execution_error(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/note.md", "---\ntitle: Note\n---\nATP evidence.")
    _write(
        vault,
        "system/retrieval-policy.yml",
        "schema_version: 1\nunknown_policy_field: true\n",
    )

    with pytest.raises(ToolExecutionError):
        get_vault_context(
            vault_root=vault,
            request=VaultContextRequest(question="ATP"),
        )
