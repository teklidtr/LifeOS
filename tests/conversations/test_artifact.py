from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.conversations import (
    ConversationArtifactService,
    ConversationError,
    ConversationEvidence,
    ConversationParagraph,
    ConversationTurn,
)
from lifeos.retrieval import RetrievalScope

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def evidence() -> ConversationEvidence:
    return ConversationEvidence(
        "chunk:one", "wiki/source.md", "Evidence", 4, 6,
        "sha256:" + "a" * 64, "sha256:" + "b" * 64,
        "Source passage.", {"lexical": 1.0, "total": 0.5},
    )


def turn(identifier: str = "turn-001") -> ConversationTurn:
    return ConversationTurn(
        identifier, NOW.isoformat(), "What supports this?", "ready", (evidence(),),
        (ConversationParagraph("The source supports it.", ("chunk:one",), "direct"),),
        "Citation validated.", {"mode": "local"},
    )


def test_create_append_load_and_preserve_human_annotations(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    service = ConversationArtifactService(vault_root=vault, runtime_dir=vault / ".lifeos")
    created = service.create(title="Energy evidence", scope=RetrievalScope(tags=("biology",)), now=NOW)
    assert created.metadata.schema_version == 1
    assert created.relative_path.startswith("conversations/2026/")
    path = vault / created.relative_path
    path.write_text(path.read_text().replace("## Annotations\n", "## Annotations\n\nHuman note stays byte-for-byte.\n"), encoding="utf-8")
    refreshed = service.load(created.relative_path)
    updated = service.append_turn(created.relative_path, turn(), expected_hash=refreshed.content_hash, now=NOW)
    assert updated.turns[0].answer[0].citations == ("chunk:one",)
    assert "Human note stays byte-for-byte." in updated.human_body
    assert "[[wiki/source.md#Evidence]]" in path.read_text(encoding="utf-8")


def test_scope_pin_exclude_rename_archive_and_stale_write(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    service = ConversationArtifactService(vault_root=vault, runtime_dir=vault / ".lifeos")
    item = service.create(title="Session", now=NOW)
    changed = service.update(
        item.relative_path,
        expected_hash=item.content_hash,
        title="Renamed session",
        scope=RetrievalScope(folders=("wiki",)),
        pinned_sources=("wiki/a.md",),
        excluded_sources=("wiki/b.md",),
        now=NOW,
    )
    assert changed.metadata.title == "Renamed session"
    assert changed.metadata.scope.folders == ("wiki",)
    assert changed.metadata.pinned_sources == ("wiki/a.md",)
    archived = service.archive(changed.relative_path, expected_hash=changed.content_hash, now=NOW)
    assert archived.metadata.status == "archived"
    assert service.list(include_archived=False) == ()
    with pytest.raises(ConversationError, match="changed"):
        service.update(item.relative_path, expected_hash=item.content_hash, title="stale", now=NOW)


def test_branch_copies_history_and_parent_provenance(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    service = ConversationArtifactService(vault_root=vault, runtime_dir=vault / ".lifeos")
    item = service.create(title="Root", now=NOW)
    item = service.append_turn(item.relative_path, turn(), expected_hash=item.content_hash, now=NOW)
    branch = service.branch(item.relative_path, from_turn_id="turn-001", now=NOW)
    assert branch.metadata.parent_conversation_id == item.metadata.conversation_id
    assert branch.metadata.branch_from_turn_id == "turn-001"
    assert branch.turns == item.turns


def test_malformed_managed_boundary_and_unsupported_schema_fail_safely(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    service = ConversationArtifactService(vault_root=vault, runtime_dir=vault / ".lifeos")
    item = service.create(title="Root", now=NOW)
    path = vault / item.relative_path
    path.write_text(path.read_text().replace("conversation_schema: 1", "conversation_schema: 99"), encoding="utf-8")
    with pytest.raises(ConversationError) as error:
        service.load(item.relative_path)
    assert error.value.code == "unsupported_schema"
