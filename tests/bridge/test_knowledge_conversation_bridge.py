from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient


def setup(tmp_path: Path, notifications: list[dict] | None = None):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "wiki" / "source.md"
    source.parent.mkdir()
    source.write_text("# Evidence\n\nMitochondria produce ATP.\n", encoding="utf-8")
    bridge = BridgeApplication(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        actor_id="local",
        notify=notifications.append if notifications is not None else None,
    )
    return bridge, ReferenceBridgeClient(bridge), vault


def test_retrieval_capabilities_health_rebuild_search_and_progress(tmp_path: Path) -> None:
    notifications: list[dict] = []
    _, client, _ = setup(tmp_path, notifications)
    handshake = client.call("system.handshake", protocol="1.2")
    assert "retrieval.search" in handshake["capabilities"]
    assert client.call("retrieval.index.health")["state"] == "missing"
    rebuilt = client.call("retrieval.index.rebuild", batch_size=1)
    assert rebuilt["status"] == "complete"
    assert any(item["method"] == "retrieval.index.progress" for item in notifications)
    result = client.call("retrieval.search", query="ATP", limit=3)
    assert result["results"][0]["path"] == "wiki/source.md"
    assert result["results"][0]["ranking"]["lexical"] > 0


def test_conversation_lifecycle_scope_evidence_branch_and_proposal(tmp_path: Path) -> None:
    _, client, vault = setup(tmp_path)
    client.call("retrieval.index.rebuild")
    created = client.call("conversation.create", title="Energy", scope={"folders": ["wiki"]})
    path = created["path"]
    asked = client.call(
        "conversation.ask",
        path=path,
        query="ATP",
        expected_hash=created["content_hash"],
        evidence_only=True,
    )
    turn = asked["turns"][-1]
    assert turn["state"] == "evidence-only" and turn["evidence"]
    pinned = client.call(
        "conversation.source.pin",
        path=path,
        source_path="wiki/source.md",
        expected_hash=asked["content_hash"],
        enabled=True,
    )
    assert pinned["metadata"]["pinned_sources"] == ["wiki/source.md"]
    branch = client.call("conversation.branch", path=path, turn_id=turn["turn_id"])
    assert branch["metadata"]["parent_conversation_id"] == asked["metadata"]["conversation_id"]
    preview = client.call(
        "conversation.proposal.preview",
        conversation_path=path,
        turn_id=turn["turn_id"],
        action="draft_note",
        target_path="wiki/new.md",
        content="Grounded note.",
    )
    assert preview["target_path"] == "wiki/new.md"
    published = client.call(
        "conversation.proposal.create",
        conversation_path=path,
        turn_id=turn["turn_id"],
        action="draft_note",
        target_path="wiki/new.md",
        content="Grounded note.",
    )
    assert (vault / published["proposal_path"] / "patches.json").exists()
    assert not (vault / "wiki/new.md").exists()


def test_strict_params_and_protected_scope_denial_cross_bridge(tmp_path: Path) -> None:
    _, client, vault = setup(tmp_path)
    private = vault / "private" / "secret.md"
    private.parent.mkdir()
    private.write_text("# Secret\n\nSensitive phrase.\n", encoding="utf-8")
    client.call("retrieval.index.rebuild")
    result = client.call(
        "retrieval.search", query="Sensitive phrase", scope={"paths": ["private/secret.md"]}
    )
    assert result["results"] == []
    with pytest.raises(ProtocolError) as caught:
        client.call("conversation.create", title="x", unknown=True)
    assert caught.value.code == "extra_fields"
