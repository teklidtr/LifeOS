from pathlib import Path

import pytest

import lifeos.retrieval.coherence_search as coherence_search
from lifeos.retrieval import HybridRetriever, RetrievalIndex, RetrievalIndexService, RetrievalRequest


def test_retrieval_exposes_stable_id_beside_current_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "current-location.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\nid: durable-concept\ntype: concept\ntitle: Durable Concept\n---\n"
        "# Identity\n\nRelocation safe evidence lives here.\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("relocation safe evidence")
    )

    assert response.results[0].path == "wiki/current-location.md"
    assert response.results[0].stable_id == "durable-concept"
    serialized = response.to_dict()["results"][0]
    assert serialized["path"] == "wiki/current-location.md"
    assert serialized["stable_id"] == "durable-concept"


def test_retrieval_reports_none_for_legacy_path_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "journal" / "legacy.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Legacy\n\nPath-only evidence remains searchable.\n", encoding="utf-8")
    runtime = vault / ".lifeos"
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("path-only evidence")
    )

    assert response.results[0].path == "journal/legacy.md"
    assert response.results[0].stable_id is None


def test_retrieval_does_not_expose_ambiguous_stable_id_hidden_by_index_key(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text(
        "---\nid: duplicate-id\ntype: concept\ntitle: First\n---\nFirst duplicate body.\n",
        encoding="utf-8",
    )
    (wiki / "b.md").write_text(
        "---\nid: duplicate-id\ntype: concept\ntitle: Second\n---\n"
        "Surviving duplicate carries the saffron-marker phrase.\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("saffron-marker")
    )

    assert response.results
    assert response.results[0].path == "wiki/b.md"
    assert response.results[0].stable_id is None
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {document.path: document.document_id for document in index.documents()}
    assert set(documents) == {"wiki/a.md", "wiki/b.md"}
    assert all(document_id.startswith("path:") for document_id in documents.values())


def test_incremental_index_reconciles_duplicate_identity_without_content_edit(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    first = wiki / "a.md"
    second = wiki / "b.md"
    first.write_text(
        "---\nid: shared-id\ntype: concept\ntitle: First\n---\nAlpha body.\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    second.write_text(
        "---\nid: shared-id\ntype: concept\ntitle: Second\n---\nBeta body.\n",
        encoding="utf-8",
    )
    service.incremental_sync()
    with RetrievalIndex(service.active_path, create=False) as index:
        duplicate_documents = {
            document.path: document.document_id for document in index.documents()
        }
    assert set(duplicate_documents) == {"wiki/a.md", "wiki/b.md"}
    assert all(value.startswith("path:") for value in duplicate_documents.values())

    second.unlink()
    service.incremental_sync()
    with RetrievalIndex(service.active_path, create=False) as index:
        resolved_documents = {document.path: document.document_id for document in index.documents()}
    assert resolved_documents == {"wiki/a.md": "id:shared-id"}


def test_retrieval_suppresses_stable_id_when_uniqueness_proof_is_stale(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    first = wiki / "a.md"
    first.write_text(
        "---\nid: shared-id\ntype: concept\ntitle: First\n---\n"
        "The vermilion-marker phrase belongs to the indexed note.\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    # Introduce a duplicate after the last synchronization. Text retrieval may continue from the
    # stale index, but build-time uniqueness is no longer proof of current stable identity.
    (wiki / "b.md").write_text(
        "---\nid: shared-id\ntype: concept\ntitle: Second\n---\nOther body.\n",
        encoding="utf-8",
    )
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("vermilion-marker")
    )

    assert response.index_state == "stale"
    assert response.results
    assert response.results[0].path == "wiki/a.md"
    assert response.results[0].stable_id is None


def test_retrieval_normalizes_durable_id_during_rebuild_and_incremental_sync(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "spaced-id.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\nid: " durable-id "\ntype: concept\ntitle: Spaced ID\n---\n'
        "The indigo-marker phrase is indexed here.\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {document.path: document.document_id for document in index.documents()}
    assert documents == {"wiki/spaced-id.md": "id:durable-id"}
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("indigo-marker")
    )
    assert response.results[0].stable_id == "durable-id"

    note.write_text(
        '---\nid: " durable-id "\ntype: concept\ntitle: Spaced ID\n---\n'
        "The indigo-marker phrase changed after rebuild.\n",
        encoding="utf-8",
    )
    service.incremental_sync()
    with RetrievalIndex(service.active_path, create=False) as index:
        refreshed = {document.path: document.document_id for document in index.documents()}
    assert refreshed == {"wiki/spaced-id.md": "id:durable-id"}


def test_retrieval_identity_verification_reads_only_returned_stable_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    target = wiki / "target.md"
    target.write_text(
        "---\nid: target-id\ntype: concept\ntitle: Target\n---\n"
        "The ultraviolet-marker phrase is unique.\n",
        encoding="utf-8",
    )
    for index in range(40):
        (wiki / f"legacy-{index}.md").write_text(
            f"# Legacy {index}\n\nUnrelated ordinary text {index}.\n",
            encoding="utf-8",
        )
    runtime = vault / ".lifeos"
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()
    real_read = coherence_search.read_vault_markdown
    reads: list[str] = []

    def recording_read(root: Path, relative_path: str):
        reads.append(relative_path)
        return real_read(root, relative_path)

    monkeypatch.setattr(coherence_search, "read_vault_markdown", recording_read)
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("ultraviolet-marker")
    )

    assert response.results[0].stable_id == "target-id"
    assert reads == ["wiki/target.md"]


def test_retrieval_does_not_attach_old_index_identity_to_changed_canonical_path(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\nid: old-id\ntype: concept\ntitle: Old\n---\n"
        "The cobalt-marker phrase is indexed here.\n",
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    note.write_text(
        "---\nid: new-id\ntype: concept\ntitle: New\n---\nCanonical content changed after indexing.\n",
        encoding="utf-8",
    )
    response = HybridRetriever(vault_root=vault, runtime_dir=runtime).search(
        RetrievalRequest("cobalt-marker")
    )

    assert response.results == ()
