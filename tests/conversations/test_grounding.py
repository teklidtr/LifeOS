from datetime import datetime, timezone
from pathlib import Path

from lifeos.conversations import KnowledgeConversationService
from lifeos.retrieval import (
    DeterministicAnswerProvider,
    FailingAnswerProvider,
    GeneratedAnswer,
    GeneratedParagraph,
)

NOW = datetime(2026, 7, 16, 10, tzinfo=timezone.utc)


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def setup(tmp_path: Path) -> tuple[Path, KnowledgeConversationService, str, str]:
    vault = tmp_path / "vault"
    vault.mkdir()
    write(
        vault,
        "wiki/source.md",
        "---\nid: source\ntype: concept\n---\n# Evidence\n\nMitochondria produce ATP.",
    )
    service = KnowledgeConversationService(vault_root=vault, runtime_dir=vault / ".lifeos")
    service.retriever.index_service.rebuild()
    artifact = service.create(title="Grounding", now=NOW)
    return vault, service, artifact.relative_path, artifact.content_hash


def test_evidence_only_no_provider_and_no_answer_states(tmp_path: Path) -> None:
    _, service, path, digest = setup(tmp_path)
    evidence_only = service.ask(
        path, query="ATP", expected_hash=digest, evidence_only=True, now=NOW
    )
    assert evidence_only.turns[-1].state == "evidence-only"
    assert evidence_only.turns[-1].answer[0].citations
    unavailable = service.ask(path, query="ATP", expected_hash=evidence_only.content_hash, now=NOW)
    assert unavailable.turns[-1].state == "unavailable-provider"
    no_results = service.ask(
        path, query="xyzzynotfound", expected_hash=unavailable.content_hash, now=NOW
    )
    assert no_results.turns[-1].state == "no-results"
    assert "does not contain enough evidence" in no_results.turns[-1].explanation


def test_valid_claim_citations_are_saved_and_nonexistent_citations_rejected(tmp_path: Path) -> None:
    _, service, path, digest = setup(tmp_path)
    preview = service.retriever.search(
        __import__("lifeos.retrieval", fromlist=["RetrievalRequest"]).RetrievalRequest("ATP")
    )
    evidence_id = preview.results[0].evidence_id
    good = DeterministicAnswerProvider(
        GeneratedAnswer(
            (GeneratedParagraph("ATP is produced.", (evidence_id,), "direct"),), "Validated."
        )
    )
    saved = service.ask(path, query="ATP", expected_hash=digest, answer_provider=good, now=NOW)
    assert saved.turns[-1].state == "ready"
    bad = DeterministicAnswerProvider(
        GeneratedAnswer(
            (GeneratedParagraph("Invented.", ("chunk:missing",), "direct"),), "Invalid."
        )
    )
    rejected = service.ask(
        path, query="ATP", expected_hash=saved.content_hash, answer_provider=bad, now=NOW
    )
    assert rejected.turns[-1].state == "malformed-response"
    assert rejected.turns[-1].answer == ()


def test_timeout_and_stale_source_detection(tmp_path: Path) -> None:
    vault, service, path, digest = setup(tmp_path)
    timeout = service.ask(
        path,
        query="ATP",
        expected_hash=digest,
        answer_provider=FailingAnswerProvider("timeout"),
        now=NOW,
    )
    assert timeout.turns[-1].state == "timeout"
    service.ask(path, query="ATP", expected_hash=timeout.content_hash, evidence_only=True, now=NOW)
    write(
        vault,
        "wiki/source.md",
        "---\nid: source\ntype: concept\n---\n# Changed\n\nMitochondria produce energy.",
    )
    checked = service.stale_status(path)
    assert checked[-1].evidence[0].stale
    assert "stale-evidence" in checked[-1].diagnostics
