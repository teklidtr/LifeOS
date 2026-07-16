import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.conversations import (
    ConversationProposalRequest,
    ConversationProposalService,
    KnowledgeConversationService,
    ConversationError,
)

NOW = datetime(2026, 7, 16, 11, tzinfo=timezone.utc)


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def setup(tmp_path: Path) -> tuple[Path, str, str]:
    vault = tmp_path / "vault"
    vault.mkdir()
    write(vault, "wiki/source.md", "# Evidence\n\nA grounded source passage.")
    write(vault, "wiki/target.md", "# Target\n\nHuman text.\n")
    conversations = KnowledgeConversationService(vault_root=vault, runtime_dir=vault / ".lifeos")
    conversations.retriever.index_service.rebuild()
    artifact = conversations.create(title="Proposal source", now=NOW)
    artifact = conversations.ask(
        artifact.relative_path,
        query="grounded source",
        expected_hash=artifact.content_hash,
        evidence_only=True,
        now=NOW,
    )
    return vault, artifact.relative_path, artifact.turns[-1].turn_id


def test_create_note_proposal_contains_exact_target_patch_and_evidence(tmp_path: Path) -> None:
    vault, conversation_path, turn_id = setup(tmp_path)
    service = ConversationProposalService(vault_root=vault, runtime_dir=vault / ".lifeos")
    request = ConversationProposalRequest(
        conversation_path, turn_id, "draft_note", "wiki/new-insight.md", "Grounded insight."
    )
    result = service.publish(request, now=NOW)
    assert not (vault / "wiki/new-insight.md").exists()
    patch = json.loads((vault / result.proposal_path / "patches.json").read_text())
    assert patch["operations"][0]["op"] == "create_file"
    assert patch["operations"][0]["target_path"] == "wiki/new-insight.md"
    proposal = (vault / result.proposal_path / "proposal.md").read_text()
    assert "wiki/source.md" in proposal and turn_id in proposal


def test_append_proposal_carries_stale_target_hash_and_never_mutates_target(tmp_path: Path) -> None:
    vault, conversation_path, turn_id = setup(tmp_path)
    original = (vault / "wiki/target.md").read_text()
    service = ConversationProposalService(vault_root=vault, runtime_dir=vault / ".lifeos")
    result = service.publish(
        ConversationProposalRequest(
            conversation_path, turn_id, "append_section", "wiki/target.md", "A proposed section."
        ),
        now=NOW,
    )
    assert (vault / "wiki/target.md").read_text() == original
    assert result.preview.base_hash and result.preview.base_hash.startswith("sha256:")
    assert "+A proposed section." in (result.preview.unified_diff or "")


@pytest.mark.parametrize(
    "action",
    [
        "create_capture",
        "suggest_links",
        "research_questions",
        "extract_claims",
        "flashcard_candidates",
        "mark_contradiction",
        "mark_unresolved_question",
    ],
)
def test_all_supported_actions_produce_reviewable_previews(tmp_path: Path, action: str) -> None:
    vault, conversation_path, turn_id = setup(tmp_path)
    service = ConversationProposalService(vault_root=vault, runtime_dir=vault / ".lifeos")
    target = "captures/outcome.md" if action == "create_capture" else "wiki/target.md"
    preview, _, _, _ = service.preview(
        ConversationProposalRequest(
            conversation_path, turn_id, action, target, "Reviewed content."
        ),  # type: ignore[arg-type]
        now=NOW,
    )
    assert preview.evidence and preview.target_path == target


def test_proposal_requires_a_real_evidence_turn(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    conversations = KnowledgeConversationService(vault_root=vault, runtime_dir=vault / ".lifeos")
    artifact = conversations.create(title="Empty", now=NOW)
    service = ConversationProposalService(vault_root=vault, runtime_dir=vault / ".lifeos")
    with pytest.raises(ConversationError):
        service.preview(
            ConversationProposalRequest(
                artifact.relative_path, "turn-001", "draft_note", "wiki/x.md", "x"
            ),
            now=NOW,
        )
