from pathlib import Path

from lifeos.retrieval import (
    CancellationToken,
    DeterministicEmbeddingProvider,
    RetrievalIndex,
    RetrievalIndexService,
    RetrievalPolicy,
)


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_full_rebuild_health_embedding_and_discard(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/a.md", "---\nid: a\ntype: concept\n---\n# A\n\nAlpha.")
    write(vault, "journal/private/secret.md", "# Secret\n\nNever index me.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    assert service.health().state == "missing"
    result = service.rebuild(batch_size=1)
    assert result.status == "complete" and result.created == ("wiki/a.md",)
    assert service.health().state == "healthy"
    provider = DeterministicEmbeddingProvider(dimensions=4)
    service.embed_missing(provider)
    health = service.health(embedding_provider=provider)
    assert health.state == "healthy" and health.embeddings == 1
    removed = service.discard()
    assert "retrieval/index.sqlite3" in removed
    assert service.health().state == "missing"


def test_interrupted_rebuild_resumes_without_publishing_partial_index(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    for index in range(4):
        write(vault, f"wiki/{index}.md", f"# {index}\n\nText {index}.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    partial = service.rebuild(batch_size=1, stop_after=2)
    assert partial.status == "interrupted"
    assert not service.active_path.exists() and service.staging_path.exists()
    resumed = service.rebuild(batch_size=1, resume=True)
    assert resumed.status == "complete"
    assert service.health().documents == 4
    assert not service.staging_path.exists()


def test_incremental_create_edit_delete_and_legacy_move(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/a.md", "# A\n\nAlpha.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    (vault / "wiki/a.md").rename(vault / "wiki/renamed.md")
    moved = service.incremental_sync()
    assert moved.renamed == ()
    assert moved.deleted == ("wiki/a.md",)
    assert moved.created == ("wiki/renamed.md",)
    write(vault, "wiki/renamed.md", "# A\n\nChanged.")
    write(vault, "wiki/new.md", "# New\n\nNew note.")
    changed = service.incremental_sync()
    assert changed.created == ("wiki/new.md",) and changed.updated == ("wiki/renamed.md",)
    (vault / "wiki/new.md").unlink()
    deleted = service.incremental_sync()
    assert deleted.deleted == ("wiki/new.md",)
    assert service.health().state == "healthy"


def test_durable_id_preserves_move_identity_even_when_content_changes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/a.md", "---\nid: stable-a\n---\n# A\n\nAlpha.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    old = RetrievalIndex(service.active_path, create=False)
    old_id = old.documents()[0].document_id
    old.close()
    (vault / "wiki/a.md").unlink()
    write(vault, "notes/moved.md", "---\nid: stable-a\n---\n# A\n\nChanged while moving.")
    result = service.incremental_sync()
    assert result.renamed == (("wiki/a.md", "notes/moved.md"),)
    current = RetrievalIndex(service.active_path, create=False)
    assert current.documents()[0].document_id == old_id
    current.close()


def test_malformed_note_is_reported_and_does_not_poison_rebuild(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/good.md", "# Good\n\nText.")
    write(vault, "wiki/bad.md", "---\ntitle: [\n---\nText")
    result = RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()
    assert result.skipped == ("wiki/bad.md",)
    assert any("malformed_note" in item for item in result.diagnostics)


def test_incremental_cancellation_is_recorded_and_safe_to_retry(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/a.md", "# A\n\nAlpha.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    write(vault, "wiki/b.md", "# B\n\nBeta.")
    token = CancellationToken()
    token.cancel()
    interrupted = service.incremental_sync(cancellation=token)
    assert interrupted.status == "interrupted"
    complete = service.incremental_sync()
    assert complete.created == ("wiki/b.md",)


def test_policy_exclusions_are_applied_before_indexing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/public.md", "# Public")
    write(vault, "wiki/blocked.md", "# Blocked")
    policy = RetrievalPolicy(excluded_prefixes=("wiki/blocked.md",), protected_prefixes=())
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime, policy=policy)
    service.rebuild()
    index = RetrievalIndex(service.active_path, create=False)
    assert [item.path for item in index.documents()] == ["wiki/public.md"]
    index.close()
