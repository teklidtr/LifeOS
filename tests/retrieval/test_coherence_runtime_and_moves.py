from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.retrieval.service as retrieval_service
import lifeos.retrieval.coherence_service as legacy_service
import lifeos.retrieval.search as retrieval_search
from lifeos.retrieval import (
    HybridRetriever,
    RetrievalIndex,
    RetrievalIndexService,
    RetrievalRequest,
)


def _note(stable_id: str, title: str, body: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\n{body}\n"


def _legacy_note(title: str, body: str) -> str:
    return f"---\ntype: concept\ntitle: {title}\n---\n{body}\n"


def test_public_imports_construct_one_identity_aware_index_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert RetrievalIndexService is retrieval_service.RetrievalIndexService
    assert legacy_service.RetrievalIndexService is RetrievalIndexService
    assert retrieval_search.RetrievalIndexService is RetrievalIndexService
    assert RetrievalIndexService.__module__ == "lifeos.retrieval.service"

    constructed: list[RetrievalIndexService] = []
    original_init = RetrievalIndexService.__init__

    def recording_init(self, **kwargs):
        constructed.append(self)
        original_init(self, **kwargs)

    monkeypatch.setattr(RetrievalIndexService, "__init__", recording_init)
    vault = tmp_path / "vault"
    vault.mkdir()
    retriever = HybridRetriever(vault_root=vault, runtime_dir=vault / ".lifeos")
    assert constructed == [retriever.index_service]
    assert type(retriever.index_service) is RetrievalIndexService


@pytest.mark.parametrize(
    "service_type",
    [
        RetrievalIndexService,
        retrieval_service.RetrievalIndexService,
        legacy_service.RetrievalIndexService,
    ],
    ids=["package", "service", "legacy"],
)
def test_incremental_retrieval_reconciles_three_note_cycle(
    tmp_path: Path, service_type: type[RetrievalIndexService]
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    paths = [wiki / f"{name}.md" for name in ("a", "b", "c")]
    contents = [_note(f"note-{name}", name, f"{name} cycle evidence") for name in ("a", "b", "c")]
    for path, content in zip(paths, contents, strict=True):
        path.write_text(content, encoding="utf-8")
    service = service_type(vault_root=vault, runtime_dir=vault / ".lifeos")
    service.rebuild()
    with RetrievalIndex(service.active_path, create=False) as index:
        prior_chunk_ids = {chunk.document_id: chunk.chunk_id for chunk in index.chunks()}

    for path, content in zip(paths, [contents[2], contents[0], contents[1]], strict=True):
        path.write_text(content, encoding="utf-8")
    result = service.incremental_sync()

    assert result.status == "complete"
    assert set(result.renamed) == {
        ("wiki/a.md", "wiki/b.md"),
        ("wiki/b.md", "wiki/c.md"),
        ("wiki/c.md", "wiki/a.md"),
    }
    assert result.created == result.deleted == result.skipped == ()
    assert result.index_path == str(service.active_path)
    with RetrievalIndex(service.active_path, create=False) as index:
        assert {document.path: document.document_id for document in index.documents()} == {
            "wiki/a.md": "id:note-c",
            "wiki/b.md": "id:note-a",
            "wiki/c.md": "id:note-b",
        }
        assert {chunk.document_id: chunk.chunk_id for chunk in index.chunks()} == prior_chunk_ids
    assert service.health().state == "healthy"
    assert not (service.root / "index.sqlite3.relocation-sync").exists()


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

    real_read = retrieval_service.read_vault_markdown
    reads: list[str] = []

    def recording_read(root: Path, relative_path: str):
        reads.append(relative_path)
        assert not relative_path.startswith("runtime/node-a/")
        return real_read(root, relative_path)

    monkeypatch.setattr(retrieval_service, "read_vault_markdown", recording_read)
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


def test_incremental_retrieval_parks_legacy_occupant_of_stable_id_destination(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    path_a = wiki / "a.md"
    path_b = wiki / "b.md"
    stable_content = _note("note-a", "A", "The stable-destination-marker belongs to A.")
    legacy_content = _legacy_note("Legacy", "The legacy-destination-marker has no durable id.")
    path_a.write_text(stable_content, encoding="utf-8")
    path_b.write_text(legacy_content, encoding="utf-8")

    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    path_a.write_text(legacy_content, encoding="utf-8")
    path_b.write_text(stable_content, encoding="utf-8")
    result = service.incremental_sync()

    assert result.status == "complete"
    assert ("wiki/a.md", "wiki/b.md") in result.renamed
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
        assert not any(
            item.path.startswith(".lifeos/retrieval-relocations/")
            for item in (*index.documents(), *index.chunks())
        )
    assert documents["wiki/b.md"] == "id:note-a"
    assert documents["wiki/a.md"].startswith("path:")

    stable = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("stable-destination-marker")
    )
    legacy = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("legacy-destination-marker")
    )
    assert stable.results[0].path == "wiki/b.md"
    assert stable.results[0].stable_id == "note-a"
    assert legacy.results[0].path == "wiki/a.md"
    assert legacy.results[0].stable_id is None
