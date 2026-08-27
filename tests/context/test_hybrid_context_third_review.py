from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.context import ContextSearchError, build_context_pack
from lifeos.retrieval import RetrievalIndexService, RetrievalScope


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_hybrid_retries_do_not_reintroduce_duplicate_sources(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    body = "ATP duplicate evidence with identical canonical wording."
    _write(vault, "wiki/alpha.md", f"---\ntitle: Alpha\n---\n{body}")
    _write(vault, "wiki/beta.md", f"---\ntitle: Beta\n---\n{body}")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP duplicate evidence",
        limit=2,
    )

    assert len(pack.sources) == 1
    assert pack.sources[0].path in {"wiki/alpha.md", "wiki/beta.md"}
    assert set(pack.sources[0].duplicate_paths) == {
        "wiki/alpha.md",
        "wiki/beta.md",
    } - {pack.sources[0].path}


@pytest.mark.parametrize(
    "scope",
    [
        RetrievalScope(paths=("wiki/topic/note.md",)),
        RetrievalScope(folders=("wiki/topic",)),
    ],
)
def test_scoped_lexical_fallback_keeps_ancestors_traversable(
    tmp_path: Path,
    scope: RetrievalScope,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "wiki/topic/note.md",
        "---\ntitle: Scoped note\n---\nATP nested scoped evidence.",
    )
    _write(
        vault,
        "wiki/other.md",
        "---\ntitle: Other\n---\nATP nested scoped evidence.",
    )

    pack = build_context_pack(
        vault_root=vault,
        question="ATP nested scoped evidence",
        retrieval_scope=scope,
    )

    assert [source.path for source in pack.sources] == ["wiki/topic/note.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"


@pytest.mark.parametrize("question", ["", "   ", "!!!"])
def test_focus_only_context_still_validates_question(
    tmp_path: Path,
    question: str,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "study/focus.md", "---\ntitle: Focus\n---\nExplicit context.")

    with pytest.raises(ContextSearchError):
        build_context_pack(
            vault_root=vault,
            question=question,
            focus_paths=("study/focus.md",),
            limit=1,
        )
