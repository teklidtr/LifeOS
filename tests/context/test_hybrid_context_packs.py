from __future__ import annotations

from pathlib import Path

from lifeos.context import build_context_pack
from lifeos.retrieval import (
    DeterministicEmbeddingProvider,
    RetrievalIndexService,
    RetrievalScope,
)


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


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
