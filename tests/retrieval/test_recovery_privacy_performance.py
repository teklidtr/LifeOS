import sqlite3
from pathlib import Path

from lifeos.conversations import KnowledgeConversationService
from lifeos.retrieval import (
    CancellationToken,
    DeterministicAnswerProvider,
    DeterministicEmbeddingProvider,
    GeneratedAnswer,
    GeneratedParagraph,
    HybridRetriever,
    RetrievalIndexService,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalScope,
)


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_incompatible_and_corrupt_indexes_rebuild_without_touching_markdown(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/a.md", "# A\n\nCanonical text.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    canonical = (vault / "wiki/a.md").read_bytes()
    with sqlite3.connect(service.active_path) as connection:
        connection.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        connection.commit()
    plan = service.recovery_plan()
    assert plan.state == "incompatible" and plan.action == "discard-and-rebuild"
    assert not plan.canonical_markdown_affected
    assert service.recover().status == "complete"
    assert (vault / "wiki/a.md").read_bytes() == canonical
    service.active_path.write_bytes(b"not sqlite")
    assert service.recovery_plan().state == "corrupt"
    service.recover()
    assert service.health().state == "healthy"


def test_full_index_deletion_and_interrupted_rebuild_recovery_are_explicit(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    for index in range(8):
        write(vault, f"wiki/{index}.md", f"# Note {index}\n\nPassage {index}.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    service.discard()
    assert service.recovery_plan().action == "full-rebuild"
    assert service.recover().processed == 8
    service.discard()
    service.rebuild(stop_after=3, batch_size=1)
    plan = service.recovery_plan()
    assert plan.action == "resume-rebuild" and plan.resumable
    assert service.recover().processed == 8


def test_large_vault_result_and_context_budgets_remain_bounded_and_stable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    for index in range(250):
        write(
            vault,
            f"wiki/{index:03d}.md",
            f"# Topic {index}\n\nShared retrieval phrase with detail {index}." + " x" * 100,
        )
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild(batch_size=17)
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    request = RetrievalRequest("shared retrieval phrase", limit=7, context_budget=333)
    first = retriever.search(request)
    second = retriever.search(request)
    assert len(first.results) <= 7 and first.context_characters <= 333
    assert first.to_dict() == second.to_dict()


def test_embedding_batches_are_bounded_and_cancellation_preserves_active_index(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    for index in range(30):
        write(vault, f"wiki/{index}.md", f"# {index}\n\nText {index}.")
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    provider = DeterministicEmbeddingProvider(dimensions=8)
    result = service.embed_missing(provider, batch_size=5)
    assert result.processed == 30
    before = service.health().documents
    write(vault, "wiki/new.md", "# New\n\nPending change.")
    token = CancellationToken()
    token.cancel()
    interrupted = service.incremental_sync(cancellation=token)
    assert interrupted.status == "interrupted" and service.health().documents == before


def test_protected_content_is_default_denied_and_external_disclosure_is_exact(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    write(vault, "wiki/public.md", "# Public\n\nA public evidence sentence.")
    write(vault, "private/secret.md", "# Secret\n\nA private evidence sentence.")
    policy = RetrievalPolicy(protected_prefixes=("private",), external_allowed_prefixes=())
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime, policy=policy)
    service.rebuild()
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime, policy=policy)
    denied = retriever.search(
        RetrievalRequest(
            "private evidence",
            scope=RetrievalScope(paths=("private/secret.md",), allow_protected=True),
        )
    )
    assert denied.results == ()
    conversations = KnowledgeConversationService(
        vault_root=vault, runtime_dir=runtime, policy=policy
    )
    artifact = conversations.create(title="Privacy")
    preview = retriever.search(RetrievalRequest("public evidence"))
    evidence_id = preview.results[0].evidence_id
    external = DeterministicAnswerProvider(
        GeneratedAnswer(
            (GeneratedParagraph("Public claim.", (evidence_id,), "direct"),), "Grounded."
        ),
        local_only=False,
    )
    saved = conversations.ask(
        artifact.relative_path,
        query="public evidence",
        expected_hash=artifact.content_hash,
        answer_provider=external,
    )
    disclosure = saved.turns[-1].provider_disclosure
    assert disclosure["mode"] == "external"
    assert disclosure["items"][0]["path"] == "wiki/public.md"
    assert disclosure["total_characters"] == len(preview.results[0].context_text)
