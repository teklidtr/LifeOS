from __future__ import annotations

from pathlib import Path

from lifeos.retrieval import RetrievalIndex, RetrievalIndexService


def test_legacy_equal_content_move_is_reported_as_delete_and_create(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    old_path = wiki / "legacy-a.md"
    new_path = wiki / "legacy-b.md"
    content = "---\ntype: concept\ntitle: Legacy\n---\nIdentical legacy bytes.\n"
    old_path.write_text(content, encoding="utf-8")

    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    rebuild = service.rebuild()
    assert rebuild.status == "complete"

    old_path.rename(new_path)
    result = service.incremental_sync()

    assert result.status == "complete"
    assert result.renamed == ()
    assert result.deleted == ("wiki/legacy-a.md",)
    assert result.created == ("wiki/legacy-b.md",)
    assert "wiki/legacy-b.md" not in result.updated

    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
    assert set(documents) == {"wiki/legacy-b.md"}
    assert documents["wiki/legacy-b.md"].startswith("path:")
