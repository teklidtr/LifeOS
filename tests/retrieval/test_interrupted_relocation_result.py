from __future__ import annotations

from pathlib import Path

from lifeos.retrieval import RetrievalIndex, RetrievalIndexService
from lifeos.retrieval.contracts import CancellationToken


def _note(stable_id: str, title: str, body: str) -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\n{body}\n"


def test_interrupted_staged_relocation_reports_only_active_index_changes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    old_path = wiki / "a.md"
    new_path = wiki / "b.md"
    old_path.write_text(
        _note("note-a", "A", "The staged-cancel-marker belongs to A."),
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    old_path.rename(new_path)
    (wiki / "new.md").write_text("# New\n\nA pending extra operation.\n", encoding="utf-8")
    cancellation = CancellationToken()
    cancellation.cancel()

    result = service.incremental_sync(cancellation=cancellation)

    assert result.status == "interrupted"
    assert result.created == ()
    assert result.updated == ()
    assert result.renamed == ()
    assert result.deleted == ()
    assert result.index_path == str(service.active_path)
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
    assert documents == {"wiki/a.md": "id:note-a"}
    assert not (service.root / "index.sqlite3.relocation-sync").exists()
