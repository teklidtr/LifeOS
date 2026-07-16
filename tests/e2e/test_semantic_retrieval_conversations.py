from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from lifeos.bridge import BridgeApplication, ReferenceBridgeClient
from lifeos.conversations import (
    ConversationArtifactService,
    ConversationProposalRequest,
    ConversationProposalService,
    KnowledgeConversationService,
)
from lifeos.retrieval import (
    DeterministicAnswerProvider,
    DeterministicEmbeddingProvider,
    GeneratedAnswer,
    GeneratedParagraph,
    RetrievalRequest,
    RetrievalScope,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def ready_vault(vault: Path) -> None:
    write(
        vault,
        "wiki/mitochondria.md",
        """---
id: concept-mitochondria
type: concept
tags: [biology, metabolism]
source: cell-textbook
date: 2026-01-15
---
# Energy conversion

Mitochondria produce ATP through oxidative phosphorylation. [[wiki/cell]]
""",
    )
    write(
        vault,
        "wiki/cell.md",
        """---
id: concept-cell
type: concept
tags: [biology]
source: lecture
date: 2026-02-10
---
# Organelles

Cells contain energy-transforming organelles.
""",
    )
    write(
        vault,
        "wiki/duplicate.md",
        "---\ntags: [biology]\n---\n# Quoted passage\n\nMitochondria produce ATP through oxidative phosphorylation.\n",
    )
    write(
        vault,
        "private/health.md",
        "# Protected\n\nA sensitive phrase that semantic similarity must not reveal.\n",
    )


def test_semantic_conversation_to_reviewable_proposal_keeps_markdown_canonical(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    ready_vault(vault)
    runtime = vault / ".lifeos"
    service = KnowledgeConversationService(vault_root=vault, runtime_dir=runtime)
    assert service.retriever.index_service.rebuild(batch_size=1).status == "complete"

    embedding = DeterministicEmbeddingProvider(
        dimensions=4,
        phrase_vectors={
            "how do cells make usable energy": [1.0, 0.0, 0.0, 0.0],
            "Mitochondria produce ATP through oxidative phosphorylation.": [1.0, 0.0, 0.0, 0.0],
        },
    )
    service.retriever.index_service.embed_missing(embedding, batch_size=1)
    preview = service.retriever.search(
        RetrievalRequest(
            "how do cells make usable energy",
            scope=RetrievalScope(folders=("wiki",), tags=("biology",)),
            limit=4,
            context_budget=500,
        ),
        embedding_provider=embedding,
    )
    assert preview.results[0].path == "wiki/mitochondria.md"
    assert preview.results[0].ranking.semantic > 0.7
    assert preview.results[0].duplicate_paths == ("wiki/duplicate.md",)
    assert all(not result.path.startswith("private/") for result in preview.results)

    conversation = service.create(
        title="Cellular energy evidence",
        scope=RetrievalScope(folders=("wiki",), tags=("biology",)),
        now=NOW,
    )
    evidence_id = preview.results[0].evidence_id
    provider = DeterministicAnswerProvider(
        GeneratedAnswer(
            (
                GeneratedParagraph(
                    "The indexed source directly states that mitochondria produce ATP through oxidative phosphorylation.",
                    (evidence_id,),
                    "direct",
                ),
            ),
            "The citation was selected from the bounded vault evidence and validated independently.",
        )
    )
    answered = service.ask(
        conversation.relative_path,
        query="how do cells make usable energy",
        expected_hash=conversation.content_hash,
        embedding_provider=embedding,
        answer_provider=provider,
        limit=4,
        context_budget=500,
        now=NOW,
    )
    turn = answered.turns[-1]
    assert turn.state == "ready"
    assert turn.answer[0].citations == (evidence_id,)
    assert "[[wiki/mitochondria.md#Energy conversion]]" in (
        vault / answered.relative_path
    ).read_text(encoding="utf-8")

    target = vault / "wiki" / "energy-summary.md"
    proposal_service = ConversationProposalService(
        vault_root=vault, runtime_dir=runtime, actor_id="e2e-user"
    )
    request = ConversationProposalRequest(
        conversation_path=answered.relative_path,
        turn_id=turn.turn_id,
        action="draft_note",
        target_path="wiki/energy-summary.md",
        title="Energy summary",
        content="Mitochondria produce ATP through oxidative phosphorylation.",
    )
    previewed, _, _, _ = proposal_service.preview(request, now=NOW)
    assert previewed.operation == "create_file"
    assert previewed.evidence[0]["path"] == "wiki/mitochondria.md"
    published = proposal_service.publish(request, now=NOW)
    assert (vault / published.proposal_path / "patches.json").exists()
    assert not target.exists(), (
        "Conversation outcomes must remain proposals until approval and application."
    )

    canonical_conversation = (vault / answered.relative_path).read_text(encoding="utf-8")
    shutil.rmtree(runtime)
    loaded_without_runtime = ConversationArtifactService(
        vault_root=vault, runtime_dir=runtime
    ).load(answered.relative_path)
    assert loaded_without_runtime.turns[-1].answer[0].text.startswith("The indexed source")
    assert (vault / answered.relative_path).read_text(encoding="utf-8") == canonical_conversation


def test_index_recovery_sync_stale_evidence_and_bridge_contract(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    ready_vault(vault)
    runtime = vault / ".lifeos"
    notifications: list[dict[str, object]] = []
    bridge = BridgeApplication(
        vault_root=vault,
        runtime_dir=runtime,
        actor_id="e2e-user",
        notify=notifications.append,
    )
    client = ReferenceBridgeClient(bridge)

    handshake = client.call("system.handshake", protocol="1.2")
    required = {
        "retrieval.index.health",
        "retrieval.index.rebuild",
        "retrieval.index.sync",
        "retrieval.index.recover",
        "retrieval.search",
        "conversation.create",
        "conversation.ask",
        "conversation.stale.check",
        "conversation.proposal.preview",
    }
    assert required <= set(handshake["capabilities"])
    assert client.call("retrieval.index.rebuild", batch_size=1)["status"] == "complete"
    assert any(item["method"] == "retrieval.index.progress" for item in notifications)

    created = client.call(
        "conversation.create",
        title="Recovery session",
        scope={"folders": ["wiki"]},
        now=NOW.isoformat(),
    )
    answered = client.call(
        "conversation.ask",
        path=created["path"],
        query="oxidative phosphorylation",
        expected_hash=created["content_hash"],
        evidence_only=True,
        now=NOW.isoformat(),
    )
    assert answered["turns"][-1]["state"] == "evidence-only"

    source = vault / "wiki" / "mitochondria.md"
    moved = vault / "wiki" / "bioenergetics.md"
    moved.write_text(
        source.read_text(encoding="utf-8").replace(
            "Mitochondria produce ATP through oxidative phosphorylation.",
            "Mitochondria convert energy and support ATP production.",
        ),
        encoding="utf-8",
    )
    source.unlink()
    (vault / "wiki" / "duplicate.md").unlink()
    synced = client.call("retrieval.index.sync")
    assert ("wiki/mitochondria.md", "wiki/bioenergetics.md") in synced["renamed"]
    assert "wiki/duplicate.md" in synced["deleted"]

    stale = client.call("conversation.stale.check", path=answered["path"])
    assert stale[-1]["evidence"][0]["stale"] is True
    assert "stale-evidence" in stale[-1]["diagnostics"]

    bridge.knowledge.retriever.index_service.discard()
    assert client.call("retrieval.index.health")["state"] == "missing"
    plan = client.call("retrieval.index.recovery.plan")
    assert plan["action"] == "full-rebuild"
    recovered = client.call("retrieval.index.recover")
    assert recovered["status"] == "complete"
    result = client.call(
        "retrieval.search",
        query="ATP production",
        scope={"folders": ["wiki"]},
        limit=3,
        context_budget=300,
    )
    assert result["results"][0]["path"] == "wiki/bioenergetics.md"
    protected = client.call(
        "retrieval.search",
        query="sensitive phrase",
        scope={"paths": ["private/health.md"], "allow_protected": True},
    )
    assert protected["results"] == []
