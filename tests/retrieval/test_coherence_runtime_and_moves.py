from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.retrieval.coherence_service as coherence_service
from lifeos.retrieval import HybridRetriever, RetrievalIndex, RetrievalIndexService, RetrievalRequest


def _note(stable_id: str, title: str, body: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\n{body}\n"


def test_custom_in_vault_runtime_is_filtered_before_retrieval_content_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    canonical = wiki / "note.md"
    canonical.write_text(
        _note("same-id", "Canonical", "The canonical amber-marker is searchable."),
        encoding="utf-8",
    )
    runtime = vault / "runtime" / "node-a"
    derived = runtime / "exports" / "public-wiki" / "generation" / "wiki" / "note.md"
    derived.parent.mkdir(parents=True)
    derived.write_text(
        _note("same-id", "Derived", "The disposable derived-only-marker must be ignored."),
        encoding="utf-8",
    )

    real_read = coherence_service.read_vault_markdown
    reads: list[str] = []

    def recording_read(root: Path, relative_path: str):
        reads.append(relative_path)
        assert not relative_path.startswith("runtime/node-a/")
        return real_read(root, relative_path)

    monkeypatch.setattr(coherence_service, "read_vault_markdown", recording_read)
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    result = service.rebuild()

    assert result.status == "complete"
    assert reads == ["wiki/note.md"]
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
    assert documents == {"wiki/note.md": "id:same-id"}

    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("amber-marker")
    )
    assert response.results[0].path == "wiki/note.md"
    assert response.results[0].stable_id == "same-id"


def test_incremental_retrieval_reconciles_stable_id_path_swap_as_a_set(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    path_a = wiki / "a.md"
    path_b = wiki / "b.md"
    content_a = _note("note-a", "A", "The alpha-swap-marker belongs to A.")
    content_b = _note("note-b", "B", "The beta-swap-marker belongs to B.")
    path_a.write_text(content_a, encoding="utf-8")
    path_b.write_text(content_b, encoding="utf-8")

    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    path_a.write_text(content_b, encoding="utf-8")
    path_b.write_text(content_a, encoding="utf-8")
    result = service.incremental_sync()

    assert result.status == "complete"
    assert set(result.renamed) == {
        ("wiki/a.md", "wiki/b.md"),
        ("wiki/b.md", "wiki/a.md"),
    }
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
    assert documents == {
        "wiki/a.md": "id:note-b",
        "wiki/b.md": "id:note-a",
    }

    alpha = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("alpha-swap-marker")
    )
    beta = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("beta-swap-marker")
    )
    assert alpha.results[0].path == "wiki/b.md"
    assert alpha.results[0].stable_id == "note-a"
    assert beta.results[0].path == "wiki/a.md"
    assert beta.results[0].stable_id == "note-b"
