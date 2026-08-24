from pathlib import Path

from lifeos.retrieval import HybridRetriever, RetrievalIndexService, RetrievalRequest


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
